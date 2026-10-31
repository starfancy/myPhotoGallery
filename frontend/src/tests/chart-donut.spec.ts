import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import DonutChart from "../components/charts/DonutChart.vue"

const SEGS = [
  { key: "wide", name: "广角", count: 1, color: "rgb(var(--color-chart-1))" },
  { key: "standard", name: "中焦", count: 1, color: "rgb(var(--color-chart-2))" },
  { key: "tele", name: "长焦", count: 1, color: "rgb(var(--color-chart-3))" },
  { key: "unknown", name: "未知", count: 1, color: "rgb(var(--color-ink-muted) / 0.5)" },
]

function mountChart(segments = SEGS, total = 4) {
  return mount(DonutChart, {
    props: { title: "焦段分布", label: "张", total, segments },
  })
}

describe("DonutChart", () => {
  it("draws one arc per non-zero segment with lengths summing to the circumference minus gaps", () => {
    const w = mountChart()
    const arcs = w.findAll("svg circle[stroke-dasharray]")
    expect(arcs.length).toBe(4)
    const C = 2 * Math.PI * 40
    const drawn = arcs.map((c) => Number(c.attributes("stroke-dasharray")!.split(" ")[0]))
    // 4 段各 25%，实现对每段扣 2px 间隔（首尾相邻，共 4 个间隔）→ C-8
    expect(drawn.reduce((a, b) => a + b, 0)).toBeCloseTo(C - 2 * 4, 0)
  })

  it("skips zero-count segments but keeps them in the legend (dimmed)", () => {
    const segs = [
      { key: "wide", name: "广角", count: 3, color: "c1" },
      { key: "standard", name: "中焦", count: 0, color: "c2" },
    ]
    const w = mountChart(segs, 3)
    expect(w.findAll("svg circle[stroke-dasharray]").length).toBe(1)
    const legend = w.findAll("li")
    expect(legend.length).toBe(2)
    expect(legend[1].classes().join(" ")).toContain("opacity-40")
  })

 it("renders count and rounded percentage in the legend", () => {
    const segs = [{ key: "a", name: "甲类", count: 1, color: "c1" },
                  { key: "b", name: "乙类", count: 3, color: "c2" }]
    const w = mountChart(segs, 4)
    const text = w.text()
    expect(text).toContain("25%")
    expect(text).toContain("75%")
  })

  it("exposes an img role with summarized aria-label and an sr-only data table", () => {
    const w = mountChart()
    const img = w.find('[role="img"]')
    expect(img.attributes("aria-label")).toContain("焦段分布")
    expect(img.attributes("aria-label")).toContain("广角")
    const table = w.find("table.sr-only")
    expect(table.exists()).toBe(true)
    expect(table.findAll("tbody tr").length).toBe(4)
  })

  it("shows an empty state when total is zero", () => {
    const w = mountChart([], 0)
    expect(w.text()).toContain("暂无数据")
    expect(w.find("svg").exists()).toBe(false)
  })
})
