# LUT 风格滤镜预览 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PhotoSwipe 灯箱顶栏新增"风格滤镜"按钮，新标签页打开独立预览页，可套用内置 `.cube` LUT 滤镜、调强度、对比原图、下载处理后 JPEG。

**Architecture:** 手写 WebGL 2 渲染器（`lib/lutRenderer.ts`）把 `.cube` 文本解析为 3D texture 采样；预览页 `FilterPreviewView.vue` 读取 query 中的 sha1，从 `/api/thumb/{sha1}?size=1600` 加载 1600 缩略图，纯前端处理，零后端改动。

**Tech Stack:** Vue 3 `<script setup>` + TypeScript + WebGL 2（原生，无新 npm 依赖）+ vitest/jsdom。

**Spec:** [docs/superpowers/specs/2026-11-09-lut-filter-preview-design.md](../specs/2026-11-09-lut-filter-preview-design.md)

## Deviations from spec (deliberate, logged here)

1. **URL 简化为 `/filter-preview?sha1=...&name=...`**——丢弃 spec 里的 w/h 参数。缩略图返回后 `img.naturalWidth/Height` 天然给出尺寸，query 里的 w/h 反而可能过期（原图方向/旋转修正后）。
2. **首批内置 3 支合成 LUT（warm / cool / mono），而非 6 支真实胶片 LUT**。真实胶片 LUT（Kodak 2383 等）需要人工从许可渠道下载，无法在计划里自动获取；管线用合成预设完整跑通后，真实 LUT 只需丢进 `public/filters/` 并在 manifest.json 加一行（见 Task 3 的"后续接入"说明）。
3. **小样缩略条用第二个离屏 `LutRenderer` 实例**（总共 2 个 gl context），而非主渲染器 resize——避免每支滤镜来回改主 canvas 尺寸导致主画面闪烁。

## Global Constraints

- **不新增任何 npm 依赖**（WebGL 2 是浏览器原生 API；项目当前依赖：vue, vue-router, pinia, photoswipe, vue-virtual-scroller）。
- 所有用户可见文案用中文（与现有灯箱 `pswp__filename-label` 等一致）。
- 测试命令统一为 `cd frontend && npx vitest run src/tests/<file>.spec.ts`；类型检查为 `cd frontend && npx vue-tsc --noEmit`。
- 每 Task 结束 commit 一次，commit message 用 conventional 前缀（`feat(preview): ...` 等）。
- `frontend/public/` 目录尚不存在，Task 3 首次创建。
- 灯箱按钮的注册模式严格遵循现有 `ImageLightbox.vue` 里 `pswp.ui.registerElement({...})` 的写法（参照 "exif-info" / "histogram" 按钮）。

---

## File Structure

| 文件 | 责任 |
|---|---|
| `frontend/src/lib/lutParser.ts` | `.cube` 文本 → `{size, data: Uint8Array}`，纯函数，jsdom 可测 |
| `frontend/src/lib/lutRenderer.ts` | WebGL2 context 生命周期、shader program、3D LUT texture 缓存、`render(mix)`、JPEG 导出 |
| `frontend/src/views/FilterPreviewView.vue` | 预览页：query 解析、manifest 加载、图片加载、控件、小样条 |
| `frontend/src/components/ImageLightbox.vue` (修改) | 顶栏新增"风格滤镜"按钮（order 13） |
| `frontend/src/router.ts` (修改) | 新增 `/filter-preview` 路由 |
| `frontend/public/filters/manifest.json` | 滤镜清单 |
| `frontend/public/filters/*.cube` (3 个) | 合成预设（Task 3 的脚本生成） |
| `frontend/public/filters/LICENSE.md` | 许可证说明 |
| `frontend/scripts/gen-builtin-luts.mjs` | 一次性生成脚本（生成后保留，可重跑） |
| `frontend/src/tests/lut-parser.spec.ts` | 解析器单测 |
| `frontend/src/tests/lut-renderer.spec.ts` | 渲染器单测（mock gl context） |
| `frontend/src/tests/filter-assets.spec.ts` | manifest/文件存在性 + 可解析 |
| `frontend/src/tests/filter-preview-view.spec.ts` | 预览页行为（mock LutRenderer 模块） |
| `frontend/src/tests/lightbox-filter.spec.ts` | 灯箱按钮注册 + onClick URL |

---

## Task 1: `.cube` 解析器

**Files:**
- Create: `frontend/src/lib/lutParser.ts`
- Test: `frontend/src/tests/lut-parser.spec.ts`

**Interfaces:**
- Produces: `export interface LutData { size: number; data: Uint8Array }`；`export function parseCube(text: string): LutData`。`data.length === size**3 * 3`，每个分量为 0–255 的无符号字节（顺序：B 最快，然后 G，然后 R——即 `.cube` 标准行序）。

- [ ] **Step 1: 写失败测试**

`frontend/src/tests/lut-parser.spec.ts`:

```ts
import { describe, expect, it } from "vitest"
import { parseCube } from "../lib/lutParser"

const SAMPLE = `
# comment line
TITLE "tiny"
LUT_3D_SIZE 2
DOMAIN_MIN 0.0 0.0 0.0
DOMAIN_MAX 1.0 1.0 1.0
0.0 0.0 0.0
1.0 0.0 0.0
0.0 1.0 0.0
1.0 1.0 0.0
0.0 0.0 1.0
1.0 0.0 1.0
0.0 1.0 1.0
1.0 1.0 1.0
`

describe("parseCube", () => {
  it("parses size and RGB triples in .cube row order", () => {
    const lut = parseCube(SAMPLE)
    expect(lut.size).toBe(2)
    expect(lut.data.length).toBe(2 * 2 * 2 * 3)
    // 第一行 "0 0 0"
    expect(lut.data[0]).toBe(0)
    expect(lut.data[1]).toBe(0)
    expect(lut.data[2]).toBe(0)
    // 第二行 "1 0 0" → 255
    expect(lut.data[3]).toBe(255)
    expect(lut.data[4]).toBe(0)
    expect(lut.data[5]).toBe(0)
  })

  it("clamps out-of-range floats into 0..255", () => {
    const lut = parseCube(`LUT_3D_SIZE 1\n-0.5 2.0 0.5`)
    expect(lut.data[0]).toBe(0)
    expect(lut.data[1]).toBe(255)
    expect(lut.data[2]).toBe(Math.round(0.5 * 255))
  })

  it("throws when LUT_3D_SIZE missing", () => {
    expect(() => parseCube("0.0 0.0 0.0")).toThrow(/LUT_3D_SIZE/)
  })

  it("throws when triple count mismatches size^3", () => {
    expect(() => parseCube("LUT_3D_SIZE 2\n0.0 0.0 0.0")).toThrow(/expected 24, got 3/)
  })

  it("skips blank lines and non-header text rows without 3 numeric parts", () => {
    const lut = parseCube(`LUT_3D_SIZE 1\n\nnot a row\n0.1 0.2 0.3`)
    expect(lut.size).toBe(1)
    expect(lut.data.length).toBe(3)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/tests/lut-parser.spec.ts`
Expected: FAIL — `Failed to resolve import "../lib/lutParser"`。

- [ ] **Step 3: 实现解析器**

`frontend/src/lib/lutParser.ts`:

```ts
/**
 * .cube 3D LUT 解析器。
 *
 * .cube 是纯文本格式：头行声明 LUT_3D_SIZE N，随后 N³ 行 RGB 浮点三元组
 * （0.0–1.0，B 通道最快变化）。这里把浮点打包为 0–255 字节，供 WebGL
 * TEXTURE_3D 直接上传。
 */

export interface LutData {
  /** 每边采样数（典型 17 / 33 / 65）。 */
  size: number
  /** length = size^3 * 3，按 .cube 行序（B 最快）排列的 RGB 字节。 */
  data: Uint8Array
}

export function parseCube(text: string): LutData {
  let size = 0
  const values: number[] = []
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith("#")) continue
    if (line.startsWith("LUT_3D_SIZE")) {
      size = parseInt(line.split(/\s+/)[1], 10)
      continue
    }
    // TITLE / DOMAIN_MIN / DOMAIN_MAX 头行不需要参与采样
    if (line.startsWith("TITLE") || line.startsWith("DOMAIN_")) continue
    const parts = line.split(/\s+/)
    if (parts.length !== 3) continue
    const [r, g, b] = parts.map(Number)
    if (Number.isNaN(r) || Number.isNaN(g) || Number.isNaN(b)) continue
    values.push(r, g, b)
  }
  if (!size) throw new Error(".cube: missing LUT_3D_SIZE")
  const expected = size ** 3 * 3
  if (values.length !== expected) {
    throw new Error(`.cube: expected ${expected} floats, got ${values.length}`)
  }
  const data = new Uint8Array(expected)
  for (let i = 0; i < expected; i++) {
    data[i] = Math.max(0, Math.min(255, Math.round(values[i] * 255)))
  }
  return { size, data }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/tests/lut-parser.spec.ts`
Expected: 5 tests PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/lutParser.ts frontend/src/tests/lut-parser.spec.ts
git commit -m "feat(preview): parse .cube LUT text into byte 3D tables"
```

---

## Task 2: WebGL 2 LUT 渲染器

**Files:**
- Create: `frontend/src/lib/lutRenderer.ts`
- Test: `frontend/src/tests/lut-renderer.spec.ts`

**Interfaces:**
- Consumes: `LutData` from `./lutParser`。
- Produces: `export class LutRenderer`
  - `constructor(canvas: HTMLCanvasElement)` —— 拿不到 WebGL2 context 时 `throw new Error("WebGL2 not available")`。
  - `setImage(img: HTMLImageElement): void` —— 把 canvas backing store 设为图片自然尺寸并上传 2D texture。
  - `loadLut(id: string, lut: LutData): void` —— 同一 id 只上传一次 3D texture（Map 缓存）。
  - `render(mix: number): void` —— `mix=0` 输出原图，`mix=1` 全滤镜；用当前最近一次 `loadLut` 的 LUT（未加载过则退化为原图）。
  - `async exportJpeg(quality = 0.92): Promise<Blob>` —— 同一 tick 内先 `render(mix)` 再 `canvas.toBlob`。
  - `dispose(): void`。

- [ ] **Step 1: 写失败测试**

`frontend/src/tests/lut-renderer.spec.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { LutRenderer } from "../lib/lutRenderer"

// 最小假 gl：只记录调用，返回最小合法 stub。jsdom 没有真 WebGL。
function makeFakeGl() {
  return {
    createShader: vi.fn(() => ({})),
    shaderSource: vi.fn(),
    compileShader: vi.fn(),
    getShaderParameter: vi.fn(() => true),
    createProgram: vi.fn(() => ({})),
    attachShader: vi.fn(),
    linkProgram: vi.fn(),
    getProgramParameter: vi.fn(() => true),
    getProgramInfoLog: vi.fn(() => ""),
    useProgram: vi.fn(),
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
  let getContextSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    canvas = document.createElement("canvas")
  })

  afterEach(() => { getContextSpy?.mockRestore() })

  it("throws when WebGL2 is unavailable", () => {
    getContextSpy = vi.spyOn(canvas, "getContext").mockReturnValue(null)
    expect(() => new LutRenderer(canvas)).toThrow(/WebGL2/)
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
    // 直接断言最后一次 texImage3D 调用的 data 参数长度
    const last = gl.texImage3D.mock.calls.at(-1)!
    expect((last[6] as Uint8Array).length).toBe(2 * 2 * 2 * 3)
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
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/tests/lut-renderer.spec.ts`
Expected: FAIL — `Failed to resolve import "../lib/lutRenderer"`。

- [ ] **Step 3: 实现渲染器**

`frontend/src/lib/lutRenderer.ts`:

```ts
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

const VERT_SRC = `
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
  gl_Position = vec4(a_pos, 0.0, 1.0);
  v_uv = a_pos * 0.5 + 0.5;
}`

const FRAG_SRC = `
precision mediump float;
varying vec2 v_uv;
uniform sampler2D u_image;
uniform sampler3D u_lut;
uniform float u_mix;
void main() {
  vec4 c = texture2D(u_image, v_uv);
  vec3 graded = texture(u_lut, clamp(c.rgb, 0.0, 1.0)).rgb;
  gl_FragColor = vec4(mix(c.rgb, graded, u_mix), 1.0);
}`

export class LutRenderer {
  private gl: WebGL2RenderingContext
  private prog: WebGLProgram
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
    this.prog = this.buildProgram()
    // 单个全屏三角形（3 个顶点覆盖整个 clip space），uv 由 shader 内
    // a_pos*0.5+0.5 推算，不需要单独的 uv attribute / buffer。
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer())
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

  private buildProgram(): WebGLProgram {
    const gl = this.gl
    const compile = (type: number, src: string) => {
      const sh = gl.createShader(type)!
      gl.shaderSource(sh, src)
      gl.compileShader(sh)
      return sh
    }
    const prog = gl.createProgram()!
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT_SRC))
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG_SRC))
    gl.linkProgram(prog)
    gl.useProgram(prog)
    return prog
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
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img)
    gl.uniform1i(this.uImage, 0)
  }

  loadLut(id: string, lut: LutData): void {
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
    if (!this.activeLut) return
    gl.uniform1f(this.uMix, mix)
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
    gl.deleteProgram(this.prog)
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/tests/lut-renderer.spec.ts`
Expected: 5 tests PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/lutRenderer.ts frontend/src/tests/lut-renderer.spec.ts
git commit -m "feat(preview): WebGL2 3D-LUT renderer with strength mix"
```

---

## Task 3: 内置合成 LUT 资产 + manifest

**Files:**
- Create: `frontend/scripts/gen-builtin-luts.mjs`
- Create: `frontend/public/filters/manifest.json`
- Create: `frontend/public/filters/LICENSE.md`
- Test: `frontend/src/tests/filter-assets.spec.ts`

**Interfaces:**
- Produces: `frontend/public/filters/manifest.json` 内容：
  ```json
  [
    { "id": "warm", "label": "暖色调", "file": "warm.cube" },
    { "id": "cool", "label": "冷色调", "file": "cool.cube" },
    { "id": "mono", "label": "黑白", "file": "mono.cube" }
  ]
  ```
- Produces: `warm.cube` / `cool.cube` / `mono.cube`（`LUT_3D_SIZE 33`）。

**后续接入真实胶片 LUT 的方式（v1 之后人工操作）：**
把 `.cube` 文件丢进 `frontend/public/filters/`，在 manifest.json 追加一行，在 `LICENSE.md` 补一行来源/许可即可，代码零改动。

- [ ] **Step 1: 写失败测试**

`frontend/src/tests/filter-assets.spec.ts`:

```ts
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"
import { parseCube } from "../lib/lutParser"

const FILTERS_DIR = join(__dirname, "../../public/filters")

describe("filter assets", () => {
  const manifest = JSON.parse(
    readFileSync(join(FILTERS_DIR, "manifest.json"), "utf8"),
  )

  it("manifest has at least 3 presets with unique ids", () => {
    expect(manifest.length).toBeGreaterThanOrEqual(3)
    const ids = manifest.map((f: any) => f.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it("every manifest entry points to a parseable .cube file", () => {
    for (const f of manifest) {
      const text = readFileSync(join(FILTERS_DIR, f.file), "utf8")
      const lut = parseCube(text)
      expect(lut.size).toBe(33)
      expect(lut.data.length).toBe(33 ** 3 * 3)
    }
  })

  it("LICENSE.md documents the synthetic-preset provenance", () => {
    const lic = readFileSync(join(FILTERS_DIR, "LICENSE.md"), "utf8")
    expect(lic).toMatch(/synthetic|built-in/i)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/tests/filter-assets.spec.ts`
Expected: FAIL — `ENOENT: no such file or directory, open '.../public/filters/manifest.json'`。

- [ ] **Step 3: 写生成脚本**

`frontend/scripts/gen-builtin-luts.mjs`:

```js
// 一次性（可重跑）生成 3 支内置合成 .cube 预设到 ../public/filters/。
// 这是占位资产：真实胶片 LUT 后续人工丢进同目录并在 manifest.json 加行。
import { mkdirSync, writeFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const outDir = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "filters")
mkdirSync(outDir, { recursive: true })

const N = 33
function toCube(title, fn) {
  const lines = [`# ${title} (built-in synthetic preset)`, `LUT_3D_SIZE ${N}`]
  for (let b = 0; b < N; b++)
    for (let g = 0; g < N; g++)
      for (let r = 0; r < N; r++) {
        const [R, G, B] = fn(r / (N - 1), g / (N - 1), b / (N - 1))
        lines.push([R, G, B].map((v) => v.toFixed(6)).join(" "))
      }
  return lines.join("\n") + "\n"
}

const presets = {
  "warm.cube": toCube("warm", (r, g, b) => [
    Math.min(1, r * 1.08 + 0.02),
    Math.min(1, g * 1.0 + 0.0),
    Math.max(0, b * 0.88 - 0.02),
  ]),
  "cool.cube": toCube("cool", (r, g, b) => [
    Math.max(0, r * 0.88 - 0.02),
    Math.min(1, g * 1.0 + 0.0),
    Math.min(1, b * 1.08 + 0.02),
  ]),
  "mono.cube": toCube("mono", (r, g, b) => {
    const y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return [y, y, y]
  }),
}

for (const [file, content] of Object.entries(presets)) {
  writeFileSync(join(outDir, file), content)
  console.log("wrote", file)
}
```

运行：`cd frontend && node scripts/gen-builtin-luts.mjs`
Expected: 输出 `wrote warm.cube / cool.cube / mono.cube`，目录里出现 3 个文件。

- [ ] **Step 4: 手写 manifest.json 和 LICENSE.md**

`frontend/public/filters/manifest.json`:

```json
[
  { "id": "warm", "label": "暖色调", "file": "warm.cube" },
  { "id": "cool", "label": "冷色调", "file": "cool.cube" },
  { "id": "mono", "label": "黑白", "file": "mono.cube" }
]
```

`frontend/public/filters/LICENSE.md`:

```markdown
# 滤镜资产许可

## 内置合成预设（warm.cube / cool.cube / mono.cube）

由 `scripts/gen-builtin-luts.mjs` 程序化生成，为本项目自带的 synthetic
preset，随仓库以 MIT 许可分发。它们用于打通管线，不是真实胶片模拟。

## 后续加入的真实 LUT

每一支真实胶片 LUT 丢进本目录时，必须在此追加：
- 文件名列
- 原始来源 URL
- 许可证（个人免费 / 商用条款）
- 是否允许随仓库分发

未确认许可的 LUT 不得提交。
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/tests/filter-assets.spec.ts`
Expected: 3 tests PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/scripts/gen-builtin-luts.mjs frontend/public/filters/
git commit -m "feat(preview): built-in synthetic LUT presets with manifest"
```

---

## Task 4: 路由 + 预览页骨架（图片能显示，渲染器接 mock）

**Files:**
- Modify: `frontend/src/router.ts`（加路由）
- Create: `frontend/src/views/FilterPreviewView.vue`
- Test: `frontend/src/tests/filter-preview-view.spec.ts`

**Interfaces:**
- Consumes: `LutRenderer`（测试里被 mock）；`/filters/manifest.json`（静态 fetch）；`/api/thumb/{sha1}?size=1600`（图片 URL）。
- Produces: 路由 `/filter-preview`，query 参数 `{ sha1: string, name?: string }`；组件对外无 props。

- [ ] **Step 1: 写失败测试**

`frontend/src/tests/filter-preview-view.spec.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"

// mock 路由：返回 query
const mockRouter = { replace: vi.fn() }
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: { sha1: "abc123", name: "IMG_0001.jpg" } }),
  useRouter: () => mockRouter,
}))

// mock LutRenderer：构造时记录 canvas，方法都是 vi.fn
class MockRenderer {
  static instances: MockRenderer[] = []
  setImage = vi.fn()
  loadLut = vi.fn()
  render = vi.fn()
  exportJpeg = vi.fn(async () => new Blob(["x"], { type: "image/jpeg" }))
  dispose = vi.fn()
  constructor(public canvas: HTMLCanvasElement) {
    MockRenderer.instances.push(this)
  }
}
vi.mock("../src/lib/lutRenderer", () => ({ LutRenderer: MockRenderer }))

// mock 图片加载：new Image() → 立即触发 onload
const imgLoaders: ((img: HTMLImageElement) => void)[] = []
vi.stubGlobal("Image", class {
  onload: (() => void) | null = null
  set src(_url: string) {
    queueMicrotask(() => {
      ;(this as any).width = 1600
      ;(this as any).height = 1000
      this.onload?.()
    })
  }
})

// mock fetch：manifest + 3 个 cube
vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
  ok: true,
  text: async () =>
    url.includes("manifest")
      ? JSON.stringify([{ id: "warm", label: "暖色调", file: "warm.cube" }])
      : "LUT_3D_SIZE 1\n0.1 0.2 0.3",
})))

import FilterPreviewView from "../src/views/FilterPreviewView.vue"

describe("FilterPreviewView", () => {
  beforeEach(() => { MockRenderer.instances.length = 0 })

  it("loads image from /api/thumb/{sha1}?size=1600", async () => {
    mount(FilterPreviewView)
    await flushPromises()
    expect(MockRenderer.instances[0]?.setImage).toHaveBeenCalled()
  })

  it("renders filename from query in header", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    expect(w.text()).toContain("IMG_0001.jpg")
  })

  it("shows fallback message when renderer constructor throws", async () => {
    vi.doMock("../src/lib/lutRenderer", () => ({
      LutRenderer: class {
        constructor() { throw new Error("WebGL2 not available") }
      },
    }))
    // 重新动态 import 确保 mock 生效
    const mod = await import("../src/views/FilterPreviewView.vue?fallback=" + Date.now())
    const w = mount(mod.default)
    await flushPromises()
    expect(w.text()).toContain("WebGL")
  })
})
```

> 备注：第三个测试用 `vi.doMock` 动态 import 的方式有点取巧；实现时如果太绕，就把"WebGL2 不可用"分支拆成一个独立测试文件单独 mock，别让骨架测试过度耦合。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/tests/filter-preview-view.spec.ts`
Expected: FAIL — 路由/视图文件不存在。

- [ ] **Step 3: 加路由**

在 `frontend/src/router.ts` 的 routes 数组里（`/settings/password` 之后）加：

```ts
  {
    path: "/filter-preview",
    component: () => import("./views/FilterPreviewView.vue"),
  },
```

（无 `meta.public`，走默认 authGuard 需要登录——符合"未登录不能看图"的既有语义。）

- [ ] **Step 4: 写视图骨架**

`frontend/src/views/FilterPreviewView.vue`:

```vue
<template>
  <div class="fp-page">
    <header class="fp-topbar">
      <span class="fp-name">{{ name }}</span>
    </header>

    <main class="fp-stage">
      <canvas ref="canvasEl" class="fp-canvas"></canvas>
      <div v-if="fallbackMsg" class="fp-fallback">{{ fallbackMsg }}</div>
    </main>

    <section class="fp-controls">
      <label class="fp-strength">
        强度
        <input
          type="range" min="0" max="100"
          :value="mixPct"
          :disabled="!rendererReady"
          @input="onMixInput"
        />
        <span>{{ mixPct }}%</span>
      </label>
      <button
        :disabled="!rendererReady"
        @pointerdown="holdStart"
        @pointerup="holdEnd"
        @pointerleave="holdEnd"
      >按住看原图</button>
      <button :disabled="!rendererReady" @click="onDownload">下载 JPEG</button>
    </section>

    <section class="fp-strip">
      <button
        v-for="f in filters" :key="f.id"
        class="fp-thumb" :class="{ active: f.id === activeId }"
        @click="pick(f)"
      >
        <img v-if="thumbs[f.id]" :src="thumbs[f.id]" :alt="f.label" />
        <span class="fp-thumb-label">{{ f.label }}</span>
      </button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute } from "vue-router"
import { LutRenderer } from "../lib/lutRenderer"
import { parseCube } from "../lib/lutParser"

interface FilterEntry { id: string; label: string; file: string }

const route = useRoute()
const sha1 = String(route.query.sha1 ?? "")
const name = String(route.query.name ?? "")

const canvasEl = ref<HTMLCanvasElement | null>(null)
const fallbackMsg = ref("")
const rendererReady = ref(false)
const filters = ref<FilterEntry[]>([])
const thumbs = ref<Record<string, string>>({})
const activeId = ref<string | null>(null)
const mixPct = ref(0)

let renderer: LutRenderer | null = null
let currentMix = 0
let heldMix: number | null = null

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error("image load failed"))
    img.src = url
  })
}

function onMixInput(e: Event) {
  mixPct.value = Number((e.target as HTMLInputElement).value)
  applyMix()
}

function applyMix() {
  currentMix = mixPct.value / 100
  renderer?.render(currentMix)
}

function holdStart() {
  heldMix = currentMix
  renderer?.render(0)
}
function holdEnd() {
  if (heldMix === null) return
  renderer?.render(heldMix)
  heldMix = null
}

function pick(f: FilterEntry) {
  activeId.value = f.id
  renderer?.loadLut(f.id, lutCache.get(f.id)!)
  if (mixPct.value === 0) mixPct.value = 100
  applyMix()
}

async function onDownload() {
  if (!renderer) return
  renderer.render(currentMix)
  const blob = await renderer.exportJpeg()
  const a = document.createElement("a")
  const base = name.replace(/\.[^.]+$/, "") || "photo"
  a.href = URL.createObjectURL(blob)
  a.download = `${base}-${activeId.value ?? "original"}.jpg`
  a.click()
  URL.revokeObjectURL(a.href)
}

const lutCache = new Map<string, import("../lib/lutParser").LutData>()

onMounted(async () => {
  if (!sha1) {
    fallbackMsg.value = "缺少图片参数（sha1）"
    return
  }
  // 1. 初始化渲染器（WebGL2 不可用 → 降级提示）
  try {
    renderer = new LutRenderer(canvasEl.value!)
  } catch (err) {
    fallbackMsg.value = err instanceof Error ? err.message : "WebGL 初始化失败"
    return
  }
  // 2. 加载图片（1600 长边缩略图）
  try {
    const img = await loadImage(`/api/thumb/${sha1}?size=1600`)
    renderer.setImage(img)
    rendererReady.value = true
    renderer.render(0)
  } catch {
    fallbackMsg.value = "图片加载失败"
    return
  }
  // 3. 加载滤镜清单与每支 LUT。manifest 整体失败才置空；单支 LUT 失败
  // 只跳过该支（小样位置无图，label 仍在），不影响其他滤镜。
  try {
    const res = await fetch("/filters/manifest.json")
    filters.value = await res.json()
  } catch {
    filters.value = []
  }
  for (const f of filters.value) {
    try {
      const cubeText = await (await fetch(`/filters/${f.file}`)).text()
      lutCache.set(f.id, parseCube(cubeText))
    } catch {
      // 该支 LUT 损坏：从清单剔除，避免 UI 点到空白
      filters.value = filters.value.filter((x) => x.id !== f.id)
    }
  }
  // 4. 小样条：Task 5 会改为离屏小 canvas。这里先复用主 canvas 渲一遍
  // （1600px 渲 N 次成本可接受），渲完立刻 render(0) 回到原图。
  for (const f of filters.value) {
    const lut = lutCache.get(f.id)
    if (!lut) continue
    renderer.loadLut(f.id, lut)
    renderer.render(1)
    thumbs.value[f.id] = canvasEl.value!.toDataURL("image/jpeg", 0.6)
  }
  renderer.render(0)
})
</script>

<style scoped>
.fp-page {
  display: flex; flex-direction: column;
  height: 100vh; background: #111; color: #eee;
}
.fp-topbar {
  padding: 10px 16px; font-size: 14px;
  border-bottom: 1px solid #222;
}
.fp-name { color: #ccc; }
.fp-stage {
  flex: 1; display: flex; align-items: center; justify-content: center;
  overflow: hidden; position: relative;
}
.fp-canvas {
  max-width: 100%; max-height: 100%;
  object-fit: contain;
}
.fp-fallback {
  position: absolute; padding: 24px; color: #f87171; text-align: center;
}
.fp-controls {
  display: flex; gap: 16px; align-items: center;
  padding: 10px 16px; border-top: 1px solid #222;
}
.fp-strength {
  display: flex; align-items: center; gap: 8px; font-size: 13px;
}
.fp-strength input { width: 200px; }
.fp-controls button {
  min-height: 36px; padding: 6px 14px;
  background: #2a2a2a; color: #eee; border: 1px solid #444;
  border-radius: 6px; cursor: pointer;
}
.fp-controls button:disabled { opacity: 0.4; cursor: not-allowed; }
.fp-strip {
  display: flex; gap: 8px; padding: 10px 16px;
  overflow-x: auto; border-top: 1px solid #222;
}
.fp-thumb {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  background: transparent; border: 2px solid transparent;
  padding: 4px; cursor: pointer; border-radius: 6px;
}
.fp-thumb.active { border-color: #3b82f6; }
.fp-thumb img {
  width: 96px; height: 64px; object-fit: cover; border-radius: 4px;
  background: #333; display: block;
}
.fp-thumb-label { font-size: 12px; color: #ccc; }
</style>
```

**注意**：上面"小样条复用主 canvas 渲一次再 toDataURL"的做法有副作用——1600px 主 canvas toDataURL 出来的不是缩略条要的 96×64 小图。Task 5 会把小样渲染改到一个离屏小 canvas 上（用第二个 `LutRenderer` 实例）。Task 4 先让管线跑通，小样图尺寸不对但功能闭环。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/tests/filter-preview-view.spec.ts`
Expected: 前两个测试 PASS（第三个 fallback 测试如果太绕就删掉，把"构造抛错 → fallbackMsg"用 spyOn `LutRenderer` 构造函数来测）。

简化版第三个测试（替代 doMock 取巧方案）：

```ts
it("shows fallback when renderer constructor throws", async () => {
  const mod = await import("../src/lib/lutRenderer")
  vi.spyOn(mod, "LutRenderer").mockImplementationOnce(() => {
    throw new Error("WebGL2 not available")
  })
  const w = mount(FilterPreviewView)
  await flushPromises()
  expect(w.text()).toContain("WebGL2")
})
```

- [ ] **Step 6: 类型检查 + Commit**

```bash
cd frontend && npx vue-tsc --noEmit
# 期望无错误
git add frontend/src/router.ts frontend/src/views/FilterPreviewView.vue frontend/src/tests/filter-preview-view.spec.ts
git commit -m "feat(preview): filter preview route and view skeleton"
```

---

## Task 5: 小样条改用离屏 canvas

**Files:**
- Modify: `frontend/src/views/FilterPreviewView.vue`（"3. 加载滤镜清单"段）
- Test: `frontend/src/tests/filter-preview-view.spec.ts`（追加测试）

**动机：** Task 4 用主 canvas toDataURL 出来的是 1600px 全尺寸图，`<img>` 虽然被 CSS 缩到 96×64，但内存里堆了 3 张全尺寸 JPEG dataURL。改成离屏小 canvas（192×128）+ 第二个 `LutRenderer` 实例。

- [ ] **Step 1: 追加失败测试**

在 `filter-preview-view.spec.ts` 里加：

```ts
it("renders thumbnails on an offscreen small canvas, not the main canvas", async () => {
  const w = mount(FilterPreviewView)
  await flushPromises()
  // 主 renderer 的 render(1) 只在生成小样期间被调用过 N 次（N=filters 数），
  // 且最后一次调用必须是 render(0)（回到原图）
  const r = MockRenderer.instances[0]
  expect(r.render).toHaveBeenLastCalledWith(0)
  // 主 canvas 本身不被 toDataURL —— 由 spyOn 保证
  const mainCanvas = w.find("canvas").element as HTMLCanvasElement
  const spy = vi.spyOn(mainCanvas, "toDataURL")
  // 触发 pick
  await w.findAll("button.fp-thumb").then((bs) => bs[0]?.trigger("click"))
  expect(spy).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/tests/filter-preview-view.spec.ts`
Expected: FAIL — 主 canvas 上调用了 toDataURL。

- [ ] **Step 3: 修改视图的小样生成段**

把 `onMounted` 里 "3. 加载滤镜清单与每支 LUT，渲小样" 段改为：

```ts
  // 3. 加载滤镜清单与每支 LUT
  for (const f of filters.value) {
    const cubeText = await (await fetch(`/filters/${f.file}`)).text()
    lutCache.set(f.id, parseCube(cubeText))
  }
  // 4. 用离屏小 canvas 渲小样（独立的第二个 gl context，避免反复改主 canvas 尺寸）
  const thumbCanvas = document.createElement("canvas")
  thumbCanvas.width = 192
  thumbCanvas.height = 128
  let thumbRenderer: LutRenderer | null = null
  try {
    thumbRenderer = new LutRenderer(thumbCanvas)
    // 用主图（1600）作为纹理源：缩到 192×128 由 GL LINEAR 采样完成
    thumbRenderer.setImage(lastImg)
    for (const f of filters.value) {
      thumbRenderer.loadLut(f.id, lutCache.get(f.id)!)
      thumbRenderer.render(1)
      thumbs.value[f.id] = thumbCanvas.toDataURL("image/jpeg", 0.7)
    }
  } catch {
    // 小样渲染失败不阻塞主预览
  } finally {
    thumbRenderer?.dispose()
  }
```

同时把 "2. 加载图片" 段的 `const img = await loadImage(...)` 改为把 img 存到外层变量：

```ts
  let lastImg: HTMLImageElement | null = null
  // ... 在 onMounted 里
  lastImg = await loadImage(`/api/thumb/${sha1}?size=1600`)
  renderer.setImage(lastImg)
```

- [ ] **Step 4: 跑测试确认通过 + Commit**

```bash
cd frontend && npx vitest run src/tests/filter-preview-view.spec.ts
git add frontend/src/views/FilterPreviewView.vue frontend/src/tests/filter-preview-view.spec.ts
git commit -m "feat(preview): render filter thumbnails on offscreen small canvas"
```

---

## Task 6: 灯箱顶栏"风格滤镜"按钮

**Files:**
- Modify: `frontend/src/components/ImageLightbox.vue`（uiRegister 段内，histogram 按钮之后）
- Test: `frontend/src/tests/lightbox-filter.spec.ts`

**Interfaces:**
- 在 PhotoSwipe UI 注册一个 `name: "filter-preview"` 的按钮，`ariaLabel: "风格滤镜"`，order 13。onClick 行为：
  ```ts
  const it = pswp ? props.items[pswp.currIndex] : undefined
  if (it) {
    const q = new URLSearchParams({ sha1: it.sha1, name: it.filename })
    window.open(`/filter-preview?${q}`, "_blank", "noopener")
  }
  ```

- [ ] **Step 1: 写失败测试**

`frontend/src/tests/lightbox-filter.spec.ts` —— **直接从 `lightbox-original.spec.ts` 复制前 110 行**（`MockInstance` 接口、`instances` 数组、`vi.mock("photoswipe", ...)` 整块），只把测试体换成下面的断言。这套 mock 已经能捕获所有 `registerElement` 调用并支持手动 `onClick!()`：

```ts
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

// ……（与 lightbox-original.spec.ts 相同的 MockPhotoSwipe / instances 骨架）

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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/tests/lightbox-filter.spec.ts`
Expected: FAIL — `btn` undefined（没有 filter-preview 按钮）。

- [ ] **Step 3: 在 ImageLightbox.vue 注册按钮**

在 `uiRegister` 回调里，"直方图按钮"注册块（约 850–862 行）之后插入：

```ts
    // "风格滤镜"按钮：新标签页打开滤镜预览
    pswp!.ui!.registerElement({
      name: "filter-preview",
      ariaLabel: "风格滤镜",
      order: 13,
      isButton: true,
      html: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="13.5" cy="6.5" r=".5" fill="white"/>
        <circle cx="17.5" cy="10.5" r=".5" fill="white"/>
        <circle cx="8.5" cy="7.5" r=".5" fill="white"/>
        <circle cx="6.5" cy="12.5" r=".5" fill="white"/>
        <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.129a1.688 1.688 0 0 1 1.668-1.688h1.996c1.661 0 3.313-1.333 3.313-2.999C21.942 6.014 17.451 2 12 2z"/>
      </svg>`,
      onClick: () => {
        const it = pswp ? props.items[pswp.currIndex] : undefined
        if (!it) return
        const q = new URLSearchParams({ sha1: it.sha1, name: it.filename })
        window.open(`/filter-preview?${q}`, "_blank", "noopener")
      },
    })
```

- [ ] **Step 4: 跑测试确认通过 + Commit**

```bash
cd frontend && npx vitest run src/tests/lightbox-filter.spec.ts
git add frontend/src/components/ImageLightbox.vue frontend/src/tests/lightbox-filter.spec.ts
git commit -m "feat(lightbox): add style-filter button opening preview tab"
```

---

## Task 7: 全量回归 + 手工验收

- [ ] **Step 1: 跑全量测试**

Run: `cd frontend && npx vitest run`
Expected: 全部现有测试 + 新增 5 个 spec 全 PASS。

- [ ] **Step 2: 类型检查**

Run: `cd frontend && npx vue-tsc --noEmit`
Expected: 无错误。

- [ ] **Step 3: 构建一次**

Run: `cd frontend && npx vite build`
Expected: 构建成功，`dist/filters/manifest.json` 与 3 个 `.cube` 被拷入 dist。

- [ ] **Step 4: 手工验收（参照 spec 的"手工验收清单"）**

启动前后端后逐条点：
1. 灯箱顶栏出现调色板按钮 → 新标签页打开 `/filter-preview?sha1=...&name=...`
2. 主画布显示 1600 缩略图，首屏为原图（无滤镜）
3. 底部 3 张小样（暖/冷/黑白）视觉差异明显
4. 点小样 → 主画面切换滤镜，强度默认 100%
5. 拖强度滑块 0→100% 平滑
6. 按住"看原图"立即回原图，松开恢复
7. 下载 JPEG：文件名 `<原名>-<滤镜id>.jpg`，1600 长边
8. （可选）浏览器 flag 关 WebGL2 验证降级文案

- [ ] **Step 5: Commit（如有手工阶段的小修正）**

```bash
git add -A
git commit -m "chore(preview): manual acceptance fixes for LUT filter preview" --allow-empty
```
