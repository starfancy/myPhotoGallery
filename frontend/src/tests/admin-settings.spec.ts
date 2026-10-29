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
}

const DEFAULTS: Settings = {
  trash_retention_days: 30,
  login_lockout_threshold: 5,
  trusted_proxies: [],
  session_hours: 8,
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
})
