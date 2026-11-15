# 人物页位置开关拆分与灯箱路径底部居中 — 设计

日期：2026-11-15
状态：已批准

## 背景与问题

[2026-11-15-people-grid-lightbox-design](2026-11-15-people-grid-lightbox-design.md)
上线后人物页存在两个体验问题：

1. 缩略图的文件名与所在路径由**同一个开关**（`showInfo`）同时控制。实际照片文件名
   多为 `4750c2f4fc09446ca0500ff22f3dae8b.jpg` 这类哈希名，又长又无信息量；用户
   希望关掉文件名、只保留可读的所在路径，单开关做不到。
2. 灯箱里的路径标注（`location-label`）当前渲染在**顶部栏**、跟在文件名右侧，
   长路径挤占顶部空间；希望把它移到**底部居中**，文件名维持原位。

## 目标

- 人物页把单开关拆成两个互相独立的图库式开关：文件名显隐、所在位置显隐，
  各自持久化。
- 灯箱路径标注移到底部居中；文件名标签位置与样式不变。
- 图库普通浏览灯箱零变化（它本来就不显示路径）。

## 非目标（明确不做）

- 不改灯箱文件名标签的位置、样式与注册方式。
- 不移动「在所在文件夹中查看」按钮（留在顶部工具栏）。
- 不改 PhotoCell、JustifiedGrid 两个共享组件的 props 与行为。
- 不迁移旧 localStorage 键 `people.grid.showInfo`（同日引入、未发布，本地偏好，
  直接废弃）。
- 后端无改动。

## 现有机制（复用点）

- PhotoCell 已支持两套独立的底部叠加元素：文件名层（`showFilename` prop，
  `.lb-cell-filename`）与角标层（`badge` prop，`.lb-cell-badge`）；二者同时出现时
  角标自动上抬一行（`lb-cell-badge--up`），只有角标时它独占底部渐变叠加层——
  搜索结果缩略图早已用这套机制显示目录。
- 图库页工具栏已有两个同类图标按钮的范式（BrowseView：文件名开关 + 场景标签开关，
  `min-h-11 min-w-11`、激活态 `bg-surface-3 text-ink`、`aria-pressed`）。
- ImageLightbox 的 `location-label` 与「在所在文件夹中查看」按钮只在
  `if (props.locationResolver)` 分支注册（
  [ImageLightbox.vue:747](../../../frontend/src/components/ImageLightbox.vue#L747)）：
  图库普通浏览不传 resolver，天然不渲染路径，无需新增门控。
- PhotoSwipe `ui.registerElement` 支持 `appendTo: "wrapper"` 挂到全屏容器，
  现有缩放比例/拍摄时间两个底部胶囊即此模式，绝对定位 `bottom/right/left` 生效，
  并随灯箱 idle 逻辑自动淡隐。

## 设计

### 1. 人物页：单开关拆成两个独立开关

文件：[PersonClusterView.vue](../../../frontend/src/views/PersonClusterView.vue)。

把现有的 `showInfo`/`SHOW_INFO_KEY` 替换为两个独立状态：

```ts
/** 文件名开关：偏好独立持久化，默认关。 */
const SHOW_FILENAMES_KEY = "people.grid.showFilenames"
const showFilenames = ref(localStorage.getItem(SHOW_FILENAMES_KEY) === "1")
watch(showFilenames, (v) => localStorage.setItem(SHOW_FILENAMES_KEY, v ? "1" : "0"))

/** 所在位置开关：默认关。 */
const SHOW_LOCATION_KEY = "people.grid.showLocation"
const showLocation = ref(localStorage.getItem(SHOW_LOCATION_KEY) === "1")
watch(showLocation, (v) => localStorage.setItem(SHOW_LOCATION_KEY, v ? "1" : "0"))
```

标题行右侧放两个图库式按钮（文件名在前、位置在后，对应图库页
「文件名 → 场景标签」的次序）：

- 文件名按钮：沿用现有「图片卡片 + 底部文字行」SVG，`title`/`aria-label`
  为「缩略图上显示文件名」（与图库页逐字一致），`:aria-pressed="showFilenames"`。
- 位置按钮：文件夹 SVG（复用灯箱「在所在文件夹中查看」的 folder 图标，
  尺寸设为 16px），`title`/`aria-label` 为「缩略图上显示所在位置」，
  `:aria-pressed="showLocation"`。
- 两个按钮样式与现开关一致：`min-h-11 min-w-11` 圆角、激活态
  `bg-surface-3 text-ink`、非激活 `text-ink-2 hover:text-ink`。

网格接线改为：

```vue
<JustifiedGrid
  :items="g.images"
  :show-filename="showFilenames"
  :badge-for="showLocation ? locationText : undefined"
  @open="openLightbox"
  @menu-action="onGridMenuAction"
/>
```

四种显隐组合全部由 PhotoCell 现成逻辑承载：

| 文件名 | 位置 | 缩略图表现 |
| --- | --- | --- |
| 关 | 关 | 纯图片（默认） |
| 开 | 关 | 仅底部文件名层 |
| 关 | 开 | 路径独占底部渐变叠加层（与搜索结果缩略图同款） |
| 开 | 开 | 路径小字行在上、文件名行在下 |

位置文本函数 `locationText` 不变（根目录图片只显示图库名，其余显示
「图库名/文件夹路径」），灯箱继续复用。

### 2. 灯箱：路径标注移到底部居中，文件名不动

文件：[ImageLightbox.vue](../../../frontend/src/components/ImageLightbox.vue)。

注册 `location-label` 时增加 `appendTo: "wrapper"`（其余注册参数
name/order/tagName/className/onInit 不变）：

```ts
pswp!.ui!.registerElement({
  name: "location-label",
  order: 7,
  isButton: false,
  tagName: "span",
  className: "pswp__location-label",
  appendTo: "wrapper",
  onInit: (el) => {
    locationEl = el
    updateLocationLabel()
  },
})
```

把现有顶部栏内联样式（`.pswp__location-label` 旧规则）整体替换为底部居中胶囊，
视觉对齐既有的缩放比例/拍摄时间胶囊：

```css
/* 搜索/人物灯箱专属：路径标注底部居中（仅传入 locationResolver 时才注册）。
   bottom 44px 抬高一档，避开左下拍摄时间与右下缩放比例两个胶囊。 */
.pswp__location-label {
  position: absolute;
  left: 50%;
  bottom: 44px;
  transform: translateX(-50%);
  max-width: min(70vw, calc(100vw - 200px));
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  font-size: 13px;
  line-height: 20px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.8);
  user-select: none;
}
```

要点：

- `filename-label` 的注册与 CSS **一行不改**，图库/搜索/人物三处灯箱的文件名
  都留在顶部栏原位。
- 路径元素仍在 `if (props.locationResolver)` 分支内：图库普通浏览灯箱不传
  resolver，DOM 中不会出现该元素，**图库灯箱零变化**；受影响的只有搜索结果
  灯箱与人物页灯箱，二者都属于跨目录聚合场景，本就需要路径上下文。
- `bottom: 44px` 使路径胶囊高于两个贴底（`bottom: 10px`、高约 24px）的角落胶囊，
  任意屏宽都不重叠；`max-width` 兜底防止窄屏路径过长，超长省略号、
  PhotoSwipe 元素自带 `title` 之外不另加提示（与现状一致，YAGNI）。

## 边界与行为

| 情况 | 行为 |
| --- | --- |
| 两个开关都关（默认） | 缩略图纯图片，与无开关时视觉一致 |
| 只开位置 | 路径独占底部叠加层；根目录图片显示纯图库名 |
| 只开文件名 | 只显示文件名（含哈希名），用户可自行关闭 |
| 旧键 `people.grid.showInfo` 残留 | 不读取、不迁移、不清理；新两键默认关 |
| 图库普通浏览灯箱 | 无 resolver，路径元素不注册，与改动前完全一致 |
| 搜索/人物灯箱 | 路径在底部居中；文件名仍在顶部；翻页时两者同步更新（现有 change 处理不变） |
| 路径很长 | 省略号截断，不挤压角落胶囊 |

## 测试

### 前端：`person-cluster-view.spec.ts`（改写信息开关用例）

1. 默认挂载：`.lb-cell-filename` 与 `.lb-cell-badge` 均为 0（现有用例保留）。
2. 文件名开关：点击 `button[aria-label="缩略图上显示文件名"]` 后
   `.lb-cell-filename` 数 = 图片数 3、角标仍为 0；localStorage 写入
   `people.grid.showFilenames=1`；重挂载（`preserveStorage`）后保持显示。
3. 位置开关：点击 `button[aria-label="缩略图上显示所在位置"]` 后
   `.lb-cell-badge` 数 = 3，文本集合为
   `["家庭相册", "家庭相册", "家庭相册/2024/旅行"]`；localStorage 写入
   `people.grid.showLocation=1`；重挂载后保持显示。
4. 两开关互不影响：只开位置时文件名层不出现，反之亦然。

### 前端：`lightbox-location.spec.ts`（扩注册断言）

1. 传 resolver 挂载：`location-label` 注册项的 `appendTo` 为 `"wrapper"`；
   `filename-label` 注册项没有 `appendTo`（锁定文件名留顶部栏）。
2. 既有用例保持：无 resolver 时两个元素都不注册；view-in-folder 按钮行为不变。

### 回归

- `cd frontend && pnpm test && pnpm build`：全量前端测试与类型检查/构建通过。
- 后端无改动，跑一次后端全量 `.venv/Scripts/python -m pytest backend/tests/`
  确认无外溢。

## YAGNI 记录

曾评估的另两个方向：

- **给灯箱加布局 prop、仅人物页启用底部居中**：图库灯箱本就因 resolver 门控
  不存在路径元素，加 prop 是多余分叉，还要维护两套 CSS 与测试，排除。
- **把文件名也移到底部、与路径合并成一个两行容器**：用户明确要求文件名维持
  顶部原位；合并容器还需重写更新逻辑与既有测试，排除。
