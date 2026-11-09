import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.stubGlobal("fetch", vi.fn(async (url: string, opts?: any) => {
  if (url === "/api/admin/luts" && opts?.method === "PATCH") {
    return { ok: true, json: async () => ({}) }
  }
  if (url === "/api/admin/luts") {
    return { ok: true, json: async () => [
      { slug: "velvia", label: "富士 Velvia", group: "fujifilm", enabled: 1,
        sort_order: 1, source: "https://x", license: "MIT",
        file_path: "fujifilm/velvia.cube", created_at: 1 },
      { slug: "warm", label: "暖色调", group: "synthetic", enabled: 0,
        sort_order: 0, source: "", license: "", file_path: "synthetic/warm.cube", created_at: 1 },
    ]}
  }
  if (url === "/api/admin/luts/rescan" && opts?.method === "POST") {
    return { ok: true, json: async () => ({ discovered: [], skipped_existing: [], soft_deleted: [] }) }
  }
  return { ok: false, json: async () => ({}) }
}))

import AdminLuts from "../views/AdminLuts.vue"

describe("AdminLuts", () => {
  beforeEach(() => { setActivePinia(createPinia()) })

  it("renders LUTs grouped, toggles PATCH on click", async () => {
    const w = mount(AdminLuts)
    await flushPromises()
    // 默认折叠，先展开两个分组
    const expands = w.findAll('button[aria-label="展开分组"]')
    expect(expands.length).toBe(2)
    for (const b of expands) await b.trigger("click")
    await flushPromises()
    expect(w.text()).toContain("富士 Velvia")
    expect(w.text()).toContain("暖色调")
    // 找 warm 的 toggle，点它
    const toggles = w.findAll('button[aria-label="toggle-enabled"]')
    expect(toggles.length).toBe(2)
    await toggles[1].trigger("click")
    await flushPromises()
    // 应有 PATCH /api/admin/luts/warm
    const patchCalls = (fetch as any).mock.calls.filter(
      (c: any[]) => c[1]?.method === "PATCH" && c[0].includes("/warm"),
    )
    expect(patchCalls.length).toBe(1)
  })

  it("group select-all toggles every row in the group", async () => {
    const w = mount(AdminLuts)
    await flushPromises()
    // 展开第一个分组（fujifilm，1 支 enabled=1）
    await w.findAll('button[aria-label="展开分组"]')[0].trigger("click")
    await flushPromises()
    // 点全选 checkbox
    const selectAll = w.find('input[data-test="group-select-all"]')
    await selectAll.setValue(false)  // 取消全选
    await flushPromises()
    // 应有 PATCH 把 velvia 从 enabled=1 改成 0
    const patchCalls = (fetch as any).mock.calls.filter(
      (c: any[]) => c[1]?.method === "PATCH" && c[0].includes("/velvia"),
    )
    expect(patchCalls.length).toBe(1)
    expect(JSON.parse((patchCalls[0][1] as any).body)).toEqual({ enabled: 0 })
  })

  it("rescan button triggers POST", async () => {
    const w = mount(AdminLuts)
    await flushPromises()
    await w.find('button[data-test="rescan"]').trigger("click")
    await flushPromises()
    const postCalls = (fetch as any).mock.calls.filter(
      (c: any[]) => c[1]?.method === "POST" && c[0].includes("/rescan"),
    )
    expect(postCalls.length).toBe(1)
  })
})
