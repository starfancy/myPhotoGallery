import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import MonthChart from "../components/charts/MonthChart.vue"

const THREE_MONTHS = [
  { month: "2025-01", count: 2 },
  { month: "2025-02", count: 0 },
  { month: "2025-03", count: 4 },
]

function mountChart(months = THREE_MONTHS) {
  return mount(MonthChart, { props: { months } })
}

describe("MonthChart", () => {
  it("renders one titled hit-area per month including zero months", () => {
    const w = mountChart()
    const titles = w.findAll("rect title").map((t) => t.text())
    expect(titles.length).toBe(3)
    expect(titles).toContain("2025-01 · 2 张")
    expect(titles).toContain("2025-02 · 0 张")
    expect(titles).toContain("2025-03 · 4 张")
  })

  it("labels years only on January columns", () => {
    const w = mountChart()
    const labels = w.findAll("text[data-testid='year-tick']").map((t) => t.text())
    expect(labels).toEqual(["2025"])
  })

  it("draws a real bar only for non-zero months", () => {
    const w = mountChart()
    const bars = w.findAll("rect[data-testid='bar']")
    expect(bars.length).toBe(2)
    // 柱体须放行指针事件，悬停才能到达下方带 title 的命中区
    for (const bar of bars) {
      expect(bar.attributes("pointer-events")).toBe("none")
    }
  })

  it("summarizes range and peak in the img aria-label; sr-only table lists non-zero months only", () => {
    const w = mountChart()
    const label = w.find('[role="img"]').attributes("aria-label")
    expect(label).toContain("2025-01")        // 起始月
    expect(label).toContain("2025-03")        // 结束月兼峰值月
    expect(label).toContain("最多的月份 2025-03")
    const rows = w.findAll("table.sr-only tbody tr")
    expect(rows.length).toBe(2) // 零值月不进表
  })

  it("shows empty state for no months", () => {
    const w = mountChart([])
    expect(w.text()).toContain("暂无数据")
  })
})
