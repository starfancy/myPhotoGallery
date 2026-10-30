# 浏览页文件夹缩略图快捷排除（管理员）

日期：2026-10-30
状态：已批准
范围：前端为主 + 后端排除接口的小幅增量；不涉及扫描/索引逻辑变更。

## 1. 目标与非目标

### 目标

管理员在浏览页（BrowseView）鼠标悬停某个**文件夹缩略图**（SubfolderStrip 卡片）时，右上角出现省略号（三点）按钮；点击后弹出快捷菜单，菜单含一项「排除此文件夹」，确认后复用 P5 已有的目录排除能力（纯 DB 清索引 + 触发重扫，不删除磁盘文件）。

触摸设备无 hover，管理员长按文件夹卡片 550ms（与图片卡片一致）弹出同一菜单。

### 非目标（YAGNI）

- 不做浏览页内「解除排除」入口：被排除的文件夹从浏览页消失，解除仍在图库管理页（AdminGalleryEdit）。
- 不改动 AdminGalleryEdit 已有的「+ 添加排除目录」流程（DirectoryChooser + 绝对路径 + 备注 prompt）。
- 不做右键以外的更多菜单项；本次菜单只有一项。
- 不为普通用户改变任何 UI（省略号仅管理员可见）。

## 2. 后端改动

文件：`backend/src/myphoto/routes_admin.py`，`POST /api/admin/galleries/{gid}/roots/{rid}/exclusions`。

### 2.1 请求体

`ExclusionCreate` 增加可选字段：

```python
class ExclusionCreate(BaseModel):
    absolute_path: str | None = Field(None, min_length=1, max_length=4096)
    relative_path: str | None = Field(None, min_length=1, max_length=4096)
    reason: str | None = Field(None, max_length=500)
```

约束：

- 两个路径字段**必须恰好提供一个**，否则 400 `path_invalid`（"provide exactly one of absolute_path / relative_path"）。空字符串按未提供处理（min_length=1 已拒绝空串）。
- `absolute_path` 分支：行为与现状完全一致（`_validate_path_within_root`）。
- `relative_path` 分支新增解析：
  1. 把 `\` 归一化为 `/`，按 `/` 切分；任一片段为 `..` 或为空（即 `//`、以 `/` 开头——拒绝绝对路径形式）→ 400 `path_invalid`。Windows 盘符（如 `C:`）作为片段也无法通过 root 内真实目录校验，无需特判。
  2. `p = Path(root.absolute_path) / rel_posix`，随后走与绝对路径分支**相同**的终态校验：`resolve()`、拒绝 symlink、必须真实存在且是目录、不得等于 root 本身、必须在 root 内（POSIX 风格片段拼出的路径必在 root 内，该校验作为防御纵深保留）。
  3. 以 `resolve()` 后的 `rel.as_posix()` 作为落库 `relative_path`。

实现方式：把现有 `_validate_path_within_root(raw_path, root)` 重构为内部共用的「已解析 Path 终态校验」小函数，两个入口分别完成各自的前段解析后调用；查重 409、IntegrityError 兜底、审计（`exclusion_add`）、`request_rescan` 全部不变。

### 2.2 安全

- 管理员鉴权不变（`admin_required`）。
- 相对路径不暴露服务器磁盘绝对路径；root 路径取自服务端 DB。
- 拒绝 `..` / 绝对路径形式 + resolve 后 root 归属校验，与现有绝对路径入口同等强度。

### 2.3 后端测试

`backend/tests/test_routes_admin_exclusions.py` 增加：

1. relative_path 成功创建（201，落库为 posix 相对路径，触发 rescan）。
2. relative_path 含 `..` → 400。
3. relative_path 为绝对路径形式（`/etc/x`、`C:/x`）→ 400。
4. 两字段都不传 / 同时传 → 400。
5. relative_path 重复 → 409（与绝对路径路径归一化后同一路径视为重复）。
6. relative_path 指向不存在目录 → 400。
7. 回归：绝对路径方式仍 201。

## 3. 前端改动

### 3.1 菜单基建泛化（共享文件）

- `composables/useCellMenu.ts`：菜单状态的 `id: number` 泛化为 key `string | number`；action 类型从字面量 `"delete"` 泛化为 `string`（由调用方在事件处理处收窄）；其余（文档绝对坐标、全局点击关闭、`open`/`openAt`/`runAction`）不变。
- `components/CellContextMenu.vue`：菜单项由 props 驱动（`items: { action: string; label: string }[]`），替代硬编码的「移入回收站」。点击项时 `emit("action", item.action)`，由 `runAction(action)` 带着当前菜单 key 一并抛出。

图片网格（JustifiedGrid / MasonryGrid）传入 `[{ action: "delete", label: "移入回收站" }]`，行为与现状逐字一致；`menuAction` 的签名变为 `(key: string | number, action: string)`，网格/视图侧在处理处断言为 number/"delete"。

### 3.2 SubfolderStrip

- 新增 prop `canExclude?: boolean`（BrowseView 传 `auth.isAdmin`）。
- 卡片 DOM 结构调整（按钮不能嵌套在 `<a>` 内）：

  ```
  <div class="group relative ... 卡片容器">
    <router-link class="absolute inset-0 ..."> 封面 + 底部文字区域 </router-link>
    <button v-if="canExclude" class="lb-folder-menu-btn ..."> 三点 svg </button>
  </div>
  ```

  视觉与现状一致：圆角、hover ring、封面 96px 高、底部文件夹名/张数。
- 三点按钮样式复刻 `PhotoCell` 的 `.lb-cell-menu-btn`（右上角 6px、28px 圆形半透明黑底、`display:none` → 卡片 `:hover` 或按钮 `:focus-visible` 时 `display:flex`），scoped 样式命名 `.lb-folder-menu-btn`。
- 交互：
  - 三点按钮 click（`.stop`，不触发链接导航）→ 在点击位置打开菜单。
  - 管理员在卡片上**右键** → `preventDefault` 打开菜单（非管理员不拦截默认右键）。
  - 触摸长按 550ms → 以触摸起点坐标打开菜单（逻辑照 PhotoCell 的 onTouchStart/onTouchEnd/onTouchMove 复刻；仅 canExclude 时计时）。
  - 菜单 key 使用 `folder.relative_path`（string）。
  - 菜单组件实例：`<CellContextMenu :items="[{ action: 'exclude', label: '排除此文件夹' }]" :menu=... />`。
- emits 增加 `(e: "exclude", folder: FolderItem): void`。
- 封面来源标注（`cover_source_name` 渐变条）、竖版判定等现状逻辑不动。

### 3.3 BrowseView

- `<SubfolderStrip ... :can-exclude="auth.isAdmin" @exclude="onExcludeFolder" />`。
- `onExcludeFolder(folder)`：
  1. `window.confirm` 文案：
     `确定排除文件夹「${folder.name}」？\n\n该文件夹及其所有子文件夹、图片将从图库索引中移除，磁盘上的文件不会被删除。之后可在「图库管理」中解除排除。`
     取消则直接返回。
  2. `apiPost("/api/admin/galleries/${gid}/roots/${rid}/exclusions", { relative_path: folder.relative_path })`，不带 reason（null）。
  3. 成功：**乐观更新**——直接从 `folders.value` 本地摘除该卡片（`filter(relative_path !==)`），不重置图片分页、不滚动。原因（2026-10-30 实测修正）：POST 只把重扫**入队**，Folder 行由后台 worker 重扫时才删除（`scanner._remove_unwalked_folders`）；POST 返回后立即 GET folders 会读到重扫窗口内的旧行，重拉反而把卡片加回来。下次进入目录时 `loadAll` 与服务端最终状态收敛；若重扫失败，管理页扫描状态可见。
  4. 失败：`window.alert("排除失败：" + message)`，含 409「该目录已排除」，风格同 `onGridMenuAction`。

注意：菜单的全局「点击外部关闭」监听在三点按钮的 `@click.stop` 场景下不会被同一点击触发关闭（stop 阻止冒泡到 window），与图片菜单行为相同。

## 4. 测试

### 前端（vitest，新 spec `src/tests/folder-exclude-menu.spec.ts`，mount SubfolderStrip / BrowseView 按现有测试惯例）

1. 非管理员：DOM 中不存在三点按钮。
2. 管理员：默认按钮不可见（display:none 可不强断言，断言存在即可），触发 click 后菜单出现且文本为「排除此文件夹」。
3. 点击菜单项 + confirm 确认：断言以 `{ relative_path }` 为 body POST 到正确 URL；随后发出 folders 列表重拉请求。
4. confirm 取消：不发 POST。
5. POST 409/500：alert 被调用且含错误信息。
6. 长按：dispatch touchstart→550ms 后 touchend（用 vi fake timers），菜单出现。
7. 回归保障：现有 203 个前端测试全绿（特别确认 JustifiedGrid/MasonryGrid/CellContextMenu 相关 spec 随泛化更新后通过）。

### 手工验证（可选，边用边验）

管理员 hover 文件夹 → 三点 → 菜单 → 确认 → 卡片消失；AdminGalleryEdit 该 root 排除列表出现新条目；图库管理页可解除。

## 5. 受影响文件

- 改：`backend/src/myphoto/routes_admin.py`
- 改：`backend/tests/test_routes_admin_exclusions.py`
- 改：`frontend/src/composables/useCellMenu.ts`
- 改：`frontend/src/components/CellContextMenu.vue`
- 改：`frontend/src/components/JustifiedGrid.vue`、`frontend/src/components/MasonryGrid.vue`（菜单项 props + key/action 类型收窄）
- 改：`frontend/src/components/SubfolderStrip.vue`
- 改：`frontend/src/views/BrowseView.vue`
- 新增：`frontend/src/tests/folder-exclude-menu.spec.ts`
- 可能微调：现有引用 `menuAction`/CellContextMenu 的测试断言。
