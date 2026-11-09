import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"

// mock 路由：直接返回 query，无需真实 router 插件
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: { sha1: "abc123", name: "IMG_0001.jpg" } }),
  useRouter: () => ({ replace: vi.fn() }),
}))

// mock LutRenderer：构造时记录 canvas，方法都是 vi.fn。
// 类定义放在 factory 内部，避免 vi.mock 提升导致的 TDZ 问题。
vi.mock("../lib/lutRenderer", () => {
  class MockRenderer {
    static instances: MockRenderer[] = []
    setImage = vi.fn()
    setViewport = vi.fn()
    loadLut = vi.fn()
    render = vi.fn()
    exportJpeg = vi.fn(async () => new Blob(["x"], { type: "image/jpeg" }))
    dispose = vi.fn()
    constructor(public canvas: HTMLCanvasElement) {
      MockRenderer.instances.push(this)
    }
  }
  return { LutRenderer: MockRenderer }
})

// mock 图片加载：new Image() → 立即触发 onload
vi.stubGlobal("Image", class {
  onload: (() => void) | null = null
  set src(_url: string) {
    queueMicrotask(() => {
      ;(this as unknown as { width: number }).width = 1600
      ;(this as unknown as { height: number }).height = 1000
      this.onload?.()
    })
  }
})

// mock fetch：manifest + 1 个 cube
vi.stubGlobal(
  "fetch",
  vi.fn(async (url: string) => {
    if (url.includes("manifest")) {
      const list = [{ id: "warm", label: "暖色调", file: "warm.cube" }]
      return {
        ok: true,
        json: async (): Promise<unknown> => list,
        text: async (): Promise<string> => JSON.stringify(list),
      }
    }
    return {
      ok: true,
      text: async (): Promise<string> => "LUT_3D_SIZE 1\n0.1 0.2 0.3",
    }
  }),
)

import FilterPreviewView from "../views/FilterPreviewView.vue"
const lutMod = await import("../lib/lutRenderer")

type MockInstance = { setImage: ReturnType<typeof vi.fn> }
function instances(): MockInstance[] {
  return (lutMod.LutRenderer as unknown as { instances: MockInstance[] })
    .instances
}

describe("FilterPreviewView", () => {
  beforeAll(() => {
    // jsdom 未实现 toDataURL，视图在小样循环里会调一次；给个桩避免 stderr 噪音
    HTMLCanvasElement.prototype.toDataURL = () => "data:image/jpeg;base64,x"
  })
  beforeEach(() => {
    instances().length = 0
  })

  it("loads image from /api/thumb/{sha1}?size=1600", async () => {
    mount(FilterPreviewView)
    await flushPromises()
    expect(instances()[0]?.setImage).toHaveBeenCalled()
  })

  it("renders filename from query in header", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    expect(w.text()).toContain("IMG_0001.jpg")
  })

  it("renders thumbnails on an offscreen small canvas, not the main canvas", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    // 主 renderer 的最后一次 render 必须是 render(0)（回到原图），
    // 而不是停留在小样循环的 render(1)。
    const r = instances()[0] as unknown as { render: ReturnType<typeof vi.fn> }
    expect(r.render).toHaveBeenLastCalledWith(0)
    // 主 canvas 本身不被 toDataURL —— 点击任何小样触发 pick 后也不应碰
    const mainCanvas = w.find("canvas").element as HTMLCanvasElement
    const spy = vi.spyOn(mainCanvas, "toDataURL")
    const btns = w.findAll("button.fp-thumb")
    await btns[0]?.trigger("click")
    expect(spy).not.toHaveBeenCalled()
  })

  it("shows fallback when renderer constructor throws", async () => {
    vi.spyOn(lutMod, "LutRenderer").mockImplementationOnce(() => {
      throw new Error("WebGL2 not available")
    })
    const w = mount(FilterPreviewView)
    await flushPromises()
    expect(w.text()).toContain("WebGL2")
  })
})
