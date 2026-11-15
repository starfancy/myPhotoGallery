/** 滤镜条高度键盘调节的步进像素。 */
export const RESIZE_STEP = 16

/** 把高度钳进 [min, max]；min/max 倒挂时以较小者为下界。 */
export function clampHeight(h: number, min: number, max: number): number {
  const lo = Math.min(min, max)
  return Math.min(Math.max(h, lo), Math.max(min, max))
}

/** 拖拽数学：手柄在区域上沿，指针上移（currentY < startY）时区域增高。 */
export function draggedHeight(
  startHeight: number,
  startY: number,
  currentY: number,
): number {
  return startHeight + (startY - currentY)
}

/** 键盘步进后再钳制。dir：+1 增高（↑）、-1 降低（↓）。 */
export function steppedHeight(
  current: number,
  dir: 1 | -1,
  min: number,
  max: number,
): number {
  return clampHeight(current + dir * RESIZE_STEP, min, max)
}
