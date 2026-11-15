import { describe, expect, it } from "vitest"
import {
  RESIZE_STEP,
  clampHeight,
  draggedHeight,
  draggedWidth,
  steppedHeight,
} from "../lib/resize"

describe("resize helpers", () => {
  it("clampHeight：区间外钳制、区间内原样返回", () => {
    expect(clampHeight(50, 100, 400)).toBe(100)
    expect(clampHeight(500, 100, 400)).toBe(400)
    expect(clampHeight(250, 100, 400)).toBe(250)
  })

  it("clampHeight：min>max 倒挂时以较小者为下界、较大者为上界", () => {
    expect(clampHeight(10, 400, 130)).toBe(130)
    expect(clampHeight(500, 400, 130)).toBe(400)
  })

  it("draggedHeight：指针上移增高、下移缩小", () => {
    // 手柄在区域上沿：currentY 比 startY 小 20（上移）→ 高度 +20
    expect(draggedHeight(200, 300, 280)).toBe(220)
    // 下移 30 → 高度 -30
    expect(draggedHeight(200, 300, 330)).toBe(170)
  })

  it("draggedWidth：竖向右缘手柄右移加宽、左移变窄", () => {
    // currentX 比 startX 大 20（右移）→ 宽度 +20
    expect(draggedWidth(200, 300, 320)).toBe(220)
    // 左移 30 → 宽度 -30
    expect(draggedWidth(200, 300, 270)).toBe(170)
  })

  it("steppedHeight：按 RESIZE_STEP 步进并在边界钳制", () => {
    expect(steppedHeight(200, 1, 130, 400)).toBe(200 + RESIZE_STEP)
    expect(steppedHeight(200, -1, 130, 400)).toBe(200 - RESIZE_STEP)
    expect(steppedHeight(135, -1, 130, 400)).toBe(130)
    expect(steppedHeight(395, 1, 130, 400)).toBe(400)
  })
})
