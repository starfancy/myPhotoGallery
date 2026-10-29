import { describe, expect, it } from "vitest"
import { formatDateTime, formatPurgeAfter, NEVER_PURGE_TS } from "../utils/datetime"

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

describe("formatPurgeAfter", () => {
  it("renders the sentinel timestamp as 永不", () => {
    expect(formatPurgeAfter(NEVER_PURGE_TS)).toBe("永不")
    expect(formatPurgeAfter(NEVER_PURGE_TS + 100)).toBe("永不")
  })

  it("formats ordinary timestamps as YYYY-MM-DD HH:mm", () => {
    const ts = Math.floor(new Date(2026, 9, 28, 9, 5).getTime() / 1000)
    expect(formatPurgeAfter(ts)).toBe("2026-10-28 09:05")
  })
})
