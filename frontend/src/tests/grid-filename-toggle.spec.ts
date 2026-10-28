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

const IMAGES = [
  { id: 1, filename: "DSC_0001.JPG", width: 400, height: 300, sha1: "sha-a", size_bytes: 1, taken_at: null, is_raw: false },
  { id: 2, filename: "DSC_0002.JPG", width: 300, height: 400, sha1: "sha-b", size_bytes: 1, taken_at: null, is_raw: false },
]

const STORAGE_KEY = "browse.grid.showFilenames"

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

async function mountView() {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : (input as Request).url ?? String(input)
    if (url.includes("/breadcrumbs")) return response([{ name: "R", relative_path: "" }])
    if (url.includes("/folders")) return response([])
    if (url.includes("/images")) return response({ items: IMAGES, total: IMAGES.length })
    return response({ error: { code: "not_found", message: "not mocked" } }, 404)
  }))

  setActivePinia(createPinia())
  useAuthStore().$patch({ user: { id: 1, username: "u", role: "viewer", access_scope: "lan_only" } })

  const router = makeRouter()
  await router.push("/galleries/1/r/1")
  const w = mount(BrowseView, {
    global: { plugins: [router], stubs: { ImageLightbox: true } },
  })
  await flushPromises()
  await flushPromises()
  return w
}

describe("BrowseView filename overlay toggle", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
    localStorage.clear()
  })

  it("is off by default and toggles captions on, persisting the preference", async () => {
    const w = await mountView()

    expect(w.findAll(".lb-cell-filename").length).toBe(0)
    const btn = w.get('button[aria-label="缩略图上显示文件名"]')
    expect(btn.attributes("aria-pressed")).toBe("false")

    await btn.trigger("click")
    await flushPromises()

    const caps = w.findAll(".lb-cell-filename")
    expect(caps.length).toBe(IMAGES.length)
    expect(caps.map((c) => c.text())).toEqual(["DSC_0001.JPG", "DSC_0002.JPG"])
    expect(btn.attributes("aria-pressed")).toBe("true")
    expect(localStorage.getItem(STORAGE_KEY)).toBe("1")

    // 再点一次关闭
    await btn.trigger("click")
    await flushPromises()
    expect(w.findAll(".lb-cell-filename").length).toBe(0)
    expect(localStorage.getItem(STORAGE_KEY)).toBe("0")
  })

  it("honours a previously persisted preference", async () => {
    localStorage.setItem(STORAGE_KEY, "1")
    const w = await mountView()
    expect(w.findAll(".lb-cell-filename").length).toBe(IMAGES.length)
  })
})
