import { beforeEach, describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import ToastHost from "../components/ToastHost.vue"
import { useToastStore } from "../stores/toast"

beforeEach(() => {
  setActivePinia(createPinia())
})

describe("ToastHost", () => {
  it("renders pushed error text in an aria-live=polite container", () => {
    const toast = useToastStore()
    toast.push("error", "x")
    const w = mount(ToastHost)
    expect(w.text()).toContain("x")
    expect(w.find('[aria-live="polite"]').exists()).toBe(true)
  })
})
