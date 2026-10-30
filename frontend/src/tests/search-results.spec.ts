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
    await w.findAll("button").find((b) => b.text().includes("加载更多"))!.trigger("click")
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
})
