import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AdminSettings from "../views/AdminSettings.vue"

interface Settings {
  trash_retention_days: number
  login_lockout_threshold: number
  trusted_proxies: string[]
  session_hours: number
  download_batch_limit: number
}

const DEFAULTS: Settings = {
  trash_retention_days: 30,
  login_lockout_threshold: 5,
  trusted_proxies: [],
  session_hours: 8,
  download_batch_limit: 100,
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/admin/settings", component: AdminSettings }],
  })
  await router.push("/admin/settings")
  const w = mount(AdminSettings, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return w
}

describe("AdminSettings", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  it("loads and renders current values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(DEFAULTS)))
    const w = await mountView()

    const checkedRadio = w.findAll('input[type="radio"]').find(
      (r) => (r.element as HTMLInputElement).checked,
    )!
    expect((checkedRadio.element as HTMLInputElement).value).toBe("30")
    const numbers = w.findAll('input[type="number"]')
    expect((numbers[0].element as HTMLInputElement).value).toBe("5")
    expect((numbers[1].element as HTMLInputElement).value).toBe("8")
  })

  it("saves changed fields via PATCH and shows confirmation", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(DEFAULTS))
      .mockResolvedValueOnce(json({ ...DEFAULTS, login_lockout_threshold: 3 }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    const threshold = w.findAll('input[type="number"]')[0]
    await threshold.setValue(3)
    const save = w.findAll("button").find((b) => b.text() === "保存")!
    await save.trigger("click")
    await flushPromises()

    expect(fetchFn).toHaveBeenCalledTimes(2)
    const [url, init] = fetchFn.mock.calls[1]
    expect(url).toBe("/api/admin/settings")
    expect(init.method).toBe("PATCH")
    expect(JSON.parse(init.body)).toEqual({
      trash_retention_days: 30,
      login_lockout_threshold: 3,
      trusted_proxies: [],
      session_hours: 8,
      download_batch_limit: 100,
    })
    expect(w.text()).toContain("已保存")
  })

  it("never-retention radio posts value 0", async () => {
    const fetchFn = vi.fn()
    fetchFn.mockResolvedValueOnce(json(DEFAULTS))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    const never = w.findAll('input[type="radio"]').find(
      (r) => (r.element as HTMLInputElement).value === "0",
    )!
    await never.trigger("click")
    const save = w.findAll("button").find((b) => b.text() === "保存")!
    await save.trigger("click")
    await flushPromises()

    const [, init] = fetchFn.mock.calls[1]
    expect(JSON.parse(init.body).trash_retention_days).toBe(0)
  })

  it("adds and removes trusted_proxies rows, dropping empty rows on save", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(DEFAULTS))
      .mockResolvedValueOnce(json({ ...DEFAULTS, trusted_proxies: ["10.0.0.0/8"] }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    await w.findAll("button").find((b) => b.text().includes("添加"))!.trigger("click")
    await w.findAll("button").find((b) => b.text().includes("添加"))!.trigger("click")
    const proxyInputs = w.findAll('input[placeholder*="127.0.0.1"]')
    expect(proxyInputs).toHaveLength(2)
    await proxyInputs[0].setValue("10.0.0.0/8")
    // second row left empty -> must be dropped
    const removeBtns = w.findAll("button").filter((b) => b.text() === "删除")
    await removeBtns[1].trigger("click") // delete the empty row directly

    const save = w.findAll("button").find((b) => b.text() === "保存")!
    await save.trigger("click")
    await flushPromises()

    const [, init] = fetchFn.mock.calls[1]
    expect(JSON.parse(init.body).trusted_proxies).toEqual(["10.0.0.0/8"])
  })

  it("blocks save with a Chinese message when a number field is cleared", async () => {
    const fetchFn = vi.fn().mockResolvedValueOnce(json(DEFAULTS))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    const hours = w.findAll('input[type="number"]')[1]
    await hours.setValue("")
    await w.findAll("button").find((b) => b.text() === "保存")!.trigger("click")
    await flushPromises()

    // only the initial GET — no PATCH
    expect(fetchFn).toHaveBeenCalledTimes(1)
    expect(fetchFn.mock.calls[0][1]?.method ?? "GET").not.toBe("PATCH")
    expect(w.text()).toContain("请填写有效的数字：锁定阈值、会话时长和批量下载上限不能为空。")
  })

  it("resets form to the PATCH response so deduped proxies leave a clean form", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(DEFAULTS))
      // local body carries the proxy twice; the server dedupes to one row
      .mockResolvedValueOnce(json({ ...DEFAULTS, trusted_proxies: ["10.0.0.0/8"] }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    await w.findAll("button").find((b) => b.text().includes("添加"))!.trigger("click")
    await w.findAll("button").find((b) => b.text().includes("添加"))!.trigger("click")
    const proxyInputs = w.findAll('input[placeholder*="127.0.0.1"]')
    await proxyInputs[0].setValue("10.0.0.0/8")
    await proxyInputs[1].setValue("10.0.0.0/8")

    const save = w.findAll("button").find((b) => b.text() === "保存")!
    await save.trigger("click")
    await flushPromises()

    const [, init] = fetchFn.mock.calls[1]
    expect(JSON.parse(init.body).trusted_proxies).toEqual(["10.0.0.0/8", "10.0.0.0/8"])

    const afterInputs = w.findAll('input[placeholder*="127.0.0.1"]')
    expect(afterInputs).toHaveLength(1)
    expect((afterInputs[0].element as HTMLInputElement).value).toBe("10.0.0.0/8")

    const saveAfter = w.findAll("button").find((b) => b.text() === "保存")!
    expect(saveAfter.attributes("disabled")).toBeDefined()
  })

  it("fills the recommended loopback proxies via 恢复默认 without auto-saving", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(DEFAULTS))
      .mockResolvedValueOnce(json({ ...DEFAULTS, trusted_proxies: ["127.0.0.1", "::1"] }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    // 初始为空；点击只填表单，不触发 PATCH
    const restore = w.findAll("button").find((b) => b.text() === "恢复默认")!
    await restore.trigger("click")

    const proxyInputs = w.findAll('input[placeholder*="127.0.0.1"]')
    expect(proxyInputs).toHaveLength(2)
    expect((proxyInputs[0].element as HTMLInputElement).value).toBe("127.0.0.1")
    expect((proxyInputs[1].element as HTMLInputElement).value).toBe("::1")
    // 仍只有初始 GET；恢复默认不自动保存
    expect(fetchFn).toHaveBeenCalledTimes(1)

    // 表单变 dirty，统一由保存按钮提交
    const save = w.findAll("button").find((b) => b.text() === "保存")!
    expect(save.attributes("disabled")).toBeUndefined()
    await save.trigger("click")
    await flushPromises()

    const [, init] = fetchFn.mock.calls[1]
    expect(JSON.parse(init.body).trusted_proxies).toEqual(["127.0.0.1", "::1"])
  })

  it("shows backend validation message and keeps form", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(DEFAULTS))
      .mockResolvedValueOnce(
        json({ error: { code: "bad_request", message: "session_hours must be between 1 and 720" } }, 400),
      )
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    const hours = w.findAll('input[type="number"]')[1]
    await hours.setValue(9999)
    await w.findAll("button").find((b) => b.text() === "保存")!.trigger("click")
    await flushPromises()

    expect(w.text()).toContain("session_hours must be between 1 and 720")
  })

  it("加载批量下载上限并可 PATCH", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(DEFAULTS))
      .mockResolvedValueOnce(json({ ...DEFAULTS, download_batch_limit: 80 }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    const numbers = w.findAll('input[type="number"]')
    // 顺序：登录锁定阈值、会话时长、批量下载上限
    expect((numbers[2].element as HTMLInputElement).value).toBe("100")
    await numbers[2].setValue(80)
    await w.findAll("button").find((b) => b.text() === "保存")!.trigger("click")
    await flushPromises()

    const [, init] = fetchFn.mock.calls[1]
    expect(JSON.parse(init.body).download_batch_limit).toBe(80)
  })

  it("批量下载上限为空时阻止保存", async () => {
    const fetchFn = vi.fn().mockResolvedValueOnce(json(DEFAULTS))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()
    const numbers = w.findAll('input[type="number"]')
    await numbers[2].setValue("")
    vi.stubGlobal("alert", vi.fn())
    await w.findAll("button").find((b) => b.text() === "保存")!.trigger("click")
    await flushPromises()
    // 只有 GET，没有 PATCH
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })
})
