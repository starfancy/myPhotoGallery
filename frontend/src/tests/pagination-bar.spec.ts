import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import PaginationBar from "../components/PaginationBar.vue"

function mountBar(page: number, totalPages: number) {
  return mount(PaginationBar, { props: { page, totalPages } })
}

/** 数字页码按钮的文本（排除上一页/下一页）。 */
function numberLabels(w: ReturnType<typeof mountBar>): string[] {
  return w.findAll("button")
    .map((b) => b.text())
    .filter((t) => /^\d+$/.test(t))
}

describe("PaginationBar", () => {
  it("shows a windowed page list with first, neighbors and last", () => {
    const w = mountBar(5, 12)
    expect(numberLabels(w)).toEqual(["1", "4", "5", "6", "12"])
    // 两处省略号
    expect(w.findAll("span").filter((s) => s.text() === "…").length).toBe(2)
  })

  it("marks the current page", () => {
    const w = mountBar(5, 12)
    const current = w.findAll('button[aria-current="page"]')
    expect(current.length).toBe(1)
    expect(current[0].text()).toBe("5")
  })

  it("emits change when a page number is clicked", async () => {
    const w = mountBar(5, 12)
    const btn = w.findAll("button").find((b) => b.text() === "12")!
    await btn.trigger("click")
    expect(w.emitted("change")?.[0]).toEqual([12])
  })

  it("prev and next emit page-1 and page+1", async () => {
    const w = mountBar(5, 12)
    await w.findAll("button").find((b) => b.text() === "上一页")!.trigger("click")
    await w.findAll("button").find((b) => b.text() === "下一页")!.trigger("click")
    expect(w.emitted("change")?.[0]).toEqual([4])
    expect(w.emitted("change")?.[1]).toEqual([6])
  })

  it("disables prev on first page and next on last page", () => {
    const first = mountBar(1, 12)
    expect(first.findAll("button").find((b) => b.text() === "上一页")!.attributes("disabled")).toBeDefined()

    const last = mountBar(12, 12)
    expect(last.findAll("button").find((b) => b.text() === "下一页")!.attributes("disabled")).toBeDefined()
  })

  it("shows no ellipsis when all pages fit the window", () => {
    const w = mountBar(2, 3)
    expect(numberLabels(w)).toEqual(["1", "2", "3"])
    expect(w.text()).not.toContain("…")
  })
})
