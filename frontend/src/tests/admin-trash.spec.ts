import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AdminTrash from "../views/AdminTrash.vue"

const GALLERIES = [
  { id: 1, name: "Home", description: null, root_count: 1, image_count: 10 },
  { id: 2, name: "Travel", description: null, root_count: 1, image_count: 5 },
]

const now = Math.floor(Date.now() / 1000)
const TRASH_ENTRIES = [
  {
    id: 101, gallery_id: 1, root_id: 1,
    original_relative_path: "sub/a.jpg", trash_relative_path: ".trash/1/1/20260722/a.jpg",
    sha1: "sha-a", size_bytes: 1024,
    deleted_by: 1, deleted_at: now - 3600, purge_after: now + 30 * 86400,
  },
  {
    id: 102, gallery_id: 1, root_id: 1,
    original_relative_path: "b.jpg", trash_relative_path: ".trash/1/1/20260722/b.jpg",
    sha1: "sha-b", size_bytes: 2048,
    deleted_by: 1, deleted_at: now - 7200, purge_after: now + 30 * 86400,
  },
  {
    id: 103, gallery_id: 2, root_id: 2,
    original_relative_path: "trip/c.jpg", trash_relative_path: ".trash/2/2/20260722/c.jpg",
    sha1: "sha-c", size_bytes: 4096,
    deleted_by: 1, deleted_at: now - 10800, purge_after: now + 30 * 86400,
  },
]

function response(body: unknown, status = 200) {
  const isNull = body === null || body === undefined
  return new Response(isNull ? null : JSON.stringify(body), {
    status,
    headers: isNull ? {} : { "content-type": "application/json" },
  })
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/admin/trash", component: AdminTrash }],
  })
}

async function mountView(trashBody: unknown = { entries: TRASH_ENTRIES, next_cursor: null }) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : (input as Request).url ?? String(input)
    const method = init?.method ?? "GET"
    if (url === "/api/admin/galleries" && method === "GET") return response(GALLERIES)
    if (url.startsWith("/api/trash") && method === "GET") return response(trashBody)
    return response({ error: { code: "not_found", message: "not mocked" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)

  const router = makeRouter()
  await router.push("/admin/trash")
  const w = mount(AdminTrash, {
    global: { plugins: [createPinia(), router] },
  })
  await flushPromises()
  return { w, fetchFn }
}

describe("AdminTrash", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  it("renders trash entries with paths, gallery names, and timestamps", async () => {
    const { w } = await mountView()
    expect(w.text()).toContain("sub/a.jpg")
    expect(w.text()).toContain("b.jpg")
    expect(w.text()).toContain("Home") // gallery_id=1
    expect(w.text()).toContain("Travel") // gallery_id=2
    // 每行的两个操作按钮
    expect(w.findAll("button").filter((b) => b.text() === "恢复").length).toBe(3)
    expect(w.findAll("button").filter((b) => b.text() === "立即删除").length).toBe(3)
  })

  it("shows empty state when trash is empty", async () => {
    const { w } = await mountView({ entries: [], next_cursor: null })
    expect(w.text()).toContain("回收站为空")
  })

  it("filters entries by gallery", async () => {
    const { w, fetchFn } = await mountView()
    // 默认 URL 不带 gallery_id
    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const initialCall = calls.find(
      (c) => typeof c[0] === "string" && c[0].startsWith("/api/trash"),
    )
    expect(initialCall![0]).not.toContain("gallery_id=")

    const select = w.find("select")
    await select.setValue("2")
    await flushPromises()

    const calls2 = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const filteredCalls = calls2.filter(
      (c) =>
        typeof c[0] === "string" && c[0].startsWith("/api/trash") && c[0].includes("gallery_id=2"),
    )
    expect(filteredCalls.length).toBeGreaterThan(0)
  })

  it("restores a single entry via POST and removes it from the table", async () => {
    const { w, fetchFn } = await mountView()
    fetchFn.mockResolvedValueOnce(response({ status: "restored", trash_id: 101 }))

    const restoreBtns = w.findAll("button").filter((b) => b.text() === "恢复")
    await restoreBtns[0].trigger("click")
    await flushPromises()

    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const call = calls.find((c) => typeof c[0] === "string" && c[0] === "/api/trash/101/restore")
    expect(call).toBeDefined()
    expect(call![1]!.method).toBe("POST")
    // 表格里第一条已移除
    expect(w.text()).not.toContain("sub/a.jpg")
  })

  it("deletes one entry after confirmation via DELETE", async () => {
    const { w, fetchFn } = await mountView()
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
    fetchFn.mockResolvedValueOnce(response(null, 204))

    const delBtns = w.findAll("button").filter((b) => b.text() === "立即删除")
    await delBtns[1].trigger("click")
    await flushPromises()

    expect(window.confirm).toHaveBeenCalled()
    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const call = calls.find(
      (c) => typeof c[0] === "string" && c[0] === "/api/trash/102" && c[1]?.method === "DELETE",
    )
    expect(call).toBeDefined()
    expect(w.text()).not.toContain("b.jpg")
  })

  it("does not delete when confirmation is cancelled", async () => {
    const { w, fetchFn } = await mountView()
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false))

    const delBtns = w.findAll("button").filter((b) => b.text() === "立即删除")
    await delBtns[0].trigger("click")
    await flushPromises()

    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const deleteCalls = calls.filter((c) => c[1]?.method === "DELETE")
    expect(deleteCalls.length).toBe(0)
    // 条目仍在
    expect(w.text()).toContain("sub/a.jpg")
  })

  it("batch restores selected entries", async () => {
    const { w, fetchFn } = await mountView()
    // 勾选前两个（表头 checkbox + 每行 checkbox；跳过表头）
    const checkboxes = w.findAll('input[type="checkbox"]')
    // checkboxes[0] 是全选；[1]..[3] 是行
    await checkboxes[1].setValue(true)
    await checkboxes[2].setValue(true)
    await flushPromises()

    fetchFn.mockResolvedValueOnce(response({ restored: [{ trash_id: 101 }, { trash_id: 102 }], failed: [] }))

    const btn = w.findAll("button").find((b) => b.text().includes("恢复选中"))!
    await btn.trigger("click")
    await flushPromises()

    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const call = calls.find(
      (c) => typeof c[0] === "string" && c[0] === "/api/trash/batch-restore" && c[1]?.method === "POST",
    )
    expect(call).toBeDefined()
    expect(JSON.parse(call![1]!.body as string)).toEqual({ trash_ids: [101, 102] })
    // 两条被移除
    expect(w.text()).not.toContain("sub/a.jpg")
    expect(w.text()).not.toContain("b.jpg")
    expect(w.text()).toContain("trip/c.jpg")
  })

  it("select-all checkbox toggles all rows", async () => {
    const { w } = await mountView()
    const checkboxes = w.findAll('input[type="checkbox"]')
    await checkboxes[0].setValue(true)
    await flushPromises()
    expect(w.text()).toContain("已选 3 项")
    await checkboxes[0].setValue(false)
    await flushPromises()
    expect(w.text()).not.toContain("已选 3 项")
  })

  it("purge sends POST with confirm=true after user confirmation", async () => {
    const { w, fetchFn } = await mountView()
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
    vi.stubGlobal("alert", vi.fn())
    fetchFn.mockResolvedValueOnce(
      response({ purged: 2, blocked: 0, missing: 0, errors: 0 }),
    )
    // 重载列表：purge 完成后会 reload
    fetchFn.mockResolvedValueOnce(response({ entries: [], next_cursor: null }))

    const btn = w.findAll("button").find((b) => b.text().includes("清空所有"))!
    await btn.trigger("click")
    await flushPromises()

    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const call = calls.find(
      (c) => typeof c[0] === "string" && c[0] === "/api/trash/purge" && c[1]?.method === "POST",
    )
    expect(call).toBeDefined()
    const body = JSON.parse(call![1]!.body as string)
    expect(body.confirm).toBe(true)
  })

  it("purge does nothing when confirmation is cancelled", async () => {
    const { w, fetchFn } = await mountView()
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false))

    const btn = w.findAll("button").find((b) => b.text().includes("清空所有"))!
    await btn.trigger("click")
    await flushPromises()

    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const purgeCalls = calls.filter((c) => typeof c[0] === "string" && c[0] === "/api/trash/purge")
    expect(purgeCalls.length).toBe(0)
  })
})
