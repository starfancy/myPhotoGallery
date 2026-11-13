import { describe, expect, it } from "vitest"
import {
  appendFilterParams,
  dayEndEpoch,
  dayStartEpoch,
} from "../utils/filters"

describe("date filter epoch conversion", () => {
  it("converts YYYY-MM-DD to local day start/end epoch seconds", () => {
    // 2024-01-01 本地 00:00:00 与 23:59:59
    const start = dayStartEpoch("2024-01-01")!
    const end = dayEndEpoch("2024-01-01")!
    expect(new Date(start * 1000).getFullYear()).toBe(2024)
    expect(new Date(start * 1000).getMonth()).toBe(0)
    expect(new Date(start * 1000).getDate()).toBe(1)
    expect(new Date(start * 1000).getHours()).toBe(0)
    expect(new Date(end * 1000).getHours()).toBe(23)
    expect(end - start).toBe(86399) // 整天跨度
  })

  it("returns null for empty/invalid input", () => {
    expect(dayStartEpoch("")).toBeNull()
    expect(dayEndEpoch("")).toBeNull()
    expect(dayStartEpoch("not-a-date")).toBeNull()
  })

  it("appendFilterParams writes scene and date params, skips empties", () => {
    const params = new URLSearchParams()
    appendFilterParams(params, {
      sceneMajor: "自然风光",
      sceneMinor: "山景",
      dateFrom: "2024-01-01",
      dateTo: "",
    })
    expect(params.get("scene_major")).toBe("自然风光")
    expect(params.get("scene_minor")).toBe("山景")
    expect(params.get("date_from")).toBe(String(dayStartEpoch("2024-01-01")))
    expect(params.has("date_to")).toBe(false)
  })

  it("appendFilterParams produces empty params when nothing set", () => {
    const params = new URLSearchParams()
    appendFilterParams(params, {})
    expect(params.toString()).toBe("")
  })
})
