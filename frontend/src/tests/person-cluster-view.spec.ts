import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent } from "vue"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import PersonClusterView from "../views/PersonClusterView.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import { useAuthStore } from "../stores/auth"

beforeAll(() => {
  // jsdom 缺 ResizeObserver（JustifiedGrid 排版依赖）
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

const CLUSTERS = [
  { cluster_id: "P001", display_name: "张三", sample_face_id: null, image_count: 3 },
]

const IMG_11 = {
  id: 11, filename: "a.jpg", width: 400, height: 300, sha1: "s11",
  taken_at: 1709251200, size_bytes: 100, mtime: 1700000000, is_raw: false,
  scene_major: null, scene_minor: null,
  gallery_id: 7, root_id: 9, gallery_name: "家庭相册", folder_path: "2024/旅行",
}
const IMG_12 = {
  ...IMG_11, id: 12, filename: "b.jpg", sha1: "s12", folder_path: "",
}
const IMG_13 = {
  ...IMG_11, id: 13, filename: "c.jpg", sha1: "s13", taken_at: null, folder_path: "",
}

const GROUP_RESPONSE = {
  total: 3,
  groups: [
    { year: 2024, month: 3, images: [IMG_11, IMG_12] },
    { year: 0, month: 0, images: [IMG_13] },
  ],
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

// 视图在 Task 3 才挂载真灯箱；桩提前注册，未匹配时无副作用
const LightboxStub = defineComponent({
  name: "ImageLightbox",
  props: ["items", "startId", "locationResolver"],
  emits: ["close", "change", "deleted", "viewInFolder"],
  template: `<div class="lb-stub" />`,
})

async function mountView(opts: { preserveStorage?: boolean } = {}) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const u = String(input)
    const method = init?.method ?? "GET"
    if (method === "DELETE" && u.includes("/api/images/")) {
      return new Response(null, { status: 204 })
    }
    if (u.includes("/api/tags/clusters/P001/images")) return json(GROUP_RESPONSE)
    if (u.includes("/api/tags/clusters")) return json(CLUSTERS)
    return json({ error: { code: "not_found", message: "x" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({
    user: { id: 1, username: "u", role: "admin", access_scope: "lan_only" },
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/people", component: { template: "<div/>" } },
      { path: "/galleries", component: { template: "<div/>" } },
      { path: "/galleries/:gid/r/:rid/:path(.*)*", component: { template: "<div/>" } },
    ],
  })
  await router.push("/people")
  // 默认每次挂载给干净的 localStorage；持久化用例需要预置值时传 preserveStorage
  if (!opts.preserveStorage) localStorage.clear()
  const w = mount(PersonClusterView, {
    global: { plugins: [router], stubs: { ImageLightbox: LightboxStub } },
  })
  await flushPromises()
  await flushPromises()
  return { w, router, fetchFn }
}

describe("PersonClusterView", () => {
  beforeEach(() => {
    // unstub 会清掉 beforeAll 的 ResizeObserver 桩，必须立刻重建，
    // 否则 JustifiedGrid 挂载时 new ResizeObserver 抛错（同 browse-search 模式）
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
    localStorage.clear()
  })

  it("按年/月组渲染 justified 网格，默认不显示文件名与位置角标", async () => {
    const { w } = await mountView()
    expect(w.findAllComponents(JustifiedGrid).length).toBe(2)
    expect(w.text()).toContain("2024年3月")
    expect(w.text()).toContain("未知日期")
    expect(w.findAll("img").some((im) => im.attributes("alt") === "a.jpg")).toBe(true)
    expect(w.findAll(".lb-cell-filename").length).toBe(0)
    expect(w.findAll(".lb-cell-badge").length).toBe(0)
  })

  it("信息开关：显示文件名与位置角标，文本区分根目录/子目录并持久化", async () => {
    let { w } = await mountView()
    const toggle = w.get('button[aria-label="缩略图上显示文件名与所在位置"]')
    await toggle.trigger("click")
    await flushPromises()
    expect(w.findAll(".lb-cell-filename").length).toBe(3)
    const badges = w.findAll(".lb-cell-badge").map((b) => b.text()).sort()
    expect(badges).toEqual(
      ["家庭相册", "家庭相册", "家庭相册/2024/旅行"].sort(),
    )
    expect(localStorage.getItem("people.grid.showInfo")).toBe("1")
    // 再点一次关闭
    await toggle.trigger("click")
    expect(w.findAll(".lb-cell-badge").length).toBe(0)
    // 重新挂载：localStorage 中的开启态被恢复
    localStorage.setItem("people.grid.showInfo", "1")
    ;({ w } = await mountView({ preserveStorage: true }))
    expect(w.findAll(".lb-cell-filename").length).toBe(3)
  })

  /** 打开第一张缩略图对应的灯箱（PhotoCell 内无 aria-label 的主按钮）。 */
  async function openFirstCellLightbox(
    w: Awaited<ReturnType<typeof mountView>>["w"],
  ) {
    const cellBtn = w.findAll(".lb-grid-cell button")
      .find((b) => !b.attributes("aria-label"))!
    await cellBtn.trigger("click")
    await flushPromises()
    return w.findComponent(LightboxStub)
  }

  it("点缩略图开灯箱：items 为全簇拍平列表、startId 为所点图片", async () => {
    const { w } = await mountView()
    const lb = await openFirstCellLightbox(w)
    expect(lb.exists()).toBe(true)
    const ids = (lb.props("items") as Array<{ id: number }>).map((it) => it.id)
    expect(ids).toEqual([11, 12, 13])
    expect(lb.props("startId")).toBe(11)
  })

  it("locationResolver：子目录返回图库/路径，根目录只返回图库名", async () => {
    const { w } = await mountView()
    const lb = await openFirstCellLightbox(w)
    const resolver = lb.props("locationResolver") as (it: typeof IMG_11) => string
    expect(resolver(IMG_11)).toBe("家庭相册/2024/旅行")
    expect(resolver(IMG_12)).toBe("家庭相册")
  })

  it("viewInFolder 跳到对应图库/根/文件夹，根目录路径无尾斜杠", async () => {
    const { w, router } = await mountView()
    const lb = await openFirstCellLightbox(w)
    lb.vm.$emit("viewInFolder", IMG_11)
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(
      "/galleries/7/r/9/2024/%E6%97%85%E8%A1%8C",
    )
    lb.vm.$emit("viewInFolder", IMG_12)
    await flushPromises()
    expect(router.currentRoute.value.path).toBe("/galleries/7/r/9")
  })

  it("网格菜单删除：确认后调 DELETE、本地摘除图片并重拉簇列表", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const { w, fetchFn } = await mountView()
    const menuBtn = w.findAll(".lb-cell-menu-btn")[0]
    await menuBtn.trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")
    await flushPromises()
    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    expect(calls.some(
      ([u, init]) => init?.method === "DELETE" && u.includes("/api/images/11"),
    )).toBe(true)
    expect(w.findAll("img").some((im) => im.attributes("alt") === "a.jpg")).toBe(false)
    // 初始 1 次簇列表 + 删除收尾再拉 1 次（images 路径不以 bare clusters 结尾）
    const clusterCalls = calls.filter(([u]) => u.endsWith("/api/tags/clusters"))
    expect(clusterCalls.length).toBeGreaterThanOrEqual(2)
  })

  it("灯箱 deleted 事件：摘除图片并关闭灯箱", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const { w } = await mountView()
    let lb = await openFirstCellLightbox(w)
    expect(lb.exists()).toBe(true)
    lb.vm.$emit("deleted", 11)
    await flushPromises()
    lb = w.findComponent(LightboxStub)
    expect(lb.exists()).toBe(false)
    expect(w.findAll("img").some((im) => im.attributes("alt") === "a.jpg")).toBe(false)
  })
})
