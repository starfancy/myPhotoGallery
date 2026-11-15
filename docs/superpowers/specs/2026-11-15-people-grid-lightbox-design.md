# 人物页网格信息开关与灯箱翻页 — 设计

日期：2026-11-15
状态：已批准（方案 A：后端补字段，前端复用 JustifiedGrid + ImageLightbox）

## 背景与问题

人物页 [PersonClusterView.vue](../../../frontend/src/views/PersonClusterView.vue)
当前右侧照片区是手写的 `flex flex-wrap` 定高（h-28）缩略图，与图库的
「按行对齐」（justified）排版不一致；缩略图只显示图片，看不出每张照片属于哪个
图库、哪个文件夹；点击缩略图无任何反应，无法看大图。

用户提出三点增强：

1. 顶部增加一个开关，开启后缩略图上显示**文件名**与**所在图库、文件夹路径**。
2. 点击缩略图用灯箱打开大图，浏览方式与图库一致，并能在**当前人物簇的全部图片**
   中左右翻页（可跨年/月组）。
3. 缩略图的显示尺寸、间隔等布局与图库「按行对齐」方式保持一致。

## 目标

- 右侧照片区改用图库同款 JustifiedGrid（行高 200px、间距 16px），**保留年/月
  分组标题**，每个分组渲染一个独立网格。
- 信息开关（持久化）控制缩略图叠加层：文件名 + 「图库名/文件夹路径」位置角标。
- 点击缩略图打开现有 ImageLightbox，灯箱图片集为**全簇拍平列表**，可跨分组翻页；
  灯箱内显示位置标注并支持「在所在文件夹中查看」跳回图库对应目录。
- 灯箱与网格自带的 admin 删除能力在人物页同样可用，删除后本地摘除并刷新簇计数。

## 非目标（明确不做）

- 不做选择模式/批量下载/批量删除（人物页无此诉求，JustifiedGrid 相关 prop 不传）。
- 不做 masonry 排版切换、不做场景标签开关（人物页只有 justified 一种排版）。
- 灯箱打开状态不进 URL（人物页路由无图片参数；刷新后回到簇默认视图，YAGNI）。
- 不调整后端接口 200 张上限与年/月分组排序；灯箱翻页范围即接口已返回的图片，
  与页面展示范围一致。
- 不改 ImageLightbox、JustifiedGrid、PhotoCell 三个共享组件的 props 与行为，
  只做消费方接线。

## 现有机制（复用点）

- [ImageLightbox.vue](../../../frontend/src/components/ImageLightbox.vue)：
  props 为 `items: ImageRow[]`、`startId: number`、可选
  `locationResolver?: (item: ImageRow) => string | null`；图片 URL 全部基于
  sha1/id（`/api/thumb/{sha1}`、`/api/image/{id}`、`/api/images/{id}/exif`），
  与图库上下文无关。自带 EXIF 面板、直方图、原图切换/预取、滤镜、admin 删除、
  文件名标签；传入 locationResolver 时额外注册位置标注与「在所在文件夹中查看」
  按钮并 emit `viewInFolder`。搜索结果态（BrowseView 第二个 ImageLightbox）
  已验证跨目录聚合图片的用法。
- [JustifiedGrid.vue](../../../frontend/src/components/JustifiedGrid.vue)：
  吃 `ImageRow[]`，内部用 `justifiedRows()` 按容器宽度排版（目标行高 200、gap 16），
  支持 `showFilename` 叠加层、`badgeFor` 角标（搜索态用于显示所在目录）、
  admin 右键/三点菜单（emit `menuAction`），点击 emit `open(id)`。
- [PhotoCell.vue](../../../frontend/src/components/PhotoCell.vue)：文件名与
  badge 同时显示时 badge 自动上抬一行（`lb-cell-badge--up`），长文本省略号 +
  title 悬停全名，均为现成行为。
- 后端图片行序列化范式 `_image_payload`（
  [routes_browse.py:283](../../../backend/src/myphoto/routes_browse.py#L283)）：
  id/filename/width/height/sha1/size_bytes/taken_at/mtime/is_raw/scene_*。
- 模型关联：`Image.root_id → GalleryRoot.id`，
  `GalleryRoot.gallery_id → Gallery.id`；`Image.relative_path` 为含文件名的
  posix 完整相对路径，目录部分用 rpartition 取。

## 设计

### 1. 后端：`GET /api/tags/clusters/{cluster_id}/images` 补字段

文件：[routes_tags.py](../../../backend/src/myphoto/routes_tags.py) 的
`cluster_images`。

查询由单表 `select(Image)` 改为 join 根与图库：

```python
rows = (await s.execute(
    select(Image, GalleryRoot, Gallery)
    .join(GalleryRoot, GalleryRoot.id == Image.root_id)
    .join(Gallery, Gallery.id == GalleryRoot.gallery_id)
    .where(Image.id.in_(image_ids))
    .order_by(Image.taken_at.desc().nullslast(), Image.id.desc())
    .limit(limit)
)).all()
```

每个图片项在现有 6 字段（id/filename/width/height/sha1/taken_at）基础上输出：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `size_bytes` | `Image.size_bytes` | 灯箱原图预取阈值判断需要 |
| `mtime` | `Image.mtime` | 灯箱拍摄时间回退显示需要 |
| `is_raw` | `bool(Image.is_raw)` | 与 `_image_payload` 对齐 |
| `scene_major` / `scene_minor` | `Image.scene_*` | 与 `_image_payload` 对齐，可空 |
| `gallery_id` | `Gallery.id` | 「在所在文件夹中查看」跳转用 |
| `root_id` | `GalleryRoot.id` | 同上 |
| `gallery_name` | `Gallery.name` | 位置角标/灯箱标注显示用 |
| `folder_path` | `Image.relative_path` 派生 | posix 目录部分；根目录图片为 `""` |

`folder_path` 派生：

```python
folder_path = img.relative_path.rpartition("/")[0]
# "2024/a.jpg" → "2024"；"a.jpg" → ""
```

响应外壳 `{groups: [...], total: n}`、年/月分桶逻辑与排序均不变；现有前端与
既有测试只断言旧字段，向后兼容。

### 2. 前端类型与数据

文件：[PersonClusterView.vue](../../../frontend/src/views/PersonClusterView.vue)。

把现有 `ClusterImage` 接口替换为继承共享类型的扩展接口：

```ts
import type { ImageRow } from "../stores/browse"

interface ClusterImage extends ImageRow {
  gallery_id: number
  root_id: number
  gallery_name: string
  folder_path: string
}
interface Group { year: number; month: number; images: ClusterImage[] }
```

后端返回的字段集满足 ImageRow 全部必填项（含 size_bytes、mtime、is_raw）。

新增 computed 拍平列表（保持分组顺序：年/月倒序、组内拍摄时间倒序），供灯箱
作为完整图片集：

```ts
const flatImages = computed(() => groups.value.flatMap((g) => g.images))
```

位置文本统一一个函数，网格角标与灯箱标注共用。共享组件的函数类型以
`ImageRow` 为参数（严格函数类型逆变），故入参标注 `ImageRow`，内部收窄为
`ClusterImage` 访问扩展字段：

```ts
function locationText(it: ImageRow): string {
  const c = it as ClusterImage
  return c.folder_path ? `${c.gallery_name}/${c.folder_path}` : c.gallery_name
}
```

### 3. 信息开关

- 新增 `showInfo` ref，持久化到 localStorage，键 `people.grid.showInfo`
  （`"1"`/`"0"`，默认关；与图库的 `browse.grid.showFilenames` 独立，互不影响）。
- 开关按钮放在右侧 section 标题行（簇名/重命名所在的 flex 行）末尾，`ml-auto`，
  样式与图库文件名开关一致：`aria-pressed`、`aria-label`/`title`
  （「缩略图上显示文件名与所在位置」）、`min-h-11` 触摸目标、激活态
  `bg-surface-3 text-ink`，图标复用图库同款 SVG（圆角矩形 + 底部文字行）。
- 开启时给每个 JustifiedGrid 传 `:show-filename="true"` 与
  `:badge-for="locationText"`；关闭时两者均不传（falsy），缩略图回到纯图片。
- 角标渲染规则：根目录图片只显示图库名；子目录图片显示
  「图库名/文件夹路径」，超长由 PhotoCell 现成逻辑省略，`title` 悬停全名。

### 4. JustifiedGrid 接线（保留年/月分组）

模板中每个分组由手写缩略图行改为：

```vue
<div v-for="g in groups" :key="`${g.year}-${g.month}`" class="mb-4">
  <h3 class="mb-1.5 text-xs font-medium text-ink-2">{{ groupTitle(g) }}</h3>
  <JustifiedGrid
    :items="g.images"
    :show-filename="showInfo"
    :badge-for="showInfo ? locationText : undefined"
    @open="openLightbox"
    @menu-action="onGridMenuAction"
  />
</div>
```

不传 `selection-mode`/`selected-ids`（无选择模式）；JustifiedGrid 内部的 admin
菜单判断（`isAdmin && !selectionMode`）自动生效，viewer 角色不显示菜单。
网格容器为 section 全宽，ResizeObserver 自动按实际宽度排版，与图库同算法、
同行高（200）、同间距（16）。

### 5. 灯箱接线

新增 `lightboxId = ref<number | null>(null)`：

```ts
function openLightbox(id: number) {
  lightboxId.value = id
}
```

模板根部（与 BrowseView 同级位置）挂载：

```vue
<ImageLightbox
  v-if="lightboxId !== null && flatImages.some((it) => it.id === lightboxId)"
  :items="flatImages"
  :start-id="lightboxId"
  :location-resolver="locationText"
  @close="lightboxId = null"
  @deleted="onImageDeleted"
  @view-in-folder="onViewInFolder"
/>
```

- 不监听 `change` 事件（不做 URL 追踪）。
- `items` 为全簇拍平列表 → 灯箱内左右翻页可跨年/月组覆盖整个簇，序号/文件名/
  EXIF/直方图/原图/滤镜等图库灯箱能力全部原样可用。
- `locationResolver` 传入后，灯箱顶部常显位置标注、工具栏出现
  「在所在文件夹中查看」。

跳回所在文件夹（跨图库也成立，因为数据里带了各自的 gallery_id/root_id）。
emit 的载荷类型是 `ImageRow`，同样内部收窄：

```ts
function onViewInFolder(row: ImageRow) {
  const it = row as ClusterImage
  const suffix = encodePathSegments(it.folder_path)
  router.push(
    suffix
      ? `/galleries/${it.gallery_id}/r/${it.root_id}/${suffix}`
      : `/galleries/${it.gallery_id}/r/${it.root_id}`,
  )
}
```

### 6. 删除接线

网格菜单与灯箱内删除都走现有 `DELETE /api/images/{id}`：

- 网格：`onGridMenuAction(id, "delete")` 内 `window.confirm` 确认（文案与
  BrowseView 一致）后调 `apiDelete`，成功后交 `onImageDeleted`。
- 灯箱：ImageLightbox 内部已完成确认与 DELETE，只 emit `deleted`；组件自身会
  关闭灯箱。
- `onImageDeleted(id)` 统一处理：
  1. 从所有分组本地摘除该图片，移除变空的分组；
  2. `lightboxId.value = null`；
  3. `await loadClusters()` 刷新左栏（image_count 变化、孤儿簇自动从列表消失）；
  4. 若当前 selectedId 已不在新簇列表中：有其他簇则 `selectCluster` 第一个，
     否则 groups 清空，页面落入既有「暂无人物簇」空态。

### 7. 数据流

```text
选择簇
  → GET /api/tags/clusters/{cid}/images（补字段后的行）
  → groups（年/月分组）→ 每组 JustifiedGrid；flatImages = 拍平全簇
  → 点缩略图 → ImageLightbox(items=flatImages, startId=点击id)
      → 左右翻页跨全簇；locationResolver 显示图库/路径
      → 「在所在文件夹中查看」→ /galleries/{gid}/r/{rid}/{folder_path}
  → 删除 → DELETE /api/images/{id} → 本地摘除 + loadClusters 刷新计数
```

## 边界与错误处理

| 情况 | 行为 |
| --- | --- |
| 根目录图片（无文件夹层级） | 角标/灯箱标注只显示图库名；跳转落到 root 根路径（无尾斜杠） |
| 图库名或路径很长 | PhotoCell/灯箱标签现成省略号 + title 全名 |
| 翻页到簇内最后一张 | PhotoSwipe 原生循环关闭，停在末张，不跨簇 |
| 簇内图片超过 200 张上限 | 网格与灯箱都只覆盖接口返回的部分（现状行为，total 仍显示全量计数） |
| 灯箱中删除当前图片 | 灯箱自关，本地摘除并刷新左栏；当前簇被删空时自动切到第一个簇或空态 |
| 非 admin 用户 | 网格三点/右键菜单与灯箱「更多操作」均不渲染，删除入口不可见 |
| 接口请求失败 | 沿用现有 loadError/加载态，灯箱不会被打开（无 items） |
| 图片 width/height 为 null | JustifiedGrid 以 4:3 兜底（现成逻辑）；灯箱以默认尺寸兜底（现成逻辑） |

## 测试

### 后端（[test_routes_tags.py](../../../backend/tests/test_routes_tags.py)）

1. **补字段回归**：扩展 `test_cluster_images_groups_by_year_month` 或新增用例，
   断言返回图片包含 `size_bytes`、`mtime`、`is_raw`、`scene_major`、
   `scene_minor`、`gallery_id`、`root_id`、`gallery_name`、`folder_path`，
   且 gallery_id/root_id 与夹具一致、gallery_name == "G"。
2. **folder_path 派生**：新夹具插入一张子目录图片
   （`relative_path="sub/x.jpg"`、Folder `relative_path="sub"`），断言
   `folder_path == "sub"`；同簇根目录图片 `folder_path == ""`。
3. 既有分组/404/重命名/孤儿簇测试保持不变、全部通过。

### 前端（新增 `src/tests/person-cluster-view.spec.ts`）

挂载前 mock `api` 模块（apiGet/apiPut/apiDelete）与 photoswipe（沿用
lightbox 测试里的现成 mock 模式）、ResizeObserver（沿用 grid 测试里的现成
mock）。用例：

1. **初始渲染**：簇列表加载后默认选中第一个簇，渲染年/月组标题与 justified
   网格单元格，缩略图 src 含对应 sha1。
2. **信息开关**：默认无文件名叠加层与位置角标；点击开关后两者出现，角标文本
   根目录图为图库名、子目录图为「图库名/路径」；localStorage 写入
   `people.grid.showInfo=1`，重新挂载保持开启。
3. **灯箱打开与翻页范围**：点击单元格后 ImageLightbox 被挂载，`items` 为全簇
   拍平数组（顺序 = 分组顺序拼接）、`startId` 为所点图片 id。
4. **locationResolver**：直接调用组件传入的 resolver 验证两种路径文本。
5. **跳回所在文件夹**：emit `viewInFolder` 后 router push 到
   `/galleries/{gid}/r/{rid}/{folder_path}`；根目录图片无尾斜杠。
6. **删除**：stub `window.confirm` 放行、mock apiDelete 成功后，该图片从
   groups 摘除且 loadClusters 被重新调用；灯箱删除路径（emit deleted）同样
   触发摘除。

## YAGNI 记录

曾评估的另两个方案：

- **方案 B（扩展 PhotoCell 支持双行图库/路径）**：PhotoCell 被图库、搜索、
  人物三处共用，为单页面改共享组件回归面大；现有 badge 单行角标（搜索态已用于
  目录路径）足以承载「图库名/路径」文本，无需改组件。排除。
- **方案 C（人物页自写网格/灯箱）**：要重复 justified 排版、PhotoSwipe 接线、
  EXIF/直方图/原图预取等大量已测逻辑，维护双份实现。排除。
