# myPhotoGallery Phase 3 实现计划：单图删除 + 回收站 + EXIF 抽取与展示

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P2 管理 API 基础上新增图片删除/回收站/恢复/清理功能（spec §3.4 红线 2、3），以及扫描时 EXIF 元数据抽取与 Lightbox 展示（方案 B：扫描时存 `exif_json`）。

**Architecture:** 新增 `trash.py` 和 `routes_trash.py`；修改 `models.py`（+Trash 表 + images.exif_json 字段）、`scanner.py`（EXIF 抽取）、`main.py`（+trash router + 启动时 purge_expired）。前端新增 AdminTrash 页面，修改 BrowseView（admin 删除按钮）和 Lightbox（EXIF 面板）。

**Tech Stack:** 与 P1/P2 完全一致：Python 3.11+ / FastAPI / SQLAlchemy 2.0 async + aiosqlite / Vue 3 + Vite + Pinia + Router + UnoCSS

---

## Global Constraints

- 所有 P1 和 P2 的 Global Constraints 继续生效
- **红线 2**（单图删除 = 回收站）：`DELETE /api/images/{id}` 走 `os.rename` 到 `.trash/`，不使用 `os.remove`
- **红线 3**（物理删除只在回收站）：`os.remove` 唯一位点在 `trash.purge_expired()`，路径必须以 `TRASH_DIR` 为前缀，否则抛异常
- **红线 1**（文件夹永不物理删除）：本 phase 不涉及图库根目录写操作
- `.trash/` 目录为每个 root 独立，位于 `<root_absolute_path>/.trash/`，尽量与图片同盘以便 `os.rename` 成功
- 跨盘 `os.rename` 失败时退回 `shutil.move`（spec §5.3）
- 启动时执行一次 `trash.purge_expired()`（防主机长时间关机漏掉到期清理）
- **不实现每日定时清理**（本 phase 只做启动 + 手动；定时器延后到 P4 或 P5）
- 审计写入失败绝不传播 —— `write_audit()` 内部 catch 并 log（P2 已建立）
- EXIF 抽取失败不影响扫描 —— 跳过 exif_json 字段，不抛异常
- 错误码新增但保持向后兼容
- 所有管理端路由由 `admin_required` 保护

---

## 目录结构（P3 完成时新增/修改）

```
backend/src/myphoto/
├─ trash.py              # NEW: purge_expired(), os.remove 唯一物理删除位点
├─ routes_trash.py       # NEW: /api/trash/* 路由
├─ models.py             # MODIFY: +Trash ORM, +images.exif_json TEXT NULL
├─ scanner.py            # MODIFY: _process_file 返回 exif_json; _read_image_meta 扩展 EXIF 抽取; _read_raw_meta 尝试读 EXIF; _upsert_image 写 exif_json
├─ routes_images.py      # NEW: DELETE /api/images/{id}, POST /api/images/batch-delete (或复用 routes_browse.py)
├─ routes_browse.py      # MODIFY: +DELETE /api/images/{id}, +POST /api/images/batch-delete
├─ routes_admin.py       # MODIFY: 无需改动（已有审计/status 等）
├─ main.py               # MODIFY: +trash router mount; +startup purge_expired()
├─ cli.py                # MODIFY: +rescan --force-exif 或 +rescan-exif 子命令
└─ config.py              # MODIFY: trash section 配置项已在 config.toml 模板中但未生效

backend/tests/
├─ test_models.py              # MODIFY: +Trash ORM 测试, +exif_json 字段测试
├─ test_trash.py               # NEW: purge_expired 单元测试（红线 3 路径前缀护栏）
├─ test_routes_trash.py        # NEW: /api/trash/* 路由测试
├─ test_routes_images_delete.py# NEW: 删除/批量删除/恢复路由测试
├─ test_scanner.py             # MODIFY: +exif_json 抽取验证
├─ test_cli.py                 # MODIFY: +rescan --force-exif 测试

frontend/src/
├─ router.ts                   # MODIFY: +/admin/trash 路由
├─ components/
│  ├─ AppHeader.vue            # MODIFY: +管理菜单扩展（可选）
│  └─ Lightbox.vue（或 BrowseView.vue 内 PhotoSwipe 配置） # MODIFY: +删除按钮 +EXIF 面板
├─ views/
│  ├─ AdminTrash.vue           # NEW: 回收站管理页面
│  └─ BrowseView.vue           # MODIFY: admin hover 三点菜单 + 删除确认
└─ tests/
   ├─ admin-trash.spec.ts      # NEW
   ├─ browse-view-delete.spec.ts # NEW（或合并到现有 smoke/测试）
   └─ lightbox-exif.spec.ts    # NEW
```

---

## Task 清单概览（16 个任务）

| # | 主题 | 端 |
|---|---|---|
| 1 | Trash ORM 模型 + images.exif_json 字段 | BE |
| 2 | 路径安全工具 `trash.py` — TRASH_DIR + purge_expired() | BE |
| 3 | EXIF 抽取扩展 — 20 字段 JSON + _process_file 签名变更 | BE |
| 4 | CLI `rescan --force-exif` | BE |
| 5 | 单图删除 + 批量删除 API | BE |
| 6 | 回收站 API（列表/恢复/批量恢复/单条删除/清理） | BE |
| 7 | 启动时 purge_expired 集成 + 相关审计 | BE |
| 8 | GET /api/images/{id}/exif 端点 | BE |
| 9 | 前端 Lightbox 删除按钮 + EXIF 面板 | FE |
| 10 | BrowseView admin hover 三点菜单（"移入回收站"） | FE |
| 11 | 前端 `/admin/trash` 路由 | FE |
| 12 | AdminTrash 页面 | FE |
| 13 | 前端批量选择模式（BrowseView 多选） | FE |
| 14 | 前端测试 — 删除/回收站/EXIF | FE |
| 15 | 后端集成测试 | BE |
| 16 | 端到端验证 + 红线 grep + 提交 | Full |

---

## 关键接口速查（跨任务共享）

### Trash ORM（§4.8）

```python
class Trash(Base):
    __tablename__ = "trash"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gallery_id: Mapped[int] = mapped_column(Integer, nullable=False)
    root_id: Mapped[int] = mapped_column(Integer, nullable=False)
    original_relative_path: Mapped[str] = mapped_column(String, nullable=False)
    trash_relative_path: Mapped[str] = mapped_column(String, nullable=False)
    sha1: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    deleted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    deleted_at: Mapped[int] = mapped_column(Integer, nullable=False)
    purge_after: Mapped[int] = mapped_column(Integer, nullable=False)
    # INDEX (deleted_at)
    # INDEX (gallery_id, deleted_at)
```

### images.exif_json 字段

```python
# 在 Image 模型上新增
exif_json: Mapped[str | None] = mapped_column(String, nullable=True)
```

### 20 个 EXIF 字段（扫描时抽取，JSON 序列化）

```python
EXIF_TAGS = {
    # PIL ExifTags 映射
    0x010F: "Make",              # 相机厂商
    0x0110: "Model",             # 相机型号
    0x9003: "DateTimeOriginal",  # 拍摄时间（原始字符串）
    0x0132: "ModifyDate",        # 修改时间
    0x829A: "ExposureTime",      # 快门速度（分数字符串）
    0x829D: "FNumber",           # 光圈值
    0x8827: "ISOSpeedRatings",   # ISO
    0x920A: "FocalLength",       # 焦距
    0xA434: "LensModel",         # 镜头型号
    0x8825: "GPSInfo",           # GPS（子 dict，含 GPSLatitude/GPSLongitude）
    0x0112: "Orientation",       # 方向（1-8）
    0x0131: "Software",          # 软件
    0x9209: "Flash",             # 闪光灯
    0xA403: "WhiteBalance",      # 白平衡
    0xA001: "ColorSpace",        # 色彩空间
    0x8822: "ExposureProgram",   # 曝光程序
    0x9207: "MeteringMode",      # 测光模式
    0x9204: "ExposureBiasValue", # 曝光补偿
    0xA406: "SceneCaptureType",  # 场景类型
    0xA300: "FileSource",        # 文件来源
}
```

**抽取策略：** 遍历 `image.getexif()`，匹配 tag ID → 可序列化值（str/int/float/dict/list），跳过二进制/大对象。RAW 通过 `rawpy.imread().exif` 或 Pillow 侧读（优先尝试 rawpy 内嵌 JPEG 的 EXIF，失败则跳过）。抽取失败不抛异常，`exif_json` 留 NULL。

**响应形状（GET /api/images/{id}/exif）：**
```json
{
  "image_id": 42,
  "filename": "DSC_0001.jpg",
  "exif": {
    "Make": "Nikon",
    "Model": "Z6",
    "DateTimeOriginal": "2024:01:15 14:32:00",
    "ExposureTime": "1/250",
    "FNumber": "4.0",
    ...
  }
}
```

### 删除/回收站 API（§6.4）

**DELETE /api/images/{image_id}**
```python
# 从 images 表查 root_id, relative_path, sha1, size_bytes
# os.makedirs(TRASH_DIR_FOR(root_id))  # 确保 .trash/ 存在
# src = join(root.absolute_path, relative_path)
# dst = join(TRASH_DIR_FOR(root_id), f"{yyyymmdd}/{basename}")
# 若 dst 已存在: dst += "-{short_uuid}"
# os.rename(src, dst)  # 同盘原子操作
# 若跨盘 OSError: shutil.move(src, dst)
# insert into trash(...)
# delete from images where id = image_id
# 写审计 image_delete
```

**POST /api/images/batch-delete** `{image_ids: [...]}`（上限 500）

**GET /api/trash?gallery_id=&root_id=&sort=deleted_at_desc&limit=&cursor=**
```python
# 返回 {entries: [{id, gallery_id, root_id, original_relative_path, trash_relative_path, sha1, size_bytes, deleted_by, deleted_at, purge_after}], next_cursor}
```

**POST /api/trash/{trash_id}/restore**
```python
# 查 trash 行
# dst = join(root.absolute_path, original_relative_path)
# 若 dst 已存在: dst += " (restored yyyymmdd-HHMMSS)"
# os.rename(trash_file, dst)
# 触发轻量扫描其父目录（或直接写回 images 表 + 重算 folder counts）
# delete from trash where id = trash_id
# 写审计 image_restore
```

**POST /api/trash/batch-restore** `{trash_ids: [...]}`（上限 500）

**DELETE /api/trash/{trash_id}**
```python
# 查 trash 行
# 校验 trash 文件路径以 TRASH_DIR 为前缀
# os.remove(trash_file)
# delete from trash where id = trash_id
# 不写审计（非批量清理）
```

**POST /api/trash/purge** `{gallery_id?, root_id?, before?, confirm=true}`
```python
# 调用 trash.purge_expired(session, gallery_id, root_id, before)
# 扫 trash where purge_after < now()（或业务指定 before）
# 每行: 校验 trash 文件路径以 TRASH_DIR 为前缀 → os.remove → delete from trash
# 写审计 trash_purge，detail 包含 purged_count
# 确认 confirm=true 防止误操作
```

### 恢复后的轻量扫描

恢复操作不触发完整 root 扫描，而是：
1. 从 trash 记录获取原图路径和 sha1
2. 直接写回 `images` 表（复用原 id，或新插入）
3. 为其父目录重新执行一次 `_ensure_folders` + `_recompute_counts`
4. 这样可以避免对一万张的图库做一次完整重扫

### CLI rescan-exif

```python
@cli.command("rescan-exif")
@click.argument("gallery_name", required=False)
@click.argument("root_label", required=False)
@click.pass_context
def rescan_exif(ctx, gallery_name, root_label):
    """Scan all images (or filtered by gallery/root) and backfill exif_json.
    
    Differs from 'rescan' in that it skips new-file detection (mtime/size)
    and only reads EXIF for images where exif_json IS NULL. Does NOT trigger
    folder count recomputation.
    """
```

### 前端接口速查

**Lightbox EXIF 面板：**
- PhotoSwipe 顶部 `i` 按钮 → 打开侧边面板
- 调 `GET /api/images/{id}/exif` 获取结构化数据
- 前端映射：PIL tag name → 中文标签（Make → 相机厂商, Model → 相机型号, …）
- 面板显示键值对表格，无数据时显示"无 EXIF 信息"

**BrowseView admin 删除：**
- PC: 图片 hover 时右上角三点菜单 → "移入回收站" → 二次确认弹窗（含缩略图 + 文件名 + 路径）
- 移动: 长按弹出
- 确认后：`DELETE /api/images/{id}` → 从当前视图移除该图片 → toast 通知

**AdminTrash 页面：**
- 表格列：缩略图（thumb 200）、原路径、图库名、删除人、删除时间、到期时间、[恢复] [立即删除]
- 过滤：图库下拉选择、时间范围
- 批量操作：勾选多行 → 顶部工具栏 [恢复选中] [删除选中] [清空所有]
- 清空按钮：勾选"我理解不可恢复，将永久删除" → POST /api/trash/purge

---

### Task 1: Trash ORM 模型 + images.exif_json 字段

**Files:**
- Modify: `backend/src/myphoto/models.py`

**Steps:**
- [ ] **Step 1: 添加 Trash ORM** — 按上面接口速查的 schema 实现，含 INDEX (deleted_at) 和 INDEX (gallery_id, deleted_at)
- [ ] **Step 2: 添加 images.exif_json 字段** — `Mapped[str | None] = mapped_column(String, nullable=True)`
- [ ] **Step 3: 写测试** — Trash ORM 创建/查询/删除；exif_json 字段可空写入
- [ ] **Step 4: 运行测试验证通过并提交**

---

### Task 2: 路径安全工具 `trash.py` — TRASH_DIR + purge_expired()

**Files:**
- Create: `backend/src/myphoto/trash.py`
- Create: `backend/tests/test_trash.py`

**Steps:**
- [ ] **Step 1: 实现 TRASH_DIR** — `def trash_dir_for(root: GalleryRoot) -> Path` 返回 `<root.absolute_path>/.trash/{gallery_id}/{root_id}/`
- [ ] **Step 2: 实现 purge_expired()** — 遍历 `trash where purge_after < now()`，每行校验路径以 `TRASH_DIR` 为前缀（红线 3），**不成立则拒绝并写审计 `trash_purge` detail=path_guard_blocked**，成立则 `os.remove` → delete from trash
- [ ] **Step 3: 写单元测试** — 正常清理、路径前缀校验拒绝、空目录、幂等
- [ ] **Step 4: 运行测试验证通过并提交**

---

### Task 3: EXIF 抽取扩展 — 20 字段 JSON + _process_file 签名变更

**Files:**
- Modify: `backend/src/myphoto/scanner.py`
- Modify: `backend/tests/test_scanner.py`

**Steps:**
- [ ] **Step 1: 扩展 _read_image_meta** — 返回 `(width, height, taken_at, exif_json)` 四元组；新增 `_extract_exif_tags(image)` 函数遍历 20 个 tag，返回 dict 或 None（抽取失败）
- [ ] **Step 2: 扩展 _read_raw_meta** — 尝试通过 `rawpy` 获取 EXIF（`raw.extract_thumb()` 的 JPEG 或 `rawpy.imread().exif`），失败返回 None
- [ ] **Step 3: 修改 _process_file** — 返回 `(sha1, width, height, taken_at, exif_json)` 五元组；调用方适配
- [ ] **Step 4: 修改 _upsert_image** — 接收 exif_json 参数，写入 Image 行
- [ ] **Step 5: 写测试** — 已知 EXIF 的 JPEG 测试图片；无 EXIF 的图片；RAW；抽取失败不抛异常
- [ ] **Step 6: 运行测试验证通过并提交**

---

### Task 4: CLI `rescan-exif` 命令

**Files:**
- Modify: `backend/src/myphoto/cli.py`
- Modify: `backend/tests/test_cli.py`

**Steps:**
- [ ] **Step 1: 实现 rescan-exif 命令** — 扫指定 gallery/root 的 images where exif_json IS NULL；对每张图片重新 `_process_file`（只读 EXIF 不重算 sha1/mtime）；UPDATE images SET exif_json = ... WHERE id = ...
- [ ] **Step 2: 写测试** — 创建图库 + root + 扫描 → 清空 exif_json → rescan-exif → 验证 exif_json 已回填
- [ ] **Step 3: 运行测试验证通过并提交**

---

### Task 5: 单图删除 + 批量删除 API

**Files:**
- Create: `backend/src/myphoto/routes_images.py`（或修改 `routes_browse.py`）
- Create: `backend/tests/test_routes_images_delete.py`

**Steps:**
- [ ] **Step 1: 实现 DELETE /api/images/{image_id}** — 按上面接口速查的伪代码实现；权限 `admin_required`；事务内完成 os.rename + insert trash + delete images + 写审计；跨盘 fallback 到 shutil.move
- [ ] **Step 2: 实现 POST /api/images/batch-delete** — 上限 500，逐条走删除逻辑，部分失败不阻断
- [ ] **Step 3: 写测试** — 单图删除（trash 表有记录、images 表无记录、文件已移到 .trash/）、404、批量删除、超上限 422、非 admin 401
- [ ] **Step 4: 运行测试验证通过并提交**

---

### Task 6: 回收站 API（列表/恢复/批量恢复/单条删除/清理）

**Files:**
- Create: `backend/src/myphoto/routes_trash.py`
- Create: `backend/tests/test_routes_trash.py`

**Steps:**
- [ ] **Step 1: 实现 GET /api/trash** — 分页列表，支持 gallery_id 和 root_id 过滤，默认按 deleted_at DESC 排序
- [ ] **Step 2: 实现 POST /api/trash/{trash_id}/restore** — 查 trash 行 → os.rename 回原位 → 直接写回 images 表 → 轻量更新父目录 counts → delete trash 行 → 写审计 image_restore
- [ ] **Step 3: 实现 POST /api/trash/batch-restore** — 上限 500
- [ ] **Step 4: 实现 DELETE /api/trash/{trash_id}** — 物理删除单条（路径前缀校验 + os.remove）
- [ ] **Step 5: 实现 POST /api/trash/purge** — 调用 purge_expired()；confirm=true 参数校验；写审计 trash_purge
- [ ] **Step 6: 写测试** — 列表/分页/过滤、恢复（目标已存在时的重命名）、批量恢复、单条删除、purge（confirm 缺失 400）、非 admin 401
- [ ] **Step 7: 运行测试验证通过并提交**

---

### Task 7: 启动时 purge_expired 集成 + 配置

**Files:**
- Modify: `backend/src/myphoto/main.py`
- Modify: `backend/src/myphoto/config.py`（如需要追加 trash 配置项）

**Steps:**
- [ ] **Step 1: 在 lifespan 中集成** — 启动时（scanner 初始化之后、请求接收之前）调用 `trash.purge_expired(session)` 一次
- [ ] **Step 2: 确认 config.toml 中 [trash] 段已有** — 当前 P1/P2 的 config 模板中已有 `retention_days`、`purge_hour`、`purge_minute`；本 phase 只使用 `retention_days`（purge_hour/minute 为 P4 定时器预留）
- [ ] **Step 3: 写集成测试** — 模拟过期 trash 行 → 启动 app → 确认被清理
- [ ] **Step 4: 运行测试验证通过并提交**

---

### Task 8: GET /api/images/{id}/exif 端点

**Files:**
- Modify: `backend/src/myphoto/routes_browse.py`（或 `routes_media.py`）
- Create: `backend/tests/test_routes_exif.py`

**Steps:**
- [ ] **Step 1: 实现 GET /api/images/{id}/exif** — 查 images 表获取 exif_json 字段；若为 NULL 返回空 exif 对象；权限 current_user（任何登录用户可见自己有权访问的图片的 EXIF）
- [ ] **Step 2: 写测试** — 有 EXIF 的图片返回 exif 字段、无 EXIF 的图片返回空对象、404、非登录 401
- [ ] **Step 3: 运行测试验证通过并提交**

---

### Task 9: 前端 Lightbox 删除按钮 + EXIF 面板

**Files:**
- Modify: `frontend/src/views/BrowseView.vue`（PhotoSwipe 配置部分）

**Steps:**
- [ ] **Step 1: Lightbox 底部增加删除按钮** — admin 角色可见；二次确认弹窗；调用 `DELETE /api/images/{id}` → 关闭 Lightbox → 从当前浏览视图移除该图片
- [ ] **Step 2: Lightbox 顶部增加 `i` 按钮** — 点击打开侧边 EXIF 面板；调 `GET /api/images/{id}/exif`；键值对表格展示（前端中文标签映射）
- [ ] **Step 3: 暗色/无数据状态** — 无 EXIF 时显示"无 EXIF 信息"；面板跟随深色模式
- [ ] **Step 4: 提交**

---

### Task 10: BrowseView admin hover 三点菜单（"移入回收站"）

**Files:**
- Modify: `frontend/src/views/BrowseView.vue`

**Steps:**
- [ ] **Step 1: PC hover 三点菜单** — 图片缩略图右上角小三点按钮；hover 时显示；点击弹出菜单："移入回收站"
- [ ] **Step 2: 二次确认弹窗** — 缩略图 + 文件名 + 路径 + 确认/取消；确认后调用 DELETE /api/images/{id}
- [ ] **Step 3: 移动端长按** — 长按弹出菜单
- [ ] **Step 4: 提交**

---

### Task 11: 前端 `/admin/trash` 路由

**Files:**
- Modify: `frontend/src/router.ts`

**Steps:**
- [ ] **Step 1: 添加路由** — `{ path: "/admin/trash", component: () => import("./views/AdminTrash.vue"), meta: { requiresAdmin: true } }`
- [ ] **Step 2: 验证 guard** — 非 admin 无法访问
- [ ] **Step 3: 提交**

---

### Task 12: AdminTrash 页面

**Files:**
- Create: `frontend/src/views/AdminTrash.vue`

**Steps:**
- [ ] **Step 1: 实现表格视图** — onMounted 调 `GET /api/trash`；表格列：缩略图（thumb 200）、原路径、图库名、删除人、删除时间、到期时间、[恢复] [立即删除] 按钮
- [ ] **Step 2: 实现过滤** — 图库下拉选择（调 `GET /api/admin/galleries` 获取列表）；时间范围输入（from/to ts）
- [ ] **Step 3: 实现批量操作** — 勾选多行 → 顶部工具栏 [恢复选中]（POST /api/trash/batch-restore）[删除选中]（逐条 DELETE /api/trash/{id}）；清空按钮（勾选确认 → POST /api/trash/purge）
- [ ] **Step 4: 提交**

---

### Task 13: 前端批量选择模式（BrowseView 多选）

**Files:**
- Modify: `frontend/src/views/BrowseView.vue`
- Modify: `frontend/src/stores/`（useBrowseStore 或新 store）

**Steps:**
- [ ] **Step 1: 实现多选模式** — 工具栏增加"选择"按钮切换进入选择模式；每张图片缩略图显示勾选框；已选图片高亮；底部浮动工具条显示已选数量 + [移入回收站] [取消]
- [ ] **Step 2: 批量删除** — "移入回收站" 调 `POST /api/images/batch-delete`；成功后从视图移除已选图片；toast 通知
- [ ] **Step 3: 提交**

---

### Task 14: 前端测试 — 删除/回收站/EXIF

**Files:**
- Create: `frontend/src/tests/admin-trash.spec.ts`
- Create: `frontend/src/tests/browse-view-delete.spec.ts`
- Create: `frontend/src/tests/lightbox-exif.spec.ts`

**Steps:**
- [ ] **Step 1: AdminTrash 测试** — 加载列表、过滤、恢复、删除、批量、清空确认
- [ ] **Step 2: BrowseView 删除测试** — 三点菜单可见性（admin/viewer）、删除确认流程、移动端长按
- [ ] **Step 3: Lightbox EXIF 测试** — 面板渲染、中文标签映射、无数据状态
- [ ] **Step 4: 运行测试验证通过并提交**

---

### Task 15: 后端集成测试

**Files:**
- Create: `backend/tests/test_trash_integration.py`

**Steps:**
- [ ] **Step 1: 端到端删除→恢复→清理流程** — 扫描图片 → 删除 → 验证 trash 表有记录 + images 表无记录 + 文件在 .trash/ → 恢复 → 验证 images 表有记录 + files 表无记录 → 再次删除 → purge → 验证文件已消失 + trash 表无记录
- [ ] **Step 2: 红线 3 测试** — 构造 trash 行指向外部路径（非 TRASH_DIR 前缀），验证 purge_expired 拒绝并审计
- [ ] **Step 3: 批量操作测试** — 批量删除 3 张 → 批量恢复 2 张 → 验证剩余 1 张仍在 trash
- [ ] **Step 4: 运行测试验证通过并提交**

---

### Task 16: 端到端验证 + 红线 grep + 提交

**Steps:**
- [ ] **Step 1: 重启后端确认 schema 升级无报错** — `trash` 表 + `images.exif_json` 字段由 `create_all` 自动创建
- [ ] **Step 2: curl 验证完整删除/恢复/清理流程** — delete → trash list → restore → delete again → purge
- [ ] **Step 3: 验证 EXIF 全链路** — 新建 root → 扫描（含 EXIF 的 JPEG）→ `GET /api/images/{id}/exif` → 验证返回 JSON 含相机型号等
- [ ] **Step 4: 前端构建** — `pnpm build` 确认无构建错误
- [ ] **Step 5: 运行全部 backend 测试确认无回归**
- [ ] **Step 6: 运行全部 frontend 测试确认无回归**
- [ ] **Step 7: 红线 grep** — `rg -i 'os\.remove' backend/src/myphoto/` 确认只在 `trash.py` 的 purge_expired 中调用；`rg -i 'shutil\.rmtree' backend/src/myphoto/` 确认只在 `routes_admin.py` 的 thumb-cache purge 中调用（已有护栏）
- [ ] **Step 8: 提交并打 tag `phase3-delete-trash-exif`**

---

## Design Decision Summary

1. **Task granularity:** 16 tasks — 8 backend, 7 frontend, 1 integration
2. **Trash directory:** per-root `<root>/.trash/{gallery_id}/{root_id}/` — 同盘 rename 原子操作，跨盘 fallback shutil.move
3. **EXIF:** 20 个常用字段在扫描时抽取，存 `images.exif_json` TEXT NULL；提供 `myphoto rescan-exif` 回补已入库图片
4. **定时清理:** 不实现 daily scheduler，仅启动时 purge_expired + 手动 POST /api/trash/purge
5. **恢复策略:** 轻量扫描（直接写回 images 表 + 重算父目录 counts），不触发完整 root 扫描
6. **红线 3 护栏:** `trash.purge_expired()` 每行校验 trash 文件路径以 TRASH_DIR 为前缀，不匹配则拒绝并写审计
7. **前端:** 复用现有 BrowseView + Lightbox 结构；新增 AdminTrash 页面；批量选择模式为 BrowseView 新增功能
8. **审计:** image_delete / image_restore / trash_purge 三个新事件，所有通过 write_audit 写入（P2 已建立）