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
    throw new Error(`.cube: expected ${expected}, got ${values.length}`)
  }
  const data = new Uint8Array(expected)
  for (let i = 0; i < expected; i++) {
    data[i] = Math.max(0, Math.min(255, Math.round(values[i] * 255)))
  }
  return { size, data }
}
