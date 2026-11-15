# LUT 预览：缩略图完整显示与滤镜条可调高度 — 设计

日期：2026-11-15
状态：已批准

## 背景与问题

[FilterPreviewView.vue](../../../frontend/src/views/FilterPreviewView.vue)
滤镜小样条存在两个问题：

1. 上一轮修复了小样 canvas 的宽高比拉伸，但显示端 `.fp-thumb img` 仍是固定
   88×58 窗格 + `object-fit: cover`，竖版照片会被居中裁掉上下部分，看不到全图。
2. 滤镜条高度固定为 `max-height: 280px`，LUT 数量多时只能在 280px 内滚动，
   用户无法按屏幕/偏好扩大浏览区域。

## 目标

- 竖版缩略图完整显示：等比缩小到能放进窗格，不裁剪。
- 滤镜条高度可通过顶部拖拽手柄调节：最小为一行缩略图（含组标题）的实测高度，
  最大为视口高度的 1/2；支持鼠标、触屏与键盘操作。

## 非目标（明确不做）

- 不改缩略图窗格尺寸（88×58）、列宽（96px）与标签排版，保持各滤镜严格按列对齐。
- 不做高度的 localStorage 持久化：刷新/重新打开回到默认高度（YAGNI）。
- 不改收起/展开按钮（strip toggle）的现有行为与 LUT 渲染管线。
- 后端零改动。

## 现有机制（复用点）

- 小样 dataURL 已在 [上一轮修复](../../../frontend/src/views/FilterPreviewView.vue)
  中按源图宽高比等比渲染（`renderThumbs` 拟合进 192×128 盒），像素本身不失真，
  本设计只改显示端的填充方式。
- `.fp-strip` 已是 `overflow-y: auto` 的滚动容器，固定高度后滚动行为天然成立。
- 页面根 `.fp-page` 是 `height:100vh` 的 flex 列布局，滤镜条增高时主舞台
  （`.fp-stage`，`flex:1`）自动收缩，无需额外布局处理。
- 项目测试中 jsdom 不做真实布局，几何计算需抽成纯函数单测，DOM 测量部分在
  组件测试里 mock `getBoundingClientRect`/`offsetHeight`。

## 设计

### 1. 缩略图完整显示（纯 CSS）

`.fp-thumb img` 的 `object-fit: cover` 改为 `object-fit: contain`：

```css
.fp-thumb img {
  width: 88px; height: 58px; object-fit: contain; border-radius: 4px;
  background: #333; display: block;
}
```

- 窗格与列宽不变，横版图视觉基本不变（仅边缘可能出现极小留白）；
  竖版图等比缩小、完整居中，留白区域由现有 `#333` 深底填充，与深色页面一致。
- 纯视觉属性，jsdom 无法断言计算值，不写自动化用例，列入浏览器手动验证。

### 2. 纯函数模块 `frontend/src/lib/resize.ts`（可单测）

```ts
/** 键盘调节的步进像素。 */
export const RESIZE_STEP = 16

/** 把高度钳进 [min, max]；min/max 倒挂时以较小者为下界。 */
export function clampHeight(h: number, min: number, max: number): number {
  const lo = Math.min(min, max)
  return Math.min(Math.max(h, lo), Math.max(min, max))
}

/** 拖拽数学：手柄在区域上沿，指针上移（currentY < startY）时区域增高。 */
export function draggedHeight(
  startHeight: number, startY: number, currentY: number,
): number {
  return startHeight + (startY - currentY)
}

/** 键盘步进后再钳制。dir：+1 增高（↑）、-1 降低（↓）。 */
export function steppedHeight(
  current: number, dir: 1 | -1, min: number, max: number,
): number {
  return clampHeight(current + dir * RESIZE_STEP, min, max)
}
```

### 3. 滤镜条与拖拽手柄（FilterPreviewView）

**模板**：`.fp-strip` 内最前面插入手柄，并绑定动态高度：

```vue
<section v-show="stripOpen" class="fp-strip" ref="stripEl"
         :style="stripStyle">
  <div class="fp-resize-handle"
       role="separator"
       tabindex="0"
       aria-label="调节滤镜列表高度"
       aria-orientation="horizontal"
       :aria-valuenow="ariaNow"
       :aria-valuemin="minHeight ?? 0"
       :aria-valuemax="maxHeight"
       @pointerdown="onPointerDown"
       @pointermove="onPointerMove"
       @pointerup="onPointerUp"
       @pointercancel="onPointerUp"
       @keydown="onKeydown"></div>
  <!-- 原有 v-for 分组不变 -->
</section>
```

**状态**：

```ts
const stripEl = ref<HTMLElement | null>(null)
/** null = 未手动调节，沿用 CSS 默认 max-height；数字 = 显式像素高度 */
const stripHeight = ref<number | null>(null)
const minHeight = ref<number | null>(null)
const dragging = ref(false)
const maxHeight = computed(() => Math.round(window.innerHeight / 2))
// 显式高度必须同时覆盖 CSS 默认的 max-height:280px，否则 >280 的拖拽结果被钳回去
const stripStyle = computed(() =>
  stripHeight.value === null
    ? {}
    : { height: `${stripHeight.value}px`, maxHeight: "50vh" },
)
const ariaNow = computed(() =>
  stripHeight.value === null ? undefined : Math.round(stripHeight.value),
)
```

**最小高度实测**（首次交互时惰性计算一次）：取滤镜条内第一个 `.fp-group`
的 `offsetHeight`，加滤镜条自身的上下 padding（`getComputedStyle` 解析，
当前为 8px + 12px）；找不到分组时回退 120px：

```ts
function ensureMin(): number {
  if (minHeight.value !== null) return minHeight.value
  const strip = stripEl.value
  const group = strip?.querySelector<HTMLElement>(".fp-group")
  if (!strip || !group) {
    minHeight.value = 120
    return minHeight.value
  }
  const cs = getComputedStyle(strip)
  // || 0 兜底：jsdom 不解析 scoped CSS 时 padding 返回空串
  const pt = parseInt(cs.paddingTop, 10) || 0
  const pb = parseInt(cs.paddingBottom, 10) || 0
  minHeight.value = group.offsetHeight + pt + pb
  return minHeight.value
}
```

**指针拖拽**（Pointer Events，setPointerCapture 保证移出元素仍持续收事件；
`touch-action: none` 在 CSS 上声明，触屏拖动不引发页面滚动）：

```ts
let dragStartY = 0
let dragStartH = 0

function onPointerDown(e: PointerEvent) {
  const min = ensureMin()
  const max = maxHeight.value
  dragStartY = e.clientY
  dragStartH = clampHeight(
    stripHeight.value ?? stripEl.value!.getBoundingClientRect().height,
    min, max,
  )
  stripHeight.value = dragStartH
  dragging.value = true
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  stripHeight.value = clampHeight(
    draggedHeight(dragStartH, dragStartY, e.clientY),
    ensureMin(), maxHeight.value,
  )
}

function onPointerUp(e: PointerEvent) {
  if (!dragging.value) return
  dragging.value = false
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
}
```

**键盘可达性**：↑/↓ 以 16px 步进、Home 到最小、End 到最大：

```ts
function onKeydown(e: KeyboardEvent) {
  const min = ensureMin()
  const max = maxHeight.value
  const cur = stripHeight.value
    ?? Math.round(stripEl.value!.getBoundingClientRect().height)
  if (e.key === "ArrowUp") stripHeight.value = steppedHeight(cur, 1, min, max)
  else if (e.key === "ArrowDown") stripHeight.value = steppedHeight(cur, -1, min, max)
  else if (e.key === "Home") stripHeight.value = min
  else if (e.key === "End") stripHeight.value = max
  else return
  e.preventDefault()
}
```

**CSS**：

```css
.fp-strip {
  position: relative; /* 手柄绝对定位的参照 */
  /* 保留现有 border-top / padding / overflow-y:auto；默认 max-height 改为 */
  max-height: min(280px, 50vh);
}
.fp-resize-handle {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 6px;                /* 热区 */
  cursor: row-resize;
  touch-action: none;
  z-index: 2;
}
.fp-resize-handle::after {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 2px;
  height: 2px;               /* 视觉线 */
  background: #444;
}
.fp-resize-handle:hover::after,
.fp-resize-handle:focus-visible::after,
.fp-resize-handle.active::after {
  background: #3b82f6;
}
.fp-resize-handle:focus-visible { outline: none; }
/* 拖拽期间禁止选中文本（dragging ref 在 .fp-page 上切 is-resizing 类，
   不用 :has() 以规避旧浏览器兼容问题） */
.fp-page.is-resizing { user-select: none; }
```

模板根节点同步绑定：`<div class="fp-page" :class="{ 'is-resizing': dragging }">`，
手柄的视觉激活类同样由 `dragging` 驱动（`:class="{ active: dragging }"`）。

显式高度生效时，`.fp-strip` 的 `height` 由内联样式给定、`overflow-y: auto`
负责内部滚动；默认态（未拖拽过）行为与现状完全一致。收起（v-show=false）
同时隐藏手柄，重新展开恢复已调高度。

## 边界与错误处理

| 情况 | 行为 |
| --- | --- |
| 没有任何 LUT 分组 | ensureMin 回退 120px；手柄仍可操作但列表为空 |
| 视口很小导致 50vh 小于一行高度 | clampHeight 以 min/max 较小者为下界，高度停在 50vh 不报错 |
| 触屏拖拽 | touch-action:none + Pointer Events，不触发页面滚动 |
| 收起后重新展开 | stripHeight 保留，恢复上次高度 |
| 窗口尺寸变化 | 已设高度不自动重算（下次拖拽/按键时重新钳制）；默认态随 vh 自适应 |
| 键盘 Tab | 手柄可聚焦，焦点环走蓝色视觉线，aria-valuenow 报告当前像素高度 |

## 测试

### 新建 `frontend/src/tests/resize.spec.ts`（纯函数）

1. `clampHeight`：低于 min、高于 max、区间内、min>max 倒挂四种输入。
2. `draggedHeight`：指针上移 20px → 高度 +20；下移 30px → 高度 −30。
3. `steppedHeight`：±16 步进、触边钳制。

### 扩 `frontend/src/tests/filter-preview-view.spec.ts`

mock `getBoundingClientRect`（滤镜条高度 200）、`.fp-group` 的
`offsetHeight`（110）、`getComputedStyle`（paddingTop 8px、paddingBottom 12px
→ 最小高度 130）、`window.innerHeight`（800 → max 400）：

1. 手柄存在，具备 `role="separator"`、`tabindex="0"`、`aria-orientation`。
2. 键盘 ↓：内联 height 变为 184px（200−16）；↑ 回到 200。
3. Home：高度 = 最小实测值（110 + padding 20 = 130）；End：400。
4. 既有「strip toggle 收起/展开」用例保持通过（手柄在 section 内随 v-show 隐藏）。

### 手动验证（jsdom 无法覆盖的视觉/指针部分）

- contain：竖版照片缩略图完整可见、居中、不裁剪；横版无明显变化。
- 鼠标拖手柄实时变高，到一行高度和 50vh 处停住；触屏拖动不滚页面。
- 键盘焦点在手柄上时 ↑/↓/Home/End 行为正确。

全量 `pnpm test && pnpm build` 通过；后端零改动，不跑后端回归。

## YAGNI 记录

曾评估的另一个方案：

- **浏览器原生 `resize: vertical`**：零 JS、纯 CSS，但手柄是系统默认右下角样式，
  与本页深色自定义 UI 不一致，不支持触屏，且 min-height 只能给固定估值、无法
  实测「一行」高度，排除。
