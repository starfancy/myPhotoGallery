import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import BrowseView from "../views/BrowseView.vue"
import SubfolderStrip from "../components/SubfolderStrip.vue"
import { useAuthStore } from "../stores/auth"

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

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
    ],
  })
}

interface FetchOpts {
  /** path(相对路径片段) -> 该空文件夹补查返回的直接子项列表 */
  children: Record<string, unknown[]>
  /** 需要让补查返回 500 的 path 集合 */
  failPaths?: string[]
}

async function mountView(opts: FetchOpts) {
  const folders = [
    { name: "有图文件夹", relative_path: "has", image_count: 5, descendant_count: 5, cover_thumb_sha1: "sha-has" },
    { name: "真空文件夹", relative_path: "empty", image_count: 0, descendant_count: 0, cover_thumb_sha1: null },
    { name: "借封面文件夹", relative_path: "borrow", image_count: 0, descendant_count: 3, cover_thumb_sha1: null },
  ]
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : (input as Request).url ?? String(input)
    const method = init?.method ?? "GET"
    if (method === "GET" && url.includes("/breadcrumbs")) {
      return response([{ name: "R", relative_path: "" }])
    }
    if (method === "GET" && url.includes("/folders")) {
      const p = new URL(url, "http://test/").searchParams.get("path") ?? ""
      if (p === "") return response(folders)
      if (opts.failPaths?.includes(p)) return response({ error: { code: "internal_error", message: "x" } }, 500)
      return response(opts.children[p] ?? [])
    }
    if (method === "GET" && url.includes("/images")) {
      return response({ items: [], total: 0 })
    }
    return response({ error: { code: "not_found", message: "not mocked" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)

  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({ user: { id: 1, username: "u", role: "viewer", access_scope: "lan_only" } })

  const router = makeRouter()
  await router.push("/galleries/1/r/1")
  const w = mount(BrowseView, {
    global: { plugins: [router], stubs: { ImageLightbox: true } },
  })
  await flushPromises()
  await flushPromises()
  return { w, fetchFn, folders }
}

function folderCalls(fetchFn: { mock: { calls: unknown[][] } }) {
  return fetchFn.mock.calls.flatMap((rawCall) => {
    const url = String(rawCall[0])
    if (!url.includes("/folders")) return []
    return [new URL(url, "http://test/").searchParams.get("path") ?? ""]
  })
}

describe("BrowseView borrowed folder covers", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("fetches only for empty-with-descendants folders and borrows first child with images", async () => {
    const { w, fetchFn } = await mountView({
      children: {
        // 第一个子项自身无图、无封面；第二个才有 -> 应借第二个
        borrow: [
          { name: "中山", relative_path: "borrow/zs", image_count: 0, descendant_count: 0, cover_thumb_sha1: null },
          { name: "广州", relative_path: "borrow/gz", image_count: 2, descendant_count: 2, cover_thumb_sha1: "sha-gz" },
        ],
      },
    })

    const paths = folderCalls(fetchFn)
    // 1 次主列表 + 仅 borrow 1 次补查；has 与 empty 不触发
    expect(paths).toEqual(["", "borrow"])

    const strip = w.findComponent(SubfolderStrip)
    const items = strip.props("folders") as Array<Record<string, unknown>>
    expect(items[0].cover_thumb_sha1).toBe("sha-has")
    expect(items[0].cover_source_name).toBeUndefined()
    expect(items[1].cover_thumb_sha1).toBeNull()
    expect(items[2].cover_thumb_sha1).toBe("sha-gz")
    expect(items[2].cover_source_name).toBe("广州")
  })

  it("issues one enrichment request per candidate folder in a single load", async () => {
    // 两候选（a、b 自身无图但后代有图）+ 一个自身有图的 c
    const folders = [
      { name: "A", relative_path: "a", image_count: 0, descendant_count: 1, cover_thumb_sha1: null },
      { name: "B", relative_path: "b", image_count: 0, descendant_count: 2, cover_thumb_sha1: null },
      { name: "C", relative_path: "c", image_count: 3, descendant_count: 3, cover_thumb_sha1: "sha-c" },
    ]
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url ?? String(input)
      if (url.includes("/breadcrumbs")) return response([{ name: "R", relative_path: "" }])
      if (url.includes("/folders")) {
        const p = new URL(url, "http://test/").searchParams.get("path") ?? ""
        if (p === "") return response(folders)
        return response([
          { name: `${p}-child`, relative_path: `${p}/x`, image_count: 1, descendant_count: 1, cover_thumb_sha1: `sha-${p}` },
        ])
      }
      if (url.includes("/images")) return response({ items: [], total: 0 })
      return response(null, 404)
    })
    vi.stubGlobal("fetch", fetchFn)

    setActivePinia(createPinia())
    useAuthStore().$patch({ user: { id: 1, username: "u", role: "viewer", access_scope: "lan_only" } })

    const router = makeRouter()
    await router.push("/galleries/1/r/1")
    const w = mount(BrowseView, {
      global: { plugins: [router], stubs: { ImageLightbox: true } },
    })
    await flushPromises()
    await flushPromises()

    // 1 次主列表 + a、b 各 1 次补查；自身有图的 c 不补查
    expect(folderCalls(fetchFn).sort()).toEqual(["", "a", "b"])
    const items = w.findComponent(SubfolderStrip).props("folders") as Array<Record<string, unknown>>
    expect(items[0].cover_thumb_sha1).toBe("sha-a")
    expect(items[0].cover_source_name).toBe("a-child")
    expect(items[1].cover_thumb_sha1).toBe("sha-b")
    expect(items[1].cover_source_name).toBe("b-child")
    expect(items[2].cover_thumb_sha1).toBe("sha-c")
    expect(items[2].cover_source_name).toBeUndefined()
  })

  it("keeps grey placeholder when no direct child has images of its own", async () => {
    const { w } = await mountView({
      children: {
        borrow: [
          { name: "只有孙级有图", relative_path: "borrow/deep", image_count: 0, descendant_count: 9, cover_thumb_sha1: null },
        ],
      },
    })
    const items = w.findComponent(SubfolderStrip).props("folders") as Array<Record<string, unknown>>
    expect(items[2].cover_thumb_sha1).toBeNull()
    expect(items[2].cover_source_name).toBeUndefined()
  })

  it("survives a failed enrichment request without breaking the list", async () => {
    const { w } = await mountView({ children: {}, failPaths: ["borrow"] })
    const items = w.findComponent(SubfolderStrip).props("folders") as Array<Record<string, unknown>>
    // 三个文件夹名照常渲染
    expect(w.text()).toContain("借封面文件夹")
    expect(items[2].cover_thumb_sha1).toBeNull()
    expect(items[2].cover_source_name).toBeUndefined()
  })
})
