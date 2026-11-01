import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import HBarChart from "../components/charts/HBarChart.vue"

const ITEMS = [
  { name: "Pentax", count: 100 },
  { name: "Nikon", count: 50 },
  { name: "其他", count: 10, dimmed: true },
  { name: "未知", count: 5, dimmed: true },
]

function mountChart(items = ITEMS, total = 165) {
  return mount(HBarChart, { props: { title: "相机厂商", items, total } })
}

describe("HBarChart", () => {
  it("renders one row per item with name and count", () => {
    const w = mountChart()
    const rows = w.findAll("li")
    expect(rows.length).toBe(4)
    expect(w.text()).toContain("Pentax")
    expect(w.text()).toContain("Nikon")
  })

  it("scales bar widths to the largest count (largest = 100%)", () => {
    const w = mountChart()
    const fills = w.findAll('[data-testid="bar-fill"]')
    expect(fills[0].attributes("style")).toContain("width: 100%")
    expect(fills[1].attributes("style")).toContain("width: 50%")
  })

  it("dims 其他/未知 rows with the muted fill class", () => {
    const w = mountChart()
    const fills = w.findAll('[data-testid="bar-fill"]')
    expect(fills[0].classes()).toContain("bg-primary")
    expect(fills[2].classes().join(" ")).toContain("bg-ink-muted/40")
    expect(fills[3].classes().join(" ")).toContain("bg-ink-muted/40")
  })

  it("shows count/total percentage in the row title tooltip", () => {
    const w = mountChart()
    const track = w.find('[data-testid="bar-track"]')
    // 100/165 ≈ 61%
    expect(track.attributes("title")).toContain("61%")
    expect(track.attributes("title")).toContain("Pentax")
  })

  it("has an img role with aria-label and an sr-only table", () => {
    const w = mountChart()
    expect(w.find('[role="img"]').attributes("aria-label")).toContain("相机厂商")
    const table = w.find("table.sr-only")
    expect(table.findAll("tbody tr").length).toBe(4)
  })

  it("shows empty state with no items", () => {
    const w = mountChart([], 0)
    expect(w.text()).toContain("暂无数据")
  })
})
