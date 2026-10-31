import { onMounted, onUnmounted, ref } from "vue"

export type CellMenuKey = string | number

export interface CellMenuState<K extends CellMenuKey = CellMenuKey> {
  key: K
  x: number
  y: number
}

export interface CellMenuItem<A extends string = string> {
  action: A
  label: string
}

type MenuActionEmit<K extends CellMenuKey, A extends string> = (
  e: "menuAction", key: K, action: A,
) => void

/**
 * 缩略图三点菜单 / 右键 / 移动端长按共用的单例弹出菜单：
 * 管菜单状态、视口坐标换算与全局点击关闭。
 * K/A 由调用方收窄（图片网格：number/"delete"；文件夹条：string/"exclude"）。
 */
export function useCellMenu<K extends CellMenuKey = CellMenuKey, A extends string = string>(
  emit: MenuActionEmit<K, A>,
) {
  const menu = ref<CellMenuState<K> | null>(null)

  function openAt(key: K, clientX: number, clientY: number) {
    // 使用相对文档的坐标，避免叠加页面卷动
    menu.value = { key, x: clientX + window.scrollX, y: clientY + window.scrollY }
  }

  function open(key: K, ev: MouseEvent) {
    openAt(key, ev.clientX, ev.clientY)
  }

  function close() {
    menu.value = null
  }

  function runAction(action: string) {
    if (!menu.value) return
    // K 仅限 string | number，UnwrapRef<K> 运行时即 K；泛型 ref 的静态解包类型需收窄。
    const key = menu.value.key as K
    menu.value = null
    // 组件把自己的 A 收窄在 emit 签名里；菜单组件只认 string。
    emit("menuAction", key, action as A)
  }

  // Esc 关闭弹出菜单（焦点归还由 CellContextMenu 负责）
  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") close()
  }

  onMounted(() => {
    window.addEventListener("click", close)
    window.addEventListener("keydown", onKeydown)
  })
  onUnmounted(() => {
    window.removeEventListener("click", close)
    window.removeEventListener("keydown", onKeydown)
  })

  return { menu, open, openAt, close, runAction }
}
