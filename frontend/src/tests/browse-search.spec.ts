import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent } from "vue"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import BrowseView from "../views/BrowseView.vue"
import SearchResults from "../components/SearchResults.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import { useAuthStore } from "../stores/auth"
import { useBrowseStore } from "../stores/browse"

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

const IMG_A = {
  id: 11, filename: "a.jpg", width: 400, height: 300, sha1: "s11",
  size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
  relative_path: "2024/旅行/a.jpg",
}
const BROWSE_IMAGES = [
  { id: 1, filename: "x.jpg", width: 40, height: 30, sha1: "s1",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false },
  { id: 2, filename: "y.jpg", width: 40, height: 30, sha1: "s2",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false },
]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

const LightboxStub = defineComponent({
  name: "ImageLightbox",
  props: ["items", "startId", "locationResolver"],
  emits: ["viewInFolder", "close", "change", "deleted"],
  template: `<div class="lb-stub" />`,
})

async function mountAt(url: string) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const u = String(input)
    const method = init?.method ?? "GET"
    if (method === "POST" && u.includes("/api/images/batch-delete")) {
      const { image_ids } = JSON.parse(init?.body as string) as { image_ids: number[] }
      return json({ deleted: image_ids, failed: [] })
    }
    if (u.includes("/breadcrumbs")) return json([{ name: "R", relative_path: "" }])
    if (u.includes("/folders")) return json([])
    if (u.includes("/search")) {
      return json({
        q: "旅行", path: "", folders_truncated: false,
        folders: [{ name: "旅行", relative_path: "2024/旅行", image_count: 0,
                    descendant_count: 2, cover_thumb_sha1: "sf" }],
        images: [IMG_A], next_cursor: null,
      })
    }
    if (u.includes("/images")) return json({ items: BROWSE_IMAGES, total: 2 })
    return json({ error: { code: "not_found", message: "x" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({ user: { id: 1, username: "u", role: "admin",
                         access_scope: "lan_only", download_batch_limit: 100 } })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/galleries/:gid/r/:rid/:path(.*)*", component: BrowseView },
      { path: "/galleries/:gid/r/:rid/:path(.*)*/image/:iid", component: BrowseView },
    ],
  })
  await router.push(url)
  const w = mount(BrowseView, {
    global: { plugins: [router], stubs: { ImageLightbox: LightboxStub } },
  })
  await flushPromises()
  await flushPromises()
  return { w, router, fetchFn }
}

describe("BrowseView 搜索态", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("?q= 进入搜索态：请求 search、显示文件夹命中、不显示分页条", async () => {
    const { w, fetchFn } = await mountAt("/galleries/1/r/1?q=%E6%97%85%E8%A1%8C")
    const searchCall = (fetchFn.mock.calls as unknown as Array<[string]>).find(
      (c) => c[0].includes("/search"),
    )!
    expect(decodeURIComponent(searchCall[0])).toContain("q=旅行")
    expect(w.text()).toContain("匹配的文件夹")
    expect(w.findComponent(SearchResults).exists()).toBe(true)
    expect(w.text()).not.toContain("此目录暂无图片")
  })

  it("输入搜索词：防抖后写入路由 query 并进入搜索态", async () => {
    vi.useFakeTimers()
    const { w, router } = await mountAt("/galleries/1/r/1")
    const input = w.get('input[aria-label="搜索"]')
    await input.setValue("abc")
    expect(router.currentRoute.value.query.q).toBeUndefined()
    vi.advanceTimersByTime(300)
    await flushPromises()
    expect(router.currentRoute.value.query.q).toBe("abc")
    expect(w.findComponent(SearchResults).exists()).toBe(true)
  })

  it("结果网格 open：以结果集开 Lightbox，resolver 给出目录，viewInFolder 跳目录", async () => {
    const { w, router } = await mountAt("/galleries/1/r/1?q=%E6%97%85%E8%A1%8C")
    w.findComponent(JustifiedGrid).vm.$emit("open", 11)
    await flushPromises()
    expect(router.currentRoute.value.query.image).toBe("11")

    const lb = w.findComponent(LightboxStub)
    expect(lb.props("startId")).toBe(11)
    const resolver = lb.props("locationResolver") as (it: { relative_path?: string }) => string
    expect(resolver(IMG_A)).toBe("2024/旅行")
    expect(resolver({ relative_path: "a.jpg" })).toBe("")

    lb.vm.$emit("viewInFolder", IMG_A)
    await flushPromises()
    // 目录按段百分号编码（与 SearchResults 文件夹链接一致）；params 解码后仍为原目录
    expect(router.currentRoute.value.path).toBe(
      "/galleries/1/r/1/2024/%E6%97%85%E8%A1%8C",
    )
    const rawPath = router.currentRoute.value.params.path
    expect(Array.isArray(rawPath) ? rawPath.join("/") : String(rawPath ?? "")).toBe("2024/旅行")
    expect(router.currentRoute.value.query.q).toBeUndefined()
  })

  it("scope=all 时 SearchResults 的 path 为空（整 root）", async () => {
    const ctx = await mountAt("/galleries/1/r/1/sub?q=x")
    const cb = ctx.w.find('input[type="checkbox"]')
    expect(cb.exists()).toBe(true)
    await cb.setValue(true)
    await flushPromises()
    expect(ctx.router.currentRoute.value.query.scope).toBe("all")
    expect(ctx.w.findComponent(SearchResults).props("path")).toBe("")
  })

  it("改搜索词清空选择集", async () => {
    vi.useFakeTimers()
    const { w } = await mountAt("/galleries/1/r/1?q=old")
    await flushPromises()
    await w.findAll("button").find((b) => b.text() === "选择")!.trigger("click")
    w.findComponent(JustifiedGrid).vm.$emit("toggle-select", 11)
    await flushPromises()
    expect(w.text()).toContain("已选 1 项")

    const input = w.get('input[aria-label="搜索"]')
    await input.setValue("new")
    vi.advanceTimersByTime(300)
    await flushPromises()
    expect(w.text()).not.toContain("已选")
  })

  it("搜索态全选作用于结果集：全选选中结果，网格 toggle 仍可用", async () => {
    const { w } = await mountAt("/galleries/1/r/1?q=%E6%97%85%E8%A1%8C")
    await flushPromises()
    await w.findAll("button").find((b) => b.text() === "选择")!.trigger("click")
    await flushPromises()
    await w.findAll("button").find((b) => b.text() === "全选")!.trigger("click")
    await flushPromises()
    expect(w.text()).toContain("已选 1 项")
    const grid = w.findComponent(JustifiedGrid)
    expect(Array.from(grid.props("selectedIds") as Set<number>)).toContain(11)

    grid.vm.$emit("toggle-select", 11)
    await flushPromises()
    expect(w.text()).not.toContain("已选 1 项")
    expect((grid.props("selectedIds") as Set<number>).size).toBe(0)
  })

  it("清除搜索后加载普通视图", async () => {
    const { w, fetchFn } = await mountAt("/galleries/1/r/1?q=%E6%97%85%E8%A1%8C")
    const imageCalls = () =>
      (fetchFn.mock.calls as unknown as Array<[string]>).filter((c) => c[0].includes("/images?"))
    // 搜索态下不应请求普通 /images
    expect(imageCalls().length).toBe(0)
    expect(w.findComponent(SearchResults).exists()).toBe(true)

    await w.get('button[aria-label="清除搜索"]').trigger("click")
    await flushPromises()
    await flushPromises()

    // 同路径清除 q 后补拉普通视图
    expect(imageCalls().length).toBe(1)
    expect(w.findComponent(SearchResults).exists()).toBe(false)
    expect(w.text()).not.toContain("此目录暂无图片")
    const grid = w.findComponent(JustifiedGrid)
    expect(grid.exists()).toBe(true)
    expect((grid.props("items") as Array<{ id: number }>).map((it) => it.id)).toEqual([1, 2])
  })

  it("搜索态批量删除后刷新结果", async () => {
    const { w, fetchFn } = await mountAt("/galleries/1/r/1?q=%E6%97%85%E8%A1%8C")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))

    await w.findAll("button").find((b) => b.text() === "选择")!.trigger("click")
    await flushPromises()
    w.findComponent(JustifiedGrid).vm.$emit("toggle-select", 11)
    await flushPromises()
    expect(w.text()).toContain("已选 1 项")

    await w.findAll("button").find((b) => b.text().includes("移入回收站"))!.trigger("click")
    await flushPromises()
    await flushPromises()

    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const postIdx = calls.findIndex(
      (c) => c[0].includes("/api/images/batch-delete") && c[1]?.method === "POST",
    )
    expect(postIdx).toBeGreaterThanOrEqual(0)
    expect(JSON.parse(calls[postIdx][1]!.body as string)).toEqual({ image_ids: [11] })
    // POST 之后必须有第二次 /search（reload），且不补拉隐藏的普通 /images
    const searchesAfter = calls
      .slice(postIdx + 1)
      .filter((c) => c[0].includes("/search")).length
    expect(searchesAfter).toBe(1)
    expect(calls.filter((c) => c[0].includes("/images?")).length).toBe(0)
  })

  it("搜索态单张删除后清空普通浏览缓存（防幽灵卡片 / 批量下载 404）", async () => {
    const { w } = await mountAt("/galleries/1/r/1?q=%E6%97%85%E8%A1%8C")
    // 制造非空缓存，证明删除路径真的清了，而不是本来就空
    const store = useBrowseStore()
    store.cache.set("1|1|old|name_asc", {
      pages: new Map([[1, [{ id: 99, filename: "ghost.jpg" }]]]),
      total: 1, scrollY: 0, keyString: "1|1|old|name_asc", atime: 0,
    } as never)
    const clearSpy = vi.spyOn(store, "clearAll")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))

    const menuBtn = w.findAll('button[aria-label^="更多操作"]')[0]
    await menuBtn.trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")
    await flushPromises()
    await flushPromises()

    expect(clearSpy).toHaveBeenCalledTimes(1)
    expect(store.cache.size).toBe(0)
  })

  it("仅切换整个 root 范围不触发普通 /images 请求", async () => {
    const { w, fetchFn } = await mountAt("/galleries/1/r/1/sub?q=x")
    const imageCallCount = () =>
      (fetchFn.mock.calls as unknown as Array<[string]>).filter((c) => c[0].includes("/images?")).length
    expect(imageCallCount()).toBe(0)

    await w.get('input[type="checkbox"]').setValue(true)
    await flushPromises()
    await flushPromises()

    expect(imageCallCount()).toBe(0)
    expect(w.findComponent(SearchResults).props("path")).toBe("")
  })
})
