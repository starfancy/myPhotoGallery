<template>
  <div v-if="folders.length" class="lb-folder-grid py-2">
    <div v-for="f in folders" :key="f.relative_path"
         class="lb-folder-card group relative flex w-full flex-col overflow-hidden rounded bg-neutral-800 text-sm hover:ring-2 hover:ring-blue-500"
         @contextmenu="onContextMenu(f.relative_path, $event)"
         @touchstart="onTouchStart(f.relative_path, $event)"
         @touchend="onTouchEnd"
         @touchmove="onTouchEnd">
      <!-- 卡片整体可点进目录；省略号按钮作为链接的兄弟节点，避免 button 嵌套在 a 内 -->
      <router-link :to="linkFor(f.relative_path)"
                   class="flex w-full flex-1 flex-col">
        <div class="relative h-24 w-full overflow-hidden bg-neutral-700">
          <img v-if="f.cover_thumb_sha1"
               :src="`/api/thumb/${f.cover_thumb_sha1}?size=200`"
               class="h-full w-full"
               :class="portrait[f.cover_thumb_sha1] ? 'object-contain' : 'object-cover'"
               loading="lazy"
               :alt="f.name"
               @load="onCoverLoad(f.cover_thumb_sha1, $event)" />
          <!-- 封面借自某个直接子文件夹时，图底渐变条标注来源名 -->
          <div v-if="f.cover_source_name"
               class="lb-folder-source pointer-events-none absolute inset-x-0 bottom-0 flex h-8 items-end px-1.5 pb-0.5"
               :title="f.cover_source_name">
            <span class="truncate text-xs text-white">{{ f.cover_source_name }}</span>
          </div>
        </div>
        <div class="truncate p-2">
          <div class="truncate font-medium">{{ f.name }}</div>
          <div class="text-xs text-neutral-400">{{ f.descendant_count }} 张</div>
        </div>
      </router-link>
      <!-- Admin-only 省略号：hover / 键盘 focus 才显示，点击弹快捷菜单 -->
      <button v-if="canExclude"
              type="button"
              :aria-label="`排除文件夹 ${f.name}`"
              class="lb-folder-menu-btn"
              @click.stop="open(f.relative_path, $event)">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <circle cx="5" cy="12" r="2" />
          <circle cx="12" cy="12" r="2" />
          <circle cx="19" cy="12" r="2" />
        </svg>
      </button>
    </div>
    <CellContextMenu :menu="menu"
                     :items="MENU_ITEMS"
                     @action="runAction" />
  </div>
</template>

<script setup lang="ts">
import { reactive } from "vue"
import CellContextMenu from "./CellContextMenu.vue"
import { useCellMenu, type CellMenuItem } from "../composables/useCellMenu"

// 用 type 别名而非 interface：保持隐式索引签名，兼容既有测试把 folders
// 收窄为 Array<Record<string, unknown>> 的断言。
type FolderItem = {
  name: string
  relative_path: string
  image_count: number
  descendant_count: number
  cover_thumb_sha1: string | null
  cover_source_name?: string | null
}

const props = defineProps<{
  folders: FolderItem[]
  gid: number
  rid: number
  /** 管理员为 true：显示省略号、响应右键与长按 */
  canExclude?: boolean
}>()

const emit = defineEmits<{
  (e: "exclude", folder: FolderItem): void
}>()

const MENU_ITEMS: CellMenuItem[] = [
  { action: "exclude", label: "排除此文件夹" },
]

const { menu, open, openAt, runAction } = useCellMenu<string, "exclude">(
  (_e, key, action) => {
    if (action !== "exclude") return
    const folder = props.folders.find((f) => f.relative_path === key)
    if (folder) emit("exclude", folder)
  },
)

function onContextMenu(key: string, ev: MouseEvent) {
  // 非管理员不拦截浏览器默认右键菜单
  if (!props.canExclude) return
  ev.preventDefault()
  open(key, ev)
}

// ---------- 移动端长按（与 PhotoCell 一致：550ms，移动/抬手即取消） ----------

let pressTimer: number | null = null
let pressStart: { key: string; x: number; y: number } | null = null

function onTouchStart(key: string, _ev: TouchEvent) {
  if (!props.canExclude) return
  const t = _ev.touches[0]
  pressStart = { key, x: t.clientX, y: t.clientY }
  pressTimer = window.setTimeout(() => {
    if (!pressStart) return
    openAt(pressStart.key, pressStart.x, pressStart.y)
    pressTimer = null
  }, 550)
}

function onTouchEnd() {
  if (pressTimer !== null) {
    clearTimeout(pressTimer)
    pressTimer = null
  }
  pressStart = null
}

// 记录每张封面缩略图是否为竖版（宽 < 高）。key 为 sha1，多个文件夹复用同一封面时可共享判定。
const portrait = reactive<Record<string, boolean>>({})

function onCoverLoad(sha1: string | null, e: Event) {
  if (!sha1) return
  const img = e.target as HTMLImageElement
  portrait[sha1] = img.naturalWidth < img.naturalHeight
}

function linkFor(rel: string) {
  return `/galleries/${props.gid}/r/${props.rid}/${rel}`
}
</script>

<style scoped>
/*
 * auto-fill + 1fr：卡片等比拉伸铺满整行，左右边缘与图片网格
 * （JustifiedGrid/MasonryGrid 均为内容区满宽）严格对齐；
 * 最小列宽 128（原 w-32），间距与图片网格同为 16px。
 */
.lb-folder-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
  gap: 16px;
}
/* 借来的封面：图底黑色渐变，托住白色来源名 */
.lb-folder-source {
  background: linear-gradient(to top, rgba(0, 0, 0, 0.75), rgba(0, 0, 0, 0));
}
/* 与 PhotoCell 的 .lb-cell-menu-btn 同款：右上角圆形半透明黑底 */
.lb-folder-menu-btn {
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
.lb-folder-card:hover .lb-folder-menu-btn,
.lb-folder-menu-btn:focus-visible {
  display: flex;
}
.lb-folder-menu-btn:hover {
  background: rgba(0, 0, 0, 0.75);
}
</style>
