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

// mock fetch：/api/luts 分组清单 + 每支 /api/luts/{slug}/cube
vi.stubGlobal(
  "fetch",
  vi.fn(async (url: string) => {
    if (url === "/api/luts") {
      return {
        ok: true,
        json: async (): Promise<unknown> => [
          {
            group: "synthetic",
            items: [{ slug: "warm", label: "暖色调", sort_order: 0 }],
          },
        ],
      }
    }
    if (url.includes("/cube")) {
      return {
        ok: true,
        text: async (): Promise<string> => "LUT_3D_SIZE 1\n0.1 0.2 0.3",
      }
    }
    return { ok: false, status: 404, text: async (): Promise<string> => "", json: async (): Promise<unknown> => ({}) }
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

  it("original-size download button rendered only when image_id present", () => {
    // 当前文件级 mock 的 useRoute 没有 image_id（见顶部 vi.mock），
    // 所以"原尺寸下载"按钮应被禁用（:disabled="!imageId"）。
    const w = mount(FilterPreviewView)
    const origBtn = w.findAll("button").find((b) => b.text().includes("原尺寸"))
    expect(origBtn).toBeTruthy()
    expect(origBtn!.attributes("disabled")).toBeDefined()
  })

  it("strip toggle hides thumbnail strip", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    const toggle = w.find('button[data-test="strip-toggle"]')
    // 默认展开：按钮文案"收起"，section 无内联 display
    expect(toggle.text()).toContain("收起")
    expect(w.find("section.fp-strip").attributes("style")).toBeUndefined()
    await toggle.trigger("click")
    await flushPromises()
    // v-show 折叠：内联 display:none，按钮文案切换
    expect(toggle.text()).toContain("滤镜")
    expect(w.find("section.fp-strip").attributes("style")).toBe("display: none;")
  })

  it("竖版图片的小样 viewport 保持源图宽高比，不被拉伸", async () => {
    // 改用竖版 3:4 的 Image mock；结束后恢复文件级横版 mock
    vi.stubGlobal("Image", class {
      onload: (() => void) | null = null
      set src(_url: string) {
        queueMicrotask(() => {
          ;(this as unknown as { width: number }).width = 300
          ;(this as unknown as { height: number }).height = 400
          this.onload?.()
        })
      }
    })
    try {
      mount(FilterPreviewView)
      await flushPromises()
      await flushPromises()
      // 小样 renderer 是第二个实例（主 renderer 之后在 renderThumbs 中创建）
      const thumb = instances()[1] as unknown as {
        setViewport: ReturnType<typeof vi.fn>
      }
      expect(thumb).toBeTruthy()
      const [w, h] = thumb.setViewport.mock.calls[0]
      expect(h).toBe(128) // 竖版以高度 128 为约束
      expect(w).toBe(96) // 128 × 300/400 = 96
      expect(w / h).toBeCloseTo(300 / 400, 2)
    } finally {
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
    }
  })

  it("shows fallback when renderer constructor throws", async () => {
    // spy 必须 restore：否则 lutMod.LutRenderer 被替换成无静态 instances 的
    // 包装函数，会让后续用例 beforeEach 的 instances().length=0 抛错
    const spy = vi.spyOn(lutMod, "LutRenderer").mockImplementationOnce(() => {
      throw new Error("WebGL2 not available")
    })
    try {
      const w = mount(FilterPreviewView)
      await flushPromises()
      expect(w.text()).toContain("WebGL2")
    } finally {
      spy.mockRestore()
    }
  })

  it("工具栏三栏：侧栏按钮存在，初始侧栏隐藏、底部条可见", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    const sideBtn = w.find('[data-test="side-toggle"]')
    expect(sideBtn.exists()).toBe(true)
    expect(sideBtn.text()).toContain("◀")
    // v-show=false：元素在但 display:none
    expect(w.find("aside.fp-side").attributes("style")).toContain("display: none")
    expect(w.find("section.fp-strip").attributes("style")).toBeUndefined()
  })

  it("侧栏与底部条互斥：开侧栏关底部条，开底部条关侧栏", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    await w.get('[data-test="side-toggle"]').trigger("click")
    await flushPromises()
    expect(w.find("aside.fp-side").attributes("style") ?? "").not.toContain("display: none")
    expect(w.find("section.fp-strip").attributes("style")).toContain("display: none")

    await w.get('[data-test="strip-toggle"]').trigger("click")
    await flushPromises()
    expect(w.find("section.fp-strip").attributes("style") ?? "").not.toContain("display: none")
    expect(w.find("aside.fp-side").attributes("style")).toContain("display: none")
  })

  it("竖向手柄具备 separator ARIA 语义", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    const h = w.find(".fp-side-handle")
    expect(h.attributes("role")).toBe("separator")
    expect(h.attributes("aria-orientation")).toBe("vertical")
    expect(h.attributes("tabindex")).toBe("0")
    expect(h.attributes("aria-label")).toBe("调节左侧滤镜栏宽度")
  })

  it("侧栏键盘调宽：→/← 步进、Home 最窄、End 半屏并钳制", async () => {
    // 宽度钳制基于 innerWidth；用 getter spy 而非 stubGlobal，避免清掉文件级 Image stub
    const wSpy = vi.spyOn(window, "innerWidth", "get").mockReturnValue(800)
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ width: 200 } as DOMRect)
    const csSpy = vi
      .spyOn(window, "getComputedStyle")
      .mockReturnValue({
        paddingLeft: "12px", paddingRight: "12px",
        paddingTop: "8px", paddingBottom: "12px",
      } as CSSStyleDeclaration)
    try {
      const w = mount(FilterPreviewView)
      await flushPromises()
      // 最小宽 = 缩略图 96 + 左右 padding 24 = 120
      Object.defineProperty(w.get(".fp-side .fp-thumb").element, "offsetWidth", {
        value: 96, configurable: true,
      })
      // 先打开侧栏
      await w.get('[data-test="side-toggle"]').trigger("click")
      const handle = w.find(".fp-side-handle")
      const side = () => w.find("aside.fp-side")

      await handle.trigger("keydown", { key: "ArrowRight" })
      expect(side().attributes("style")).toContain("width: 216px")
      await handle.trigger("keydown", { key: "ArrowLeft" })
      expect(side().attributes("style")).toContain("width: 200px")
      await handle.trigger("keydown", { key: "Home" })
      expect(side().attributes("style")).toContain("width: 120px")
      await handle.trigger("keydown", { key: "End" })
      expect(side().attributes("style")).toContain("width: 400px")
      expect(side().attributes("style")).toContain("max-width: 50vw")
    } finally {
      wSpy.mockRestore()
      rectSpy.mockRestore()
      csSpy.mockRestore()
    }
  })

  it("滤镜条高度手柄：ARIA 语义齐全，键盘可调高度并钳制", async () => {
    vi.stubGlobal("innerHeight", 800) // max = 400
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ height: 200 } as DOMRect)
    const csSpy = vi
      .spyOn(window, "getComputedStyle")
      .mockReturnValue({ paddingTop: "8px", paddingBottom: "12px" } as CSSStyleDeclaration)
    try {
      const w = mount(FilterPreviewView)
      await flushPromises()
      // 最小高度 = 组高 110 + 上下 padding 20 = 130。
      // 页面现有侧栏/底部条两个 LutGroupList，必须精确定位底部条内的分组
      Object.defineProperty(w.get("section.fp-strip .fp-group").element, "offsetHeight", {
        value: 110,
        configurable: true,
      })

      const handle = w.find(".fp-resize-handle")
      expect(handle.exists()).toBe(true)
      expect(handle.attributes("role")).toBe("separator")
      expect(handle.attributes("tabindex")).toBe("0")
      expect(handle.attributes("aria-orientation")).toBe("horizontal")
      expect(handle.attributes("aria-label")).toBe("调节滤镜列表高度")

      const strip = () => w.find("section.fp-strip")

      // ↓：200 - 16 = 184
      await handle.trigger("keydown", { key: "ArrowDown" })
      expect(strip().attributes("style")).toContain("height: 184px")
      expect(handle.attributes("aria-valuenow")).toBe("184")

      // ↑：184 + 16 = 200
      await handle.trigger("keydown", { key: "ArrowUp" })
      expect(strip().attributes("style")).toContain("height: 200px")

      // Home：最小实测值 130
      await handle.trigger("keydown", { key: "Home" })
      expect(strip().attributes("style")).toContain("height: 130px")

      // End：50vh = 400
      await handle.trigger("keydown", { key: "End" })
      expect(strip().attributes("style")).toContain("height: 400px")
      expect(strip().attributes("style")).toContain("max-height: 50vh")
    } finally {
      rectSpy.mockRestore()
      csSpy.mockRestore()
      vi.unstubAllGlobals()
    }
  })
})
