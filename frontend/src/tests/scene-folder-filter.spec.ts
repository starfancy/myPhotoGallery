import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { defineComponent } from "vue"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import BrowseView from "../views/BrowseView.vue"
import SubfolderStrip from "../components/SubfolderStrip.vue"
import Breadcrumb from "../components/Breadcrumb.vue"
import SceneFilter from "../components/SceneFilter.vue"
import { useAuthStore } from "../stores/auth"

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/galleries/:gid/r/:rid/:path(.*)*", component: BrowseView }],
  })
}

async function mountAt(
  url: string,
  fetchFn: (input: RequestInfo | URL) => Promise<Response>,
) {
  vi.stubGlobal("fetch", fetchFn)
  setActivePinia(createPinia())
  useAuthStore().$patch({
    user: { id: 1, username: "u", role: "admin", access_scope: "lan_only" },
  })
  const router = makeRouter()
  // memory history 支持带 query 的初始 URL；必须 await，否则挂载时
  // currentRoute 还是初始路由，loadAll 读不到 scene query
  await router.push(url)
  const w = mount(BrowseView, {
    global: { plugins: [router], stubs: { ImageLightbox: true } },
  })
  return { w, router }
}

describe("scene filter drives folder facet filtering via URL", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("passes scene_major to both /folders and /images and shows matching count", async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : String(input)
      if (url.includes("/breadcrumbs")) return jsonResponse([{ name: "R", relative_path: "" }])
      if (url.includes("/tags/stats")) return jsonResponse({ majors: [] })
      if (url.includes("/folders")) {
        return jsonResponse([
          {
            name: "旅行", relative_path: "trip", image_count: 55, descendant_count: 55,
            cover_thumb_sha1: "sha1", matching_count: 3,
          },
        ])
      }
      if (url.includes("/images")) return jsonResponse({ items: [], total: 0 })
      return jsonResponse({ error: "not mocked" }, 404)
    })

    const { w } = await mountAt("/galleries/1/r/1?scene_major=自然风光", fetchFn)
    await flushPromises()
    await flushPromises()

    const requested = fetchFn.mock.calls.map((c) => String(c[0]))
    const folderUrl = requested.find((u) => u.includes("/folders"))!
    const imagesUrl = requested.find((u) => u.includes("/images"))!
    expect(new URL(folderUrl, "http://t/").searchParams.get("scene_major")).toBe("自然风光")
    expect(new URL(imagesUrl, "http://t/").searchParams.get("scene_major")).toBe("自然风光")

    // 匹配数 + “（匹配）” 标注
    expect(w.text()).toContain("3 张（匹配）")
    // 工具栏在零图片时仍保留（hasScene），筛选下拉存在
    expect(w.findComponent(SubfolderStrip).exists()).toBe(true)
  })

  it("keeps scene query when drilling into a subfolder", async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : String(input)
      if (url.includes("/breadcrumbs")) return jsonResponse([{ name: "R", relative_path: "" }])
      if (url.includes("/tags/stats")) return jsonResponse({ majors: [] })
      if (url.includes("/folders")) return jsonResponse([])
      if (url.includes("/images")) return jsonResponse({ items: [], total: 0 })
      return jsonResponse({ error: "not mocked" }, 404)
    })

    const { router } = await mountAt("/galleries/1/r/1?scene_major=自然风光", fetchFn)
    await flushPromises()
    await flushPromises()
    vi.clearAllMocks()

    // 模拟点文件夹卡片下钻（SubfolderStrip 的链接带 query）
    await router.push({
      path: "/galleries/1/r/1/trip",
      query: { scene_major: "自然风光" },
    })
    await flushPromises()
    await flushPromises()

    const requested = fetchFn.mock.calls.map((c) => String(c[0]))
    const folderUrl = requested.find((u) => u.includes("/folders"))!
    expect(new URL(folderUrl, "http://t/").searchParams.get("scene_major")).toBe("自然风光")
    expect(new URL(folderUrl, "http://t/").searchParams.get("path")).toBe("trip")
  })
})

describe("folder/breadcrumb links preserve scene query", () => {
  const LinkStub = defineComponent({
    props: { to: { type: [String, Object], required: true } },
    template: '<a :data-to="JSON.stringify(to)"><slot /></a>',
  })

  it("SubfolderStrip link carries scene query and matching_count label", () => {
    const w = mount(SubfolderStrip, {
      props: {
        gid: 1, rid: 1,
        query: { scene_major: "自然风光", scene_minor: "山景" },
        folders: [{
          name: "trip", relative_path: "trip", image_count: 10, descendant_count: 10,
          cover_thumb_sha1: null, matching_count: 2,
        }],
      },
      global: { stubs: { RouterLink: LinkStub } },
    })
    const to = JSON.parse(w.find("a").attributes("data-to")!)
    expect(to.query).toEqual({ scene_major: "自然风光", scene_minor: "山景" })
    expect(to.path).toBe("/galleries/1/r/1/trip")
    expect(w.text()).toContain("2 张（匹配）")
  })

  it("Breadcrumb link carries scene query; no query prop yields empty query", () => {
    const w = mount(Breadcrumb, {
      props: {
        gid: 1, rid: 1,
        crumbs: [{ name: "R", relative_path: "" }, { name: "trip", relative_path: "trip" }],
        query: { scene_major: "自然风光" },
      },
      global: { stubs: { RouterLink: LinkStub } },
    })
    const links = w.findAll("a").map((a) => JSON.parse(a.attributes("data-to")!))
    expect(links[1].query).toEqual({ scene_major: "自然风光" })
    expect(links[1].path).toBe("/galleries/1/r/1/trip")
  })
})

describe("SceneFilter minor selection survives mount", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          majors: [{
            name: "自然风光", count: 5,
            minors: [{ name: "山景", count: 3 }, { name: "湖泊", count: 2 }],
          }],
        }),
      ),
    )
  })

  it("does not clear scene_minor on mount when both params present in URL", async () => {
    const w = mount(SceneFilter, {
      props: { major: "自然风光", minor: "山景", gid: 1, rid: 1, path: "" },
    })
    await flushPromises()
    const minorEvents = w.emitted("update:minor") ?? []
    expect(minorEvents).not.toContainEqual([""])
    // stats 加载后二级列表包含山景
    expect(w.text()).toContain("山景")
  })
})
