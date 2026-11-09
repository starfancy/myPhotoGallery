/**
 * WebGL 2 3D-LUT 渲染器。
 *
 * 设计要点：
 *  - 构造时创建一次 context / shader program / vertex buffer，之后复用；
 *  - LUT 以 TEXTURE_3D 上传，shader 内一次 texture() 采样，无需手算 bilinear；
 *  - mix 强度走 uniform，拖滑块时只改 uniform 不重编译；
 *  - 不设 preserveDrawingBuffer；exportJpeg 在同一 tick 内先 render 再 toBlob。
 */
import type { LutData } from "./lutParser"

const VERT_SRC = `#version 300 es
in vec2 a_pos;
out vec2 v_uv;
void main() {
  gl_Position = vec4(a_pos, 0.0, 1.0);
  v_uv = a_pos * 0.5 + 0.5;
}`

const FRAG_SRC = `#version 300 es
precision mediump float;
in vec2 v_uv;
uniform sampler2D u_image;
uniform sampler3D u_lut;
uniform float u_mix;
layout(location = 0) out vec4 fragColor;
void main() {
  vec4 c = texture(u_image, v_uv);
  vec3 graded = texture(u_lut, clamp(c.rgb, 0.0, 1.0)).rgb;
  fragColor = vec4(mix(c.rgb, graded, u_mix), 1.0);
}`

export class LutRenderer {
  private gl: WebGL2RenderingContext
  private prog: WebGLProgram
  private vbo: WebGLBuffer
  private vertShader: WebGLShader
  private fragShader: WebGLShader
  private imgTex: WebGLTexture | null = null
  private lutCache = new Map<string, WebGLTexture>()
  private activeLut: WebGLTexture | null = null
  private uImage: WebGLUniformLocation | null
  private uLut: WebGLUniformLocation | null
  private uMix: WebGLUniformLocation | null

  constructor(private canvas: HTMLCanvasElement) {
    const gl = canvas.getContext("webgl2")
    if (!gl) throw new Error("WebGL2 not available")
    this.gl = gl
    const { prog, vertShader, fragShader } = this.buildProgram()
    this.prog = prog
    this.vertShader = vertShader
    this.fragShader = fragShader
    // 单个全屏三角形（3 个顶点覆盖整个 clip space），uv 由 shader 内
    // a_pos*0.5+0.5 推算，不需要单独的 uv attribute / buffer。
    this.vbo = gl.createBuffer()!
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
      -1, -1, 3, -1, -1, 3,
    ]), gl.STATIC_DRAW)
    const aPos = gl.getAttribLocation(this.prog, "a_pos")
    gl.enableVertexAttribArray(aPos)
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0)

    this.uImage = gl.getUniformLocation(this.prog, "u_image")
    this.uLut = gl.getUniformLocation(this.prog, "u_lut")
    this.uMix = gl.getUniformLocation(this.prog, "u_mix")
  }

  private buildProgram(): {
    prog: WebGLProgram
    vertShader: WebGLShader
    fragShader: WebGLShader
  } {
    const gl = this.gl
    const compile = (type: number, src: string, label: string): WebGLShader => {
      const sh = gl.createShader(type)!
      gl.shaderSource(sh, src)
      gl.compileShader(sh)
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        const log = gl.getShaderInfoLog(sh) || "(no info log)"
        gl.deleteShader(sh)
        throw new Error(`Failed to compile ${label} shader: ${log}`)
      }
      return sh
    }
    const vertShader = compile(gl.VERTEX_SHADER, VERT_SRC, "vertex")
    const fragShader = compile(gl.FRAGMENT_SHADER, FRAG_SRC, "fragment")
    const prog = gl.createProgram()!
    gl.attachShader(prog, vertShader)
    gl.attachShader(prog, fragShader)
    gl.linkProgram(prog)
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      const log = gl.getProgramInfoLog(prog) || "(no info log)"
      gl.deleteProgram(prog)
      throw new Error(`Failed to link shader program: ${log}`)
    }
    gl.useProgram(prog)
    return { prog, vertShader, fragShader }
  }

  setImage(img: HTMLImageElement): void {
    const gl = this.gl
    this.canvas.width = img.naturalWidth || img.width
    this.canvas.height = img.naturalHeight || img.height
    gl.viewport(0, 0, this.canvas.width, this.canvas.height)
    if (!this.imgTex) {
      this.imgTex = gl.createTexture()
    }
    gl.activeTexture(gl.TEXTURE0)
    gl.bindTexture(gl.TEXTURE_2D, this.imgTex)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    // texImage2D 默认把图片顶行存在 t=0，而 uv 0 在屏幕底部，会倒置。
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true)
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img)
    gl.uniform1i(this.uImage, 0)
  }

  /**
   * 把 backing store 与 GL viewport 显式钉到指定尺寸。
   *
   * setImage() 会把 canvas 重设为图片原生尺寸（主预览场景是对的）；
   * 小样渲染器在 setImage 之后调用本方法，把 canvas 从 1600px 压回 192×128，
   * 让缩略图在小 buffer 上渲染、再由 GL LINEAR 完成下采样。
   */
  setViewport(w: number, h: number): void {
    this.canvas.width = w
    this.canvas.height = h
    this.gl.viewport(0, 0, w, h)
  }

  loadLut(id: string, lut: LutData): void {
    if (lut.size > 65) throw new Error("LUT size exceeds 65")
    const hit = this.lutCache.get(id)
    if (hit) {
      this.activeLut = hit
      return
    }
    const gl = this.gl
    const tex = gl.createTexture()!
    gl.activeTexture(gl.TEXTURE1)
    gl.bindTexture(gl.TEXTURE_3D, tex)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
    gl.texImage3D(
      gl.TEXTURE_3D, 0, gl.RGB8,
      lut.size, lut.size, lut.size, 0,
      gl.RGB, gl.UNSIGNED_BYTE, lut.data,
    )
    gl.uniform1i(this.uLut, 1)
    this.lutCache.set(id, tex)
    this.activeLut = tex
  }

  render(mix: number): void {
    const gl = this.gl
    mix = Math.max(0, Math.min(1, mix))
    // 未加载过 LUT 时退化为原图：仍画一次全屏三角形，但把 mix 钳成 0
    //（u_lut 未绑定时采样回黑色，权重 0 即完全保留原图）。
    gl.uniform1f(this.uMix, this.activeLut ? mix : 0)
    gl.drawArrays(gl.TRIANGLES, 0, 3)
  }

  async exportJpeg(quality = 0.92): Promise<Blob> {
    // 当前 mix 由调用方在调用前 render() 决定；这里只需同步快照。
    return new Promise((resolve, reject) => {
      this.canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error("toBlob returned null"))),
        "image/jpeg",
        quality,
      )
    })
  }

  dispose(): void {
    const gl = this.gl
    if (this.imgTex) gl.deleteTexture(this.imgTex)
    for (const t of this.lutCache.values()) gl.deleteTexture(t)
    gl.deleteBuffer(this.vbo)
    gl.deleteProgram(this.prog)
    // shader 可以在 program 删除后再删
    gl.deleteShader(this.vertShader)
    gl.deleteShader(this.fragShader)
  }
}
