import { describe, expect, it } from "vitest"
import { justifiedRows } from "../utils/layout"

describe("justifiedRows", () => {
  it("packs items into full rows", () => {
    const items = Array.from({ length: 10 }, () => ({ w: 300, h: 200 }))
    const rows = justifiedRows(items, 1000, 200, 4)
    for (const r of rows.slice(0, -1)) {
      const total = r.items.reduce((a, x) => a + x.scaledW, 0) + 4 * (r.items.length - 1)
      expect(Math.abs(total - 1000)).toBeLessThan(1)
    }
  })

  it("keeps trailing partial row at target height", () => {
    const items = [{ w: 300, h: 200 }]
    const rows = justifiedRows(items, 1000, 200, 4)
    expect(rows[0].height).toBe(200)
  })

  it("empty input returns no rows", () => {
    expect(justifiedRows([], 1000, 200, 4)).toEqual([])
  })
})
