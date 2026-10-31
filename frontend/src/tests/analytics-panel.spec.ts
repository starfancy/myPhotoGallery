import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import AnalyticsPanel from "../components/charts/AnalyticsPanel.vue"

function mockAnalytics(payload: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status,
        headers: { "content-type": "application/json" },
      }),
    ),
  )
}

const PAYLOAD = {
  total: 10,
  with_exif: 9,
  without_taken_at: 1,
  makes: [
    { name: "Pentax", count: 6 },
    { name: "Nikon", count: 3 },
    { name: "未知", count: 1 },
  ],
  cameras: [{ name: "Pentax K-5", count: 6 }, { name: "Nikon D7000", count: 3 }],
  focal_ranges: [
    { key: "wide", name: "广角 (<35mm)", count: 2 },
    { key: "standard", name: "中焦 (35–70mm)", count: 3 },
    { key: "tele", name: "长焦 (>70mm)", count: 4 },
    { key: "unknown", name: "未知", count: 1 },
  ],
  apertures: [
    { key: "f28", name: "≤ f/2.8", count: 2 },
    { key: "f4", name: "f/4", count: 2 },
    { key: "f56", name: "f/5.6", count: 2 },
    { key: "f8", name: "f/8", count: 2 },
    { key: "f11plus", name: "f/11+", count: 1 },
    { key: "unknown", name: "未知", count: 1 },
  ],
  months: [
    { month: "2025-01", count: 4 },
    { month: "2025-02", count: 0 },
    { month: "2025-03", count: 5 },
  ],
}

describe("AnalyticsPanel", () => {
  beforeEach(() => { vi.unstubAllGlobals() })

  it("renders five chart titles and the coverage subtitle", async () => {
    mockAnalytics(PAYLOAD)
    const w = mount(AnalyticsPanel)
    await flushPromises()
    const t = w.text()
    expect(t).toContain("相机厂商")
    expect(t).toContain("相机机型")
    expect(t).toContain("焦段分布")
    expect(t).toContain("光圈分布")
    expect(t).toContain("拍摄趋势")
    expect(t).toContain("共 10 张")
    expect(t).toContain("9 张含拍摄参数")
    expect(t).toContain("无拍摄日期 1 张")
  })

  it("passes makes/cameras rows to the two bar charts and dims 未知", async () => {
    mockAnalytics(PAYLOAD)
    const w = mount(AnalyticsPanel)
    await flushPromises()
    expect(w.text()).toContain("Pentax K-5")
    expect(w.text()).toContain("Nikon D7000")
    // makes 带「未知」桶：对应填充条使用弱化中性色（cameras 无未知桶）
    const mutedFills = w.findAll('[data-testid="bar-fill"]')
      .filter((f) => f.classes().some((c) => c.includes("ink-muted")))
    expect(mutedFills.length).toBe(1)
  })

  it("shows a loading state before the request resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})))
    const w = mount(AnalyticsPanel)
    expect(w.text()).toContain("加载中")
  })

  it("shows an alert banner with retry on failure", async () => {
    mockAnalytics({ error: { code: "internal_error", message: "boom" } }, 500)
    const w = mount(AnalyticsPanel)
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)
    const retry = w.find("button")
    expect(retry.text()).toContain("重试")
  })

  it("shows an empty state for a fresh library", async () => {
    mockAnalytics({
      total: 0, with_exif: 0, without_taken_at: 0,
      makes: [], cameras: [],
      focal_ranges: [
        { key: "wide", name: "广角 (<35mm)", count: 0 },
        { key: "standard", name: "中焦 (35–70mm)", count: 0 },
        { key: "tele", name: "长焦 (>70mm)", count: 0 },
        { key: "unknown", name: "未知", count: 0 },
      ],
      apertures: [],
      months: [],
    })
    const w = mount(AnalyticsPanel)
    await flushPromises()
    expect(w.text()).toContain("暂无已扫描的图片")
  })
})
