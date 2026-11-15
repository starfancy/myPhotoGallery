# 图库页搜索折叠面板 — 设计

日期：2026-11-15
状态：已批准（方案 A：本地 ref 折叠面板 + 条件自动展开）

## 背景与问题

图库浏览页 [BrowseView.vue](../../../frontend/src/views/BrowseView.vue)
工具栏右侧常驻三个搜索相关控件：[DateRangeFilter](../../../frontend/src/components/DateRangeFilter.vue)
（起止日期）、[SearchBox](../../../frontend/src/components/SearchBox.vue)
（搜索框 + 「整个 root」勾选），加上 SceneFilter 等，工具栏元素越来越多，
日常浏览时搜索控件持续占位、视觉嘈杂。

用户要求：工具栏增加一个搜索按钮，点击后展开包含「起止日期、搜索框、整个 root
选框」的搜索区；未点击时三部分全部折叠；展开后再次点击按钮折叠。

## 目标

- 搜索三要素（起止日期、搜索框、整个 root 选框）默认折叠，由一个放大镜按钮
  控制显隐。
- 带生效条件进入页面（刷新、前进/后退、打开带参数链接）时面板自动展开，
  用户能看到当前生效的搜索/日期条件。
- 折叠只影响显隐，不清除任何条件；条件的唯一权威仍是 URL query。
- 复用现有 SearchBox、DateRangeFilter 组件与其全部事件/防抖/URL 同步逻辑，
  组件零改动。

## 非目标（明确不做）

- 不折叠 SceneFilter（场景筛选），它留在工具栏原位。
- 不把面板开关写进 URL query、不做 localStorage 持久化。
- 不改搜索/日期/scope 的请求参数、防抖时间与后端接口。
- 不改空文件夹/空结果下工具栏整体不渲染的现有行为（无图无文件夹无条件时
  搜索按钮同样不出现）。
- 不做面板展开/折叠动画（YAGNI，v-if 直接显隐）。

## 现有机制（复用点）

- SearchBox 已封装搜索输入框（300ms 防抖 emit `update:modelValue`、回车立即
  触发、清除按钮）与「整个 root」勾选（emit `update:scopeAll`，`isRoot` 时
  自动隐藏勾选）。
- DateRangeFilter 封装两个原生 date input（YYYY-MM-DD）与清除按钮，emit
  `update:dateFrom`/`update:dateTo`。
- BrowseView 已把三者状态绑定到 URL：`q`（searchQ）、`scope=all`（scopeAll）、
  `date_from`/`date_to`（dateFrom/dateTo，hasDate computed）；
  `queryWithoutImage()` 统一透传 query，面板显隐不需要新参数。
- 工具栏按钮的现成样式范式：`min-h-11 min-w-11` 圆角、激活态
  `bg-surface-3 text-ink`、非激活 `text-ink-2 hover:text-ink`、`aria-pressed`
  类开关按钮（文件名/场景标签开关同款）。

## 设计

### 1. 工具栏新增搜索开关按钮

在工具栏右侧控件组（`ml-auto` 的 div 内）**最前面**，即 SceneFilter 之前，
新增一个按钮：

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
  <!-- 放大镜图标（feather search，16px） -->
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
       stroke="currentColor" stroke-width="2" stroke-linecap="round"
       stroke-linejoin="round" aria-hidden="true">
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
</button>
```

激活态同时覆盖「面板打开」与「条件生效中但面板被手动折叠」两种情况，
折叠状态下用户仍能一眼看出有搜索/日期条件在生效。

### 2. 折叠面板

在工具栏 div 之后、`<template v-if="!searchQ">` 之前，新增面板行：

```vue
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

- 工具栏中原有的 DateRangeFilter 与 SearchBox 两个标签**移动**到面板内，
  绑定的 props/事件逐字不变；工具栏右侧只留新按钮 + SceneFilter +
  GridLayoutSwitch + 文件名/场景标签开关。
- `flex-wrap` 使窄屏自动换行；浅一层的 `bg-surface-2/60` 容器把搜索区与
  内容区视觉分组。
- 面板 `v-if` 卸载/挂载：SearchBox 的输入文字由 `modelValue`（URL 的 q）
  回显，折叠不会丢失已提交的搜索词；未防抖的临打文字随卸载丢弃，与
  「折叠=收起搜索区」的直觉一致。

### 3. 展开状态规则

BrowseView script 中新增：

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

行为矩阵：

| 进入/操作 | 面板状态 |
| --- | --- |
| 普通目录，无任何条件 | 折叠（默认） |
| URL 带 `q` / `date_from` / `date_to` 进入（刷新、分享链接、前进后退） | 自动展开 |
| 面板内输入搜索词/选日期 | 条件生效，面板保持展开 |
| 条件生效中手动点按钮折叠 | 折叠但按钮高亮，条件仍生效 |
| 清除全部条件 | 按钮取消高亮；面板保持当前开关状态（不自动关） |
| 下钻/上跳文件夹 | 组件复用不重建，面板开关状态保持；query 中的条件也保持（现有逻辑） |

### 4. 数据流

无新数据流。面板内控件的 emit 仍走现有处理函数
（onSearchQuery/onScopeAll/onDateFrom/onDateTo）写入 router query，
SearchResults 与普通浏览的请求逻辑完全不变；`scope=all` 不参与
hasSearchCondition，因此单独勾选不会触发展开逻辑变化（勾选时面板本就开着）。

## 边界与错误处理

| 情况 | 行为 |
| --- | --- |
| root 根目录 | SearchBox 既有逻辑隐藏「整个 root」勾选，面板只剩日期 + 搜索框 |
| 窄屏 | 面板内 flex-wrap 换行，不溢出横向滚动 |
| 面板折叠时路由带上 `?q=`（外部链接） | watcher/初始化判定有条件，自动展开并显示搜索结果 |
| 搜索结果态（searchQ 非空） | 面板自动展开，用户可折叠后继续浏览结果，工具栏按钮保持高亮 |
| 键盘/读屏 | 按钮有 aria-expanded/aria-controls，面板 id 匹配；控件卸载后 Tab 序列自然移除 |

## 测试

文件：[browse-search.spec.ts](../../../frontend/src/tests/browse-search.spec.ts)
（mountAt 挂载的是真实 BrowseView，SearchBox/DateRangeFilter 均为真实组件）。

新增用例：

1. **默认折叠**：挂载到无 query 的目录路由，`input[aria-label="搜索"]`
   不存在、`#search-panel` 不存在，搜索按钮 `aria-expanded="false"`。
2. **手动展开/折叠**：点击「展开搜索」按钮后搜索 input 与两个 date input
   出现、`aria-expanded="true"`；再点一次后全部消失。
3. **带 q 进入自动展开**：挂载到 `?q=旅行`，面板存在且搜索 input 回显
   「旅行」。
4. **带日期进入自动展开**：挂载到 `?date_from=2024-01-01`，面板存在、
   起始日期 input 值为 2024-01-01。

既有用例调整（1 个）：「输入搜索词：防抖后写入路由 query 并进入搜索态」
挂载在无 query 路由、面板默认折叠，需在操作前先点击「展开搜索」按钮。
其余挂载 URL 带 `q` 的用例（scope=all、改搜索词、清除搜索、仅切 root 等）
由自动展开机制保证面板已开，无需改动；不操作面板控件的用例不受影响。

search-box.spec.ts 为组件级直测，不经过 BrowseView，无需改动。
全量 `pnpm test && pnpm build` 通过；后端零改动。

## YAGNI 记录

曾评估的另两个方案：

- **方案 B（开关写进 URL query，如 search_panel=1）**：可分享展开态，
  但开关是纯界面偏好，污染查询参数，还要在 queryWithoutImage 等多处
  透传/剔除逻辑中特殊处理，收益不抵复杂度，排除。
- **方案 C（v-show 常挂载，仅 CSS 隐藏）**：能保留未防抖的临打文字，
  但面板 DOM 常驻、读屏 Tab 序列需额外 inert 处理，而 SearchBox 文字
  本就由 URL prop 回显，无实际收益，排除。
