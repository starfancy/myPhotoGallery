import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AdminGalleryList from "../views/AdminGalleryList.vue"

const GALLERIES = [
  { id: 1, name: "Home", description: "Family photos", root_count: 2, image_count: 42 },
  { id: 2, name: "Travel", description: null, root_count: 1, image_count: 120 },
]

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/admin/galleries", component: AdminGalleryList },
      { path: "/admin/galleries/:gid", component: { template: "<div />" } },
    ],
  })
}

function mockFetchOnce(response: unknown, status = 200) {
  return new Response(JSON.stringify(response), {
    status,
    headers: { "content-type": "application/json" },
  })
}

function mockFetchSequence(...responses: Array<{ body: unknown; status?: number }>) {
  const fn = vi.fn()
  for (const r of responses) {
    fn.mockResolvedValueOnce(mockFetchOnce(r.body, r.status ?? 200))
  }
  vi.stubGlobal("fetch", fn)
  return fn
}

async function mountView() {
  const router = makeRouter()
  await router.push("/admin/galleries")
  const w = mount(AdminGalleryList, {
    global: { plugins: [createPinia(), router] },
  })
  await flushPromises()
  return w
}

describe("AdminGalleryList", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  it("shows loading state before fetch resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))
    const router = makeRouter()
    router.push("/admin/galleries")
    const w = mount(AdminGalleryList, {
      global: { plugins: [createPinia(), router] },
    })
    expect(w.text()).toContain("加载中")
  })

  it("renders gallery list with names, descriptions, and counts", async () => {
    mockFetchSequence({ body: GALLERIES })
    const w = await mountView()

    expect(w.text()).toContain("Home")
    expect(w.text()).toContain("Family photos")
    expect(w.text()).toContain("2 个根目录")
    expect(w.text()).toContain("42 张图片")
    expect(w.text()).toContain("Travel")
    expect(w.text()).toContain("1 个根目录")
    expect(w.text()).toContain("120 张图片")
    expect(w.text()).toContain("2 个图库")
  })

  it("shows empty state when no galleries exist", async () => {
    mockFetchSequence({ body: [] })
    const w = await mountView()
    expect(w.text()).toContain("暂无图库，点击上方按钮创建")
  })

  it("shows error message on API failure", async () => {
    mockFetchSequence({
      body: { error: { code: "forbidden", message: "admin only" } },
      status: 403,
    })
    const w = await mountView()
    expect(w.text()).toContain("admin only")
  })

  it("opens and closes the create gallery form", async () => {
    mockFetchSequence({ body: [] })
    const w = await mountView()

    // Initially the form is hidden: no "创建" button or input fields visible
    expect(w.findAll("input").length).toBe(0)
    const submitBtn = w.findAll("button").find((b) => b.text() === "创建")
    expect(submitBtn).toBeUndefined()

    // Click "新建图库" button
    const createBtn = w.findAll("button").find((b) => b.text() === "新建图库")
    expect(createBtn).toBeDefined()
    await createBtn!.trigger("click")
    await flushPromises()

    // Form should now be visible: input fields and "创建"/"取消" buttons appear
    expect(w.findAll("input").length).toBeGreaterThan(0)
    const submitBtn2 = w.findAll("button").find((b) => b.text() === "创建")
    expect(submitBtn2).toBeDefined()
    const cancelBtn = w.findAll("button").find((b) => b.text() === "取消")
    expect(cancelBtn).toBeDefined()

    // Click "取消" to close
    await cancelBtn!.trigger("click")
    await flushPromises()

    // Form should be hidden again: no inputs
    expect(w.findAll("input").length).toBe(0)
    const submitBtn3 = w.findAll("button").find((b) => b.text() === "创建")
    expect(submitBtn3).toBeUndefined()
  })

  it("creates a gallery and refreshes the list", async () => {
    // Initial empty list
    const fetchFn = mockFetchSequence({ body: [] })
    const w = await mountView()

    // Open create form
    const createBtn = w.findAll("button").find((b) => b.text() === "新建图库")!
    await createBtn.trigger("click")
    await flushPromises()

    // Fill in name
    const inputs = w.findAll("input")
    await inputs[0].setValue("New Gallery")

    // Now mock: POST create + GET reload
    fetchFn
      .mockResolvedValueOnce(mockFetchOnce({ id: 3, name: "New Gallery", description: null }))
      .mockResolvedValueOnce(mockFetchOnce([
        { id: 3, name: "New Gallery", description: null, root_count: 0, image_count: 0 },
      ]))

    // Click "创建"
    const submitBtn = w.findAll("button").find((b) => b.text() === "创建")!
    await submitBtn.trigger("click")
    await flushPromises()

    // Verify POST call
    const postCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) => c[0] === "/api/admin/galleries" && c[1].method === "POST",
    )
    expect(postCall).toBeDefined()
    expect(JSON.parse(postCall![1].body!)).toEqual({ name: "New Gallery" })

    // The new gallery should appear in the list
    expect(w.text()).toContain("New Gallery")
  })

  it("shows create error message on conflict", async () => {
    mockFetchSequence({ body: [] })
    const w = await mountView()

    // Open form
    const createBtn = w.findAll("button").find((b) => b.text() === "新建图库")!
    await createBtn.trigger("click")
    await flushPromises()

    // Fill in name
    const inputs = w.findAll("input")
    await inputs[0].setValue("Duplicate")

    // Mock POST returning 409 conflict
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "conflict", message: "gallery 'Duplicate' already exists" } }),
          { status: 409, headers: { "content-type": "application/json" } },
        ),
      ),
    )

    // Click "创建"
    const submitBtn = w.findAll("button").find((b) => b.text() === "创建")!
    await submitBtn.trigger("click")
    await flushPromises()

    // Error should be shown; form still open
    expect(w.text()).toContain("gallery 'Duplicate' already exists")
  })

  it("deletes a gallery after confirmation", async () => {
    const fetchFn = mockFetchSequence({ body: GALLERIES })
    const w = await mountView()

    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))

    // Find the first "删除" button
    const deleteBtns = w.findAll("button").filter((b) => b.text() === "删除")
    expect(deleteBtns.length).toBeGreaterThanOrEqual(1)

    // Mock DELETE
    fetchFn.mockResolvedValueOnce(new Response(null, { status: 204 }))

    await deleteBtns[0].trigger("click")
    await flushPromises()

    expect(window.confirm).toHaveBeenCalled()
    const deleteCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) => c[0] === "/api/admin/galleries/1" && c[1].method === "DELETE",
    )
    expect(deleteCall).toBeDefined()
  })

  it("does not delete when confirmation is cancelled", async () => {
    mockFetchSequence({ body: GALLERIES })
    const w = await mountView()

    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false))

    const deleteBtns = w.findAll("button").filter((b) => b.text() === "删除")
    await deleteBtns[0].trigger("click")
    await flushPromises()

    // confirm was called but no DELETE should have been sent
    expect(window.confirm).toHaveBeenCalled()
    // Gallery should still be there
    expect(w.text()).toContain("Home")
  })

  it("edit button links to the gallery edit page", async () => {
    mockFetchSequence({ body: GALLERIES })
    const w = await mountView()

    const editLinks = w.findAll('a[href="/admin/galleries/1"]')
    const editBtn = editLinks.find((a) => a.text().includes("编辑"))
    expect(editBtn).toBeDefined()
  })
})