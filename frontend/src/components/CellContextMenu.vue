<template>
  <div v-if="menu"
       class="lb-cell-menu"
       :style="{ top: `${menu.y}px`, left: `${menu.x}px` }"
       @click.stop>
    <button v-for="item in items" :key="item.action"
            type="button" class="lb-cell-menu-item"
            @click="$emit('action', item.action)">
      {{ item.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import type { CellMenuItem, CellMenuState } from "../composables/useCellMenu"

defineProps<{
  menu: CellMenuState | null
  items: CellMenuItem[]
}>()
defineEmits<{
  (e: "action", action: string): void
}>()
</script>

<style>
/* 菜单用文档绝对坐标定位，需要脱离 scoped 才能被作用到 */
.lb-cell-menu {
  position: absolute;
  z-index: 60;
  background: rgba(24, 24, 27, 0.98);
  color: #f3f4f6;
  border: 1px solid rgba(255, 255, 255, 0.08);
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
  background: rgba(255, 255, 255, 0.08);
}
</style>
