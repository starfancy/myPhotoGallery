import { getCurrentInstance, onBeforeUnmount, watch, type Ref } from "vue"

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "input:not([disabled])",
  "select:not([disabled])", "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",")

// jsdom has no layout engine: offsetParent is always null there, so the
// real-browser display:none check must be gated on layout actually existing
// (a plain static element's offsetParent is <body> in browsers, null in jsdom).
let supportsLayout: boolean | null = null
function hasLayout(): boolean {
  if (supportsLayout !== null) return supportsLayout
  const probe = document.createElement("div")
  document.body.appendChild(probe)
  supportsLayout = probe.offsetParent !== null
  probe.remove()
  return supportsLayout
}

function visibleFocusable(root: ParentNode): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => {
    if ((el as HTMLInputElement).disabled) return false
    // [hidden] / aria-hidden ancestors keep controls out of the a11y tree
    if (el.closest("[hidden],[aria-hidden='true']")) return false
    // Real browsers only: drop display:none elements. The currently focused
    // element is kept regardless (it can momentarily report null offsetParent).
    if (hasLayout() && el.offsetParent === null && el !== document.activeElement) {
      return false
    }
    return true
  })
}

/**
 * 模态对话框焦点管理：进入时聚焦面板内首个可聚焦元素（无则面板本身）、
 * Esc 关闭、Tab 在面板内循环、退出时把焦点归还触发器。
 *
 * watcher 用 immediate：父组件可能以 open=true 直接挂载（如 v-model 初始为真）。
 */
export function useDialogFocus(
  open: Ref<boolean>,
  panelRef: Ref<HTMLElement | null>,
  onClose: () => void,
) {
  let previous: HTMLElement | null = null

  function onKeydown(e: KeyboardEvent) {
    const panel = panelRef.value
    if (!panel) return
    if (e.key === "Escape") {
      e.stopPropagation()
      onClose()
      return
    }
    if (e.key !== "Tab") return
    const items = visibleFocusable(panel)
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  // flush: "post" —— 面板常由 v-if 随 open 一起挂载，post 回调在 DOM 更新后
  // 触发，此时 panelRef 已就位，无需再等一个 tick，焦点移动与 open 同帧完成。
  watch(open, (isOpen) => {
    if (isOpen) {
      previous = document.activeElement as HTMLElement | null
      document.addEventListener("keydown", onKeydown, true)
      const panel = panelRef.value
      if (panel) {
        const items = visibleFocusable(panel)
        ;(items[0] ?? panel)?.focus()
      }
    } else {
      document.removeEventListener("keydown", onKeydown, true)
      const restore = previous
      previous = null
      // 触发器可能已随父节点卸载（如删除后关闭）；此时 focus() 静默无效。
      restore?.focus?.()
    }
  }, { immediate: true, flush: "post" })

  // 单测在组件实例外调用本 composable；无实例时不注册卸载钩子。
  // 弹窗仍处于打开状态时组件被卸载（如路由切走）：除移除监听外还要把焦点
  // 归还触发器；触发器若已随视图一起卸载（document.contains 为假）则不处理。
  if (getCurrentInstance()) {
    onBeforeUnmount(() => {
      document.removeEventListener("keydown", onKeydown, true)
      if (previous && document.contains(previous)) {
        previous.focus()
      }
      previous = null
    })
  }
}
