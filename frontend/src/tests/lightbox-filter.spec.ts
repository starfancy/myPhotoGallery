/**
 * Lightbox "风格滤镜"（filter-preview）按钮测试。
 *
 * 直接复用 lightbox-original.spec.ts 的 MockPhotoSwipe 骨架：
 * mock 整个 photoswipe 模块，暴露实例本身，捕获所有 registerElement 调用，
 * 测试可手动 btn.onClick!() 断言 window.open 行为。
 *   - 顶栏注册 name="filter-preview" 按钮（ariaLabel/isButton）
 *   - 点击以当前项 sha1/filename 打开 /filter-preview?<query> 新标签页
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

interface UIRegistration {
  name: string
  ariaLabel?: string
  isButton?: boolean
  tagName?: string
  className?: string
  appendTo?: string
  onClick?: () => void
  onInit?: (el: HTMLElement) => void
}

interface MockInstance {
  opts: { dataSource: any[] }
  handlers: Record<string, ((payload?: any) => void)[]>
  filters: Record<string, ((def: unknown, ...args: any[]) => unknown)[]>
  registered: UIRegistration[]
  currIndex: number
  currSlide: any
  zoomTo: ReturnType<typeof vi.fn>
  dispatch: (evt: string, payload?: any) => void
}

const instances: MockInstance[] = []

vi.mock("photoswipe", () => {
  class MockPhotoSwipe {
    _inst: MockInstance
    ui: { registerElement: (o: UIRegistration) => void }
    constructor(opts: { dataSource: any[] }) {
      const inst: MockInstance = {
        opts,
        handlers: {},
        filters: {},
        registered: [],
        currIndex: 0,
        currSlide: undefined,
        zoomTo: vi.fn(),
        dispatch: (evt, payload) => {
          ;(inst.handlers[evt] ?? []).forEach((cb) => cb(payload))
        },
      }
      this._inst = inst
      this.ui = {
        registerElement: (o) => {
          inst.registered.push(o)
          // 模拟真实 UI：为带 onInit 的元素创建 DOM 并回调
          if (o.onInit) {
            const el = document.createElement(o.tagName ?? "button")
            if (o.className) el.className = o.className
            document.body.appendChild(el)
            o.onInit(el)
          }
        },
      }
      instances.push(inst)
    }
    on(evt: string, cb: (payload?: any) => void) {
      ;(this._inst.handlers[evt] ??= []).push(cb)
    }
    addFilter(name: string, fn: (def: unknown, ...args: any[]) => unknown) {
      ;(this._inst.filters[name] ??= []).push(fn)
    }
    init() {
      this._inst.dispatch("uiRegister")
    }
    get currIndex() {
      return this._inst.currIndex
    }
    set currIndex(v) {
      this._inst.currIndex = v
    }
    get currSlide() {
      return this._inst.currSlide
    }
    set currSlide(v) {
      this._inst.currSlide = v
    }
    zoomTo(...args: any[]) {
      this._inst.zoomTo(...(args as [any]))
    }
  }
  return { default: MockPhotoSwipe }
})
vi.mock("photoswipe/style.css", () => ({}))

import ImageLightbox from "../components/ImageLightbox.vue"

const ITEMS = [
  {
    id: 1, sha1: "abc", filename: "IMG_0001.jpg",
    width: 4000, height: 3000, size_bytes: 1024,
  },
]

describe("lightbox filter-preview button", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    instances.length = 0
    vi.stubGlobal("open", vi.fn())
  })

  it("registers a 'filter-preview' button in the top bar", async () => {
    mount(ImageLightbox, { props: { items: ITEMS as any, startId: 1 } })
    await flushPromises()
    const inst = instances[0]
    const btn = inst.registered.find((r) => r.name === "filter-preview")
    expect(btn).toBeTruthy()
    expect(btn!.ariaLabel).toBe("风格滤镜")
    expect(btn!.isButton).toBe(true)
  })

  it("opens /filter-preview with sha1 and filename on click", async () => {
    mount(ImageLightbox, { props: { items: ITEMS as any, startId: 1 } })
    await flushPromises()
    const inst = instances[0]
    const btn = inst.registered.find((r) => r.name === "filter-preview")!
    btn.onClick!()
    expect(window.open).toHaveBeenCalledWith(
      expect.stringContaining("/filter-preview?sha1=abc"),
      "_blank", "noopener",
    )
    expect(window.open).toHaveBeenCalledWith(
      expect.stringContaining("name=IMG_0001.jpg"),
      "_blank", "noopener",
    )
  })
})
