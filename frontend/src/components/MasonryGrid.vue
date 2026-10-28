<template>
  <div ref="rootEl" class="w-full">
    <div :style="gridStyle">
      <PhotoCell v-for="cell in layout.items" :key="cell.id"
                 :id="cell.id"
                 :sha1="cell.sha1"
                 :filename="cell.filename"
                 :selected="isSelected(cell.id)"
                 :selection-mode="selectionMode"
                 :show-menu="isAdmin && !selectionMode"
                 :show-filename="showFilename"
                 :cell-style="{ gridRow: `span ${cell.span}` }"
                 @activate="onCellClick(cell.id)"
                 @toggle-select="toggleSelect(cell.id)"
                 @menu="onMenu(cell.id, $event)"
                 @contextmenu="onMenu(cell.id, $event)"
                 @longpress="onLongPress(cell.id, $event)" />
    </div>
    <CellContextMenu :menu="menu" @action="runAction" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import type { ImageRow } from "../stores/browse"
import { MASONRY_ROW_UNIT, masonryLayout } from "../utils/layout"
import { useAuthStore } from "../stores/auth"
import { useCellMenu } from "../composables/useCellMenu"
import PhotoCell from "./PhotoCell.vue"
import CellContextMenu from "./CellContextMenu.vue"

const props = defineProps<{
  items: ImageRow[]
  selectionMode?: boolean
  /** 已选图片 id。父组件保持权威状态；此组件仅发出 toggle 事件。 */
  selectedIds?: Set<number>
  /** 在缩略图底部渐变阴影上叠加文件名 */
  showFilename?: boolean
}>()

const emit = defineEmits<{
  (e: "open", id: number): void
  (e: "menuAction", id: number, action: "delete"): void
  (e: "toggleSelect", id: number): void
}>()

const auth = useAuthStore()
const isAdmin = computed(() => auth.isAdmin)

const { menu, open, openAt, runAction } = useCellMenu(emit)

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
})
onUnmounted(() => {
  ro?.disconnect()
})

const gap = 16

const layout = computed(() => {
  const input = props.items.map((it) => ({
    id: it.id,
    sha1: it.sha1,
    filename: it.filename,
    w: it.width ?? 4,
    h: it.height ?? 3,
  }))
  return masonryLayout(input, width.value, gap)
})

const gridStyle = computed<Record<string, string>>(() => ({
  display: "grid",
  gridTemplateColumns: `repeat(${layout.value.columns}, 1fr)`,
  gridAutoRows: `${MASONRY_ROW_UNIT}px`,
  // 先行后列顺序放置；dense 让浏览器回填高处图片留下的空隙
  gridAutoFlow: "row dense",
  gap: `${gap}px`,
}))

// ---------- selection ----------

function isSelected(id: number): boolean {
  return props.selectedIds?.has(id) === true
}

function toggleSelect(id: number) {
  emit("toggleSelect", id)
}

/** 点击缩略图：选择模式下切换选中；否则打开 lightbox。 */
function onCellClick(id: number) {
  if (props.selectionMode) {
    toggleSelect(id)
  } else {
    emit("open", id)
  }
}

/** 三点按钮 / 右键：弹出单例菜单。 */
function onMenu(id: number, ev: MouseEvent) {
  open(id, ev)
}

/** 移动端长按：用触摸起点的视口坐标弹菜单。 */
function onLongPress(id: number, p: { x: number; y: number }) {
  openAt(id, p.x, p.y)
}
</script>
