import { onMounted, onUnmounted, ref } from "vue"

export interface CellMenuState {
  id: number
  x: number
  y: number
}

type MenuActionEmit = (e: "menuAction", id: number, action: "delete") => void

/**
 * 缩略图三点菜单 / 右键 / 移动端长按共用的单例弹出菜单：
 * 管菜单状态、视口坐标换算与全局点击关闭。两种网格排版复用。
 */
export function useCellMenu(emit: MenuActionEmit) {
  const menu = ref<CellMenuState | null>(null)

  function openAt(id: number, clientX: number, clientY: number) {
    // 使用相对文档的坐标，避免叠加页面卷动
    menu.value = { id, x: clientX + window.scrollX, y: clientY + window.scrollY }
  }

  function open(id: number, ev: MouseEvent) {
    openAt(id, ev.clientX, ev.clientY)
  }

  function close() {
    menu.value = null
  }

  function runAction(action: "delete") {
    if (!menu.value) return
    const id = menu.value.id
    menu.value = null
    emit("menuAction", id, action)
  }

  onMounted(() => window.addEventListener("click", close))
  onUnmounted(() => window.removeEventListener("click", close))

  return { menu, open, openAt, close, runAction }
}
