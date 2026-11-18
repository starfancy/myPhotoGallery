import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"

// 本地模式：query.local=1
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: { local: "1" } }),
  useRouter: () => ({ replace: vi.fn() }),
}))

vi.mock("../lib/lutRenderer", () => {
  class MockRenderer {
    static instances: MockRenderer[] = []
    setImage = vi.fn()
    setViewport = vi.fn()
    loadLut = vi.fn()
    render = vi.fn()
    exportJpeg = vi.fn(async () => new Blob(["jpeg-bytes"], { type: "image/jpeg" }))
    dispose = vi.fn()
    constructor(public canvas: HTMLCanvasElement) {
      MockRenderer.instances.push(this)
    }
  }
  return { LutRenderer: MockRenderer }
})

// EXIF 合并在 exif.spec.ts 做二进制级验证；这里只验证视图接线
vi.mock("../lib/exif", () => ({
  injectExif: vi.fn(() => new Uint8Array([9, 9, 9])),
}))

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

vi.stubGlobal(
  "fetch",
  vi.fn(async (url: string) => {
    if (url === "/api/luts") {
      return {
        ok: true,
        json: async () => [
          { group: "synthetic", items: [{ slug: "warm", label: "暖色调", sort_order: 0 }] },
        ],
      }
    }
    if (url.includes("/cube")) {
      return { ok: true, text: async () => "LUT_3D_SIZE 1\n0.1 0.2 0.3" }
    }
    return { ok: false, status: 404 }
  }),
)

import FilterPreviewView from "../views/FilterPreviewView.vue"
import { injectExif } from "../lib/exif"

const injectMock = vi.mocked(injectExif)

/** 构造带确定性 arrayBuffer() 桩的图片 File（jsdom 的 Blob 未实现该方法）。 */
function imageFile(name: string, bytes: number[], type = "image/jpeg"): File {
  const f = new File([new Uint8Array(bytes)], name, { type })
  Object.defineProperty(f, "arrayBuffer", {
    value: () => Promise.resolve(Uint8Array.from(bytes).buffer),
  })
  return f
}

function dropEvent(files: File[], types = ["Files"]): Event {
  const ev = new Event("drop", { bubbles: true, cancelable: true })
  Object.defineProperty(ev, "dataTransfer", { value: { files, types } })
  return ev
}

describe("FilterPreviewView 本地模式", () => {
  let createdBlobs: Blob[]

  beforeEach(() => {
    // jsdom 未实现 canvas.toDataURL（renderThumbs 内部 try/catch 会吞，桩掉避免噪音）
    HTMLCanvasElement.prototype.toDataURL = () => "data:image/jpeg;base64,x"
    // jsdom Blob 无 arrayBuffer()；测试只关心字节是否接到 injectExif，内容无关
    if (!Blob.prototype.arrayBuffer) {
      Blob.prototype.arrayBuffer = vi.fn(async () => new ArrayBuffer(0))
    }

    createdBlobs = []
    injectMock.mockClear()
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: (b: Blob) => {
        createdBlobs.push(b)
        return "blob:fake"
      },
      revokeObjectURL: vi.fn(),
    })
  })

  it("拖入多张图片时只打开第一张", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    const f1 = imageFile("first.jpg", [1, 2])
    const f2 = imageFile("second.jpg", [3, 4])

    await w.element.dispatchEvent(dropEvent([f1, f2]))
    await flushPromises()

    expect(w.find(".fp-name").text()).toContain("first.jpg")
    // 只创建了一个 object URL（第二张从未加载）
    expect(createdBlobs.length).toBe(1)
  })

  it("拖入文件中混有非图片时，取第一张受支持的图片", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    const txt = new File(["notes"], "notes.txt", { type: "text/plain" })
    const img = imageFile("pic.png", [5], "image/png")

    await w.element.dispatchEvent(dropEvent([txt, img]))
    await flushPromises()

    expect(w.find(".fp-name").text()).toContain("pic.png")
  })

  it("只拖入非图片时不加载、不报错", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    await w.element.dispatchEvent(
      dropEvent([new File(["x"], "a.txt", { type: "text/plain" })]),
    )
    await flushPromises()
    expect(createdBlobs.length).toBe(0)
    expect(w.find(".fp-name").text()).toContain("未选择")
  })

  it("拖拽悬停时显示提示层，松手/离开后消失", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    const enter = new Event("dragenter", { bubbles: true, cancelable: true })
    Object.defineProperty(enter, "dataTransfer", { value: { types: ["Files"] } })
    await w.element.dispatchEvent(enter)
    expect(w.classes()).toContain("is-dragover")
    expect(w.find(".fp-drop-hint").exists()).toBe(true)

    await w.element.dispatchEvent(new Event("dragleave", { bubbles: true }))
    expect(w.classes()).not.toContain("is-dragover")
  })

  it("下载 JPEG 时把本地源文件字节与导出图合并 EXIF", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    const src = imageFile("moon.jpg", [1, 2, 3, 4])
    await w.element.dispatchEvent(dropEvent([src]))
    await flushPromises()

    const dl = w.findAll("button").find((b) => b.text().includes("下载 JPEG"))!
    expect(dl.attributes("disabled")).toBeUndefined()
    await dl.trigger("click")
    await flushPromises()

    expect(injectMock).toHaveBeenCalledTimes(1)
    const [sourceArg, canvasArg] = injectMock.mock.calls[0]
    expect(Array.from(new Uint8Array(sourceArg as ArrayBuffer))).toEqual([1, 2, 3, 4])
    expect(canvasArg).toBeInstanceOf(Uint8Array)
    // 下载用的 blob 是合并后的标记字节（3 字节），而非 renderer 原始导出
    const downloaded = createdBlobs.at(-1)!
    expect(downloaded.size).toBe(3)
    expect(downloaded.type).toBe("image/jpeg")
  })

  it("文件选择框选完即清空 value，允许再次选择同一文件", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    const input = w.find('input[type="file"]')
    const file = imageFile("again.jpg", [7])
    Object.defineProperty(input.element, "files", {
      value: [file],
      configurable: true,
    })

    await input.trigger("change")
    await flushPromises()
    expect((input.element as HTMLInputElement).value).toBe("")
    expect(w.find(".fp-name").text()).toContain("again.jpg")
  })
})
