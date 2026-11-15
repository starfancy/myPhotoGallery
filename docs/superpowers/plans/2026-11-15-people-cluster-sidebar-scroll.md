# 人物页左栏独立滚动 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让人物页左侧人物簇列表在内容超高时出现独立垂直滚动条，并在右侧照片区滚动时吸顶保持可见。

**Architecture:** 纯前端单元素 CSS class 改动：给 [PersonClusterView.vue](../../../frontend/src/views/PersonClusterView.vue) 的左侧 `<aside>` 增加 `overflow-y-auto`、`sticky` 吸顶与响应式 `max-height`，复用 AdminAudit 已验证的头部高度偏移基准（移动 69px / 桌面 53px）。不动任何组件逻辑、接口与右侧滚动方式。

**Tech Stack:** Vue 3 `<script setup>` + UnoCSS 原子类 + vue-tsc / vite / vitest（pnpm）

## Global Constraints

- 仅修改 `frontend/src/views/PersonClusterView.vue` 中左侧 `<aside>` 一个元素的 class，不改模板结构、脚本逻辑、接口调用。
- 吸顶偏移基准：移动端头部高 69px、桌面端（md 断点）53px（来源 [AdminAudit.vue:9](../../../frontend/src/views/AdminAudit.vue#L9) 的 `sticky top-[69px] md:top-[53px]`）；main 上内边距 12px（`p-3`）。
- 最终 class 必须为：`overflow-y-auto sticky top-[81px] md:top-[65px] max-h-[calc(100vh-93px)] md:max-h-[calc(100vh-77px)]`，与原有 `w-56 shrink-0 space-y-1` 共存。
- 不新增 vitest 用例（jsdom 不做真实布局，无法断言滚动条；spec 已明确）。
- 不引入新依赖、不加自定义滚动条样式、不做虚拟滚动。
- 只本地 commit，不 push（用户另有手动推送约定）。

---

### Task 1: 左侧簇列表 aside 独立滚动 + 吸顶

**Files:**

- Modify: `frontend/src/views/PersonClusterView.vue:98`（左侧 `<aside>` 开标签，当前为 `<aside class="w-56 shrink-0 space-y-1">`）

**Interfaces:**

- Consumes: 无新接口；仅消费现有 AppHeader 高度与 `#main-content` 的 `p-3` 布局事实。
- Produces: 无代码接口变更；DOM 结构与响应式数据不变，现有页面行为（选簇、重命名、懒加载图片）不受影响。

说明：本任务为纯 CSS 改动，TDD 的"先写失败测试"不适用——vitest/jsdom 不计算布局，无法对滚动条/吸顶写有意义的断言（spec「测试」节已明确）。验证依赖类型检查、构建、现有测试全绿与浏览器手动确认。

- [ ] **Step 1: 修改 aside 的 class**

在 `frontend/src/views/PersonClusterView.vue` 中，把第 98 行：

```html
        <aside class="w-56 shrink-0 space-y-1">
```

改为：

```html
        <aside
          class="w-56 shrink-0 space-y-1 overflow-y-auto
                 sticky top-[81px] md:top-[65px]
                 max-h-[calc(100vh-93px)] md:max-h-[calc(100vh-77px)]"
        >
```

模板其余部分（v-for 按钮、头像、名称、计数）与 `<script setup>` 一律不动。

- [ ] **Step 2: 类型检查 + 构建**

Run:

```bash
cd frontend && pnpm build
```

Expected: `vue-tsc --noEmit` 无报错，`vite build` 成功产出 `dist/`，退出码 0。

- [ ] **Step 3: 跑现有前端测试套件确认无回归**

Run:

```bash
cd frontend && pnpm test
```

Expected: 全部既有测试 PASS（改动前为全绿基线；本改动不涉及任何测试覆盖的逻辑，数量与结果应与改动前一致），无 FAIL。

- [ ] **Step 4: 浏览器手动验证（真实库，需足够多人物簇）**

启动前端（`cd frontend && pnpm dev`），登录后进入「人物」页（`/people`），逐项确认：

1. **少簇情况**：簇列表总高度不超过视口可用高度时，左侧不出现滚动条，排版与改动前一致。
2. **多簇情况**：簇数量足够多时，左侧 `aside` 内部出现独立垂直滚动条，可单独滚到底部选簇；页面整体高度由右侧照片区决定，左栏不再把页面撑高。
3. **吸顶**：右侧照片区很长、向下滚动页面时，左栏停在 AppHeader 正下方（间距 12px），不被头部遮挡、无横向位移。
4. **响应式**：在窄屏（< md，768px）与桌面宽度下分别重复 2–3，偏移均正确（81px / 65px），底部不贴死机视口边缘。
5. **双主题**：切换系统浅/深配色，滚动条与选中态（`bg-primary/10`）显示正常。
6. **交互不回归**：滚动后点击某个簇，右侧照常加载该簇照片；「重命名」保存后列表刷新、选中态正常。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/PersonClusterView.vue
git commit -m "feat(people): independent scroll and sticky for cluster sidebar"
```

### Task 2: 全局 color-scheme 声明，让原生滚动条适配深色模式

**Files:**

- Modify: `frontend/src/styles/base.css`（`:root` 浅色块与 `@media (prefers-color-scheme: dark)` 块）

**Interfaces:**

- Consumes: 现有主题机制——深色模式完全由 `prefers-color-scheme` 媒体查询驱动，无手动主题开关。
- Produces: UA 原生控件（滚动条等）按系统主题渲染；不产生任何 CSS 变量或组件接口变更。

背景：Task 1 手测发现深色模式下滚动条仍为 UA 默认浅色。根因是原生滚动条不消费
颜色令牌、只认 `color-scheme`，而项目从未声明它（全站既有滚动区同样受影响）。
纯 CSS 改动，jsdom 不渲染 UA 控件，无法写自动化断言，验证靠构建 + 手动确认。

- [ ] **Step 1: 在 base.css 两处声明 color-scheme**

在 `frontend/src/styles/base.css` 的浅色 `:root {` 之后、第一个颜色令牌之前插入：

```css
  /* 告知 UA 本页支持的配色方案：原生滚动条等 UA 控件不消费下方颜色
     令牌，只有声明 color-scheme 后，深色模式才会渲染深色原生控件。 */
  color-scheme: light;
```

在 `@media (prefers-color-scheme: dark) {` 内的 `:root {` 之后、第一个令牌之前插入：

```css
    color-scheme: dark;
```

- [ ] **Step 2: 类型检查 + 构建**

Run:

```bash
cd frontend && pnpm build
```

Expected: `vue-tsc --noEmit` 无报错，`vite build` 成功，退出码 0。

- [ ] **Step 3: 跑现有前端测试套件确认无回归**

Run:

```bash
cd frontend && pnpm test
```

Expected: 53 个测试文件、348 个用例全部 PASS。

- [ ] **Step 4: 浏览器手动验证**

系统切到深色配色后，在 `/people` 页确认：左侧簇列表滚动条渲染为深色、与页面
底色协调；顺手确认其他滚动区（如管理页用户表单的下拉列表、目录选择器）滚动条
同样变深。再切回浅色配色：滚动条恢复浅色，所有页面视觉与改动前一致，
按钮/输入框等控件颜色无变化（作者声明的 `bg-*` 优先于 UA 默认）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles/base.css
git commit -m "fix(theme): declare color-scheme so native scrollbars follow dark mode"
```

## Self-Review 结论

- **Spec coverage**：spec「设计」节的三项 class 职责（`overflow-y-auto` / sticky 偏移 / 响应式 max-height）全部落在 Task 1 Step 1 的完整代码中；spec「边界与行为」表的五种情况由 Step 4 的手动验证逐项覆盖；spec「测试」节的三项验证手段（vue-tsc+构建、vitest 全绿、浏览器手动）对应 Step 2/3/4。无遗漏。
- **Placeholder scan**：无 TBD/TODO；唯一代码步骤给出完整前后对照与最终 class 字面量；验证命令与预期输出具体。
- **Type consistency**：无类型/接口变更；class 字面量与 spec 中数字（81/65、93/77）逐字一致。
