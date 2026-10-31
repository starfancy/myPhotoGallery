import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import { createPinia } from "pinia"
import App from "../App.vue"

describe("App", () => {
  it("mounts", () => {
    const w = mount(App, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterView: true },
      },
    })
    expect(w.exists()).toBe(true)
  })
})
