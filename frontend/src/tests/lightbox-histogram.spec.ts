/**
 * Lightbox 直方图面板测试。
 *
 * 与 EXIF 测试同样 mock 掉 photoswipe（jsdom 无法运行）。
 * 直方图计算模块 (`lib/histogram`) 也整体 mock：真正的
 * `computeHistogramFromUrl` 需要 Image + canvas + getImageData，jsdom
 * 都不支持；在这里只关心面板生命周期、共享容器布局和缓存行为。
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

interface UIRegistration {
  name: string
  ariaLabel: string
  onClick?: () => void
}
interface MockState {
  registered: UIRegistration[]
  uiRegisterHandler: (() => void) | null
  changeHandler: (() => void) | null
  currIndex: number
  reset: () => void
}
const mockState: MockState = {
  registered: [],
  uiRegisterHandler: null,
  changeHandler: null,
  currIndex: 0,
  reset() {
    this.registered = []
    this.uiRegisterHandler = null
    this.changeHandler = null
    this.currIndex = 0
  },
}

vi.mock("photoswipe", () => {
  class MockPhotoSwipe {
    // 让实例读到共享的 currIndex，测试可通过 mockState.currIndex 模拟翻页
    get currIndex() { return mockState.currIndex }
    currSlide = { data: {} }
    ui = {
      registerElement: (opts: UIRegistration) => {
        mockState.registered.push(opts)
      },
    }
    constructor(_opts: unknown) {}
    on(evt: string, cb: () => void) {
      if (evt === "uiRegister") mockState.uiRegisterHandler = cb
      if (evt === "change") mockState.changeHandler = cb
    }
    init() {
      mockState.uiRegisterHandler?.()
    }
    goTo(i: number) {
      mockState.currIndex = i
      mockState.changeHandler?.()
    }
    close() {}
    destroy() {}
  }
  return { default: MockPhotoSwipe }
})
vi.mock("photoswipe/style.css", () => ({}))

// 全模块 mock 直方图库；测试直接控制返回值
const histCompute = vi.fn()
const histDraw = vi.fn()
vi.mock("../lib/histogram", () => ({
  computeHistogramFromUrl: (url: string, opts?: unknown) => histCompute(url, opts),
  drawHistogram: (canvas: HTMLCanvasElement, hist: unknown) => histDraw(canvas, hist),
}))

import ImageLightbox from "../components/ImageLightbox.vue"
import { useAuthStore } from "../stores/auth"

const IMAGES = [
  { id: 1, filename: "a.jpg", width: 400, height: 300, sha1: "sha-a", size_bytes: 1, taken_at: null, is_raw: false },
  { id: 2, filename: "b.jpg", width: 400, height: 300, sha1: "sha-b", size_bytes: 1, taken_at: null, is_raw: false },
]

function fakeHist(mean = 128) {
  return {
    r: new Uint32Array(256),
    g: new Uint32Array(256),
    b: new Uint32Array(256),
    samples: 1000,
    meanR: mean,
    meanG: mean,
    meanB: mean,
  }
}

async function mountLightbox() {
  mockState.reset()
  histCompute.mockReset()
  histDraw.mockReset()
  document.body.innerHTML = ""

  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({ user: { id: 1, username: "u", role: "viewer", access_scope: "lan_only" } })

  const w = mount(ImageLightbox, { props: { items: IMAGES, startId: 1 } })
  await flushPromises()
  return w
}

function findElement(name: string) {
  return mockState.registered.find((r) => r.name === name)
}

describe("ImageLightbox — histogram panel", () => {
  beforeEach(() => {
    document.body.innerHTML = ""
  })

  it("registers 'histogram' button", async () => {
    await mountLightbox()
    expect(findElement("histogram")).toBeDefined()
  })

  it("opens histogram panel and renders stats + calls drawHistogram", async () => {
    await mountLightbox()
    histCompute.mockResolvedValue(fakeHist(120.4))

    findElement("histogram")!.onClick!()
    await flushPromises()

    const panel = document.querySelector(".lb-hist-panel")
    expect(panel).not.toBeNull()
    const text = panel!.textContent ?? ""
    expect(text).toContain("直方图")
    expect(text).toContain("R 均值")
    expect(text).toContain("120.4")
    // drawHistogram 被调用一次，参数是 canvas + hist
    expect(histDraw).toHaveBeenCalledTimes(1)
    expect(histDraw.mock.calls[0][0]).toBeInstanceOf(HTMLCanvasElement)
  })

  it("uses /api/thumb/{sha1}?size=400 as sampling source", async () => {
    await mountLightbox()
    histCompute.mockResolvedValue(fakeHist())
    findElement("histogram")!.onClick!()
    await flushPromises()
    expect(histCompute).toHaveBeenCalledWith(
      "/api/thumb/sha-a?size=400",
      expect.objectContaining({ stride: 2 }),
    )
  })

  it("caches histogram by image_id: reopening same image does NOT recompute", async () => {
    await mountLightbox()
    histCompute.mockResolvedValue(fakeHist())
    findElement("histogram")!.onClick!()
    await flushPromises()
    expect(histCompute).toHaveBeenCalledTimes(1)

    // 关闭再开同一张
    document.querySelector<HTMLButtonElement>(".lb-hist-close")!.click()
    expect(document.querySelector(".lb-hist-panel")).toBeNull()
    findElement("histogram")!.onClick!()
    await flushPromises()
    expect(histCompute).toHaveBeenCalledTimes(1) // 命中缓存
    expect(document.querySelector(".lb-hist-panel")).not.toBeNull()
  })

  it("shows error message when computation fails", async () => {
    await mountLightbox()
    histCompute.mockRejectedValue(new Error("decode failed"))
    findElement("histogram")!.onClick!()
    await flushPromises()
    expect(document.querySelector(".lb-hist-panel")!.textContent).toContain("直方图计算失败")
  })

  it("EXIF + histogram share one container with EXIF on top", async () => {
    await mountLightbox()

    // 先打开 histogram
    histCompute.mockResolvedValue(fakeHist())
    findElement("histogram")!.onClick!()
    await flushPromises()

    // 再打开 EXIF
    const fetchFn = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ image_id: 1, filename: "a.jpg", exif: { Make: "Nikon" } }),
      { status: 200, headers: { "content-type": "application/json" } },
    ))
    vi.stubGlobal("fetch", fetchFn)
    findElement("exif-info")!.onClick!()
    await flushPromises()

    const container = document.querySelector(".lb-side-panels")
    expect(container).not.toBeNull()
    const children = Array.from(container!.children)
    expect(children.length).toBe(2)
    // 顺序固定为 EXIF 在上、直方图在下
    expect(children[0].classList.contains("lb-exif-panel")).toBe(true)
    expect(children[1].classList.contains("lb-hist-panel")).toBe(true)
  })

  it("closing the last panel removes the shared container", async () => {
    await mountLightbox()
    histCompute.mockResolvedValue(fakeHist())
    findElement("histogram")!.onClick!()
    await flushPromises()
    expect(document.querySelector(".lb-side-panels")).not.toBeNull()

    document.querySelector<HTMLButtonElement>(".lb-hist-close")!.click()
    expect(document.querySelector(".lb-side-panels")).toBeNull()
  })

  it("changing slide recomputes histogram for the new image", async () => {
    await mountLightbox()
    histCompute.mockResolvedValue(fakeHist(100))
    findElement("histogram")!.onClick!()
    await flushPromises()
    expect(histCompute).toHaveBeenCalledTimes(1)

    // 模拟翻到第二张
    histCompute.mockResolvedValue(fakeHist(200))
    mockState.currIndex = 1
    mockState.changeHandler?.()
    await flushPromises()

    expect(histCompute).toHaveBeenCalledTimes(2)
    expect(histCompute.mock.calls[1][0]).toBe("/api/thumb/sha-b?size=400")
  })
})
