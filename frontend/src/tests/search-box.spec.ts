import { afterEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import SearchBox from "../components/SearchBox.vue"

function mountBox(props: Partial<{ modelValue: string; scopeAll: boolean; isRoot: boolean }> = {}) {
  return mount(SearchBox, {
    props: { modelValue: "", scopeAll: false, isRoot: false, ...props },
    attachTo: document.body,
  })
}

describe("SearchBox", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it("输入后防抖 300ms 才 emit，回车立即 emit", async () => {
    vi.useFakeTimers()
    const w = mountBox()
    const input = w.get("input[type='search']")
    await input.setValue("旅行")
    expect(w.emitted("update:modelValue")).toBeUndefined()
    vi.advanceTimersByTime(299)
    expect(w.emitted("update:modelValue")).toBeUndefined()
    vi.advanceTimersByTime(1)
    expect(w.emitted("update:modelValue")![0]).toEqual(["旅行"])
  })

  it("回车立即触发，不等防抖", async () => {
    vi.useFakeTimers()
    const w = mountBox()
    const input = w.get("input[type='search']")
    await input.setValue("img")
    await w.get("form").trigger("submit.prevent")
    expect(w.emitted("update:modelValue")![0]).toEqual(["img"])
  })

  it("清除按钮：有文本时出现，点击立即 emit 空串并聚焦", async () => {
    vi.useFakeTimers()
    const w = mountBox({ modelValue: "x" })
    expect(w.find('button[aria-label="清除搜索"]').exists()).toBe(true)
    await w.get('button[aria-label="清除搜索"]').trigger("click")
    expect(w.emitted("update:modelValue")![0]).toEqual([""])
    expect(w.get("input[type='search']").element).toBe(document.activeElement)
  })

  it("isRoot=true 时隐藏整个 root 勾选；否则切换 emit scopeAll", async () => {
    const wRoot = mountBox({ isRoot: true })
    expect(wRoot.find('input[type="checkbox"]').exists()).toBe(false)

    const w = mountBox({ isRoot: false })
    const cb = w.get('input[type="checkbox"]')
    await cb.setValue(true)
    expect(w.emitted("update:scopeAll")![0]).toEqual([true])
  })

  it("外部 modelValue 变化同步回输入框", async () => {
    const w = mountBox({ modelValue: "a" })
    expect((w.get("input[type='search']").element as HTMLInputElement).value).toBe("a")
    await w.setProps({ modelValue: "b" })
    await flushPromises()
    expect((w.get("input[type='search']").element as HTMLInputElement).value).toBe("b")
  })
})
