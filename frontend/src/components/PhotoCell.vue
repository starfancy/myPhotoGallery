<template>
  <div class="lb-grid-cell relative h-full w-full overflow-hidden bg-surface-2"
       :class="{ 'lb-grid-cell--selected': selected }"
       :style="cellStyle">
    <button type="button"
            class="absolute inset-0 focus:outline-none focus:ring-2 focus:ring-primary"
            @click="$emit('activate')"
            @contextmenu.prevent="$emit('contextmenu', $event)"
            @touchstart="onTouchStart"
            @touchend="onTouchEnd"
            @touchmove="onTouchEnd">
      <img :src="`/api/thumb/${sha1}?size=400`"
           :srcset="`/api/thumb/${sha1}?size=200 200w, /api/thumb/${sha1}?size=400 400w`"
           sizes="(max-width: 640px) 200px, 400px"
           loading="lazy"
           :alt="filename"
           class="h-full w-full object-cover" />
    </button>
    <!-- 文件名开关：底部渐变阴影上居中显示文件名；不拦截点击 -->
    <div v-if="showFilename"
         class="lb-cell-filename pointer-events-none truncate text-center"
         :title="filename">
      {{ filename }}
    </div>
    <div v-if="badge"
         class="lb-cell-badge pointer-events-none truncate text-left"
         :class="{ 'lb-cell-badge--up': showFilename }"
         :title="badge">
      {{ badge }}
    </div>
    <!-- 选择模式：左上角勾选圈；非选择模式也保留一个可显示的空框，避免选择切换后布局跳动 -->
    <button v-if="selectionMode"
            type="button"
            :aria-label="`选择 ${filename}`"
            :aria-pressed="selected"
            class="lb-cell-check"
            :class="{ 'lb-cell-check--on': selected }"
            @click.stop="$emit('toggleSelect')">
      <svg v-if="selected" width="14" height="14" viewBox="0 0 24 24"
           fill="none" stroke="currentColor" stroke-width="3"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <polyline points="20 6 9 17 4 12" />
      </svg>
    </button>
    <!-- Admin-only 三点菜单：选择模式下隐藏，避免与勾选交互冲突 -->
    <button v-if="showMenu"
            type="button"
            :aria-label="`更多操作 ${filename}`"
            class="lb-cell-menu-btn"
            @click.stop="$emit('menu', $event)">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <circle cx="5" cy="12" r="2" />
        <circle cx="12" cy="12" r="2" />
        <circle cx="19" cy="12" r="2" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  id: number
  sha1: string
  filename: string
  selected?: boolean
  selectionMode?: boolean
  /** 是否显示三点菜单（admin 且非选择模式） */
  showMenu?: boolean
  /** 是否在底部渐变阴影上叠加文件名 */
  showFilename?: boolean
  /** 单元格尺寸/定位样式：行排版给宽高，列排版给 grid-row span */
  cellStyle?: Record<string, string | number>
  /** 搜索结果：所在目录小字（posix 目录路径）；root 图片与普通浏览不传 */
  badge?: string
}>()

const emit = defineEmits<{
  (e: "activate"): void
  (e: "toggleSelect"): void
  (e: "menu", ev: MouseEvent): void
  (e: "contextmenu", ev: MouseEvent): void
  (e: "longpress", p: { x: number; y: number }): void
}>()

// ---------- 移动端长按 ----------

let pressTimer: number | null = null
let pressStartXY: { x: number; y: number } | null = null

function onTouchStart(_ev: TouchEvent) {
  if (!props.showMenu) return
  const t = _ev.touches[0]
  pressStartXY = { x: t.clientX, y: t.clientY }
  pressTimer = window.setTimeout(() => {
    if (!pressStartXY) return
    emit("longpress", { x: pressStartXY.x, y: pressStartXY.y })
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
</script>

<style scoped>
.lb-grid-cell--selected {
  outline: 3px solid rgb(var(--color-primary-hover));
  outline-offset: -3px;
}
.lb-cell-filename {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1;
  padding: 18px 6px 5px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.72), rgba(0, 0, 0, 0));
  color: #fff;
  font-size: 11px;
  line-height: 1.3;
  /* truncate / text-center 由工具类提供；超长省略号，hover 看 title 全名 */
}
.lb-cell-badge {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1;
  padding: 16px 6px 3px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.72), rgba(0, 0, 0, 0));
  color: #fff;
  font-size: 10px;
  line-height: 1.2;
}
.lb-cell-badge--up {
  /* 同时显示文件名时，目录行抬到文件名行之上 */
  bottom: 15px;
}
.lb-cell-menu-btn {
  position: absolute;
  /* 8px 外边距配合 ::after 的 -8px：44px 热区刚好落在卡片 overflow:hidden 之内 */
  top: 8px;
  right: 8px;
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
/* 触屏热区扩到 44×44：可视圆钮仍是 28px，四周 8px 透明区也归按钮 */
.lb-cell-menu-btn::after {
  content: "";
  position: absolute;
  inset: -8px;
}
.lb-cell-check {
  position: absolute;
  /* 10px 外边距配合 ::after 的 -10px：44px 热区不被卡片 overflow:hidden 裁掉 */
  top: 10px;
  left: 10px;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border: 2px solid rgba(255, 255, 255, 0.85);
  z-index: 2;
}
.lb-cell-check--on {
  background: rgb(var(--color-primary-hover));
  border-color: rgb(var(--color-primary-hover));
}
/* 选择圈可视 24px，热区同样扩到 44×44（四周 10px 透明边） */
.lb-cell-check::after {
  content: "";
  position: absolute;
  inset: -10px;
}
</style>
