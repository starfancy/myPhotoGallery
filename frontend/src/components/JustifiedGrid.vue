<template>
  <div ref="rootEl" class="w-full">
    <div v-for="(row, ri) in rows" :key="ri"
         class="flex gap-1"
         :style="{ marginBottom: `${gap}px` }">
      <div v-for="cell in row.items" :key="cell.id"
           class="lb-grid-cell relative overflow-hidden bg-neutral-800"
           :style="{ width: `${cell.scaledW}px`, height: `${cell.scaledH}px` }">
        <button type="button"
                class="absolute inset-0 focus:outline-none focus:ring-2 focus:ring-blue-500"
                @click="$emit('open', cell.id)"
                @contextmenu.prevent="onLongPress(cell.id, $event)"
                @touchstart="onTouchStart(cell.id, $event)"
                @touchend="onTouchEnd"
                @touchmove="onTouchEnd">
          <img :src="`/api/thumb/${cell.sha1}?size=400`"
               :srcset="`/api/thumb/${cell.sha1}?size=200 200w, /api/thumb/${cell.sha1}?size=400 400w`"
               sizes="(max-width: 640px) 200px, 400px"
               loading="lazy"
               :alt="cell.filename"
               class="h-full w-full object-cover" />
        </button>
        <!-- Admin-only 三点菜单：hover 显示；点击后弹出 -->
        <button v-if="isAdmin"
                type="button"
                :aria-label="`更多操作 ${cell.filename}`"
                class="lb-cell-menu-btn"
                @click.stop="openMenu(cell.id, $event)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="5" cy="12" r="2" />
            <circle cx="12" cy="12" r="2" />
            <circle cx="19" cy="12" r="2" />
          </svg>
        </button>
      </div>
    </div>
    <button v-if="canLoadMore" class="mx-auto my-4 block rounded bg-neutral-800 px-4 py-2 text-sm"
            @click="$emit('loadMore')">加载更多</button>

    <!-- 单例弹出菜单 -->
    <div v-if="menu"
         class="lb-cell-menu"
         :style="{ top: `${menu.y}px`, left: `${menu.x}px` }"
         @click.stop>
      <button type="button" class="lb-cell-menu-item"
              @click="onMenuAction(menu.id, 'delete')">
        移入回收站
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import type { ImageRow } from "../stores/browse"
import { justifiedRows, LayoutInput } from "../utils/layout"
import { useAuthStore } from "../stores/auth"

const props = defineProps<{
  items: ImageRow[]
  canLoadMore: boolean
  targetHeight?: number
}>()

const emit = defineEmits<{
  (e: "open", id: number): void
  (e: "loadMore"): void
  (e: "menuAction", id: number, action: "delete"): void
}>()

const auth = useAuthStore()
const isAdmin = computed(() => auth.isAdmin)

const rootEl = ref<HTMLElement | null>(null)
const width = ref(1000)

function measure() {
  if (rootEl.value) width.value = rootEl.value.clientWidth
}

let ro: ResizeObserver | null = null
onMounted(() => {
  measure()
  ro = new ResizeObserver(measure)
  if (rootEl.value) ro.observe(rootEl.value)
  window.addEventListener("click", closeMenu)
})
onUnmounted(() => {
  ro?.disconnect()
  window.removeEventListener("click", closeMenu)
})

const gap = 4

const rows = computed(() => {
  const input: (LayoutInput & { id: number; sha1: string; filename: string })[] = props.items.map((it) => ({
    id: it.id,
    sha1: it.sha1,
    filename: it.filename,
    w: it.width ?? 4,
    h: it.height ?? 3,
  }))
  const laid = justifiedRows(input, width.value, props.targetHeight ?? 200, gap)
  return laid.map((row) => ({
    height: row.height,
    items: row.items as unknown as Array<{ id: number; sha1: string; filename: string; scaledW: number; scaledH: number }>,
  }))
})

// ---------- 菜单（admin-only） ----------

const menu = ref<{ id: number; x: number; y: number } | null>(null)

function openMenu(id: number, ev: MouseEvent) {
  // 相对视口的坐标，避免叠加卷动
  menu.value = { id, x: ev.clientX + window.scrollX, y: ev.clientY + window.scrollY }
}

function closeMenu() {
  menu.value = null
}

function onMenuAction(id: number, action: "delete") {
  menu.value = null
  emit("menuAction", id, action)
}

// ---------- 移动端长按 ----------

let pressTimer: number | null = null
let pressStartXY: { x: number; y: number } | null = null

function onTouchStart(id: number, ev: TouchEvent) {
  if (!isAdmin.value) return
  const t = ev.touches[0]
  pressStartXY = { x: t.clientX, y: t.clientY }
  pressTimer = window.setTimeout(() => {
    if (!pressStartXY) return
    menu.value = {
      id,
      x: pressStartXY.x + window.scrollX,
      y: pressStartXY.y + window.scrollY,
    }
    pressTimer = null
  }, 550)
}
function onTouchEnd() {
  if (pressTimer !== null) {
    clearTimeout(pressTimer)
    pressTimer = null
  }
  pressStartXY = null
}

function onLongPress(id: number, ev: MouseEvent) {
  // 桌面右键 → 菜单（不覆盖浏览器默认菜单是不友好的；此处主动禁止默认）
  if (!isAdmin.value) return
  openMenu(id, ev)
}
</script>

<style scoped>
.lb-grid-cell {
  /* hover 时才让子按钮出现 */
}
.lb-cell-menu-btn {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  display: none;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border: 0;
  z-index: 2;
}
.lb-grid-cell:hover .lb-cell-menu-btn,
.lb-cell-menu-btn:focus-visible {
  display: flex;
}
.lb-cell-menu-btn:hover {
  background: rgba(0, 0, 0, 0.75);
}
</style>

<style>
/* 菜单挂在 body 视口坐标下，需要脱离 scoped 才能被定位样式作用到 */
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
