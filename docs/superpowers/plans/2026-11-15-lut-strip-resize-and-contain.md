# LUT 缩略图完整显示与滤镜条可调高度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** LUT 预览页竖版缩略图改为等比完整显示；滤镜条增加可拖拽/键盘调节高度的手柄，钳制在一行高度与 50vh 之间。

**Architecture:** 几何计算抽到纯函数模块 `lib/resize.ts` 单测覆盖；FilterPreviewView 只做 DOM 事件与测量的薄接线，手柄用 Pointer Events + ARIA separator；缩略图填充方式由 cover 改 contain，窗格尺寸不变。

**Tech Stack:** Vue 3 `<script setup>` + 原生 CSS/Pointer Events + vitest/@vue/test-utils（pnpm）

## Global Constraints

- 缩略图窗格保持 88×58、列宽保持 96px，只把 `object-fit: cover` 改为 `contain`。
- 高度钳制：最小 = 第一个 `.fp-group` 实测 offsetHeight + strip 上下 padding（无分组回退 120px）；最大 = `window.innerHeight / 2`。
- 键盘步进常量 `RESIZE_STEP = 16`；↑ 增高、↓ 降低、Home 最小、End 最大。
- 显式高度内联样式必须同时给 `height` 与 `maxHeight: "50vh"`，否则会被 CSS 默认 `max-height:280px` 钳回去。
- 高度不持久化、不进 URL；收起/展开按钮行为不变；后端零改动。
- 只本地 commit，不 push。
- 测试命令：`cd frontend && pnpm test resize` / `pnpm test filter-preview`；全量 `pnpm test && pnpm build`

---

### Task 1: 纯函数模块 resize.ts（TDD）

**Files:**

- Create: `frontend/src/lib/resize.ts`
- Test: `frontend/src/tests/resize.spec.ts`

**Interfaces:**

- Consumes: 无依赖。
- Produces: `RESIZE_STEP: number`（16）、`clampHeight(h, min, max): number`、`draggedHeight(startHeight, startY, currentY): number`、`steppedHeight(current, dir: 1 | -1, min, max): number`，供 Task 2 导入。

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/tests/resize.spec.ts`：

```ts
import { describe, expect, it } from "vitest"
import {
  RESIZE_STEP,
  clampHeight,
  draggedHeight,
  steppedHeight,
} from "../lib/resize"

describe("resize helpers", () => {
  it("clampHeight：区间外钳制、区间内原样返回", () => {
    expect(clampHeight(50, 100, 400)).toBe(100)
    expect(clampHeight(500, 100, 400)).toBe(400)
    expect(clampHeight(250, 100, 400)).toBe(250)
  })

  it("clampHeight：min>max 倒挂时以较小者为下界、较大者为上界", () => {
    expect(clampHeight(10, 400, 130)).toBe(130)
    expect(clampHeight(500, 400, 130)).toBe(400)
  })

  it("draggedHeight：指针上移增高、下移缩小", () => {
    // 手柄在区域上沿：currentY 比 startY 小 20（上移）→ 高度 +20
    expect(draggedHeight(200, 300, 280)).toBe(220)
    // 下移 30 → 高度 -30
    expect(draggedHeight(200, 300, 330)).toBe(170)
  })

  it("steppedHeight：按 RESIZE_STEP 步进并在边界钳制", () => {
    expect(steppedHeight(200, 1, 130, 400)).toBe(200 + RESIZE_STEP)
    expect(steppedHeight(200, -1, 130, 400)).toBe(200 - RESIZE_STEP)
    expect(steppedHeight(135, -1, 130, 400)).toBe(130)
    expect(steppedHeight(395, 1, 130, 400)).toBe(400)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
cd frontend && pnpm test resize
```

Expected: FAIL（模块不存在，无法解析 `../lib/resize`）。

- [ ] **Step 3: 实现 resize.ts**

创建 `frontend/src/lib/resize.ts`：

```ts
/** 滤镜条高度键盘调节的步进像素。 */
export const RESIZE_STEP = 16

/** 把高度钳进 [min, max]；min/max 倒挂时以较小者为下界。 */
export function clampHeight(h: number, min: number, max: number): number {
  const lo = Math.min(min, max)
  return Math.min(Math.max(h, lo), Math.max(min, max))
}

/** 拖拽数学：手柄在区域上沿，指针上移（currentY < startY）时区域增高。 */
export function draggedHeight(
  startHeight: number,
  startY: number,
  currentY: number,
): number {
  return startHeight + (startY - currentY)
}

/** 键盘步进后再钳制。dir：+1 增高（↑）、-1 降低（↓）。 */
export function steppedHeight(
  current: number,
  dir: 1 | -1,
  min: number,
  max: number,
): number {
  return clampHeight(current + dir * RESIZE_STEP, min, max)
}
```

- [ ] **Step 4: 跑测试确认通过**

Run:

```bash
cd frontend && pnpm test resize
```

Expected: 4 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/resize.ts frontend/src/tests/resize.spec.ts
git commit -m "feat(lut): add strip height clamp/drag helper functions"
```

---

### Task 2: FilterPreviewView 接线（contain + 手柄 + 视图测试，TDD）

**Files:**

- Modify: `frontend/src/tests/filter-preview-view.spec.ts`（新增 1 个键盘/ARIA 用例）
- Modify: `frontend/src/views/FilterPreviewView.vue`（模板、script、CSS）

**Interfaces:**

- Consumes: Task 1 的 `clampHeight/draggedHeight/steppedHeight`；现有 `stripOpen` ref 与 `.fp-strip`/`.fp-group` DOM。
- Produces: `.fp-resize-handle`（role=separator）、`stripEl`/`stripHeight`/`minHeight`/`dragging` 等视图内状态，无对外接口。

- [ ] **Step 1: 写失败测试——手柄 ARIA 与键盘调节**

在 `frontend/src/tests/filter-preview-view.spec.ts` 的 `describe` 块内、最后一个 `it(...)` 之后追加：

```ts
  it("滤镜条高度手柄：ARIA 语义齐全，键盘可调高度并钳制", async () => {
    vi.stubGlobal("innerHeight", 800) // max = 400
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ height: 200 } as DOMRect)
    const csSpy = vi
      .spyOn(window, "getComputedStyle")
      .mockReturnValue({ paddingTop: "8px", paddingBottom: "12px" } as CSSStyleDeclaration)
    try {
      const w = mount(FilterPreviewView)
      await flushPromises()
      // 最小高度 = 组高 110 + 上下 padding 20 = 130
      Object.defineProperty(w.get(".fp-group").element, "offsetHeight", {
        value: 110,
        configurable: true,
      })

      const handle = w.find(".fp-resize-handle")
      expect(handle.exists()).toBe(true)
      expect(handle.attributes("role")).toBe("separator")
      expect(handle.attributes("tabindex")).toBe("0")
      expect(handle.attributes("aria-orientation")).toBe("horizontal")
      expect(handle.attributes("aria-label")).toBe("调节滤镜列表高度")

      const strip = () => w.find("section.fp-strip")

      // ↓：200 - 16 = 184
      await handle.trigger("keydown", { key: "ArrowDown" })
      expect(strip().attributes("style")).toContain("height: 184px")
      expect(handle.attributes("aria-valuenow")).toBe("184")

      // ↑：184 + 16 = 200
      await handle.trigger("keydown", { key: "ArrowUp" })
      expect(strip().attributes("style")).toContain("height: 200px")

      // Home：最小实测值 130
      await handle.trigger("keydown", { key: "Home" })
      expect(strip().attributes("style")).toContain("height: 130px")

      // End：50vh = 400
      await handle.trigger("keydown", { key: "End" })
      expect(strip().attributes("style")).toContain("height: 400px")
      expect(strip().attributes("style")).toContain("max-height: 50vh")
    } finally {
      rectSpy.mockRestore()
      csSpy.mockRestore()
      vi.unstubAllGlobals()
    }
  })
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
cd frontend && pnpm test filter-preview
```

Expected: 新用例 FAIL（找不到 `.fp-resize-handle`），其余 7 个用例 PASS。

- [ ] **Step 3: script 加导入与状态**

把 `frontend/src/views/FilterPreviewView.vue` 的：

```ts
import { onMounted, onUnmounted, ref } from "vue"
```

改为：

```ts
import { computed, onMounted, onUnmounted, ref } from "vue"
```

并在其下一行（现有 vue-router 导入之前或之后均可）加：

```ts
import { clampHeight, draggedHeight, steppedHeight } from "../lib/resize"
```

在 `const stripOpen = ref(true)` 之后插入：

```ts
// ---- 滤镜条可调高度 ----
const stripEl = ref<HTMLElement | null>(null)
/** null = 未手动调节，沿用 CSS 默认 max-height；数字 = 显式像素高度 */
const stripHeight = ref<number | null>(null)
const minHeight = ref<number | null>(null)
const dragging = ref(false)
const maxHeight = computed(() => Math.round(window.innerHeight / 2))
const stripStyle = computed(() =>
  stripHeight.value === null
    ? {}
    : { height: `${stripHeight.value}px`, maxHeight: "50vh" },
)
const ariaNow = computed(() =>
  stripHeight.value === null ? undefined : Math.round(stripHeight.value),
)

/** 首次交互时实测一行（组标题+缩略图行）所需最小高度，只算一次。 */
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

let dragStartY = 0
let dragStartH = 0

function onPointerDown(e: PointerEvent) {
  const min = ensureMin()
  const max = maxHeight.value
  dragStartY = e.clientY
  dragStartH = clampHeight(
    stripHeight.value ?? stripEl.value!.getBoundingClientRect().height,
    min,
    max,
  )
  stripHeight.value = dragStartH
  dragging.value = true
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return
  stripHeight.value = clampHeight(
    draggedHeight(dragStartH, dragStartY, e.clientY),
    ensureMin(),
    maxHeight.value,
  )
}

function onPointerUp(e: PointerEvent) {
  if (!dragging.value) return
  dragging.value = false
  ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
}

function onKeydown(e: KeyboardEvent) {
  const min = ensureMin()
  const max = maxHeight.value
  const cur =
    stripHeight.value ??
    Math.round(stripEl.value!.getBoundingClientRect().height)
  if (e.key === "ArrowUp") {
    stripHeight.value = steppedHeight(cur, 1, min, max)
  } else if (e.key === "ArrowDown") {
    stripHeight.value = steppedHeight(cur, -1, min, max)
  } else if (e.key === "Home") {
    stripHeight.value = min
  } else if (e.key === "End") {
    stripHeight.value = max
  } else {
    return
  }
  e.preventDefault()
}
```

- [ ] **Step 4: 模板加根类、ref、手柄**

把根节点：

```vue
  <div class="fp-page">
```

改为：

```vue
  <div class="fp-page" :class="{ 'is-resizing': dragging }">
```

把滤镜条 section 开标签：

```vue
    <section v-show="stripOpen" class="fp-strip">
```

改为：

```vue
    <section v-show="stripOpen" class="fp-strip" ref="stripEl" :style="stripStyle">
      <div
        class="fp-resize-handle"
        :class="{ active: dragging }"
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
        @keydown="onKeydown"
      ></div>
```

（section 内原有的 `v-for` 分组内容保持不变，位于手柄之后。）

- [ ] **Step 5: CSS——contain、strip 定位、手柄样式**

把：

```css
.fp-strip {
  border-top: 1px solid #222;
  padding: 8px 16px 12px;
  /* 两行缩略图 + 分组标题 + group 间距：约 280px */
  max-height: 280px; overflow-y: auto;
}
```

改为：

```css
.fp-strip {
  position: relative; /* 手柄绝对定位的参照 */
  border-top: 1px solid #222;
  padding: 8px 16px 12px;
  /* 两行缩略图 + 分组标题 + group 间距：约 280px；小屏不超过半屏 */
  max-height: min(280px, 50vh);
  overflow-y: auto;
}
.fp-resize-handle {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 6px; /* 热区 */
  cursor: row-resize;
  touch-action: none; /* 触屏拖动不引发页面滚动 */
  z-index: 2;
}
.fp-resize-handle::after {
  content: "";
  position: absolute;
  left: 0; right: 0; top: 2px;
  height: 2px; /* 视觉线 */
  background: #444;
}
.fp-resize-handle:hover::after,
.fp-resize-handle:focus-visible::after,
.fp-resize-handle.active::after {
  background: #3b82f6;
}
.fp-resize-handle:focus-visible { outline: none; }
/* 拖拽期间禁止选中文本（在根节点切类，避免 :has 兼容问题） */
.fp-page.is-resizing { user-select: none; }
```

再把缩略图规则：

```css
.fp-thumb img {
  width: 88px; height: 58px; object-fit: cover; border-radius: 4px;
  background: #333; display: block;
}
```

改为：

```css
.fp-thumb img {
  width: 88px; height: 58px; object-fit: contain; border-radius: 4px;
  background: #333; display: block;
}
```

- [ ] **Step 6: 跑 filter-preview 测试确认全绿**

Run:

```bash
cd frontend && pnpm test filter-preview
```

Expected: 8 个测试全部 PASS（原 7 + 新 1）。

- [ ] **Step 7: 全量前端测试 + 类型检查/构建**

Run:

```bash
cd frontend && pnpm test && pnpm build
```

Expected: 全部测试 PASS（361 基线上净增 resize 4 个 + 本文件 1 个 = 366），
`vue-tsc --noEmit` 无报错、`vite build` 成功。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/FilterPreviewView.vue frontend/src/tests/filter-preview-view.spec.ts
git commit -m "feat(lut): contain-fit thumbnails and resizable filter strip"
```

## 手动验证清单（jsdom 覆盖不到的部分，交用户浏览器确认）

1. 竖版照片的 LUT 缩略图完整可见、居中不裁剪；横版无明显变化。
2. 鼠标拖滤镜条上沿：实时变高，到一行高度与半屏处停住；触屏拖动不滚页面。
3. 键盘 Tab 到手柄后，↑/↓ 以 16px 步进、Home/End 到极值。
4. 收起滤镜列表后手柄随之隐藏，重新展开保留已调高度；刷新页面回到默认高度。

## Self-Review 结论

- **Spec coverage**：spec §1 contain（Task 2 Step 5）；§2 纯函数三函数 + 常量（Task 1 全覆盖，含倒挂边界）；§3 手柄模板/状态/指针/键盘/ARIA（Task 2 Step 3–4，键盘与 ARIA 有自动化，指针与视觉列入手动清单）；内联 maxHeight 覆盖、getComputedStyle 兜底、is-resizing 类等自查修正点均在步骤中；边界表的无分组回退 120、倒挂钳制、触屏 touch-action、收起联动逐条有对应实现。无遗漏。
- **Placeholder scan**：无 TBD/TODO；所有代码完整可粘贴，锚点为当前文件真实片段；命令与预期（含 361→366 用例数）具体。
- **Type consistency**：`clampHeight/draggedHeight/steppedHeight/RESIZE_STEP` 在两任务间签名逐字一致；`stripHeight/minHeight/dragging/stripEl/stripStyle/ariaNow/maxHeight` 在模板与脚本中命名一致；CSS 类 `.fp-resize-handle`/`.is-resizing` 在模板、样式、测试选择器三处一致。
