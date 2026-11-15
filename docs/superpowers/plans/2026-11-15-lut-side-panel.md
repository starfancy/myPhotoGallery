# LUT 左侧滤镜栏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LUT 预览页新增左侧滤镜栏（挤压舞台、宽度可拖至 50vw），工具栏三栏对称，侧栏与底部条互斥，列表抽成共享组件。

**Architecture:** resize.ts 增一个维度无关的 `draggedWidth` 纯函数；新建 LutGroupList 承载分组列表，底部条与侧栏共用；FilterPreviewView 用横向 flex 包舞台，侧栏状态/手柄与底部条同构，复用现有 clamp/步进函数与 Pointer Events 模式。

**Tech Stack:** Vue 3 `<script setup>` + scoped CSS + Pointer Events + vitest（pnpm）

## Global Constraints

- 侧栏默认宽 120px（96px 缩略图 + 左右 padding 12px×2），`max-width: 50vw`；最小宽实测首个 `.fp-thumb` offsetWidth + 左右 padding，回退 120；最大 `innerWidth/2`。
- 互斥：`sideOpen` 与 `stripOpen` 不得同时为真；初始 stripOpen=true、sideOpen=false。
- 左按钮文案 `◀ 滤镜`（关）/ `▶ 收起`（开）；右按钮文案/样式/`data-test="strip-toggle"` 一字不改。
- 宽度与模式不持久化；后端零改动；只本地 commit。
- 测试：`cd frontend && pnpm test resize` / `pnpm test filter-preview`；全量 `pnpm test && pnpm build`

---

### Task 1: resize.ts 增加 draggedWidth（TDD）

**Files:**

- Modify: `frontend/src/lib/resize.ts`
- Test: `frontend/src/tests/resize.spec.ts`

**Interfaces:**

- Consumes: 无。
- Produces: `draggedWidth(startWidth, startX, currentX): number`（右移为正），供 Task 3 侧栏手柄使用；现有 clampHeight/steppedHeight 不动。

- [ ] **Step 1: 写失败测试**

在 `frontend/src/tests/resize.spec.ts` 的 import 中加入 `draggedWidth`，并在 describe 内追加：

```ts
  it("draggedWidth：竖向右缘手柄右移加宽、左移变窄", () => {
    // currentX 比 startX 大 20（右移）→ 宽度 +20
    expect(draggedWidth(200, 300, 320)).toBe(220)
    // 左移 30 → 宽度 -30
    expect(draggedWidth(200, 300, 270)).toBe(170)
  })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && pnpm test resize`
Expected: 新用例 FAIL（draggedWidth 未导出），原 4 个 PASS。

- [ ] **Step 3: 实现**

在 `frontend/src/lib/resize.ts` 末尾追加：

```ts
/** 竖向右缘手柄：指针右移（currentX > startX）时侧栏加宽。 */
export function draggedWidth(
  startWidth: number,
  startX: number,
  currentX: number,
): number {
  return startWidth + (currentX - startX)
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && pnpm test resize`
Expected: 5 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/resize.ts frontend/src/tests/resize.spec.ts
git commit -m "feat(lut): add draggedWidth helper for side panel resize"
```

---

### Task 2: 抽出 LutGroupList 共享组件（纯重构，行为不变）

**Files:**

- Create: `frontend/src/components/LutGroupList.vue`
- Modify: `frontend/src/views/FilterPreviewView.vue`（类型导入、底部条改用组件、样式搬移、过时注释修正）

**Interfaces:**

- Consumes: 视图现有的 groups/thumbs/activeId/rendererReady 与 pick 处理。
- Produces: 组件 props `groups: LutGroup[]`、`thumbs: Record<string,string>`、`activeId: string|null`、`rendererReady: boolean`；emit `pick(entry: FilterEntry)`；并从组件 export 三个接口类型供视图复用。

- [ ] **Step 1: 创建 LutGroupList.vue**

```vue
<template>
  <div v-for="g in groups" :key="g.group" class="fp-group">
    <div class="fp-group-label">{{ groupLabel(g.group) }}</div>
    <div class="fp-group-items">
      <button
        v-for="f in g.items" :key="f.slug"
        class="fp-thumb" :class="{ active: f.slug === activeId }"
        :disabled="!rendererReady"
        :title="f.label"
        @click="$emit('pick', { id: f.slug, label: f.label, slug: f.slug })"
      >
        <img v-if="thumbs[f.slug]" :src="thumbs[f.slug]" :alt="f.label" />
        <span class="fp-thumb-label">{{ f.label }}</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { groupLabel } from "../lib/lutGroups"

export interface FilterEntry { id: string; label: string; slug: string }
export interface LutEntry { slug: string; label: string; sort_order: number }
export interface LutGroup { group: string; items: LutEntry[] }

defineProps<{
  groups: LutGroup[]
  thumbs: Record<string, string>
  activeId: string | null
  rendererReady: boolean
}>()
defineEmits<{ (e: "pick", entry: FilterEntry): void }>()
</script>

<style scoped>
.fp-group { margin-bottom: 10px; }
.fp-group:last-child { margin-bottom: 0; }
.fp-group-label {
  font-size: 12px; color: #999; margin-bottom: 6px;
}
.fp-group-items {
  display: flex; flex-wrap: wrap; gap: 8px;
}
.fp-thumb {
  /* 固定列宽：缩略图与下方名称严格按列对齐 */
  width: 96px;
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  background: transparent; border: 2px solid transparent;
  padding: 4px; cursor: pointer; border-radius: 6px;
}
.fp-thumb.active { border-color: #3b82f6; }
.fp-thumb img {
  width: 88px; height: 58px; object-fit: contain; border-radius: 4px;
  background: #333; display: block;
}
.fp-thumb-label {
  font-size: 11px; color: #ccc; text-align: center;
  width: 88px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
</style>
```

- [ ] **Step 2: 视图删除本地接口定义，改从组件导入类型**

删除 FilterPreviewView.vue 中的三行：

```ts
interface FilterEntry { id: string; label: string; slug: string }
interface LutEntry { slug: string; label: string; sort_order: number }
interface LutGroup { group: string; items: LutEntry[] }
```

在 import 区加入：

```ts
import LutGroupList, {
  type FilterEntry,
  type LutGroup,
} from "../components/LutGroupList.vue"
```

- [ ] **Step 3: 底部条内联 v-for 替换为组件**

把 `.fp-strip` 内从 `<div v-for="g in groups" ...>` 到其闭合 `</div>` 的整段
（当前 68–82 行的分组 v-for）替换为：

```vue
      <LutGroupList :groups="groups" :thumbs="thumbs"
                    :active-id="activeId" :renderer-ready="rendererReady"
                    @pick="pick" />
```

- [ ] **Step 4: 视图 scoped 样式移除已搬走的规则**

删除 FilterPreviewView.vue `<style>` 中的这些规则（已移到组件）：
`.fp-group`、`.fp-group:last-child`、`.fp-group-label`、`.fp-group-items`、
`.fp-thumb`、`.fp-thumb.active`、`.fp-thumb img`、`.fp-thumb-label`。
保留 `.fp-strip`、`.fp-resize-handle*`、`.fp-page.is-resizing` 等其余规则。

同时删除不再使用的导入：`import { groupLabel } from "../lib/lutGroups"`
（groupLabel 现在只在 LutGroupList 内使用）。

- [ ] **Step 5: 顺手修正 renderThumbs 过时注释**

把 renderThumbs 注释中的：

```text
 *  显示端 .fp-thumb img 的 object-fit:cover 再做居中裁剪；
```

改为：

```text
 *  显示端 .fp-thumb img 的 object-fit:contain 完整居中显示；
```

- [ ] **Step 6: 回归测试**

Run: `cd frontend && pnpm test filter-preview`
Expected: 8 个用例全部 PASS（DOM 结构对 wrapper 查询透明，选择器仍命中）。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/LutGroupList.vue frontend/src/views/FilterPreviewView.vue
git commit -m "refactor(lut): extract LutGroupList shared component"
```

---

### Task 3: 左侧滤镜栏、三栏工具栏与互斥状态（TDD）

**Files:**

- Modify: `frontend/src/tests/filter-preview-view.spec.ts`（新增 4 个用例）
- Modify: `frontend/src/views/FilterPreviewView.vue`（模板、script、CSS）

**Interfaces:**

- Consumes: Task 1 的 `draggedWidth`、现有 `clampHeight/steppedHeight/RESIZE_STEP`；Task 2 的 LutGroupList。
- Produces: `.fp-side`/`.fp-side-handle` DOM、`sideOpen/sideWidth/sideMin/sideMax` 等视图内状态，无对外接口。

- [ ] **Step 1: 写失败测试——在 describe 末尾追加 4 个用例**

```ts
  it("工具栏三栏：侧栏按钮存在，初始侧栏隐藏、底部条可见", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    const sideBtn = w.find('[data-test="side-toggle"]')
    expect(sideBtn.exists()).toBe(true)
    expect(sideBtn.text()).toContain("◀")
    // v-show=false：元素在但 display:none
    expect(w.find("aside.fp-side").attributes("style")).toContain("display: none")
    expect(w.find("section.fp-strip").attributes("style")).toBeUndefined()
  })

  it("侧栏与底部条互斥：开侧栏关底部条，开底部条关侧栏", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    await w.get('[data-test="side-toggle"]').trigger("click")
    await flushPromises()
    expect(w.find("aside.fp-side").attributes("style") ?? "").not.toContain("display: none")
    expect(w.find("section.fp-strip").attributes("style")).toContain("display: none")

    await w.get('[data-test="strip-toggle"]').trigger("click")
    await flushPromises()
    expect(w.find("section.fp-strip").attributes("style") ?? "").not.toContain("display: none")
    expect(w.find("aside.fp-side").attributes("style")).toContain("display: none")
  })

  it("竖向手柄具备 separator ARIA 语义", async () => {
    const w = mount(FilterPreviewView)
    await flushPromises()
    const h = w.find(".fp-side-handle")
    expect(h.attributes("role")).toBe("separator")
    expect(h.attributes("aria-orientation")).toBe("vertical")
    expect(h.attributes("tabindex")).toBe("0")
    expect(h.attributes("aria-label")).toBe("调节左侧滤镜栏宽度")
  })

  it("侧栏键盘调宽：→/← 步进、Home 最窄、End 半屏并钳制", async () => {
    // 宽度钳制基于 innerWidth；用 getter spy 而非 stubGlobal——
    // unstubAllGlobals 会连带清掉文件级 Image stub，导致后续用例图片加载挂起
    const wSpy = vi.spyOn(window, "innerWidth", "get").mockReturnValue(800)
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ width: 200 } as DOMRect)
    const csSpy = vi
      .spyOn(window, "getComputedStyle")
      .mockReturnValue({
        paddingLeft: "12px", paddingRight: "12px",
        paddingTop: "8px", paddingBottom: "12px",
      } as CSSStyleDeclaration)
    try {
      const w = mount(FilterPreviewView)
      await flushPromises()
      // 最小宽 = 缩略图 96 + 左右 padding 24 = 120
      Object.defineProperty(w.get(".fp-side .fp-thumb").element, "offsetWidth", {
        value: 96, configurable: true,
      })
      // 先打开侧栏
      await w.get('[data-test="side-toggle"]').trigger("click")
      const handle = w.find(".fp-side-handle")
      const side = () => w.find("aside.fp-side")

      await handle.trigger("keydown", { key: "ArrowRight" })
      expect(side().attributes("style")).toContain("width: 216px")
      await handle.trigger("keydown", { key: "ArrowLeft" })
      expect(side().attributes("style")).toContain("width: 200px")
      await handle.trigger("keydown", { key: "Home" })
      expect(side().attributes("style")).toContain("width: 120px")
      await handle.trigger("keydown", { key: "End" })
      expect(side().attributes("style")).toContain("width: 400px")
      expect(side().attributes("style")).toContain("max-width: 50vw")
    } finally {
      wSpy.mockRestore()
      rectSpy.mockRestore()
      csSpy.mockRestore()
    }
  })
```

> 实施补充：Task 2 抽出 LutGroupList 后页面存在侧栏、底部条两个组件实例，
> 既有「滤镜条高度手柄」用例的 `w.get(".fp-group")` 会误选到侧栏分组，
> 需把选择器收窄为 `w.get("section.fp-strip .fp-group")`，否则底部条
> ensureMin 读到的 offsetHeight 仍是 0（实测最小高度变成仅 padding 的 20px）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && pnpm test filter-preview`
Expected: 4 个新用例 FAIL（无 side-toggle / fp-side），原 8 个 PASS。

- [ ] **Step 3: script——导入与侧栏状态/函数**

resize 导入改为：

```ts
import {
  RESIZE_STEP,
  clampHeight,
  draggedHeight,
  draggedWidth,
  steppedHeight,
} from "../lib/resize"
```

在 `const stripOpen = ref(true)` 后加：

```ts
const sideOpen = ref(false)
```

在底部条高度状态块之后（onKeydown 函数之后）追加侧栏状态与处理：

```ts
// ---- 左侧滤镜栏可调宽度 ----
const sideEl = ref<HTMLElement | null>(null)
/** null = 未手动调节，沿用 CSS 默认 120px；数字 = 显式像素宽度 */
const sideWidth = ref<number | null>(null)
const sideMin = ref<number | null>(null)
const sideDragging = ref(false)
const sideMax = computed(() => Math.round(window.innerWidth / 2))
const sideStyle = computed(() =>
  sideWidth.value === null
    ? {}
    : { width: `${sideWidth.value}px`, maxWidth: "50vw" },
)
const sideAriaNow = computed(() =>
  sideWidth.value === null ? undefined : Math.round(sideWidth.value),
)

/** 首次交互实测一列缩略图所需最小宽度，只算一次。 */
function ensureSideMin(): number {
  if (sideMin.value !== null) return sideMin.value
  const side = sideEl.value
  const thumb = side?.querySelector<HTMLElement>(".fp-thumb")
  if (!side) {
    sideMin.value = 120
    return sideMin.value
  }
  const cs = getComputedStyle(side)
  const pl = parseInt(cs.paddingLeft, 10) || 0
  const pr = parseInt(cs.paddingRight, 10) || 0
  // 无缩略图时 offsetWidth 取不到，回退默认
  sideMin.value = thumb ? thumb.offsetWidth + pl + pr : 120
  return sideMin.value
}

let dragStartX = 0
let dragStartW = 0

function onSidePointerDown(e: PointerEvent) {
  const min = ensureSideMin()
  const max = sideMax.value
  dragStartX = e.clientX
  dragStartW = clampHeight(
    sideWidth.value ?? sideEl.value!.getBoundingClientRect().width,
    min,
    max,
  )
  sideWidth.value = dragStartW
  sideDragging.value = true
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onSidePointerMove(e: PointerEvent) {
  if (!sideDragging.value) return
  sideWidth.value = clampHeight(
    draggedWidth(dragStartW, dragStartX, e.clientX),
    ensureSideMin(),
    sideMax.value,
  )
}

function onSidePointerUp(e: PointerEvent) {
  if (!sideDragging.value) return
  sideDragging.value = false
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
}

function onSideKeydown(e: KeyboardEvent) {
  const min = ensureSideMin()
  const max = sideMax.value
  const cur =
    sideWidth.value ?? Math.round(sideEl.value!.getBoundingClientRect().width)
  if (e.key === "ArrowRight") {
    sideWidth.value = clampHeight(cur + RESIZE_STEP, min, max)
  } else if (e.key === "ArrowLeft") {
    sideWidth.value = clampHeight(cur - RESIZE_STEP, min, max)
  } else if (e.key === "Home") {
    sideWidth.value = min
  } else if (e.key === "End") {
    sideWidth.value = max
  } else {
    return
  }
  e.preventDefault()
}

// ---- 面板互斥状态机 ----
function toggleSide() {
  if (sideOpen.value) sideOpen.value = false
  else { sideOpen.value = true; stripOpen.value = false }
}
function toggleStrip() {
  if (stripOpen.value) stripOpen.value = false
  else { stripOpen.value = true; sideOpen.value = false }
}
```

- [ ] **Step 4: 模板——舞台包 fp-body 并插入侧栏**

把：

```vue
    <main class="fp-stage">
      <canvas ref="canvasEl" class="fp-canvas"></canvas>
      <div v-if="fallbackMsg" class="fp-fallback">{{ fallbackMsg }}</div>
      <div v-if="isLocal && !rendererReady && !fallbackMsg" class="fp-fallback">
        从上方"选择本地图片"按钮选一张照片，纯前端处理，不上传服务器
      </div>
    </main>
```

替换为：

```vue
    <div class="fp-body">
      <aside
        v-show="sideOpen"
        class="fp-side"
        ref="sideEl"
        :style="sideStyle"
      >
        <div
          class="fp-side-handle"
          :class="{ active: sideDragging }"
          role="separator"
          tabindex="0"
          aria-label="调节左侧滤镜栏宽度"
          aria-orientation="vertical"
          :aria-valuenow="sideAriaNow"
          :aria-valuemin="sideMin ?? 0"
          :aria-valuemax="sideMax"
          @pointerdown="onSidePointerDown"
          @pointermove="onSidePointerMove"
          @pointerup="onSidePointerUp"
          @pointercancel="onSidePointerUp"
          @keydown="onSideKeydown"
        ></div>
        <LutGroupList :groups="groups" :thumbs="thumbs"
                      :active-id="activeId" :renderer-ready="rendererReady"
                      @pick="pick" />
      </aside>
      <main class="fp-stage">
        <canvas ref="canvasEl" class="fp-canvas"></canvas>
        <div v-if="fallbackMsg" class="fp-fallback">{{ fallbackMsg }}</div>
        <div v-if="isLocal && !rendererReady && !fallbackMsg" class="fp-fallback">
          从上方"选择本地图片"按钮选一张照片，纯前端处理，不上传服务器
        </div>
      </main>
    </div>
```

- [ ] **Step 5: 模板——工具栏三栏化**

把整个 `<section class="fp-controls"> ... </section>` 替换为：

```vue
    <section class="fp-controls">
      <button
        type="button"
        class="fp-side-toggle"
        :class="{ active: sideOpen }"
        data-test="side-toggle"
        :title="sideOpen ? '收起左侧滤镜列表' : '左侧展开滤镜列表'"
        :aria-label="sideOpen ? '收起左侧滤镜列表' : '左侧展开滤镜列表'"
        :aria-pressed="sideOpen"
        @click="toggleSide"
      >{{ sideOpen ? "▶ 收起" : "◀ 滤镜" }}</button>
      <div class="fp-controls-center">
        <label class="fp-strength">
          强度
          <input
            type="range" min="0" max="100"
            :value="mixPct"
            :disabled="!rendererReady"
            @input="onMixInput"
          />
          <span>{{ mixPct }}%</span>
        </label>
        <button
          :disabled="!rendererReady"
          @pointerdown="holdStart"
          @pointerup="holdEnd"
          @pointercancel="holdEnd"
          @pointerleave="holdEnd"
        >按住看原图</button>
        <button :disabled="!rendererReady" @click="onDownload">下载 JPEG</button>
        <button
          v-if="!isLocal"
          :disabled="!rendererReady || !imageId || downloadingOriginal"
          @click="onDownloadOriginal"
        >{{ downloadingOriginal ? "处理中..." : "下载原尺寸 JPEG" }}</button>
      </div>
      <button
        class="fp-strip-toggle"
        :class="{ active: stripOpen }"
        :title="stripOpen ? '收起滤镜列表' : '展开滤镜列表'"
        data-test="strip-toggle"
        :aria-pressed="stripOpen"
        @click="toggleStrip"
      >{{ stripOpen ? "▲ 收起" : "▼ 滤镜" }}</button>
    </section>
```

- [ ] **Step 6: 模板——根节点 is-resizing 纳入侧栏拖拽**

把：

```vue
  <div class="fp-page" :class="{ 'is-resizing': dragging }">
```

改为：

```vue
  <div class="fp-page" :class="{ 'is-resizing': dragging || sideDragging }">
```

- [ ] **Step 7: CSS——新增 body/侧栏/手柄/三栏样式**

在 `<style scoped>` 的 `.fp-stage` 规则**之前**插入：

```css
.fp-body {
  flex: 1; min-height: 0; display: flex;
}
.fp-side {
  flex: none;
  width: 120px; /* 默认一列：96px 缩略图 + 左右 12px padding */
  max-width: 50vw;
  overflow-y: auto;
  border-right: 1px solid #222;
  padding: 8px 12px;
  position: relative;
}
.fp-side-handle {
  position: absolute;
  top: 0; bottom: 0; right: 0;
  width: 6px; /* 热区 */
  cursor: col-resize;
  touch-action: none;
  z-index: 2;
}
.fp-side-handle::after {
  content: "";
  position: absolute;
  top: 0; bottom: 0; right: 2px;
  width: 2px;
  background: #444;
}
.fp-side-handle:hover::after,
.fp-side-handle:focus-visible::after,
.fp-side-handle.active::after {
  background: #3b82f6;
}
.fp-side-handle:focus-visible { outline: none; }
```

把 `.fp-stage` 规则补上 min-width（其余属性保留）：

```css
.fp-stage {
  flex: 1; min-width: 0;
  display: flex; align-items: center; justify-content: center;
  overflow: hidden; position: relative;
}
```

在 `.fp-strip-toggle { margin-left: auto; }` 附近改为三栏配套：

```css
.fp-side-toggle { margin-right: auto; }
.fp-strip-toggle { margin-left: auto; }
.fp-controls-center {
  display: flex; gap: 16px; align-items: center;
}
.fp-side-toggle.active,
.fp-strip-toggle.active {
  border-color: #3b82f6;
}
```

（删除原单独的 `.fp-strip-toggle { margin-left: auto; }` 一行，由上面的合并规则取代。）

- [ ] **Step 8: 跑 filter-preview 测试确认全绿**

Run: `cd frontend && pnpm test filter-preview`
Expected: 12 个测试全部 PASS（原 8 + 新 4）。

- [ ] **Step 9: 全量测试 + 构建**

Run: `cd frontend && pnpm test && pnpm build`
Expected: 全部 PASS（resize 5 个、filter-preview 12 个；总数在 366 基线上净增
1 个 resize + 4 个视图 = 371），vue-tsc 无报错、build 成功。

- [ ] **Step 10: Commit**

```bash
git add frontend/src/views/FilterPreviewView.vue frontend/src/tests/filter-preview-view.spec.ts
git commit -m "feat(lut): add left-side filter panel with resizable width"
```

## 手动验证清单

1. 工具栏左右两个三角按钮对称，中间操作组居中；点 ◀ 滤镜后侧栏从左出现、底部条消失，点 ▼ 滤镜反之。
2. 侧栏默认一列宽；拖右缘手柄实时变宽（最多半屏）、变窄到一列停住；触屏不滚页面。
3. 键盘聚焦侧栏手柄后 →/← 步进、Home/End 到极值；底部条手柄原键盘行为不受影响。
4. 侧栏挤压舞台，画布在剩余空间重新居中且不裁剪；切换 LUT、强度、下载功能正常。
5. 刷新页面回到默认（底部条开、侧栏关、宽度重置）。

## Self-Review 结论

- **Spec coverage**：§1 三栏（Task 3 Step 5/7，右按钮 data-test 与文案保留）；§2 fp-body 横向 flex + 挤压（Step 4/7，stage min-width:0）；§3 互斥函数（Step 3 toggleSide/toggleStrip，测试覆盖双向切换）；§4 宽度状态/实测最小/50vw/竖手柄/键盘 ARIA（Step 3/4/7，4 个测试）；§5 LutGroupList 去重（Task 2，底部条与侧栏同一组件）；边界表的空分组回退 120、倒挂钳制、触屏、尺寸独立保留均有实现对应。无遗漏。
- **Placeholder scan**：无 TBD/TODO；三段模板与 CSS 给出完整可粘贴代码和精确 old/new 锚点；命令与用例数（366→371）具体。
- **Type consistency**：`draggedWidth/clampHeight/RESIZE_STEP` 跨任务签名一致；侧栏状态 `sideOpen/sideWidth/sideMin/sideMax/sideStyle/sideAriaNow/sideDragging` 在模板、脚本、测试中命名统一；LutGroupList 的 props/emit 与两处消费方逐字匹配；`data-test="side-toggle"`/`fp-side-handle`/`fp-side` 选择器三处一致。
