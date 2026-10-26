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

// ---------- masonry：列等宽、竖图按比例占更多高度，行顺序阅读 ----------

export const MASONRY_TARGET_COLUMN_WIDTH = 280
export const MASONRY_MIN_COLUMNS = 2
export const MASONRY_MAX_COLUMNS = 6
/** 基础行轨道高度；图片高度按它取整定跨度，误差由 object-cover 吸收 */
export const MASONRY_ROW_UNIT = 4

export interface MasonryLayoutItem extends LayoutInput {
  /** 占用多少条基础行轨道 */
  span: number
}

export interface MasonryLayout<T extends LayoutInput> {
  columns: number
  columnWidth: number
  items: (T & { span: number })[]
}

export function masonryColumns(
  containerWidth: number,
  targetColumnWidth = MASONRY_TARGET_COLUMN_WIDTH,
  gap = 8,
  minColumns = MASONRY_MIN_COLUMNS,
  maxColumns = MASONRY_MAX_COLUMNS,
): number {
  if (containerWidth <= 0) return minColumns
  const n = Math.floor((containerWidth + gap) / (targetColumnWidth + gap))
  return Math.min(maxColumns, Math.max(minColumns, n))
}

/**
 * 列宽固定（等分容器），每张图按原始宽高比折算高度并换算成
 * grid-row 跨度；配合 CSS Grid 的 grid-auto-flow: row dense 使用，
 * 浏览器按行顺序放置、遇空隙回填。
 */
export function masonryLayout<T extends LayoutInput>(
  items: T[],
  containerWidth: number,
  gap = 8,
  targetColumnWidth = MASONRY_TARGET_COLUMN_WIDTH,
): MasonryLayout<T> {
  const columns = masonryColumns(containerWidth, targetColumnWidth, gap)
  const columnWidth = Math.max(0, (containerWidth - gap * (columns - 1)) / columns)
  const laid = items.map((it) => {
    // 等比缩放到列宽后的像素高度；跨 K 条轨道实际占 K*unit + (K-1)*gap
    const h = columnWidth * (it.h / it.w)
    const span = Math.max(1, Math.round((h + gap) / (MASONRY_ROW_UNIT + gap)))
    return { ...it, span }
  })
  return { columns, columnWidth, items: laid }
}
