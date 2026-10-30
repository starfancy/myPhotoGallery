import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import BrowseView from "../views/BrowseView.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import PaginationBar from "../components/PaginationBar.vue"
import { useAuthStore } from "../stores/auth"
import { useToastStore } from "../stores/toast"

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

function pageItems(page: number) {
  if (page === 1) {
    return Array.from({ length: 200 }, (_, i) => ({
      id: i + 1, filename: `a${i + 1}.jpg`, width: 40, height: 30,
      sha1: `s${i + 1}`, size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    }))
  }
  return [{ id: 201, filename: "a201.jpg", width: 40, height: 30,
            sha1: "s201", size_bytes: 1, taken_at: null, mtime: 0, is_raw: false }]
}

async function mountView(role: "admin" | "viewer", limit = 100, total = 2) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    })
    if (url.includes("/breadcrumbs")) return json([{ name: "R", relative_path: "" }])
    if (url.includes("/folders")) return json([])
    if (url.includes("/images")) {
      const page = url.includes("offset=0") || !url.includes("offset") ? 1 : 2
      return json({ items: total === 201 ? pageItems(page) : pageItems(1).slice(0, 2),
                    total })
    }
    if (url.includes("/api/download-batch")) {
      return json({ ticket: "TICK", filename: "photos-test.zip", count: 1 })
    }
    return json({ error: { code: "not_found", message: "not mocked" } }, 404)
  })

  vi.stubGlobal("fetch", fetchFn)
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({
    user: { id: 1, username: "u", role, access_scope: "lan_only",
            download_batch_limit: limit },
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/galleries/:gid/r/:rid/:path(.*)*", component: BrowseView },
      { path: "/galleries/:gid/r/:rid/:path(.*)*/image/:iid", component: BrowseView },
    ],
  })
  await router.push("/galleries/1/r/1")
  const w = mount(BrowseView, {
    global: { plugins: [router], stubs: { ImageLightbox: true } },
  })
  await flushPromises()
  await flushPromises()
  return { w, fetchFn, auth }
}

async function enterSelection(w: VueWrapper<any>) {
  await w.findAll("button").find((b) => b.text() === "选择")!.trigger("click")
}

describe("BrowseView 多选与下载", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("viewer 底部条只有下载；admin 有下载+删除", async () => {
    const v = await mountView("viewer", 100, 2)
    await enterSelection(v.w)
    expect(v.w.text()).toContain("下载 ZIP")
    expect(v.w.findAll("button").some((b) => b.text().includes("移入回收站"))).toBe(false)

    const a = await mountView("admin", 100, 2)
    await enterSelection(a.w)
    expect(a.w.text()).toContain("下载 ZIP")
    expect(a.w.findAll("button").some((b) => b.text().includes("移入回收站"))).toBe(true)
  })

  it("下载：POST 拿票据后用 <a> 原生下载", async () => {
    const { w, fetchFn } = await mountView("admin", 100, 2)
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    await enterSelection(w)
    const grid = w.findComponent(JustifiedGrid)
    grid.vm.$emit("toggle-select", 1)
    grid.vm.$emit("toggle-select", 2)
    await flushPromises()
    await w.findAll("button").find((b) => b.text().includes("下载 ZIP"))!.trigger("click")
    await flushPromises()

    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const post = calls.find((c) => c[0] === "/api/download-batch" && c[1]?.method === "POST")!
    expect(JSON.parse(post[1]!.body as string)).toEqual({ image_ids: [1, 2] })
    const anchor = clickSpy.mock.instances[0] as unknown as HTMLAnchorElement
    expect(anchor.href).toContain("/api/download-batch/TICK")
    expect(anchor.getAttribute("download")).toBe("photos-test.zip")
  })

  it("超过 me 下发的上限：alert 且不发请求", async () => {
    const { w, fetchFn } = await mountView("admin", 1, 2)
    vi.stubGlobal("alert", vi.fn())
    await enterSelection(w)
    w.findComponent(JustifiedGrid).vm.$emit("toggle-select", 1)
    w.findComponent(JustifiedGrid).vm.$emit("toggle-select", 2)
    await flushPromises()
    await w.findAll("button").find((b) => b.text().includes("下载 ZIP"))!.trigger("click")
    expect(window.alert).toHaveBeenCalled()
    expect((fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>)
      .some((c) => c[0] === "/api/download-batch")).toBe(false)
  })

  it("选择集跨翻页保留；第 201 张被 toast 拒绝", async () => {
    const { w } = await mountView("admin", 100, 201)
    const toast = useToastStore()
    await enterSelection(w)
    w.findComponent(JustifiedGrid).vm.$emit("toggle-select", 1)
    await flushPromises()

    // 翻到第 2 页：选择模式与已选计数保留
    w.findComponent(PaginationBar).vm.$emit("change", 2)
    await flushPromises()
    await flushPromises()
    expect(w.text()).toContain("已选 1 项")

    // 在第 2 页补选第 201 张之前，先用事件把 2..200 选满
    const grid = w.findComponent(JustifiedGrid)
    for (let i = 2; i <= 200; i++) grid.vm.$emit("toggle-select", i)
    grid.vm.$emit("toggle-select", 201)
    await flushPromises()
    expect(toast.items.some((t) => t.text.includes("200"))).toBe(true)
    expect(w.text()).toContain("已选 200 项")
  })
})
