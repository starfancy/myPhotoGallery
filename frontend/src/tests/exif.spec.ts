import { describe, expect, it } from "vitest"
import { injectExif } from "../lib/exif"

// ---- 合成 JPEG/EXIF 字节夹具 ----

const SOI = [0xff, 0xd8]
const SOS = [0xff, 0xda, 0x00, 0x02, 0x00, 0x00] // marker + 长度 2 + 假扫描头
const SCAN_TAIL = [0x11, 0x22, 0x33, 0x44, 0x55]

function concat(parts: Array<ArrayLike<number>>): Uint8Array {
  const n = parts.reduce((s, p) => s + p.length, 0)
  const out = new Uint8Array(n)
  let off = 0
  for (const p of parts) {
    out.set(p, off)
    off += p.length
  }
  return out
}
const be16 = (v: number) => new Uint8Array([(v >> 8) & 0xff, v & 0xff])
const le16 = (v: number) => new Uint8Array([v & 0xff, (v >> 8) & 0xff])
const le32 = (v: number) =>
  new Uint8Array([v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff, (v >> 24) & 0xff])
const be32 = (v: number) =>
  new Uint8Array([(v >> 24) & 0xff, (v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff])
const ascii = (s: string) => new TextEncoder().encode(s)

/** 单个 IFD：entries 为 [tag, type, count, value(内联 SHORT/LONG)] 元组列表。 */
function buildIfd(
  little: boolean,
  entries: Array<[number, number, number, number]>,
  nextIfdOffset: number,
): Uint8Array {
  const rd16 = little ? le16 : be16
  const rd32 = little ? le32 : be32
  const body: Uint8Array[] = [rd16(entries.length)]
  for (const [tag, type, count, value] of entries) {
    // 内联值字段 4 字节：SHORT(3) 占前两字节（大端序关键），LONG(4) 占满
    const inline =
      type === 3 ? concat([rd16(value), new Uint8Array([0, 0])]) : rd32(value)
    body.push(rd16(tag), rd16(type), rd32(count), inline)
  }
  body.push(rd32(nextIfdOffset))
  return concat(body)
}

/** 合成含 IFD0（可带 IFD1 链）的最小 TIFF 块，起始偏移 0。 */
function buildTiff(
  little: boolean,
  ifd0Entries: Array<[number, number, number, number]>,
  ifd1Entries: Array<[number, number, number, number]> = [],
): Uint8Array {
  const rd16 = little ? le16 : be16
  const rd32 = little ? le32 : be32
  const ifd0Offset = 8
  const ifd0 = buildIfd(little, ifd0Entries, ifd1Entries.length ? 0 : 0)
  // 先占位算 IFD1 位置（IFD0 头 2 + 12N + next 4）
  const ifd1Offset = ifd0Offset + ifd0.length
  const ifd1 = ifd1Entries.length ? buildIfd(little, ifd1Entries, 0) : new Uint8Array(0)
  const rebuiltIfd0 = buildIfd(little, ifd0Entries, ifd1Entries.length ? ifd1Offset : 0)
  const header = concat([
    new Uint8Array(little ? [0x49, 0x49] : [0x4d, 0x4d]),
    rd16(0x002a),
    rd32(ifd0Offset),
  ])
  return concat([header, rebuiltIfd0, ifd1])
}

function app1(tiff: Uint8Array): Uint8Array {
  const payload = concat([ascii("Exif\0\0"), tiff])
  return concat([new Uint8Array([0xff, 0xe1]), be16(payload.length + 2), payload])
}

function jfifApp0(): Uint8Array {
  // "JFIF\0" + 版本 1.2 + 密度/缩略图占位字节
  const payload = new Uint8Array([
    0x4a, 0x46, 0x49, 0x46, 0x00, 0x01, 0x02, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
  ])
  return concat([new Uint8Array([0xff, 0xe0]), be16(payload.length + 2), payload])
}

const ORIENT = 0x0112
const IMAGE_WIDTH = 0x0100

/** 独立于被测实现的 IFD 方向读取器，返回链上每个 IFD 的 Orientation 值。 */
function readOrientations(bytes: Uint8Array): number[] {
  const exifAt = bytes.findIndex((_, i) =>
    i + 9 < bytes.length &&
    bytes[i] === 0xff && bytes[i + 1] === 0xe1 &&
    bytes[i + 4] === 0x45 && bytes[i + 9] === 0x00, // "Exif\0"
  )
  expect(exifAt).toBeGreaterThanOrEqual(0)
  const tiff = exifAt + 10
  const little = bytes[tiff] === 0x49
  const u16 = (off: number) =>
    little ? bytes[off] | (bytes[off + 1] << 8) : (bytes[off] << 8) | bytes[off + 1]
  const u32 = (off: number) =>
    little
      ? bytes[off] | (bytes[off + 1] << 8) | (bytes[off + 2] << 16) | (bytes[off + 3] << 24)
      : (bytes[off] << 24) | (bytes[off + 1] << 16) | (bytes[off + 2] << 8) | bytes[off + 3]
  const out: number[] = []
  let ifd = tiff + u32(tiff + 4)
  for (let guard = 0; guard < 8 && ifd > tiff; guard++) {
    const n = u16(ifd)
    for (let e = 0; e < n; e++) {
      const eo = ifd + 2 + e * 12
      if (u16(eo) === ORIENT) out.push(u16(eo + 8))
    }
    const next = u32(ifd + 2 + n * 12)
    if (next === 0) break
    ifd = tiff + next
  }
  return out
}

function makeSourceJpeg(tiff: Uint8Array): Uint8Array {
  return concat([new Uint8Array(SOI), app1(tiff), new Uint8Array(SOS), new Uint8Array(SCAN_TAIL)])
}
function makeCanvasJpeg(): Uint8Array {
  return concat([
    new Uint8Array(SOI), jfifApp0(), new Uint8Array(SOS), new Uint8Array(SCAN_TAIL),
  ])
}

describe("injectExif", () => {
  it("把 EXIF APP1 插到新 JPEG 的 SOI 之后、JFIF APP0 之前", () => {
    const tiff = buildTiff(true, [[ORIENT, 3, 1, 6]])
    const out = injectExif(makeSourceJpeg(tiff), makeCanvasJpeg())
    expect(out[0]).toBe(0xff)
    expect(out[1]).toBe(0xd8)
    expect(out[2]).toBe(0xff)
    expect(out[3]).toBe(0xe1)
    // EXIF 段之后仍保留 canvas 自己的 JFIF APP0
    const app0At = out.findIndex((_, i) => out[i] === 0xff && out[i + 1] === 0xe0)
    expect(app0At).toBeGreaterThan(3)
    // canvas 的扫描数据尾巴完整保留
    expect(Array.from(out.slice(out.length - SCAN_TAIL.length))).toEqual(SCAN_TAIL)
  })

  it("小端 II：IFD0 的 Orientation 6 改写为 1（canvas 像素已转正，防二次旋转）", () => {
    const tiff = buildTiff(true, [[ORIENT, 3, 1, 6]])
    const out = injectExif(makeSourceJpeg(tiff), makeCanvasJpeg())
    expect(readOrientations(out)).toEqual([1])
  })

  it("大端 MM：Orientation 同样改写为 1", () => {
    const tiff = buildTiff(false, [[ORIENT, 3, 1, 8]])
    const out = injectExif(makeSourceJpeg(tiff), makeCanvasJpeg())
    expect(readOrientations(out)).toEqual([1])
  })

  it("沿 next-IFD 链把 IFD1（缩略图）的 Orientation 一并复位", () => {
    const tiff = buildTiff(
      true,
      [[ORIENT, 3, 1, 6], [IMAGE_WIDTH, 4, 1, 4000]],
      [[ORIENT, 3, 1, 6]],
    )
    const out = injectExif(makeSourceJpeg(tiff), makeCanvasJpeg())
    expect(readOrientations(out)).toEqual([1, 1])
    // 非方向标签原样保留（含字节序）
    const exifAt = out.findIndex((_, i) => out[i] === 0xff && out[i + 1] === 0xe1)
    const tiff0 = exifAt + 10
    const ifd0 = tiff0 + 8
    // 第二个 entry：tag 在偏移 12，LONG 值在 +8
    expect(out[ifd0 + 2 + 12]).toBe(IMAGE_WIDTH & 0xff)
    expect(
      out[ifd0 + 2 + 12 + 8] |
        (out[ifd0 + 2 + 12 + 9] << 8) |
        (out[ifd0 + 2 + 12 + 10] << 16) |
        (out[ifd0 + 2 + 12 + 11] << 24),
    ).toBe(4000)
  })

  it("EXIF 中没有 Orientation 标签时原样插入，不报错", () => {
    const tiff = buildTiff(true, [[IMAGE_WIDTH, 4, 1, 1920]])
    const src = makeSourceJpeg(tiff)
    const out = injectExif(src, makeCanvasJpeg())
    expect(readOrientations(out)).toEqual([])
    expect(out.length).toBe(makeCanvasJpeg().length + app1(tiff).length)
  })

  it("源 JPEG 没有 EXIF 段时返回 canvas 原字节", () => {
    const noExif = concat([new Uint8Array(SOI), jfifApp0(), new Uint8Array(SOS)])
    const canvas = makeCanvasJpeg()
    const out = injectExif(noExif, canvas)
    expect(Array.from(out)).toEqual(Array.from(canvas))
  })

  it("源是 PNG（无 SOI/APP1）时返回 canvas 原字节", () => {
    const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    const canvas = makeCanvasJpeg()
    expect(Array.from(injectExif(png, canvas))).toEqual(Array.from(canvas))
  })

  it("APP1 长度字段越界（截断/损坏）时不抛错，返回 canvas 原字节", () => {
    const broken = concat([
      new Uint8Array(SOI),
      new Uint8Array([0xff, 0xe1, 0xff, 0xff]), // 声称长度 65535，实际没有载荷
      ascii("Exif\0\0"),
    ])
    const canvas = makeCanvasJpeg()
    expect(Array.from(injectExif(broken, canvas))).toEqual(Array.from(canvas))
  })

  it("TIFF 字节序非法时不抛错，仍把 EXIF 段原样插入", () => {
    const tiff = buildTiff(true, [[ORIENT, 3, 1, 6]])
    tiff[0] = 0x58 // 'X'，破坏 II/MM 魔数
    const out = injectExif(makeSourceJpeg(tiff), makeCanvasJpeg())
    expect(out[2]).toBe(0xff)
    expect(out[3]).toBe(0xe1)
  })

  it("canvas 字节缺少 SOI 时防御性返回原字节", () => {
    const tiff = buildTiff(true, [[ORIENT, 3, 1, 6]])
    const weird = new Uint8Array([0x00, 0x00, 0x01, 0x02])
    expect(Array.from(injectExif(makeSourceJpeg(tiff), weird))).toEqual([0, 0, 1, 2])
  })
})
