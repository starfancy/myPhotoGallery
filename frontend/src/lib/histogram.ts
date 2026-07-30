/**
 * 前端直方图计算：给定图片 URL，返回 RGB 三通道各 256 桶的分布。
 *
 * 采用方案：加载 <img> → offscreen canvas → drawImage → getImageData
 * → stride 采样累加。stride=4（水平/垂直方向每 4 像素采 1 个）对 512
 * 缩图约扫 4096 个采样点，肉眼看不出与全采样的差别，计算 <5ms。
 *
 * 抽出为独立模块方便后续升级到 Web Worker：调用签名不变。
 */

export interface Histogram {
  r: Uint32Array // length 256
  g: Uint32Array
  b: Uint32Array
  /** 采样点总数，用于把桶值归一化到 [0,1]。 */
  samples: number
  /** RGB 三通道各自的均值，方便面板下方展示概要。 */
  meanR: number
  meanG: number
  meanB: number
}

export async function computeHistogramFromUrl(
  url: string,
  opts: { stride?: number; signal?: AbortSignal } = {},
): Promise<Histogram> {
  const stride = opts.stride ?? 4
  const img = await loadImage(url, opts.signal)
  return computeHistogramFromImage(img, stride)
}

function loadImage(url: string, signal?: AbortSignal): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    // 同源图片；不设 crossOrigin 也能画到 canvas 并 getImageData
    img.decoding = "async"
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error("image load failed"))
    if (signal) {
      if (signal.aborted) {
        reject(new DOMException("aborted", "AbortError"))
        return
      }
      signal.addEventListener("abort", () => {
        img.src = "" // 取消下载
        reject(new DOMException("aborted", "AbortError"))
      }, { once: true })
    }
    img.src = url
  })
}

function computeHistogramFromImage(img: HTMLImageElement, stride: number): Histogram {
  const w = img.naturalWidth
  const h = img.naturalHeight
  // 用 OffscreenCanvas 有 GPU 到 CPU 内存拷贝更快，但兼容性一般；
  // 这里退到普通 canvas，够快也够稳。
  const canvas = document.createElement("canvas")
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext("2d", { willReadFrequently: true })
  if (!ctx) throw new Error("2d context not available")
  ctx.drawImage(img, 0, 0)
  const data = ctx.getImageData(0, 0, w, h).data

  const r = new Uint32Array(256)
  const g = new Uint32Array(256)
  const b = new Uint32Array(256)
  let sumR = 0, sumG = 0, sumB = 0, samples = 0
  const rowStride = stride * w * 4
  for (let y = 0; y < h; y += stride) {
    const rowStart = y * w * 4
    for (let x = 0; x < w; x += stride) {
      const i = rowStart + x * 4
      const rv = data[i]
      const gv = data[i + 1]
      const bv = data[i + 2]
      r[rv]++
      g[gv]++
      b[bv]++
      sumR += rv
      sumG += gv
      sumB += bv
      samples++
    }
    // rowStride 计算保留（预留跳行优化空间；当前用 y+=stride 已足够）
    void rowStride
  }
  return {
    r, g, b, samples,
    meanR: samples ? sumR / samples : 0,
    meanG: samples ? sumG / samples : 0,
    meanB: samples ? sumB / samples : 0,
  }
}

/**
 * 把直方图渲染到 canvas：三通道半透明叠加（screen 混合），
 * 让 R+G+B 都饱和的桶显示为白色，符合 Photoshop 直方图观感。
 */
export function drawHistogram(canvas: HTMLCanvasElement, hist: Histogram) {
  const w = canvas.width
  const h = canvas.height
  const ctx = canvas.getContext("2d")
  if (!ctx) return
  ctx.clearRect(0, 0, w, h)

  // 找三通道桶最大值作为竖直归一化基准；忽略 0 和 255 端的极值，
  // 否则纯黑/纯白背景会把中间调压得完全看不见。
  const maxBar = Math.max(
    peakExcludingEdges(hist.r),
    peakExcludingEdges(hist.g),
    peakExcludingEdges(hist.b),
    1,
  )

  ctx.globalCompositeOperation = "screen"
  drawChannel(ctx, hist.r, w, h, maxBar, "rgba(255, 60, 60, 0.85)")
  drawChannel(ctx, hist.g, w, h, maxBar, "rgba(60, 220, 90, 0.85)")
  drawChannel(ctx, hist.b, w, h, maxBar, "rgba(80, 130, 255, 0.9)")
  ctx.globalCompositeOperation = "source-over"
}

function peakExcludingEdges(a: Uint32Array): number {
  let m = 0
  for (let i = 1; i < 255; i++) if (a[i] > m) m = a[i]
  return m
}

function drawChannel(
  ctx: CanvasRenderingContext2D,
  bins: Uint32Array,
  w: number,
  h: number,
  maxBar: number,
  fill: string,
) {
  const step = w / 256
  ctx.beginPath()
  ctx.moveTo(0, h)
  for (let i = 0; i < 256; i++) {
    const v = Math.min(bins[i] / maxBar, 1)
    const y = h - v * (h - 2) // 顶上留 2px 空隙
    ctx.lineTo(i * step, y)
  }
  ctx.lineTo(w, h)
  ctx.closePath()
  ctx.fillStyle = fill
  ctx.fill()
}
