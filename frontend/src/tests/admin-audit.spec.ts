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
})
