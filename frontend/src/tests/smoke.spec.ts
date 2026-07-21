import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import App from "../App.vue"

describe("App", () => {
  it("mounts", () => {
    const w = mount(App, {
      global: {
        stubs: { RouterView: true },
      },
    })
    expect(w.exists()).toBe(true)
  })
})
