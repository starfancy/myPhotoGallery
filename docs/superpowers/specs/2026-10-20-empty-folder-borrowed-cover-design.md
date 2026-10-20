# 空文件夹借用直接子文件夹封面 — 设计

日期：2026-10-20
状态：已批准（方案 C：纯前端补查）

## 背景与问题

浏览图库某层目录时，[SubfolderStrip.vue](../../../frontend/src/components/SubfolderStrip.vue)
为每个直接子文件夹显示一张卡片：封面缩略图 + 文件夹名 + 后代图片总数（`descendant_count`）。

后端 `/folders` 接口（[routes_browse.py](../../../backend/src/myphoto/routes_browse.py)
的 `list_folders`）为每个子文件夹选封面时，只查**该文件夹自身**中文件名排序第一张
（`Image.folder_id == c.id`）。当文件夹自身不含图片、图片都在它的子文件夹中时，
`cover_thumb_sha1` 为 null，卡片显示一块灰色占位，即使 `descendant_count > 0`（"N 张"
正常显示）也无法一眼看出里面有什么。

## 目标

- 文件夹自身无图、但直接子文件夹中有自身含图者时，卡片显示第一个含图子文件夹的封面，
  并在封面图底部以渐变条白字标注该子文件夹名称。
- 前后端解耦：**不改动后端**，复用现有 `/folders` 接口返回的数据。

## 非目标（明确不做）

- 不递归：只看直接子文件夹。若所有直接子文件夹自身都没图（图在孙级及以下），
  该文件夹仍显示灰色占位。
- 不改变卡片跳转行为：点击卡片始终进入该文件夹自身，而不是跳到含图子文件夹。
- 不改动后端接口、扫描器、数据库结构。
- 不调整普通卡片的排版。

## 现有机制（复用点）

- `GET /api/galleries/{gid}/roots/{rid}/folders?path=<rel>` 返回某层目录的直接子文件夹，
  已按 `Folder.name` 升序；每项含 `name`、`relative_path`、`image_count`、
  `descendant_count`、`cover_thumb_sha1`（按该文件夹自身图片算出，可能为 null）。
- [BrowseView.vue](../../../frontend/src/views/BrowseView.vue) 的 `loadAll()`
  已并行请求 breadcrumbs 与 folders，folders 直接存入响应式列表供卡片渲染。
- [SubfolderStrip.vue](../../../frontend/src/components/SubfolderStrip.vue)
  目前封面区为固定高 96px 的容器（`h-24`），有 sha1 才渲染 `<img>`。

## 设计

### 1. BrowseView.loadAll：对空文件夹并行补查

拿到 `/folders` 主响应后：

1. 筛出需补查项：`image_count === 0 && descendant_count > 0`。
   - `descendant_count === 0` 的真空文件夹不发请求，保持灰块。
2. 对每个候选并行（`Promise.all`）请求：
   `GET .../folders?path=<候选文件夹的 relative_path（encodeURIComponent）>`。
   单次补查失败（网络/权限错误）不影响主列表：捕获异常并当作未找到处理。
3. 从响应（已按名称升序）中取第一个满足
   `image_count > 0 && cover_thumb_sha1 != null` 的子文件夹：
   - 回填主列表对应项的 `cover_thumb_sha1`；
   - 新增字段 `cover_source_name` = 该子文件夹的 `name`。
4. 未找到则两项保持 null（不递归）。
5. 主列表先赋值渲染（保持现有体验），补查结果回来后响应式更新，接受封面轻微 pop-in。
   实现上 folders 主响应赋值后即可继续后续分页流程，补查与其并行、不 await
   阻塞 `renderPage`。

请求规模：示例目录约 40 个文件夹、3 个空文件夹 → 仅新增 3 个并行请求；
每个补查返回的是该空文件夹的直接子文件夹列表（典型规模几个到几十个），可接受。

### 2. SubfolderStrip：图底渐变条标注来源子文件夹名

- folders 项类型新增 `cover_source_name?: string | null`。
- 封面区容器加 `relative`；当 `cover_source_name` 有值时，在封面图之上、
  容器底部渲染一个绝对定位的渐变条：
  - 背景：`linear-gradient(transparent, rgba(0,0,0,0.75))`，高度约 28–32px；
  - 文字：白色、`text-xs`、左对齐、`truncate`、`px-1.5 pb-1`；
  - 容器加 `title="{{cover_source_name}}"`（或文字元素上），悬停可见全名；
  - `pointer-events-none`，不干扰外层 `<router-link>` 的点击。
- 图下的文件夹名、"N 张"（`descendant_count`）、跳转链接均不变。
- 无 `cover_source_name` 时渐变条不渲染，普通卡片零变化。

竖版封面 `object-contain` 的现有逻辑不变；渐变条位于容器底部横带上，
与图片采用 contain 还是 cover 无关。

### 3. 数据流

```
/folders?path=当前层
  → 40 项（3 项 image_count=0, descendant_count>0, cover=null）
  → Promise.all:
      /folders?path=空文件夹A → 取首个含图子项 → 回填 cover + cover_source_name
      /folders?path=空文件夹B → 无含图子项     → 保持 null
      /folders?path=空文件夹C → ...
  → SubfolderStrip 响应式更新：借来的封面 + 图底子文件夹名
```

## 边界与错误处理

| 情况 | 行为 |
|---|---|
| 文件夹自身有图 | 不补查，封面与现状完全一致 |
| 自身无图、`descendant_count=0` | 不补查，灰块 |
| 自身无图、直接子文件夹有含图者 | 用名称最靠前的含图子项封面 + 标注其名 |
| 直接子文件夹全都自身无图（图在孙级） | 不递归，灰块 |
| 补查请求失败 | 单项保持灰块，不报错、不阻塞页面其余内容 |
| 子文件夹名过长 | 单行截断，`title` 悬停全名 |

## 测试（仅前端，vitest）

扩充/新增组件与视图测试：

1. **补查触发条件**：给定 folders 响应，断言仅对
   `image_count === 0 && descendant_count > 0` 的项发出 `/folders?path=...` 请求，
   普通文件夹与 `descendant_count === 0` 者不触发；多个候选用并行方式发起。
2. **回填正确**：补查响应中含多个子项时，选取名称排序最靠前且自身有封面者，
   卡片出现其封面 sha1 对应的 `/api/thumb/...` 与来源名。
3. **无含图子项**：保持无封面（灰块）、无来源名。
4. **补查失败**：请求 reject 时主列表仍正常渲染、不抛未捕获异常。
5. **SubfolderStrip 渲染**：有 `cover_source_name` 时渐变条与名称出现；
   无该字段时渐变条不存在。

## YAGNI 记录

曾评估的另两个方案：

- **方案 A（后端 `/folders` 直接返回借来的封面）**：首响应一次到齐、无 pop-in，
  但需改后端接口与后端测试；实际目录规模下前端补查成本仅数个并行请求，收益不值得耦合。
- **方案 B（扫描器物化存储借来的封面）**：删除/回收站/恢复均需维护来源链，易陈旧，
  直接排除。
