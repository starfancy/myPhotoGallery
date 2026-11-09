import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { LutRenderer } from "../lib/lutRenderer"

// 最小假 gl：只记录调用，返回最小合法 stub。jsdom 没有真 WebGL。
function makeFakeGl() {
  return {
    createShader: vi.fn(() => ({})),
    shaderSource: vi.fn(),
    compileShader: vi.fn(),
    getShaderParameter: vi.fn(() => true),
    getShaderInfoLog: vi.fn(() => ""),
    createProgram: vi.fn(() => ({})),
    attachShader: vi.fn(),
    linkProgram: vi.fn(),
    getProgramParameter: vi.fn(() => true),
    getProgramInfoLog: vi.fn(() => ""),
    useProgram: vi.fn(),
    pixelStorei: vi.fn(),
    deleteBuffer: vi.fn(),
    deleteShader: vi.fn(),
    createBuffer: vi.fn(() => ({})),
    bindBuffer: vi.fn(),
    bufferData: vi.fn(),
    enableVertexAttribArray: vi.fn(),
    vertexAttribPointer: vi.fn(),
    getAttribLocation: vi.fn(() => 0),
    getUniformLocation: vi.fn(() => ({})),
    activeTexture: vi.fn(),
    uniform1i: vi.fn(),
    uniform1f: vi.fn(),
    bindTexture: vi.fn(),
    texParameteri: vi.fn(),
    texImage2D: vi.fn(),
    texImage3D: vi.fn(),
    createTexture: vi.fn(() => ({})),
    viewport: vi.fn(),
    clearColor: vi.fn(),
    clear: vi.fn(),
    drawArrays: vi.fn(),
  }
}

describe("LutRenderer", () => {
  let canvas: HTMLCanvasElement
  // afterEach 只需要 mockRestore；结构化类型避免 spyOn 泛型不匹配
  let getContextSpy: { mockRestore: () => void }

  beforeEach(() => {
    canvas = document.createElement("canvas")
  })

  afterEach(() => { getContextSpy?.mockRestore() })

  it("throws when WebGL2 is unavailable", () => {
    getContextSpy = vi.spyOn(canvas, "getContext").mockReturnValue(null)
    expect(() => new LutRenderer(canvas)).toThrow(/WebGL2/)
  })

  it("throws when a shader fails to compile", () => {
    const gl = makeFakeGl()
    gl.getShaderParameter.mockReturnValue(false)
    gl.getShaderInfoLog.mockReturnValue("syntax error on line 1")
    getContextSpy = vi.spyOn(canvas, "getContext").mockReturnValue(gl as any)
    expect(() => new LutRenderer(canvas)).toThrow(/Failed to compile.*syntax error/)
  })

  it("compiles a program and uploads the image texture on setImage", () => {
    const gl = makeFakeGl()
    getContextSpy = vi.spyOn(canvas, "getContext").mockReturnValue(gl as any)
    const r = new LutRenderer(canvas)
    const img = { width: 100, height: 50 } as HTMLImageElement
    r.setImage(img)
    expect(canvas.width).toBe(100)
    expect(canvas.height).toBe(50)
    expect(gl.texImage2D).toHaveBeenCalled()
  })

  it("upload LUT via texImage3D sized N^3*3 bytes", () => {
    const gl = makeFakeGl()
    getContextSpy = vi.spyOn(canvas, "getContext").mockReturnValue(gl as any)
    const r = new LutRenderer(canvas)
    r.loadLut("warm", { size: 2, data: new Uint8Array(2 * 2 * 2 * 3).fill(128) })
    const call = gl.texImage3D.mock.calls.find(c => (c[1] as string) === "TEXTURE_3D" || true)
    // texImage3D(target, level, internalformat, w, h, d, border, format, type, pixels)
    // data 参数在第 9 位（brief 草稿误写 6，6 是 border）
    const last = gl.texImage3D.mock.calls.at(-1)!
    expect((last[9] as Uint8Array).length).toBe(2 * 2 * 2 * 3)
  })

  it("render() issues one draw call per invocation", () => {
    const gl = makeFakeGl()
    getContextSpy = vi.spyOn(canvas, "getContext").mockReturnValue(gl as any)
    const r = new LutRenderer(canvas)
    r.setImage({ width: 4, height: 4 } as HTMLImageElement)
    r.render(0.5)
    expect(gl.drawArrays).toHaveBeenCalledTimes(1)
  })

  it("re-loads the same LUT id only once", () => {
    const gl = makeFakeGl()
    getContextSpy = vi.spyOn(canvas, "getContext").mockReturnValue(gl as any)
    const r = new LutRenderer(canvas)
    const lut = { size: 2, data: new Uint8Array(2 * 2 * 2 * 3) }
    r.loadLut("warm", lut)
    r.loadLut("warm", lut)
    expect(gl.texImage3D).toHaveBeenCalledTimes(1)
  })

  it("rejects LUTs larger than 65 per edge", () => {
    const gl = makeFakeGl()
    getContextSpy = vi.spyOn(canvas, "getContext").mockReturnValue(gl as any)
    const r = new LutRenderer(canvas)
    expect(() =>
      r.loadLut("huge", { size: 66, data: new Uint8Array(66 ** 3 * 3) }),
    ).toThrow(/65/)
    expect(gl.texImage3D).not.toHaveBeenCalled()
  })

  it("setViewport pins canvas backing store and gl.viewport", () => {
    const gl = makeFakeGl()
    getContextSpy = vi.spyOn(canvas, "getContext").mockReturnValue(gl as any)
    const r = new LutRenderer(canvas)
    // 先模拟 setImage 把 canvas 拉到图片尺寸
    r.setImage({ width: 1600, height: 1000 } as HTMLImageElement)
    expect(canvas.width).toBe(1600)
    // 再把小样 renderer 钉回 192×128
    r.setViewport(192, 128)
    expect(canvas.width).toBe(192)
    expect(canvas.height).toBe(128)
    expect(gl.viewport).toHaveBeenLastCalledWith(0, 0, 192, 128)
  })
})
