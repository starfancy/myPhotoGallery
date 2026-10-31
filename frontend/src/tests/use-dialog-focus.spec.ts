import { describe, expect, it } from "vitest"
import { computed, defineComponent, h, nextTick, ref } from "vue"
import { mount } from "@vue/test-utils"
import { useDialogFocus } from "../composables/useDialogFocus"

function setupDom() {
  document.body.innerHTML = `
    <button id="trigger">open</button>
    <div id="panel" tabindex="-1">
      <input id="a" /><button id="b">x</button>
    </div>`
  const trigger = document.getElementById("trigger") as HTMLElement
  const panel = document.getElementById("panel") as HTMLElement
  return { trigger, panel }
}

describe("useDialogFocus", () => {
  it("moves focus in on open and restores on close", async () => {
    const { trigger, panel } = setupDom()
    trigger.focus()
    const open = ref(false)
    useDialogFocus(open, { value: panel } as any, () => (open.value = false))
    open.value = true
    await nextTick()
    expect(document.activeElement?.id).toBe("a")
    open.value = false
    await nextTick()
    expect(document.activeElement).toBe(trigger)
  })

  it("Esc calls onClose and Tab wraps within panel", async () => {
    const { panel } = setupDom()
    const open = ref(true)
    useDialogFocus(open, { value: panel } as any, () => (open.value = false))
    await nextTick()
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    expect(open.value).toBe(false)

    open.value = true
    await nextTick()
    const b = document.getElementById("b")!
    b.focus()
    const ev = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })
    document.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(true)
    expect(document.activeElement?.id).toBe("a")
  })

  it("restores focus to the trigger when unmounted while still open", async () => {
    // onBeforeUnmount only registers inside a component instance; drive the
    // composable through a tiny host. The trigger lives outside the wrapper so
    // it stays connected after unmount (like persistent page chrome).
    const DialogHost = defineComponent({
      props: { open: { type: Boolean, required: true } },
      setup(props) {
        const panel = ref<HTMLElement | null>(null)
        useDialogFocus(computed(() => props.open), panel, () => {})
        return () =>
          h("div", { ref: panel, tabindex: "-1" }, [h("input"), h("button", "x")])
      },
    })

    document.body.innerHTML = `<button id="trigger">open</button>`
    const trigger = document.getElementById("trigger") as HTMLElement
    trigger.focus()

    const wrapper = mount(DialogHost, {
      props: { open: false },
      attachTo: document.body,
    })
    await wrapper.setProps({ open: true })
    await nextTick()
    expect(document.activeElement?.tagName).toBe("INPUT")

    // Route-away-while-open: no close transition, the component is torn down.
    wrapper.unmount()
    expect(document.activeElement).toBe(trigger)
  })
})
