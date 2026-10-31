import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import SearchResults from "../components/SearchResults.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"

type ImageRowish = { id: number }

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
  })
}

const FOLDERS = [
  { name: "旅行", relative_path: "2024/旅行", image_count: 0,
    descendant_count: 9, cover_thumb_sha1: "sha-f" },
]
const IMAGES_A = [
  { id: 11, filename: "a.jpg", width: 400, height: 300, sha1: "s11",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    relative_path: "2024/旅行/a.jpg" },
  { id: 12, filename: "b.jpg", width: 400, height: 300, sha1: "s12",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    relative_path: "root.jpg" },
]
const IMAGES_B = [
  { id: 13, filename: "c.jpg", width: 400, height: 300, sha1: "s13",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    relative_path: "2024/旅行/c.jpg" },
]

function mountResults(
  fetchFn: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
) {
  vi.stubGlobal("fetch", fetchFn)
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/galleries/:gid/r/:rid/:path(.*)*", component: { template: "<div/>" } }],
  })
  return mount(SearchResults, {
    props: { gid: 1, rid: 2, q: "旅行", path: "", grid: "justified" as const },
    global: { plugins: [router] },
  })
}

describe("SearchResults", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("渲染匹配文件夹与图片：链接、截断提示、目录角标", async () => {
    const fetchFn = vi.fn(async () => json({
      q: "旅行", path: "", folders: FOLDERS, folders_truncated: true,
      images: IMAGES_A, next_cursor: "cur1",
    }))
    const w = mountResults(fetchFn)
    await flushPromises()
    await flushPromises()

    expect(w.text()).toContain("匹配的文件夹")
    expect(w.text()).toContain("仅显示前 50 个")
    const link = w.get("a")
    expect(link.attributes("href")).toContain("/galleries/1/r/2/2024/%E6%97%85%E8%A1%8C")
    // 子目录图片带角标，root 图片不带
    const badges = w.findAll(".lb-cell-badge")
    expect(badges.length).toBe(1)
    expect(badges[0].text()).toBe("2024/旅行")
    // 图片角标之外，缩略图本身都在
    expect(w.findAll("img").length).toBeGreaterThanOrEqual(3)
    // itemsChange 已上抛
    expect((w.emitted("itemsChange")!.at(-1) as ImageRowish[])[0]).toHaveLength(2)
  })

  it("加载更多：带 cursor 追加图片", async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("cursor=cur1")) {
        return json({ q: "旅行", path: "", folders: [], folders_truncated: false,
                      images: IMAGES_B, next_cursor: null })
      }
      return json({ q: "旅行", path: "", folders: [], folders_truncated: false,
                    images: IMAGES_A, next_cursor: "cur1" })
    })
    const w = mountResults(fetchFn)
    await flushPromises()
    await flushPromises()
    await w.findAll("button").find((b) => b.text().includes("加载"))!.trigger("click")
    await flushPromises()
    const items = w.emitted("itemsChange")!.at(-1) as unknown as ImageRowish[][]
    expect(items[0]).toHaveLength(3)
  })

  it("空结果显示空态", async () => {
    const fetchFn = vi.fn(async () => json({
      q: "zzz", path: "", folders: [], folders_truncated: false,
      images: [], next_cursor: null,
    }))
    const w = mountResults(fetchFn)
    await flushPromises()
    expect(w.text()).toContain("未找到匹配的图片或文件夹")
  })

  it("网格 open/toggleSelect 透传；defineExpose.reload 可重拉", async () => {
    const fetchFn = vi.fn(async () => json({
      q: "旅行", path: "", folders: [], folders_truncated: false,
      images: IMAGES_A, next_cursor: null,
    }))
    const w = mountResults(fetchFn)
    await flushPromises()
    await flushPromises()
    w.findComponent(JustifiedGrid).vm.$emit("open", 11)
    expect(w.emitted("open")![0]).toEqual([11])
    w.findComponent(JustifiedGrid).vm.$emit("toggleSelect", 11)
    expect(w.emitted("toggleSelect")![0]).toEqual([11])

    await (w.vm as unknown as { reload: () => Promise<void> }).reload()
    expect(fetchFn).toHaveBeenCalledTimes(2)
  })

  const Q1_IMG = { id: 1, filename: "a.jpg", width: 40, height: 30, sha1: "s",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    relative_path: "a.jpg" }

  it("换搜索词后旧的加载更多响应晚到：不污染新结果", async () => {
    let resolveMore: (r: Response) => void = () => {}
    let resolveQ2: (r: Response) => void = () => {}
    const calls: string[] = []
    const fetchFn = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      if (url.includes("cursor=")) {
        return new Promise<Response>((res) => { resolveMore = res })
      }
      if (url.includes("q=q2")) {
        return new Promise<Response>((res) => { resolveQ2 = res })
      }
      return Promise.resolve(json({ q: "q1", path: "", folders: [],
        folders_truncated: false, images: [Q1_IMG], next_cursor: "c1" }))
    })
    const w = mountResults(fetchFn)
    await flushPromises()
    await w.setProps({ q: "q1" })
    await flushPromises()
    const moreBtn = () =>
      w.findAll("button").find((b) => b.text().includes("加载"))!
    await moreBtn().trigger("click")
    await flushPromises()
    expect(calls.some((u) => u.includes("cursor=c1"))).toBe(true)

    // 换词 q2：first page 挂起期间按钮必须禁用
    await w.setProps({ q: "q2" })
    await flushPromises()
    expect((moreBtn().element as HTMLButtonElement).disabled).toBe(true)

    // 新查询首页先回
    resolveQ2(json({ q: "q2", path: "", folders: [], folders_truncated: false,
      images: [{ id: 2, filename: "b.jpg", width: 40, height: 30, sha1: "s2",
                 size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
                 relative_path: "b.jpg" }], next_cursor: null }))
    await flushPromises()
    // 旧 q1 的 cursor 响应后到（含脏数据 99），必须整条丢弃
    resolveMore(json({ q: "q1", path: "", folders: [], folders_truncated: false,
      images: [{ id: 99, filename: "stale.jpg", width: 40, height: 30, sha1: "z",
                 size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
                 relative_path: "stale.jpg" }], next_cursor: null }))
    await flushPromises()

    const items = w.emitted("itemsChange")!.at(-1) as unknown as Array<Array<{ id: number }>>
    expect(items[0].map((x) => x.id)).toEqual([2])
  })

  it("新查询首页加载中：加载更多禁用，点击不携带旧 cursor 发请求", async () => {
    let resolveQ2: (r: Response) => void = () => {}
    const calls: string[] = []
    const fetchFn = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      if (url.includes("q=q2")) {
        return new Promise<Response>((res) => { resolveQ2 = res })
      }
      return Promise.resolve(json({ q: "q1", path: "", folders: [],
        folders_truncated: false, images: [Q1_IMG], next_cursor: "c1" }))
    })
    const w = mountResults(fetchFn)
    await flushPromises()
    await w.setProps({ q: "q1" })
    await flushPromises()

    // q2 首页挂起（此刻没有挂起的加载更多）：旧 cursor c1 仍在界面上
    await w.setProps({ q: "q2" })
    await flushPromises()
    const btn = w.findAll("button").find((b) => b.text().includes("加载"))!
    expect(btn.exists()).toBe(true)
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    await btn.trigger("click")
    await flushPromises()
    // 不得用新 q + 旧 cursor 发出分页请求
    expect(calls.some((u) => u.includes("cursor="))).toBe(false)

    resolveQ2(json({ q: "q2", path: "", folders: [], folders_truncated: false,
      images: [{ id: 2, filename: "b.jpg", width: 40, height: 30, sha1: "s2",
                 size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
                 relative_path: "b.jpg" }], next_cursor: null }))
    await flushPromises()
  })
})
