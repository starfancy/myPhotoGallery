import { describe, expect, it } from "vitest"
import {
  MASONRY_MAX_COLUMNS,
  MASONRY_MIN_COLUMNS,
  masonryColumns,
  masonryLayout,
} from "../utils/layout"

describe("masonryColumns", () => {
  it("clamps to the minimum on narrow / zero-width containers", () => {
    expect(masonryColumns(0)).toBe(MASONRY_MIN_COLUMNS)
    expect(masonryColumns(320)).toBe(MASONRY_MIN_COLUMNS)
  })

  it("adds a column at each width breakpoint", () => {
    // n 列阈值 = n * (280 + 8) - 8
    expect(masonryColumns(855)).toBe(2)
    expect(masonryColumns(856)).toBe(3)
    expect(masonryColumns(1143)).toBe(3)
    expect(masonryColumns(1144)).toBe(4)
    expect(masonryColumns(1431)).toBe(4)
    expect(masonryColumns(1432)).toBe(5)
    expect(masonryColumns(1719)).toBe(5)
    expect(masonryColumns(1720)).toBe(6)
  })

  it("clamps to the maximum on very wide containers", () => {
    expect(masonryColumns(4000)).toBe(MASONRY_MAX_COLUMNS)
  })
})

describe("masonryLayout", () => {
  it("gives portrait images a larger span than landscape images", () => {
    const laid = masonryLayout(
      [
        { w: 3, h: 2 }, // 横版 3:2
        { w: 2, h: 3 }, // 竖版 2:3
      ],
      1000,
      8,
    )
    expect(laid.columns).toBe(3)
    expect(laid.items[1].span).toBeGreaterThan(laid.items[0].span)
  })

  it("always returns a positive integer span", () => {
    const laid = masonryLayout(
      [
        { w: 3, h: 2 },
        { w: 100, h: 1 },
        { w: 1, h: 100 },
      ],
      320,
      8,
    )
    for (const it of laid.items) {
      expect(Number.isInteger(it.span)).toBe(true)
      expect(it.span).toBeGreaterThanOrEqual(1)
    }
  })

  it("returns no items for empty input but still a column count", () => {
    const laid = masonryLayout([], 1000, 8)
    expect(laid.items).toEqual([])
    expect(laid.columns).toBe(3)
  })
})
