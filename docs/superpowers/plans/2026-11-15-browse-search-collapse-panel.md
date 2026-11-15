# 图库页搜索折叠面板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 图库页工具栏新增搜索开关按钮，把起止日期、搜索框、整个 root 选框收进默认折叠的面板，带搜索/日期条件进入时自动展开。

**Architecture:** 纯前端单视图改动。SearchBox 与 DateRangeFilter 两个现成组件整体移入 BrowseView 工具栏下方的 `v-if` 面板，props/事件逐字不变；面板开关为组件内 ref，初始化与 watcher 依据 URL 中的 q/date 条件自动展开，条件权威仍在 URL query。

**Tech Stack:** Vue 3 `<script setup>` + UnoCSS + vitest/@vue/test-utils（pnpm）

## Global Constraints

- 面板 id 固定为 `search-panel`；按钮 aria-label 在「展开搜索」/「收起搜索」间切换，带 `aria-expanded` 与 `aria-controls="search-panel"`。
- 自动展开条件：URL 存在 `q`（searchQ）或 `date_from`/`date_to`（hasDate）；`scope=all` 不计入。
- 折叠只切换显隐，不得清除任何 URL query；开关状态不进 URL、不写 localStorage。
- SearchBox、DateRangeFilter、SceneFilter 三个组件零改动；后端零改动。
- 只本地 commit，不 push（用户另有手动推送约定）。
- 测试命令：`cd frontend && pnpm test browse-search`（过滤）；全量 `cd frontend && pnpm test && pnpm build`

---

### Task 1: 搜索折叠面板（TDD）

**Files:**

- Modify: `frontend/src/tests/browse-search.spec.ts`（新增 4 用例，1 个既有用例加展开步骤）
- Modify: `frontend/src/views/BrowseView.vue`（script 状态 + 模板按钮/面板）
- Modify: `docs/superpowers/specs/2026-11-15-browse-search-collapse-panel-design.md`（回修用例计数）

**Interfaces:**

- Consumes: 现有 `searchQ: ComputedRef<string>`、`hasDate: ComputedRef<boolean>`、`scopeAll`、`path` 与事件处理 `onSearchQuery`/`onScopeAll`/`onDateFrom`/`onDateTo`（均为 BrowseView 现有成员）；SearchBox props `modelValue/scopeAll/isRoot`，DateRangeFilter props `dateFrom/dateTo`。
- Produces: `hasSearchCondition: ComputedRef<boolean>`、`searchPanelOpen: Ref<boolean>`；DOM 节点 `#search-panel` 与开关按钮。

- [ ] **Step 1: 写失败测试——新增 4 个折叠面板用例**

在 `frontend/src/tests/browse-search.spec.ts` 的 `describe` 块内、最后一个 `it(...)` 之后追加：

```ts
  it("无搜索条件时搜索面板默认折叠", async () => {
    const { w } = await mountAt("/galleries/1/r/1")
    expect(w.find("#search-panel").exists()).toBe(false)
    expect(w.find('input[aria-label="搜索"]').exists()).toBe(false)
    expect(w.find('input[aria-label="起始日期"]').exists()).toBe(false)
    const btn = w.get('button[aria-label="展开搜索"]')
    expect(btn.attributes("aria-expanded")).toBe("false")
    expect(btn.attributes("aria-controls")).toBe("search-panel")
  })

  it("点击搜索按钮展开面板，再次点击折叠", async () => {
    const { w } = await mountAt("/galleries/1/r/1")
    await w.get('button[aria-label="展开搜索"]').trigger("click")
    await flushPromises()
    expect(w.find("#search-panel").exists()).toBe(true)
    expect(w.find('input[aria-label="搜索"]').exists()).toBe(true)
    expect(w.findAll('input[type="date"]').length).toBe(2)
    expect(w.get('button[aria-label="收起搜索"]').attributes("aria-expanded")).toBe("true")

    await w.get('button[aria-label="收起搜索"]').trigger("click")
    await flushPromises()
    expect(w.find("#search-panel").exists()).toBe(false)
    expect(w.find('input[aria-label="搜索"]').exists()).toBe(false)
  })

  it("带 q 进入时面板自动展开并回显搜索词", async () => {
    const { w } = await mountAt("/galleries/1/r/1?q=abc")
    expect(w.find("#search-panel").exists()).toBe(true)
    expect((w.get('input[aria-label="搜索"]').element as HTMLInputElement).value).toBe("abc")
  })

  it("带日期条件进入时面板自动展开", async () => {
    const { w } = await mountAt("/galleries/1/r/1?date_from=2024-01-01")
    expect(w.find("#search-panel").exists()).toBe(true)
    expect((w.get('input[aria-label="起始日期"]').element as HTMLInputElement).value)
      .toBe("2024-01-01")
  })
```

- [ ] **Step 2: 调整 1 个既有用例（无 query 挂载后操作搜索框）**

同一文件中，用例「输入搜索词：防抖后写入路由 query 并进入搜索态」的首行
`const { w, router } = await mountAt("/galleries/1/r/1")` 之后插入展开步骤：

```ts
    await w.get('button[aria-label="展开搜索"]').trigger("click")
    await flushPromises()
```

其余既有用例无需改动：挂载 URL 带 `q` 的用例（scope=all、改搜索词、清除搜索、
仅切 root 等）由自动展开机制保证面板已开；不操作面板控件的用例不受影响。

- [ ] **Step 3: 跑测试确认失败**

Run:

```bash
cd frontend && pnpm test browse-search
```

Expected: 4 个新用例 FAIL（找不到 `#search-panel`/展开按钮），既有用例仍 PASS。

- [ ] **Step 4: script 增加面板状态**

在 `frontend/src/views/BrowseView.vue` 中，找到现有定义：

```ts
const hasDate = computed(() => dateFrom.value !== "" || dateTo.value !== "")
```

在其下方插入：

```ts
/** URL 中存在搜索词或日期条件（scope 不算：它只能由面板内勾选产生）。 */
const hasSearchCondition = computed(
  () => Boolean(searchQ.value) || hasDate.value,
)
/** 挂载时按 URL 条件初始化：带条件进入自动展开，否则默认折叠。 */
const searchPanelOpen = ref(hasSearchCondition.value)
// 条件从无到有（输入搜索词、选日期、前进后退到带条件路由）自动展开；
// 条件清空或手动折叠都不强制关闭，用户可自由开关。
watch(hasSearchCondition, (v) => {
  if (v) searchPanelOpen.value = true
})
```

（`computed`/`ref`/`watch` 均已在该文件现有 import 中。）

- [ ] **Step 5: 工具栏右侧组最前面加搜索开关按钮**

在模板工具栏的 `<div class="ml-auto flex flex-wrap items-center gap-1.5">`
内、`<SceneFilter` 之前插入：

```vue
          <button type="button"
                  class="flex min-h-11 min-w-11 items-center justify-center rounded px-1.5 py-1"
                  :class="(searchPanelOpen || hasSearchCondition)
                          ? 'bg-surface-3 text-ink'
                          : 'text-ink-2 hover:text-ink'"
                  :title="searchPanelOpen ? '收起搜索' : '展开搜索'"
                  :aria-label="searchPanelOpen ? '收起搜索' : '展开搜索'"
                  :aria-expanded="searchPanelOpen"
                  aria-controls="search-panel"
                  @click="searchPanelOpen = !searchPanelOpen">
            <!-- 放大镜（feather search，16px） -->
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2" stroke-linecap="round"
                 stroke-linejoin="round" aria-hidden="true">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </button>
```

- [ ] **Step 6: 把 DateRangeFilter 与 SearchBox 移入折叠面板**

先删除工具栏 `ml-auto` div 内现有的这两段：

```vue
          <DateRangeFilter
            :date-from="dateFrom"
            :date-to="dateTo"
            @update:date-from="onDateFrom"
            @update:date-to="onDateTo"
          />
          <SearchBox
            :model-value="searchQ"
            :scope-all="scopeAll"
            :is-root="path === ''"
            @update:model-value="onSearchQuery"
            @update:scope-all="onScopeAll"
          />
```

然后在工具栏 div 的闭合 `</div>` 之后、`<template v-if="!searchQ">` 之前插入：

```vue
      <!-- 搜索折叠面板：默认收起；URL 带 q/日期条件时自动展开 -->
      <div v-if="searchPanelOpen"
           id="search-panel"
           class="mb-2 flex flex-wrap items-center gap-2 rounded bg-surface-2/60 p-2">
        <DateRangeFilter
          :date-from="dateFrom"
          :date-to="dateTo"
          @update:date-from="onDateFrom"
          @update:date-to="onDateTo"
        />
        <SearchBox
          :model-value="searchQ"
          :scope-all="scopeAll"
          :is-root="path === ''"
          @update:model-value="onSearchQuery"
          @update:scope-all="onScopeAll"
        />
      </div>
```

- [ ] **Step 7: 跑 browse-search 测试确认全绿**

Run:

```bash
cd frontend && pnpm test browse-search
```

Expected: 该文件全部用例 PASS（原有用例 + 4 个新用例）。

- [ ] **Step 8: 回修 spec 的用例计数**

把 `docs/superpowers/specs/2026-11-15-browse-search-collapse-panel-design.md`
中「既有用例调整（5 个操作面板内控件的用例……）」整段替换为：

```markdown
既有用例调整（1 个）：「输入搜索词：防抖后写入路由 query 并进入搜索态」
挂载在无 query 路由、面板默认折叠，需在操作前先点击「展开搜索」按钮。
其余挂载 URL 带 `q` 的用例（scope=all、改搜索词、清除搜索、仅切 root 等）
由自动展开机制保证面板已开，无需改动；不操作面板控件的用例不受影响。
```

- [ ] **Step 9: 全量前端测试 + 类型检查/构建**

Run:

```bash
cd frontend && pnpm test && pnpm build
```

Expected: 全部测试文件 PASS（在 356 基线上净增 4 个用例 = 360），
`vue-tsc --noEmit` 无报错、`vite build` 成功。

- [ ] **Step 10: Commit**

```bash
git add frontend/src/views/BrowseView.vue frontend/src/tests/browse-search.spec.ts docs/superpowers/specs/2026-11-15-browse-search-collapse-panel-design.md
git commit -m "feat(browse): collapsible search panel with auto-open on active filters"
```

## Self-Review 结论

- **Spec coverage**：spec §1 开关按钮（Step 5，含 aria 三属性与激活态条件）；§2 面板与组件迁移（Step 6，props/事件逐字保留，SceneFilter 不动）；§3 状态规则（Step 4，初始化 + watcher，scope 不计入）；§4 无新数据流（事件处理函数全部复用，Step 6 原样绑定）；边界表的 root 隐藏勾选、窄屏 wrap、带链接自动展开分别由 SearchBox 现成逻辑、flex-wrap、Step 4 初始化覆盖；测试节 4 个新用例（Step 1）与既有用例调整（Step 2，按实际核对修正为 1 个并在 Step 8 回修 spec）。无遗漏。
- **Placeholder scan**：无 TBD/TODO；模板/脚本/测试均给出完整代码与精确锚点；命令与预期（含 356→360 用例数）具体。
- **Type consistency**：`searchPanelOpen`/`hasSearchCondition` 命名在脚本、模板、测试中逐字一致；按钮 aria-label 两态文案在实现与测试选择器中一致；`#search-panel` 与 aria-controls 匹配；迁移组件的 props/事件名与现有 BrowseView 绑定逐字相同。
