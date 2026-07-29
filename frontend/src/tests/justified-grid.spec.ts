import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import { useAuthStore } from "../stores/auth"

beforeAll(() => {
  // jsdom 缺 ResizeObserver
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

const items = [
  { id: 1, filename: "a.jpg", width: 400, height: 300, sha1: "sha1", size_bytes: 1, taken_at: null, is_raw: false },
  { id: 2, filename: "b.jpg", width: 400, height: 300, sha1: "sha2", size_bytes: 1, taken_at: null, is_raw: false },
]

async function mountGrid(role: "admin" | "viewer") {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({
    user: { id: 1, username: "u", role, access_scope: "lan_only" },
  })
  const w = mount(JustifiedGrid, {
    props: { items, canLoadMore: false },
  })
  await flushPromises()
  return w
}

describe("JustifiedGrid", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it("renders one thumbnail per item", async () => {
    const w = await mountGrid("viewer")
    expect(w.findAll("img").length).toBe(2)
  })

  it("does not render the three-dot menu button for viewer", async () => {
    const w = await mountGrid("viewer")
    expect(w.findAll('button[aria-label^="更多操作"]').length).toBe(0)
  })

  it("renders the three-dot menu button for admin", async () => {
    const w = await mountGrid("admin")
    const btns = w.findAll('button[aria-label^="更多操作"]')
    expect(btns.length).toBe(items.length)
  })

  it("emits open when the thumbnail button is clicked", async () => {
    const w = await mountGrid("admin")
    // 缩略图按钮 = 前两个 button（三点菜单是每格的第二个按钮）
    // 更稳的定位：找非 aria-label 的可点击按钮
    const cellButtons = w.findAll("button").filter(
      (b) => !b.attributes("aria-label")?.startsWith("更多操作"),
    ).slice(0, 2)
    await cellButtons[0].trigger("click")
    expect(w.emitted().open?.[0]).toEqual([1])
  })

  it("emits menuAction 'delete' after opening menu and clicking the item", async () => {
    const w = await mountGrid("admin")
    const menuBtn = w.findAll('button[aria-label^="更多操作"]')[1]
    await menuBtn.trigger("click")
    await flushPromises()
    const menuItem = w.get(".lb-cell-menu-item")
    expect(menuItem.text()).toContain("移入回收站")
    await menuItem.trigger("click")
    const events = w.emitted("menuAction") ?? []
    expect(events.length).toBe(1)
    expect(events[0]).toEqual([2, "delete"])
  })
})
