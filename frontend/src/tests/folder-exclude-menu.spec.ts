import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import SubfolderStrip from "../components/SubfolderStrip.vue"

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
