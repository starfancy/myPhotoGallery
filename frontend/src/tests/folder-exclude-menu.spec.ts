import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import SubfolderStrip from "../components/SubfolderStrip.vue"
import BrowseView from "../views/BrowseView.vue"
import { useAuthStore } from "../stores/auth"

interface FolderCard {
  name: string
  relative_path: string
  image_count: number
  descendant_count: number
  cover_thumb_sha1: string | null
  cover_source_name?: string | null
}

// VTU 的默认 RouterLink stub 不渲染插槽；用透传默认插槽的 a 标签占位。
const RouterLinkSlotStub = { template: "<a><slot /></a>" }

const FOLDERS: FolderCard[] = [
  { name: "旅行", relative_path: "trip", image_count: 3, descendant_count: 3, cover_thumb_sha1: null },
  { name: "日常", relative_path: "daily", image_count: 9, descendant_count: 9, cover_thumb_sha1: null },
]

function mountStrip(canExclude: boolean) {
  return mount(SubfolderStrip, {
    props: { folders: FOLDERS, gid: 1, rid: 1, canExclude },
    global: { stubs: { RouterLink: RouterLinkSlotStub } },
  })
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

describe("SubfolderStrip exclude menu", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders no three-dot button when canExclude is false/omitted", () => {
    const w = mountStrip(false)
    expect(w.findAll(".lb-folder-menu-btn").length).toBe(0)
  })

  it("opens the menu with a single '排除此文件夹' item for admins", async () => {
    const w = mountStrip(true)
    const btns = w.findAll(".lb-folder-menu-btn")
    expect(btns.length).toBe(2)

    await btns[0].trigger("click")
    await flushPromises()
    const items = w.findAll(".lb-cell-menu-item")
    expect(items.length).toBe(1)
    expect(items[0].text()).toBe("排除此文件夹")
  })

  it("emits exclude with the folder whose card opened the menu", async () => {
    const w = mountStrip(true)
    await w.findAll(".lb-folder-menu-btn")[1].trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")

    const events = w.emitted("exclude") ?? []
    expect(events.length).toBe(1)
    expect(events[0]).toEqual([FOLDERS[1]])
  })

  it("opens on right-click (contextmenu) when canExclude", async () => {
    const w = mountStrip(true)
    await w.findAll(".lb-folder-card")[0].trigger("contextmenu", { clientX: 12, clientY: 34 })
    await flushPromises()
    expect(w.find(".lb-cell-menu").exists()).toBe(true)
  })

  it("does not open a menu on right-click for non-admins", async () => {
    const w = mountStrip(false)
    await w.findAll(".lb-folder-card")[0].trigger("contextmenu")
    await flushPromises()
    expect(w.find(".lb-cell-menu").exists()).toBe(false)
  })

  it("opens on 550ms touch long-press", async () => {
    vi.useFakeTimers()
    try {
      const w = mountStrip(true)
      const card = w.findAll(".lb-folder-card")[0]
      // jsdom 无 TouchEvent 构造器：手工派发带 touches 的冒泡事件
      const ev = new Event("touchstart", { bubbles: true }) as Event & {
        touches: Array<{ clientX: number; clientY: number }>
      }
      ev.touches = [{ clientX: 10, clientY: 20 }]
      card.element.dispatchEvent(ev)

      vi.advanceTimersByTime(550)
      await w.findAll(".lb-folder-card")[0].trigger("touchend")
      expect(w.find(".lb-cell-menu").exists()).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it("cancels long-press when the finger moves before 550ms", async () => {
    vi.useFakeTimers()
    try {
      const w = mountStrip(true)
      const card = w.findAll(".lb-folder-card")[0]
      const ev = new Event("touchstart", { bubbles: true }) as Event & {
        touches: Array<{ clientX: number; clientY: number }>
      }
      ev.touches = [{ clientX: 10, clientY: 20 }]
      card.element.dispatchEvent(ev)

      await card.trigger("touchmove")
      vi.advanceTimersByTime(800)
      expect(w.find(".lb-cell-menu").exists()).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})

// ---------- BrowseView 端到端：确认 → POST relative_path → 局部刷新 ----------

const CRUMBS = [{ name: "R", relative_path: "" }]
const SERVER_FOLDERS = [
  { name: "旅行", relative_path: "trip", image_count: 0, descendant_count: 3, cover_thumb_sha1: null },
]
const IMAGES = [
  { id: 1, filename: "a.jpg", width: 400, height: 300, sha1: "sha-a", size_bytes: 1, taken_at: null, is_raw: false },
]

function jsonResponse(body: unknown, status = 200) {
  const isNull = body === null || body === undefined
  return new Response(isNull ? null : JSON.stringify(body),
    { status, headers: isNull ? {} : { "content-type": "application/json" } },
  )
}

async function mountBrowse(role: "admin" | "viewer") {
  // 服务端状态：排除 POST 只入队后台重扫，Folder 行要等 worker 重扫完成才
  // 被删除。因此 POST 之后立刻 GET folders 仍返回该文件夹（真实时序窗口）。
  const folders = SERVER_FOLDERS.map((x) => ({ ...x }))
  const excludeBodies: unknown[] = []
  let parentFolderGets = 0
  const fetchFn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : (input as Request).url ?? String(input)
    const method = init?.method ?? "GET"
    if (method === "GET" && url.includes("/breadcrumbs")) return jsonResponse(CRUMBS)
    if (method === "GET" && url.includes("/folders")) {
      // path=trip 是 enrichBorrowedCovers 的直接子级补查；父列表即使在
      // POST 之后也持续返回该文件夹，模拟重扫未完成。
      if (!url.includes("path=trip")) parentFolderGets += 1
      return jsonResponse(url.includes("path=trip") ? [] : folders.map((x) => ({ ...x })))
    }
    if (method === "GET" && url.includes("/images")) {
      return jsonResponse({ items: IMAGES, total: IMAGES.length })
    }
    if (method === "POST" && /\/exclusions$/.test(url)) {
      excludeBodies.push(JSON.parse(init?.body as string))
      return jsonResponse({ id: 99, relative_path: "trip", reason: null })
    }
    return jsonResponse({ error: { code: "not_found", message: "not mocked" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)

  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({ user: { id: 1, username: "u", role, access_scope: "lan_only" } })

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
  await flushPromises()  // 网格 onMounted 又等一轮
  return { w, fetchFn, excludeBodies, getParentFolderGets: () => parentFolderGets }
}

describe("BrowseView folder quick exclude", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("shows the folder ellipsis for admin but not for viewer", async () => {
    const admin = await mountBrowse("admin")
    expect(admin.w.findAll('button[aria-label^="排除文件夹"]').length).toBe(1)

    const viewer = await mountBrowse("viewer")
    expect(viewer.w.findAll('button[aria-label^="排除文件夹"]').length).toBe(0)
  })

  it("optimistically removes the card even before the rescan completes", async () => {
    const { w, fetchFn, excludeBodies, getParentFolderGets } = await mountBrowse("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
    const getsBefore = getParentFolderGets()
    expect(getsBefore).toBe(1)  // 仅挂载时一次

    await w.get('button[aria-label^="排除文件夹"]').trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")
    await flushPromises()
    await flushPromises()

    expect(window.confirm).toHaveBeenCalledTimes(1)
    const confirmText = (window.confirm as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    expect(confirmText).toContain("旅行")
    expect(confirmText).toContain("不会被删除")

    expect(excludeBodies).toEqual([{ relative_path: "trip" }])
    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const post = calls.find(
      (c) => c[1]?.method === "POST" && c[0] === "/api/admin/galleries/1/roots/1/exclusions",
    )
    expect(post).toBeDefined()

    // 服务端重扫窗口内 GET folders 仍会返回该文件夹，但卡片必须立即消失，
    // 且成功后不再发起会把卡片“加回来”的父列表重拉。
    expect(w.findAll('button[aria-label^="排除文件夹"]').length).toBe(0)
    expect(getParentFolderGets()).toBe(getsBefore)
    // 图片分页不受影响
    expect(w.findAll("img").length).toBeGreaterThanOrEqual(1)
  })

  it("sends no POST when the confirm is cancelled", async () => {
    const { w, excludeBodies } = await mountBrowse("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false))

    await w.get('button[aria-label^="排除文件夹"]').trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")
    await flushPromises()

    expect(excludeBodies.length).toBe(0)
    expect(w.findAll('button[aria-label^="排除文件夹"]').length).toBe(1)
  })

  it("alerts with the server message when the POST fails (e.g. 409)", async () => {
    const { w } = await mountBrowse("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
    const alertSpy = vi.fn()
    vi.stubGlobal("alert", alertSpy)
    // 挂载已完成；替换 fetch：exclusions POST 返回 409
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.includes("/exclusions")) {
        return jsonResponse(
          { error: { code: "conflict", message: "this directory is already excluded" } },
          409,
        )
      }
      return jsonResponse({ error: { code: "not_found", message: "not mocked" } }, 404)
    }))

    await w.get('button[aria-label^="排除文件夹"]').trigger("click")
    await flushPromises()
    await w.get(".lb-cell-menu-item").trigger("click")
    await flushPromises()

    expect(alertSpy).toHaveBeenCalledTimes(1)
    expect(alertSpy.mock.calls[0][0]).toContain("排除失败")
    expect(alertSpy.mock.calls[0][0]).toContain("already excluded")
  })
})
