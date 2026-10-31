/**
 * PhotoSwipe 在 jsdom 里无法真实运行，整体 mock（与 lightbox-exif.spec.ts
 * 同款手法）：init() 触发 uiRegister 回调，registerElement 保存注册项并
 * 立刻调 onInit（传入一个 span 充当 DOM 元素）。
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

interface UIRegistration {
  name: string
  ariaLabel?: string
  isButton?: boolean
  onInit?: (el: HTMLElement) => void
  onClick?: () => void
}

const registered: UIRegistration[] = []

vi.mock("photoswipe", () => {
  class MockPhotoSwipe {
    currIndex = 0
    currSlide = { data: {} }
    ui = {
      registerElement: (opts: UIRegistration) => {
        registered.push(opts)
        opts.onInit?.(document.createElement("span"))
      },
    }
    handlers: Record<string, () => void> = {}
    constructor(_opts: unknown) {}
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
]

function findEl(name: string) {
  return registered.find((r) => r.name === name)
}

async function mountBox(resolver?: (it: ImageRow) => string | null) {
  registered.length = 0
  document.body.innerHTML = ""
  setActivePinia(createPinia())
  const w = mount(ImageLightbox, {
    props: { items: ITEMS, startId: 1, ...(resolver ? { locationResolver: resolver } : {}) },
  })
  await flushPromises()
  return w
}

describe("ImageLightbox location hook", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    document.body.innerHTML = ""
  })

  it("不传 resolver 时不注册目录元素（普通浏览态零变化）", async () => {
    await mountBox()
    expect(findEl("location-label")).toBeUndefined()
    expect(findEl("view-in-folder")).toBeUndefined()
  })

  it("传入 resolver：显示目录名，按钮 emit viewInFolder", async () => {
    const resolver = (it: ImageRow) => {
      const p = it.relative_path ?? ""
      const i = p.lastIndexOf("/")
      return i >= 0 ? p.slice(0, i) : ""
    }
    const w = await mountBox(resolver)

    const label = findEl("location-label")
    expect(label).toBeDefined()
    expect(label!.isButton).toBe(false)

    const btn = findEl("view-in-folder")
    expect(btn).toBeDefined()
    expect(btn!.ariaLabel).toBe("在所在文件夹中查看")
    btn!.onClick!()
    expect(w.emitted("viewInFolder")![0][0]).toMatchObject({ id: 1, filename: "a.jpg" })
  })
})
