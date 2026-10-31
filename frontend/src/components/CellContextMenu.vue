<template>
  <div v-if="menu"
       ref="rootEl"
       class="lb-cell-menu"
       role="menu"
       :style="{ top: `${menu.y}px`, left: `${menu.x}px` }"
       @click.stop>
    <button v-for="item in items" :key="item.action"
            type="button" role="menuitem" class="lb-cell-menu-item"
            @click="$emit('action', item.action)">
      {{ item.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from "vue"
import type { CellMenuItem, CellMenuState } from "../composables/useCellMenu"

const props = defineProps<{
  menu: CellMenuState | null
  items: CellMenuItem[]
}>()
defineEmits<{
  (e: "action", action: string): void
}>()

const rootEl = ref<HTMLElement | null>(null)
// 打开菜单时焦点所在的触发器：关闭（Esc / 选中 / 外部点击）后归还。
let triggerEl: HTMLElement | null = null

// 菜单首次出现（null -> 对象）时把焦点移入首项；关闭时归还触发器，
// 保证键盘用户焦点不丢。
watch(
  () => props.menu,
  async (menu, old) => {
    if (menu && !old) {
      triggerEl = document.activeElement as HTMLElement | null
      await nextTick()
      rootEl.value
        ?.querySelector<HTMLButtonElement>(".lb-cell-menu-item")
        ?.focus()
    } else if (!menu && old) {
      const restore = triggerEl
      triggerEl = null
      // 触发器可能已随卡片卸载（如删除后）；此时 focus() 静默无效。
      restore?.focus?.()
    }
  },
)
</script>

<style>
/* 菜单用文档绝对坐标定位，需要脱离 scoped 才能被作用到 */
.lb-cell-menu {
  position: absolute;
  z-index: 60;
  background: rgb(var(--color-surface) / 0.98);
  color: rgb(var(--color-ink));
  border: 1px solid rgb(var(--color-line));
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  min-width: 140px;
  padding: 4px 0;
  font-size: 13px;
}
.lb-cell-menu-item {
  display: block;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: 0;
  text-align: left;
  color: inherit;
  cursor: pointer;
}
.lb-cell-menu-item:hover {
  background: rgb(var(--color-surface-3));
}
</style>
