import { describe, expect, it } from "vitest"
import { ref, nextTick } from "vue"
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
})
