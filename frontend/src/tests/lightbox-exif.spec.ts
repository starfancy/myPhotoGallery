/**
 * Lightbox EXIF panel tests.
 *
 * PhotoSwipe 在 jsdom 里跑不起来（需要真实 DOM 度量），因此我们 mock
 * 整个 `photoswipe` 模块——把 PhotoSwipe 构造函数替成一个可控替身：
 * `init()` 立刻触发 `uiRegister`；`ui.registerElement()` 保存注册项供
 * 测试查询与手动 onClick。这样能在保留组件本身逻辑的前提下断言：
 *   - admin 才注册删除按钮
 *   - EXIF 按钮 onClick 打开 body-level 面板
 *   - 面板消费 /api/images/{id}/exif 并渲染中文标签
 *   - 删除按钮 confirm → apiDelete → emit deleted
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

// -------- PhotoSwipe mock --------
// vi.mock 被 hoist 到文件顶部，因此 MockPhotoSwipe 必须定义在工厂函数内。
// 用一个模块级共享对象暴露给测试代码：`state.registered` 存注册的 UI 元素，
// `state.reset()` 每个 case 前清空。
interface UIRegistration {
  name: string
  ariaLabel: string
  onClick?: () => void
}
interface MockState {
  registered: UIRegistration[]
  uiRegisterHandler: (() => void) | null
  reset: () => void
}
const mockState: MockState = {
  registered: [],
  uiRegisterHandler: null,
  reset() {
    this.registered = []
    this.uiRegisterHandler = null
  },
}

vi.mock("photoswipe", () => {
  class MockPhotoSwipe {
    currIndex = 0
    currSlide = { data: {} }
    ui = {
      registerElement: (opts: UIRegistration) => {
        mockState.registered.push(opts)
      },
    }
    constructor(_opts: unknown) {}
    on(evt: string, cb: () => void) {
      if (evt === "uiRegister") mockState.uiRegisterHandler = cb
    }
    init() {
      mockState.uiRegisterHandler?.()
    }
    goTo(_i: number) {}
    close() {}
    destroy() {}
  }
  return { default: MockPhotoSwipe }
})
vi.mock("photoswipe/style.css", () => ({}))

import ImageLightbox from "../components/ImageLightbox.vue"
import { useAuthStore } from "../stores/auth"

const IMAGES = [
  { id: 1, filename: "a.jpg", width: 400, height: 300, sha1: "sha-a", size_bytes: 1, taken_at: null, is_raw: false },
  { id: 2, filename: "b.jpg", width: 400, height: 300, sha1: "sha-b", size_bytes: 1, taken_at: null, is_raw: false },
]

function response(body: unknown, status = 200) {
  const isNull = body === null || body === undefined
  return new Response(isNull ? null : JSON.stringify(body), {
    status,
    headers: isNull ? {} : { "content-type": "application/json" },
  })
}

async function mountLightbox(role: "admin" | "viewer") {
  mockState.reset()
  document.body.innerHTML = ""

  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({ user: { id: 1, username: "u", role, access_scope: "lan_only" } })

  const w = mount(ImageLightbox, {
    props: { items: IMAGES, startId: 1 },
  })
  await flushPromises()
  return w
}

function findElement(name: string) {
  return mockState.registered.find((r) => r.name === name)
}

describe("ImageLightbox — EXIF panel & delete", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    document.body.innerHTML = ""
  })

  it("registers 'exif-info' and 'delete-image' buttons for admin", async () => {
    await mountLightbox("admin")
    expect(findElement("original-image")).toBeDefined()
    expect(findElement("original-image-newtab")).toBeDefined()
    expect(findElement("exif-info")).toBeDefined()
    expect(findElement("delete-image")).toBeDefined()
  })

  it("does NOT register delete-image for viewer", async () => {
    await mountLightbox("viewer")
    expect(findElement("exif-info")).toBeDefined()
    expect(findElement("delete-image")).toBeUndefined()
  })

  it("opens EXIF panel and renders 中文 labels from API response", async () => {
    await mountLightbox("admin")
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.includes("/exif")) {
        return response({
          image_id: 1,
          filename: "a.jpg",
          exif: {
            Make: "Nikon",
            Model: "Z6",
            ExposureTime: "1/250",
            FNumber: 4.0,
            ISOSpeedRatings: 200,
          },
        })
      }
      return response({}, 404)
    })
    vi.stubGlobal("fetch", fetchFn)

    findElement("exif-info")!.onClick!()
    await flushPromises()

    const panel = document.querySelector(".lb-exif-panel")
    expect(panel).not.toBeNull()
    const text = panel!.textContent ?? ""
    expect(text).toContain("相机厂商")
    expect(text).toContain("Nikon")
    expect(text).toContain("相机型号")
    expect(text).toContain("Z6")
    expect(text).toContain("快门")
    expect(text).toContain("1/250 s")
    expect(text).toContain("光圈")
    expect(text).toContain("f/4")
    expect(text).toContain("ISO")
    expect(text).toContain("200")
  })

  it("shows '无 EXIF 信息' when exif dict is empty", async () => {
    await mountLightbox("admin")
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      image_id: 1, filename: "a.jpg", exif: {},
    })))
    findElement("exif-info")!.onClick!()
    await flushPromises()
    expect(document.querySelector(".lb-exif-panel")!.textContent).toContain("无 EXIF 信息")
  })

  it("shows error message when EXIF endpoint returns error", async () => {
    await mountLightbox("admin")
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(
      { error: { code: "not_found", message: "image not found" } }, 404,
    )))
    findElement("exif-info")!.onClick!()
    await flushPromises()
    expect(document.querySelector(".lb-exif-panel")!.textContent).toContain("image not found")
  })

  it("EXIF panel close button removes the panel from DOM", async () => {
    await mountLightbox("admin")
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({
      image_id: 1, filename: "a.jpg", exif: { Make: "X" },
    })))
    findElement("exif-info")!.onClick!()
    await flushPromises()
    expect(document.querySelector(".lb-exif-panel")).not.toBeNull()

    document.querySelector<HTMLButtonElement>(".lb-exif-close")!.click()
    expect(document.querySelector(".lb-exif-panel")).toBeNull()
  })

  it("delete button calls DELETE + emits deleted after confirm", async () => {
    const w = await mountLightbox("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
    const fetchFn = vi.fn().mockResolvedValue(response(null, 204))
    vi.stubGlobal("fetch", fetchFn)

    findElement("delete-image")!.onClick!()
    await flushPromises()

    expect(window.confirm).toHaveBeenCalled()
    const call = fetchFn.mock.calls.find(
      (c: [string, RequestInit?]) =>
        typeof c[0] === "string" && c[0] === "/api/images/1" && c[1]?.method === "DELETE",
    )
    expect(call).toBeDefined()
    const events = w.emitted("deleted") ?? []
    expect(events.length).toBe(1)
    expect(events[0]).toEqual([1])
  })

  it("delete button does not fire when confirm is cancelled", async () => {
    const w = await mountLightbox("admin")
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false))
    const fetchFn = vi.fn()
    vi.stubGlobal("fetch", fetchFn)

    findElement("delete-image")!.onClick!()
    await flushPromises()

    expect(fetchFn).not.toHaveBeenCalled()
    expect(w.emitted("deleted")).toBeUndefined()
  })
})
