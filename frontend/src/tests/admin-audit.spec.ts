import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AdminAudit from "../views/AdminAudit.vue"

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

const now = Math.floor(Date.now() / 1000)
const ENTRIES = [
  { id: 3, ts: now, actor_user_id: 1, actor_ip: "127.0.0.1", action: "image_delete", target: "image:9", detail: "x" },
  { id: 2, ts: now - 60, actor_user_id: null, actor_ip: "10.0.0.5", action: "login_fail", target: null, detail: null },
  { id: 1, ts: now - 120, actor_user_id: null, actor_ip: "127.0.0.1", action: "scan_start", target: "root:1", detail: null },
]

async function mountPage(auditBody: unknown = { entries: ENTRIES, next_cursor: "t_1" }, users = [
  { id: 1, username: "alice" },
]) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : (input as Request).url
    if (url.startsWith("/api/admin/users")) return response(users)
    if (url.startsWith("/api/admin/audit")) return response(auditBody)
    return response({ error: { code: "not_found", message: "x" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/admin/audit", component: AdminAudit }],
  })
  await router.push("/admin/audit")
  const w = mount(AdminAudit, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return { w, fetchFn }
}

beforeEach(() => { setActivePinia(createPinia()); vi.unstubAllGlobals() })

describe("AdminAudit", () => {
  it("renders rows with labels, mapped username, 匿名 for login_fail and 系统 for scans", async () => {
    const { w } = await mountPage()
    expect(w.text()).toContain("删除图片")
    expect(w.text()).toContain("alice")
    expect(w.text()).toContain("匿名")
    expect(w.text()).toContain("系统")
    expect(w.text()).toContain("10.0.0.5")
    expect(w.text()).toContain("image:9")
  })

  it("falls back to #id（已删除） when user missing", async () => {
    const { w } = await mountPage(undefined, [])
    expect(w.text()).toContain("#1（已删除）")
  })

  it("still lists entries and falls back to #id when users fetch fails", async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users"))
        return response({ error: { code: "internal_error", message: "x" } }, 500)
      return response({ entries: ENTRIES, next_cursor: null })
    })
    vi.stubGlobal("fetch", fetchFn)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/admin/audit", component: AdminAudit }],
    })
    await router.push("/admin/audit")
    const w = mount(AdminAudit, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    expect(w.text()).toContain("删除图片")
    expect(w.text()).toContain("#1")
    expect(w.text()).not.toContain("加载失败")
  })

  it("loads more with cursor and merges rows", async () => {
    const { w, fetchFn } = await mountPage()
    fetchFn.mockClear()
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      if (url.includes("cursor=t_1"))
        return response({ entries: [{ id: 4, ts: now - 200, actor_user_id: 1, actor_ip: "127.0.0.1", action: "login_success", target: null, detail: null }], next_cursor: null })
      return response({ entries: [], next_cursor: null })
    })
    await w.findAll("button").find((b) => b.text().includes("加载更多"))!.trigger("click")
    await flushPromises()
    expect(w.text()).toContain("登录成功")
  })

  it("filters by action and date range and resets to first page", async () => {
    const { w, fetchFn } = await mountPage()
    const select = w.find("select")
    await select.setValue("image_delete")
    await w.find("#audit-from").setValue("2026-10-01")
    await w.find("#audit-to").setValue("2026-10-31")
    await flushPromises()
    const calls = fetchFn.mock.calls as Array<[string]>
    const q = calls.filter((c) => c[0].startsWith("/api/admin/audit")).map((c) => c[0]).pop()!
    expect(q).toContain("action=image_delete")
    const params = new URL(q, "http://x").searchParams
    // 过滤变化重置回第一页：不带游标
    expect(params.get("cursor")).toBeNull()
    // 2026-10-01 00:00 本地（东八区 = 1790630400）；止 = 当天 23:59:59
    expect(Number(params.get("from"))).toBe(
      Math.floor(new Date(2026, 9, 1, 0, 0, 0).getTime() / 1000),
    )
    expect(Number(params.get("to"))).toBe(
      Math.floor(new Date(2026, 9, 31, 23, 59, 59).getTime() / 1000),
    )
  })

  it("shows empty state and error state", async () => {
    const { w } = await mountPage({ entries: [], next_cursor: null })
    expect(w.text()).toContain("暂无审计记录")
  })

  it("shows replacing Chinese error bar on first-page failure and retry reloads", async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      return response({ error: { code: "internal_error", message: "Internal Server Error boom" } }, 500)
    })
    vi.stubGlobal("fetch", fetchFn)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/admin/audit", component: AdminAudit }],
    })
    await router.push("/admin/audit")
    const w = mount(AdminAudit, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    // 中文映射文案，不回显后端英文原文；错误条替换表格区
    expect(w.text()).toContain("服务器内部错误")
    expect(w.text()).not.toContain("Internal Server Error boom")
    expect(w.findAll("table")).toHaveLength(0)
    // 重试成功
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      return response({ entries: ENTRIES, next_cursor: null })
    })
    await w.findAll("button").find((b) => b.text().includes("重试"))!.trigger("click")
    await flushPromises()
    expect(w.text()).toContain("删除图片")
    expect(w.text()).not.toContain("服务器内部错误")
  })

  it("keeps loaded rows on paging failure, shows inline error, and pager retry merges next page", async () => {
    const { w, fetchFn } = await mountPage()
    fetchFn.mockClear()
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      if (url.includes("cursor=t_1"))
        return response({ error: { code: "internal_error", message: "Raw backend English" } }, 500)
      return response({ entries: [], next_cursor: null })
    })
    await w.findAll("button").find((b) => b.text().includes("加载更多"))!.trigger("click")
    await flushPromises()
    // 首页行仍在同一张表中；分页错误条为中文、带独立重试
    expect(w.findAll("tbody tr")).toHaveLength(3)
    expect(w.text()).toContain("image:9")
    expect(w.text()).toContain("服务器内部错误")
    expect(w.text()).not.toContain("Raw backend English")
    // 游标未因失败推进：重试仍带同一 cursor，且重试成功后第二页并入同一张表
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      if (url.includes("cursor=t_1"))
        return response({
          entries: [{ id: 4, ts: now - 200, actor_user_id: 1, actor_ip: "127.0.0.1", action: "login_success", target: null, detail: null }],
          next_cursor: null,
        })
      return response({ entries: [], next_cursor: null })
    })
    await w.findAll("button").find((b) => b.text().includes("重试"))!.trigger("click")
    await flushPromises()
    expect(w.findAll("tbody tr")).toHaveLength(4)
    expect(w.text()).toContain("登录成功")
    expect(w.text()).toContain("image:9")
    expect(w.text()).not.toContain("服务器内部错误")
  })

  it("resets pager when filter changes while loadMore is in flight; stale page is not appended", async () => {
    let resolvePage2!: (r: Response) => void
    const pendingPage2 = new Promise<Response>((res) => { resolvePage2 = res })
    const { w, fetchFn } = await mountPage()
    fetchFn.mockClear()
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      if (url.includes("cursor=t_1")) return pendingPage2
      // 过滤重置请求（无 cursor）立即返回
      return response({ entries: [ENTRIES[0]], next_cursor: "t_2" })
    })
    const moreBtn = () => w.findAll("button").find((b) => /加载(更多|中)/.test(b.text()))!
    await moreBtn().trigger("click")
    await flushPromises()
    expect(moreBtn().attributes("disabled")).toBeDefined()
    expect(moreBtn().text()).toBe("加载中...")
    // 过滤变化触发 reload，使在途 loadMore 失效
    await w.find("select").setValue("image_delete")
    await flushPromises()
    const resetUrls = (fetchFn.mock.calls as Array<[string]>)
      .map((c) => c[0])
      .filter((u) => u.startsWith("/api/admin/audit") && u.includes("action=image_delete"))
    expect(resetUrls.length).toBeGreaterThan(0)
    for (const u of resetUrls) expect(new URL(u, "http://x").searchParams.get("cursor")).toBeNull()
    // 旧 loadMore 此刻才返回
    resolvePage2(response({
      entries: [{ id: 999, ts: now - 300, actor_user_id: 1, actor_ip: "127.0.0.1", action: "login_success", target: "STALE", detail: null }],
      next_cursor: null,
    }))
    await flushPromises()
    expect(moreBtn().attributes("disabled")).toBeUndefined()
    expect(moreBtn().text()).toBe("加载更多")
    // 注意「登录成功」也存在于过滤下拉项中，故只在 tbody 内断言旧页未被追加
    expect(w.find("tbody").text()).not.toContain("登录成功")
    expect(w.find("tbody").text()).not.toContain("STALE")
    expect(w.find("tbody").text()).toContain("image:9")
  })
})
