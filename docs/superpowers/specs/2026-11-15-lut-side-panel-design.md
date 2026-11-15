# LUT 预览左侧滤镜栏 — 设计

日期：2026-11-15
状态：已批准

## 背景与问题

[FilterPreviewView.vue](../../../frontend/src/views/FilterPreviewView.vue)
目前只有底部一条滤镜列表（`.fp-strip`，默认一行高、可拖上沿调高度）。竖版照片在
中央舞台占满高度时，底部列表与图片纵向争夺空间；用户希望增加一种**左侧栏**展开
方式：列表竖排在画面左侧，舞台被横向挤压，适合竖版图修图。同时工具栏改为
三栏对称布局。

## 目标

- 新增左侧滤镜栏模式：按钮控制，默认宽度容纳两列缩略图，右缘可拖拽调宽，
  最大 50vw（可拖窄到一列）。
- 侧栏与现有底部条互斥（同一份 LUT 列表不同时出现两遍）。
- 工具栏三栏化：左侧栏开关在最左、右侧底部条开关在最右、中间操作组居中。
- 工具栏以外（topbar、舞台画布逻辑、下载/强度功能）行为不变。

## 非目标（明确不做）

- 不持久化展开模式与侧栏宽度（刷新回到默认：底部条开、侧栏关），与现有
  高度不持久化约定一致。
- 不改 LUT 渲染管线、小样渲染与 `object-fit: contain` 显示方式。
- 不改右侧底部条按钮的样式/文案/`data-test` 选择器。
- 不做侧栏/底部条同时打开的模式。
- 后端零改动。

## 现有机制（复用点）

- 底部条已实现完整的可调面板范式：`stripHeight`（null=CSS 默认）、
  `ensureMin()` 实测最小尺寸、`clampHeight/draggedHeight/steppedHeight`
  （[resize.ts](../../../frontend/src/lib/resize.ts)，纯数学与维度无关）、
  Pointer Events + setPointerCapture 的 6px 热区手柄、
  `role="separator"` + 方向键/Home/End 的 ARIA 模式。
- 缩略图按钮固定宽 96px（`.fp-thumb`，全局 border-box），窗格 88×58，
  列间距 gap 8px；侧栏默认宽需容纳两列并预留垂直滚动条（见修订记录）= 248px。
- `.fp-page` 是 `height:100vh` 纵向 flex；`.fp-stage` 当前 `flex:1`。
- 列表内容（分组 v-for）目前内联在 `.fp-strip` 中，两个容器需要共用。

## 设计

### 1. 工具栏三栏布局

`.fp-controls` 保持 flex，内部形成三栏：

- **左栏**：新增侧栏按钮，`margin-right: auto`，深色按钮样式与现有同族，
  激活时蓝色描边（复用 `.fp-thumb.active` 同款 `#3b82f6` 边框）：
  - 侧栏关闭：`◀ 滤镜`
  - 侧栏打开：`▶ 收起`
  - `aria-pressed`、`aria-label`（「左侧展开滤镜列表」/「收起左侧滤镜列表」）。
- **中栏**：强度滑块、按住看原图、下载 JPEG、下载原尺寸 JPEG 作为一个
  flex 子组，靠左右 auto 余量自然居中（不再整体靠左）。
- **右栏**：现有底部条按钮 `margin-left: auto`，文案/样式/
  `data-test="strip-toggle"` 一字不改（`▼ 滤镜` / `▲ 收起`）。

左右各一个面板开关、视觉对称；窄屏 flex-wrap 换行（沿用现有能力）。

### 2. 主体结构改为横向 flex

模板把舞台包进新容器：

```vue
<div class="fp-body">
  <aside v-show="sideOpen" class="fp-side" ref="sideEl" :style="sideStyle">
    <LutGroupList :groups="groups" :thumbs="thumbs"
                  :active-id="activeId" :renderer-ready="rendererReady"
                  @pick="pick" />
  </aside>
  <!-- 手柄是 fp-body 的 flex 兄弟项，位于侧栏滚动条右侧，不压在轨道上 -->
  <div v-show="sideOpen" class="fp-side-handle" ...></div>
  <main class="fp-stage">
    <canvas ... /><!-- 现有 canvas/fallback 原样搬入 -->
  </main>
</div>
```

```css
.fp-body { flex: 1; min-height: 0; display: flex; }
.fp-stage { flex: 1; min-width: 0; /* 其余现有 stage 属性保留 */ }
.fp-side {
  flex: none; width: 248px; max-width: 50vw;
  overflow-y: auto; border-right: 1px solid #222;
  padding: 8px 12px;
}
.fp-side-handle { flex: none; position: relative; width: 6px; cursor: col-resize; }
```

侧栏占据 flex 宽度后舞台自动收缩，canvas 的 `max-width/max-height:100%`
与 `object-fit:contain` 在剩余空间重新居中，不被遮挡（挤压模式，非浮层）。
topbar、controls、底部条仍在 `.fp-page` 纵向流中，位置与宽度不变。

### 3. 互斥状态机

新增 `sideOpen = ref(false)`，与 `stripOpen`（默认 true）配合：

```ts
function openSide() { sideOpen.value = true; stripOpen.value = false }
function closeSide() { sideOpen.value = false }
function openStrip() { stripOpen.value = true; sideOpen.value = false }
function closeStrip() { stripOpen.value = false }
```

- 左按钮点击：`sideOpen ? closeSide() : openSide()`。
- 右按钮点击：`stripOpen ? closeStrip() : openStrip()`（替换现有
  `stripOpen = !stripOpen` 内联表达式）。
- 稳态只有三种：仅侧栏、仅底部条、两者都关；不存在同时打开。
- 关闭侧栏只是关闭，不自动拉起底部条；反之亦然（用户显式选择）。

### 4. 侧栏宽度与竖向手柄

状态与底部条同构：

```ts
const sideEl = ref<HTMLElement | null>(null)
const sideWidth = ref<number | null>(null)      // null = CSS 默认 248px
const sideMin = ref<number | null>(null)
const sideDragging = ref(false)
const sideMax = computed(() => Math.round(window.innerWidth / 2))
const sideStyle = computed(() =>
  sideWidth.value === null ? {} : { width: `${sideWidth.value}px`, maxWidth: "50vw" },
)
const sideAriaNow = computed(() =>
  sideWidth.value === null ? undefined : Math.round(sideWidth.value),
)
```

最小宽实测：首个 `.fp-thumb` 的 `offsetWidth` + 侧栏左右 padding
（无元素回退 120）；最大 `innerWidth/2`，倒挂时 clamp 自身容错。

resize.ts 新增一个纯函数（clamp/stepped 复用，不传新维度概念）：

```ts
/** 竖向右缘手柄：指针右移（currentX > startX）时侧栏加宽。 */
export function draggedWidth(
  startWidth: number, startX: number, currentX: number,
): number {
  return startWidth + (currentX - startX)
}
```

手柄（侧栏右侧、滚动条之外，与底部条上缘镜像）：

- 作为 `.fp-body` 的 flex 兄弟项放在 `.fp-side` 之外（避免被滚动容器定位、
  压在滚动条轨道上）；`flex:none; position:relative; width:6px;
  cursor:col-resize; touch-action:none`，`::after` 画 2px 竖向蓝灰线，
  hover/focus/拖拽变 `#3b82f6`。
- Pointer Events：pointerdown 记录 startX/startWidth 并 setPointerCapture，
  move 用 `clampHeight(draggedWidth(...), min, max)`。`clampHeight` 本就是
  维度无关的纯数值钳制，侧栏直接复用、不重命名（避免对已发布模块的无谓改动）。
- 键盘：`role="separator"`、`tabindex="0"`、
  `aria-orientation="vertical"`；→ 加宽、← 变窄（步进 16）、
  Home 最窄、End 半屏，`aria-valuenow/min/max` 实时更新。
- 拖拽期间在 `.fp-page` 切 `is-resizing` 类禁选中文本（复用现有样式）。

### 5. LutGroupList 组件（去重）

新建 `frontend/src/components/LutGroupList.vue`：

- props：`groups: LutGroup[]`、`thumbs: Record<string,string>`、
  `activeId: string | null`、`rendererReady: boolean`。
- emits：`pick(entry: FilterEntry)`。
- 内容为现有 `.fp-strip` 内的分组 v-for 整块（`.fp-group`/`.fp-group-label`/
  `.fp-group-items`/`.fp-thumb`/`.fp-thumb-label`），class 与行为逐字保留。
- 底部条与侧栏都渲染该组件；侧栏容器窄时自然一列，调宽后 flex-wrap 变多列。

### 6. 边界与错误处理

| 情况 | 行为 |
| --- | --- |
| 无 LUT 分组 | 侧栏/底部条内容为空，手柄仍在；最小宽回退 120 |
| 视口很窄，50vw 小于一列宽 | clamp 倒挂容错，宽度停在 50vw |
| 触屏拖手柄 | touch-action:none + 指针捕获，不引发页面滚动 |
| 舞台收缩 | canvas contain 重新适配，不裁剪、不溢出 |
| 切换模式 | 两侧各自的尺寸状态独立保留（回侧栏还是上次宽度），但互斥保证只显示一个 |
| 键盘 | 两个手柄均可 Tab 聚焦，方向键/Home/End 可调 |

## 测试

### resize.spec.ts 增补

- `draggedWidth`：右移 20 → +20；左移 30 → −30。
- `clampHeight` 现有 4 个用例不变（侧栏复用同一函数，无需新测）。

### filter-preview-view.spec.ts 增补

mock 条件：innerWidth=800、getBoundingClientRect 宽 200、`.fp-thumb`
offsetWidth=96、getComputedStyle 左右 padding 各 12 → 最小 120。

1. 三栏：左按钮（◀ 滤镜）与右按钮（strip-toggle）同时存在；初始侧栏
   不存在、底部条可见。
2. 互斥：点左按钮后侧栏出现且底部条 `display:none`；点右按钮后底部条
   恢复、侧栏隐藏。
3. 竖向手柄 ARIA：role=separator、aria-orientation=vertical、tabindex=0。
4. 键盘：→ 后宽 216、← 回 200、Home=120、End=400；内联样式含
   `max-width: 50vw`。
5. 既有 8 个用例全部保持通过（含右按钮 strip toggle、竖版小样等）。

### 手动验证

挤压后画布重排、指针拖拽跟手、窄屏换行、列数随宽度变化、深浅背景下
手柄可见性。

## 修订记录

- 2026-11-15（落地后调整）：
  1. 拖拽手柄从 `.fp-side` 内部的 absolute 元素改为 `.fp-body` 的 flex
     兄弟项，移到滚动条右侧，不再压在滚动条轨道上。
  2. 默认宽度由一列 120px 改为两列 248px。初版按「96×2+gap 8+padding 24」
     算得 224px，但 `overflow-y:auto` 的垂直滚动条（Windows 经典约 17px）
     会占用内容区，flex 可用宽度不足 200px 而换行成一列；额外预留约 24px
     给滚动条后两列稳定显示。最小可拖宽度仍是一列的 120px（ensureSideMin）。

## YAGNI 记录

- **浮层覆盖式侧栏**：画布不动但会遮挡画面，修图时不可接受，排除。
- **两种面板同时打开**：同一份列表渲染两遍、双重滚动区，排除。
- **宽度/模式持久化**：未要求，刷新回默认，排除。
