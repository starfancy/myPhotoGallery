export interface LayoutInput {
  w: number
  h: number
}

export interface LayoutItem extends LayoutInput {
  scaledW: number
  scaledH: number
}

export interface LayoutRow {
  items: LayoutItem[]
  height: number
}

export function justifiedRows(
  items: LayoutInput[],
  containerWidth: number,
  targetHeight = 200,
  gap = 4,
): LayoutRow[] {
  const rows: LayoutRow[] = []
  let cursor: LayoutInput[] = []
  for (const it of items) {
    cursor.push(it)
    const aspectSum = cursor.reduce((a, x) => a + x.w / x.h, 0)
    const rowW = aspectSum * targetHeight + gap * (cursor.length - 1)
    if (rowW >= containerWidth) {
      const scale = (containerWidth - gap * (cursor.length - 1)) / (aspectSum * targetHeight)
      const height = targetHeight * scale
      rows.push({
        items: cursor.map((x) => ({ ...x, scaledW: (x.w / x.h) * height, scaledH: height })),
        height,
      })
      cursor = []
    }
  }
  if (cursor.length) {
    rows.push({
      items: cursor.map((x) => ({ ...x, scaledW: (x.w / x.h) * targetHeight, scaledH: targetHeight })),
      height: targetHeight,
    })
  }
  return rows
}
