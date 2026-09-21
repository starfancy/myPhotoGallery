import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import BrowseView from "../views/BrowseView.vue"
import { useAuthStore } from "../stores/auth"

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

const CRUMBS = [{ name: "R", relative_path: "" }]
const FOLDERS: unknown[] = []
const IMAGES = [
  { id: 1, filename: "a.jpg", width: 400, height: 300, sha1: "sha-a", size_bytes: 1, taken_at: null, is_raw: false },
  { id: 2, filename: "b.jpg", width: 400, height: 300, sha1: "sha-b", size_bytes: 1, taken_at: null, is_raw: false },
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
    routes: [
      { path: "/galleries/:gid/r/:rid/:path(.*)*", component: BrowseView },
      { path: "/galleries/:gid/r/:rid/:path(.*)*/image/:iid", component: BrowseView },
    ],
  })
}

async function mountView(role: "admin" | "viewer" = "admin") {
  // 模拟服务端图片状态：删除/批量删除会修改它，重新拉取时反映出来
  const serverImages = IMAGES.map((x) => ({ ...x }))
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : (input as Request).url ?? String(input)
    const method = init?.method ?? "GET"
    if (method === "GET" && url.includes("/breadcrumbs")) return response(CRUMBS)
    if (method === "GET" && url.includes("/folders")) return response(FOLDERS)
    if (method === "GET" && url.includes("/images")) {
      return response({ items: serverImages, total: serverImages.length })
    }
    if (method === "DELETE" && /\/api\/images\/\d+$/.test(url)) {
      const id = Number(url.split("/").pop())
      const i = serverImages.findIndex((x) => x.id === id)
      if (i >= 0) serverImages.splice(i, 1)
      return response(null, 204)
    }
    if (method === "POST" && url.includes("/api/images/batch-delete")) {
      const { image_ids } = JSON.parse(init?.body as string)
      for (const id of image_ids) {
        const i = serverImages.findIndex((x) => x.id === id)
        if (i >= 0) serverImages.splice(i, 1)
      }
      return response({ deleted: image_ids, failed: [] })
    }
    return response({ error: { code: "not_found", message: "not mocked" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)

  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({ user: { id: 1, username: "u", role, access_scope: "lan_only" } })

  const router = makeRouter()
  await router.push("/galleries/1/r/1")
  const w = mount(BrowseView, {
    global: { plugins: [router], stubs: { ImageLightbox: true } },
  })
  await flushPromises()
  await flushPromises()  // JustifiedGrid onMounted 需要一轮
  return { w, fetchFn, auth }
}

describe("BrowseView delete flows", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    // 重新注册 ResizeObserver（unstubAllGlobals 会清掉 beforeAll 的存根）
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("shows three-dot menu for admin, hides for viewer", async () => {
    const { w } = await mountView("admin")
    expect(w.findAll('button[aria-label^="更多操作"]').length).toBe(IMAGES.length)

    const { w: w2 } = await mountView("viewer")
    expect(w2.findAll('button[aria-label^="更多操作"]').length).toBe(0)
  })

  it("shows the '选择' button only for admin", async () => {
    const { w } = await mountView("admin")
    expect(w.findAll("button").find((b) => b.text() === "选择")).toBeTruthy()

    const { w: w2 } = await mountView("viewer")
    expect(w2.findAll("button").find((b) => b.text() === "选择")).toBeFalsy()
  })

  it("deletes a single image via three-dot menu after confirmation", async () => {
    const { w, fetchFn } = await mountView("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))

    const menuBtn = w.findAll('button[aria-label^="更多操作"]')[0]
    await menuBtn.trigger("click")
    await flushPromises()
    const menuItem = w.get(".lb-cell-menu-item")
    await menuItem.trigger("click")
    await flushPromises()

    expect(window.confirm).toHaveBeenCalled()
    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const delCall = calls.find(
      (c) => typeof c[0] === "string" && c[0] === "/api/images/1" && c[1]?.method === "DELETE",
    )
    expect(delCall).toBeDefined()
    // 图片从视图移除
    expect(w.findAll("img").length).toBe(IMAGES.length - 1)
  })

  it("does not call DELETE when the confirm dialog is cancelled", async () => {
    const { w, fetchFn } = await mountView("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false))

    const menuBtn = w.findAll('button[aria-label^="更多操作"]')[0]
    await menuBtn.trigger("click")
    const menuItem = w.get(".lb-cell-menu-item")
    await menuItem.trigger("click")
    await flushPromises()

    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const delCalls = calls.filter((c) => c[1]?.method === "DELETE")
    expect(delCalls.length).toBe(0)
    // 图片保留
    expect(w.findAll("img").length).toBe(IMAGES.length)
  })

  it("selection mode: click cells to toggle, then batch delete", async () => {
    const { w, fetchFn } = await mountView("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))

    const selectBtn = w.findAll("button").find((b) => b.text() === "选择")!
    await selectBtn.trigger("click")
    await flushPromises()

    // 缩略图按钮 = 非 aria-label(更多操作/选择)
    const thumbBtns = w.findAll("button").filter(
      (b) => !b.attributes("aria-label")?.startsWith("更多操作")
        && !b.attributes("aria-label")?.startsWith("选择")
        && b.find("img").exists(),
    )
    // 点击两张缩略图 = 全选
    await thumbBtns[0].trigger("click")
    await thumbBtns[1].trigger("click")
    await flushPromises()

    expect(w.text()).toContain("已选 2 项")

    const batchBtn = w.findAll("button").find((b) => b.text().includes("移入回收站"))!
    await batchBtn.trigger("click")
    await flushPromises()

    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const call = calls.find(
      (c) => typeof c[0] === "string" && c[0] === "/api/images/batch-delete" && c[1]?.method === "POST",
    )
    expect(call).toBeDefined()
    expect(JSON.parse(call![1]!.body as string)).toEqual({ image_ids: [1, 2] })
    // 完成后退出选择模式（浮动条消失）
    expect(w.findAll("button").find((b) => b.text().includes("移入回收站"))).toBeFalsy()
    // 图片全部移除
    expect(w.findAll("img").length).toBe(0)
  })

  it("selection mode cancel button clears selection", async () => {
    const { w } = await mountView("admin")
    const selectBtn = w.findAll("button").find((b) => b.text() === "选择")!
    await selectBtn.trigger("click")
    await flushPromises()

    // 点一张选中
    const thumbBtns = w.findAll("button").filter(
      (b) => b.find("img").exists(),
    )
    await thumbBtns[0].trigger("click")
    await flushPromises()
    expect(w.text()).toContain("已选 1 项")

    const cancelBtn = w.findAll("button").find((b) => b.text() === "取消")!
    await cancelBtn.trigger("click")
    await flushPromises()
    expect(w.text()).not.toContain("已选")
    // 选择按钮回来
    expect(w.findAll("button").find((b) => b.text() === "选择")).toBeTruthy()
  })
})
