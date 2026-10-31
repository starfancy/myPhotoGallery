/**
 * 轻量回归：PhotoSwipe 幻灯片数据必须带 alt（用文件名），保证灯箱图片
 * 对读屏可命名。PhotoSwipe 无法在 jsdom 真实运行，整体 mock 并截获
 * 构造参数（手法与 lightbox-location.spec.ts 同款）。
 */
import { describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

let capturedOptions: any = null

vi.mock("photoswipe", () => {
  class MockPhotoSwipe {
    currIndex = 0
    currSlide = { data: {} }
    ui = {
      registerElement: () => {},
    }
    handlers: Record<string, () => void> = {}
    constructor(opts: unknown) {
      capturedOptions = opts
    }
    on(evt: string, cb: () => void) {
      this.handlers[evt] = cb
    }
    addFilter() {}
    init() {
      this.handlers["uiRegister"]?.()
    }
    close() {}
    destroy() {}
  }
  return { default: MockPhotoSwipe }
})
vi.mock("photoswipe/style.css", () => ({}))

import ImageLightbox from "../components/ImageLightbox.vue"
import type { ImageRow } from "../stores/browse"

const ITEMS: ImageRow[] = [
  { id: 1, filename: "a.jpg", width: 400, height: 300, sha1: "s1",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    relative_path: "2024/旅行/a.jpg" },
  { id: 2, filename: "b.png", width: 400, height: 300, sha1: "s2",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    relative_path: "2024/旅行/b.png" },
]

describe("ImageLightbox 图片 alt", () => {
  it("每张幻灯片的 dataSource 项带 alt=文件名", async () => {
    capturedOptions = null
    document.body.innerHTML = ""
    setActivePinia(createPinia())
    mount(ImageLightbox, {
      props: { items: ITEMS, startId: 2 },
    })
    await flushPromises()

    expect(capturedOptions).not.toBeNull()
    const slides = capturedOptions.dataSource as Array<{ alt?: string }>
    expect(slides).toHaveLength(2)
    expect(slides[0].alt).toBe("a.jpg")
    expect(slides[1].alt).toBe("b.png")
    // startId=2 时定位到第二张
    expect(capturedOptions.index).toBe(1)
  })
})
