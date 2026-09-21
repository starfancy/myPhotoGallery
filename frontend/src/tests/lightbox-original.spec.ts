/**
 * Lightbox 原图按需加载 + 空闲预取测试。
 *
 * 与 lightbox-exif.spec.ts 类似 mock 整个 photoswipe 模块，但这个 mock
 * 暴露实例本身（handlers / currSlide / zoomTo），测试可手动派发
 * imageSizeChange、loadComplete、loadError、change 事件，断言：
 *   - 显示尺寸未超缩略图像素：不换图
 *   - 超过阈值：content reload 原图，完成后旧缩略图被移除
 *   - RAW：originalSrc=null，放大也不换
 *   - “查看原图”按钮：zoomTo(1) / 再次点击回到 fit
 *   - 缩略图完成后空闲预取；大文件 / saveData / 3g 网络不预取
 *   - 切图中止进行中的预取
 *   - 原图加载失败回退缩略图
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
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
import { useAuthStore } from "../stores/auth"

const JPG = {
  id: 1, filename: "a.jpg", width: 4000, height: 3000, sha1: "sha-a",
  size_bytes: 3 * 1024 * 1024, taken_at: null, is_raw: false,
}
const BIG_JPG = {
  id: 2, filename: "big.jpg", width: 6000, height: 4000, sha1: "sha-b",
  size_bytes: 8 * 1024 * 1024, taken_at: null, is_raw: false,
}
const RAW = {
  id: 3, filename: "c.CR2", width: 4000, height: 3000, sha1: "sha-c",
  size_bytes: 30 * 1024 *1024, taken_at: null, is_raw: true,
}

/** 构造一个绑定到 dataSource 第 dataIndex 项的测试 slide。 */
function makeSlide(inst: MockInstance, dataIndex = 0) {
  const data = inst.opts.dataSource[dataIndex]
  const container = document.createElement("div")
  document.body.appendChild(container)
  const oldImg = document.createElement("img")
  container.appendChild(oldImg)
  const content: {
    data: any
    element: HTMLElement
    load: (_lazy?: boolean, reload?: boolean) => void
  } = {
    data,
    element: oldImg,
    // 模拟真实 reload：先按 useContentPlaceholder filter 决定是否插入占位层，
    // 再把 content.element 换成未挂载的新 img
    load: vi.fn((_lazy?: boolean, reload?: boolean) => {
      if (!reload) return
      const usePlaceholder = (inst.filters.useContentPlaceholder ?? [])
        .reduce<boolean>((acc, f) => f(acc, content) as boolean, true)
      if (usePlaceholder) {
        const ph = document.createElement("div")
        ph.className = "pswp__img pswp__img--placeholder"
        container.appendChild(ph)
      }
      content.element = document.createElement("img")
    }),
  }
  const slide = {
    data, index: dataIndex, content, container,
    currZoomLevel: 0.3, zoomLevels: { initial: 0.3 },
  }
  return { slide, container, oldImg }
}

async function mountLightbox(items: typeof JPG[], startId = items[0].id) {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({ user: { id: 1, username: "u", role: "admin", access_scope: "lan_only" } })
  const w = mount(ImageLightbox, { props: { items, startId } })
  await flushPromises()
  const inst = instances[instances.length - 1]
  return { w, inst }
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {} unobserve() {} disconnect() {}
  })
  // 空闲回调立即执行，预取在调度当轮发生
  vi.stubGlobal("requestIdleCallback", (cb: () => void) => { cb(); return 1 })
  vi.stubGlobal("cancelIdleCallback", () => {})
})

beforeEach(() => {
  instances.length = 0
  document.body.innerHTML = ""
  // 清掉可能残留的网络标记
  const nav = navigator as any
  delete nav.saveData
  delete nav.connection
})

function findRegistered(inst: MockInstance, name: string) {
  return inst.registered.find((r) => r.name === name)
}

describe("ImageLightbox — 放大换原图", () => {
  it("dataSource 标注缩略图实际像素与原图 URL", async () => {
    const { inst } = await mountLightbox([JPG, RAW])
    const jpg = inst.opts.dataSource[0]
    expect(jpg.thumbW).toBe(1600)
    expect(jpg.thumbH).toBe(1200)
    expect(jpg.originalSrc).toBe("/api/image/1")
    // RAW 无原图 URL
    expect(inst.opts.dataSource[1].originalSrc).toBeNull()
  })

  it("显示尺寸未超缩略图像素时不换图", async () => {
    const { inst } = await mountLightbox([JPG])
    const { slide } = makeSlide(inst)
    inst.dispatch("imageSizeChange", { slide, width: 1500, height: 1125 })
    expect(slide.content.load).not.toHaveBeenCalled()
    expect(slide.data.src).toBe(slide.data.thumbSrc)
  })

  it("显示尺寸超过阈值时 reload 原图，完成后移除旧缩略图", async () => {
    const { inst } = await mountLightbox([JPG])
    const { slide, container, oldImg } = makeSlide(inst)

    // 1700 > 1600*1.05=1680 → 换图
    inst.dispatch("imageSizeChange", { slide, width: 1700, height: 1275 })
    expect(slide.content.load).toHaveBeenCalledWith(false, true)
    expect(slide.data.src).toBe("/api/image/1")
    expect(slide.data.originalLoading).toBe(true)
    expect(slide.data.oldThumbEl).toBe(oldImg)
    // 回归：reload 期间不得插入占位层（会盖住旧缩略图），旧图继续可见
    expect(container.querySelector(".pswp__img--placeholder")).toBeNull()
    expect(oldImg.parentNode).not.toBeNull()

    // 原图加载完成 → 新 img 挂到旧缩略图位置、旧图移除（不能只移除旧图，
    // 否则 Content.isAttached 导致新图永远无法挂载，画面空白）
    const newImg = slide.content.element
    expect(newImg).not.toBe(oldImg)
    expect(newImg.parentNode).toBeNull()
    inst.dispatch("loadComplete", { slide, isError: undefined })
    expect(slide.data.originalLoaded).toBe(true)
    expect(slide.data.originalLoading).toBe(false)
    expect(newImg.parentNode).toBe(container)
    expect(oldImg.parentNode).toBeNull()
  })

  it("useContentPlaceholder filter：首次加载保留，原图 reload 时关闭", async () => {
    const { inst } = await mountLightbox([JPG])
    const { slide } = makeSlide(inst)
    const fns = inst.filters.useContentPlaceholder
    expect(fns).toBeDefined()
    // 未换图：沿用默认（true）
    expect(fns![0](true, slide.content)).toBe(true)

    slide.data.originalLoading = true
    expect(fns![0](true, slide.content)).toBe(false)
  })

  it("放大后缩小不换回缩略图", async () => {
    const { inst } = await mountLightbox([JPG])
    const { slide } = makeSlide(inst)
    inst.dispatch("imageSizeChange", { slide, width: 1700, height: 1275 })
    inst.dispatch("loadComplete", { slide })
    // 回到 fit 尺寸
    inst.dispatch("imageSizeChange", { slide, width: 1500, height: 1125 })
    expect(slide.data.src).toBe("/api/image/1")
  })

  it("RAW 放大也不换图", async () => {
    const { inst } = await mountLightbox([RAW])
    const { slide } = makeSlide(inst)
    inst.dispatch("imageSizeChange", { slide, width: 1700, height: 1275 })
    expect(slide.content.load).not.toHaveBeenCalled()
    expect(slide.data.src).toBe(slide.data.thumbSrc)
  })

  it("原图加载失败时回退到缩略图", async () => {
    const { inst } = await mountLightbox([JPG])
    const { slide } = makeSlide(inst)
    inst.dispatch("imageSizeChange", { slide, width: 1700, height: 1275 })
    expect(slide.data.originalLoading).toBe(true)

    inst.dispatch("loadError", { slide })
    expect(slide.data.originalLoading).toBe(false)
    expect(slide.data.src).toBe(slide.data.thumbSrc)
    // 第二次 reload（恢复缩略图）
    expect(slide.content.load).toHaveBeenLastCalledWith(false, true)
  })

  it("“查看原图”按钮：zoomTo(1)，再次点击回到 initial", async () => {
    const { inst } = await mountLightbox([JPG])
    const { slide } = makeSlide(inst)
    inst.currSlide = slide
    const btn = findRegistered(inst, "original-image")!

    btn.onClick!()
    expect(inst.zoomTo).toHaveBeenLastCalledWith(1)

    slide.currZoomLevel = 1
    btn.onClick!()
    expect(inst.zoomTo).toHaveBeenLastCalledWith(0.3)
  })
})

describe("ImageLightbox — 空闲预取", () => {
  it("缩略图加载完成后预取当前幻灯片原图", async () => {
    const fetchFn = vi.fn(async (_url: string, _opts?: RequestInit) => ({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(10),
    }))
    vi.stubGlobal("fetch", fetchFn)
    const { inst } = await mountLightbox([JPG])
    const { slide } = makeSlide(inst)

    inst.dispatch("loadComplete", { slide })
    await flushPromises()

    expect(fetchFn).toHaveBeenCalledTimes(1)
    expect(fetchFn.mock.calls[0][0]).toBe("/api/image/1")
    expect(slide.data.prefetched).toBe(true)
  })

  it("超过 5MB 的原图不预取", async () => {
    const fetchFn = vi.fn()
    vi.stubGlobal("fetch", fetchFn)
    const { inst } = await mountLightbox([BIG_JPG])
    const { slide } = makeSlide(inst)

    inst.dispatch("loadComplete", { slide })
    await flushPromises()
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it("开启省流或非 4g 网络时不预取", async () => {
    const fetchFn = vi.fn(async () => ({
      ok: true, arrayBuffer: async () => new ArrayBuffer(10),
    }))
    vi.stubGlobal("fetch", fetchFn)

    const { inst: i1 } = await mountLightbox([JPG])
    const s1 = makeSlide(i1).slide
    Object.defineProperty(navigator, "saveData", { value: true, configurable: true })
    i1.dispatch("loadComplete", { slide: s1 })
    await flushPromises()
    expect(fetchFn).not.toHaveBeenCalled()

    const { inst: i2 } = await mountLightbox([JPG])
    const s2 = makeSlide(i2).slide
    Object.defineProperty(navigator, "connection", {
      value: { effectiveType: "3g" }, configurable: true,
    })
    i2.dispatch("loadComplete", { slide: s2 })
    await flushPromises()
    expect(fetchFn).not.toHaveBeenCalled()

    const { inst: i3 } = await mountLightbox([JPG])
    const s3 = makeSlide(i3).slide
    // 清掉第一个子场景设置的 saveData
    Object.defineProperty(navigator, "saveData", { value: false, configurable: true })
    Object.defineProperty(navigator, "connection", {
      value: { effectiveType: "4g" }, configurable: true,
    })
    i3.dispatch("loadComplete", { slide: s3 })
    await flushPromises()
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })

  it("非当前幻灯片的缩略图完成不触发预取", async () => {
    const fetchFn = vi.fn()
    vi.stubGlobal("fetch", fetchFn)
    const { inst } = await mountLightbox([JPG, BIG_JPG])
    const { slide } = makeSlide(inst, 1) // index 1，currIndex=0

    inst.dispatch("loadComplete", { slide })
    await flushPromises()
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it("切图时中止进行中的预取", async () => {
    let signal: AbortSignal | null | undefined
    vi.stubGlobal("fetch", vi.fn((_url: string, opts: RequestInit) => {
      signal = opts.signal
      return new Promise(() => {}) // 挂起，模拟下载中
    }))
    const { inst } = await mountLightbox([JPG])
    const { slide } = makeSlide(inst)

    inst.dispatch("loadComplete", { slide })
    expect(signal).toBeDefined()
    expect(signal!.aborted).toBe(false)

    // currSlide 不设置：change 末尾不会重新调度预取
    inst.dispatch("change")
    expect(signal!.aborted).toBe(true)
  })
})

describe("ImageLightbox — 右下角显示比例", () => {
  it("注册 zoom-ratio-label，zoomPanUpdate 时按相对原图比例刷新", async () => {
    const { inst } = await mountLightbox([JPG])
    const reg = findRegistered(inst, "zoom-ratio-label")
    expect(reg).toBeDefined()
    // 必须挂全屏 wrapper 才能定位右下角（默认 'bar' 是 60px 顶栏）
    expect(reg!.appendTo).toBe("wrapper")
    const label = document.querySelector<HTMLElement>(".pswp__zoom-ratio-label")!
    expect(label).not.toBeNull()
    // onInit 时 currSlide 未就绪：空文本
    expect(label.textContent).toBe("")

    const { slide } = makeSlide(inst)
    inst.currSlide = slide

    slide.currZoomLevel = 0.3
    inst.dispatch("zoomPanUpdate", { slide })
    expect(label.textContent).toBe("30%")

    slide.currZoomLevel = 1
    inst.dispatch("zoomPanUpdate", { slide })
    expect(label.textContent).toBe("100%")

    slide.currZoomLevel = 2.5
    inst.dispatch("zoomPanUpdate", { slide })
    expect(label.textContent).toBe("250%")
  })

  it("非当前幻灯片的 zoomPanUpdate 不更新比例", async () => {
    const { inst } = await mountLightbox([JPG, BIG_JPG])
    const label = document.querySelector<HTMLElement>(".pswp__zoom-ratio-label")!
    const { slide: active } = makeSlide(inst, 0)
    active.currZoomLevel = 0.3
    inst.currSlide = active
    inst.dispatch("zoomPanUpdate", { slide: active })
    expect(label.textContent).toBe("30%")

    // index 1 的幻灯片缩放事件：不刷新
    const other = makeSlide(inst, 1).slide
    other.currZoomLevel = 0.9
    inst.dispatch("zoomPanUpdate", { slide: other })
    expect(label.textContent).toBe("30%")
  })

  it("change 后按新幻灯片刷新比例", async () => {
    const { inst } = await mountLightbox([JPG, BIG_JPG])
    const label = document.querySelector<HTMLElement>(".pswp__zoom-ratio-label")!
    const s1 = makeSlide(inst, 1).slide
    s1.currZoomLevel = 0.2
    inst.currSlide = s1
    inst.currIndex = 1

    inst.dispatch("change")
    expect(label.textContent).toBe("20%")
  })
})
