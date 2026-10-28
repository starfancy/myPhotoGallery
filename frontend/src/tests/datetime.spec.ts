import { describe, expect, it } from "vitest"
import { formatDateTime } from "../utils/datetime"

describe("formatDateTime", () => {
  it("formats a unix-second timestamp as YYYY-MM-DD HH:mm in local time", () => {
    // 用本地时区构造，保证断言不依赖运行环境时区
    const ts = Math.floor(new Date(2024, 4, 1, 14, 30, 0).getTime() / 1000)
    expect(formatDateTime(ts)).toBe("2024-05-01 14:30")
  })

  it("zero-pads single-digit month/day/hour/minute", () => {
    const ts = Math.floor(new Date(2025, 0, 3, 9, 5, 0).getTime() / 1000)
    expect(formatDateTime(ts)).toBe("2025-01-03 09:05")
  })
})
