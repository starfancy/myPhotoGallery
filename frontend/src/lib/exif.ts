/**
 * JPEG EXIF 段搬运（纯字节操作，零依赖）。
 *
 * 背景：canvas.toBlob 导出的 JPEG 不带任何元数据。本模块把源 JPEG 的
 * APP1/EXIF 段搬进导出文件（紧跟 SOI 之后），并把 IFD 链上的
 * Orientation(0x0112) 统一改写为 1——浏览器把 <img> 画到 canvas 时已按
 * EXIF 方向转正像素，保留原方向会让查看器二次旋转。
 *
 * 源文件无 EXIF（PNG/HEIC/被剥离的缩略图）或结构异常时原样返回 canvas
 * JPEG 字节，绝不抛错。
 */

const SOI = 0xffd8
const APP1 = 0xffe1
/** "Exif\0\0"：APP1 载荷前 6 字节的识别魔数 */
const EXIF_MAGIC = [0x45, 0x78, 0x69, 0x66, 0x00, 0x00]
const ORIENTATION_TAG = 0x0112
const MAX_IFD_CHAIN = 8

function toU8(input: ArrayBuffer | Uint8Array): Uint8Array {
  return input instanceof Uint8Array ? input : new Uint8Array(input)
}

/** 在 JPEG 段区找 EXIF APP1，返回 [起, 止) 字节区间；找不到或结构损坏返回 null。 */
function findExifSegment(bytes: Uint8Array): [number, number] | null {
  if (bytes.length < 4 || ((bytes[0] << 8) | bytes[1]) !== SOI) return null
  let i = 2
  while (i + 4 <= bytes.length) {
    if (bytes[i] !== 0xff) return null // 已进入扫描数据或遇到填充字节
    const marker = (bytes[i] << 8) | bytes[i + 1]
    if (marker < 0xffe0 || marker > 0xffef) return null // 非 APP 段（SOS 等），段区结束
    const segLen = (bytes[i + 2] << 8) | bytes[i + 3]
    if (segLen < 2 || i + 2 + segLen > bytes.length) return null // 长度越界=损坏
    if (marker === APP1 && i + 10 <= bytes.length) {
      let match = true
      for (let k = 0; k < EXIF_MAGIC.length; k++) {
        if (bytes[i + 4 + k] !== EXIF_MAGIC[k]) {
          match = false
          break
        }
      }
      if (match) return [i, i + 2 + segLen]
    }
    i += 2 + segLen
  }
  return null
}

/** 复制 EXIF 段并把 IFD 链上所有 Orientation 改写为 1；TIFF 头损坏则原样返回副本。 */
function resetOrientation(seg: Uint8Array): Uint8Array {
  const out = seg.slice()
  const tiff = 10 // marker(2) + length(2) + "Exif\0\0"(6)
  if (tiff + 8 > out.length) return out
  const little = out[tiff] === 0x49 && out[tiff + 1] === 0x49
  const big = out[tiff] === 0x4d && out[tiff + 1] === 0x4d
  if (!little && !big) return out
  const u16 = (off: number): number =>
    little ? out[off] | (out[off + 1] << 8) : (out[off] << 8) | out[off + 1]
  const u32 = (off: number): number =>
    little
      ? (out[off] | (out[off + 1] << 8) | (out[off + 2] << 16) | (out[off + 3] << 24)) >>> 0
      : ((out[off] << 24) | (out[off + 1] << 16) | (out[off + 2] << 8) | out[off + 3]) >>> 0
  if (u16(tiff + 2) !== 0x002a) return out // 非法 TIFF 魔数，不动它

  let ifd = tiff + u32(tiff + 4)
  for (let guard = 0; guard < MAX_IFD_CHAIN; guard++) {
    if (ifd <= tiff || ifd + 2 > out.length) break
    const n = u16(ifd)
    if (ifd + 2 + n * 12 + 4 > out.length) break
    for (let e = 0; e < n; e++) {
      const eo = ifd + 2 + e * 12
      if (u16(eo) === ORIENTATION_TAG) {
        // SHORT 内联在 4 字节值字段的前两字节
        out[eo + 8] = little ? 1 : 0
        out[eo + 9] = little ? 0 : 1
      }
    }
    const nextRel = u32(ifd + 2 + n * 12)
    if (nextRel === 0) break
    ifd = tiff + nextRel
  }
  return out
}

/**
 * 把源 JPEG 的 EXIF 段注入 canvas 导出 JPEG（SOI 之后），并复位 Orientation。
 * 源无可用 EXIF 或 canvas 字节不是 JPEG 时，返回 canvas 的副本。
 * 不写显式返回类型：所有分支都返回新建的 ArrayBuffer-backed Uint8Array，
 * 让 TS 推断出满足 BlobPart 的类型（5.7+ TypedArray 泛型），同时兼容旧版 TS。
 */
export function injectExif(
  source: ArrayBuffer | Uint8Array,
  canvasJpeg: ArrayBuffer | Uint8Array,
) {
  const src = toU8(source)
  const canvas = toU8(canvasJpeg)
  if (canvas.length < 2 || ((canvas[0] << 8) | canvas[1]) !== SOI) return canvas.slice()

  const range = findExifSegment(src)
  if (!range) return canvas.slice()
  const seg = resetOrientation(src.slice(range[0], range[1]))

  const out = new Uint8Array(2 + seg.length + (canvas.length - 2))
  out.set([0xff, 0xd8], 0)
  out.set(seg, 2)
  out.set(canvas.subarray(2), 2 + seg.length)
  return out
}
