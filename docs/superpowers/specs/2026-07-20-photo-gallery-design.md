# myPhotoGallery 需求与设计文档

- 文档版本: 1.0
- 日期: 2026-07-20
- 状态: 待评审

## 1. 项目定位与目标

myPhotoGallery 是一个**基于 Web 的本地图库浏览系统**，运行在个人 / 家庭单机环境（PC / NAS / 小主机）上，通过后端扫描本地图像文件夹，向局域网内及（可选）远程用户提供浏览体验。**不是外链图床**：不提供图片外链、匿名分享、批量上传给第三方引用等能力。

### 1.1 核心用户场景

1. 家庭主用户（Admin）把若干本地目录（如 `D:/Photos`、`E:/Backup/Photos`）作为图库对外服务
2. 家人（Viewer）在手机或电脑上打开浏览器，登录后按目录浏览、查看单图、下载
3. Admin 在管理端配置用户 / 图库 / 访问域 / 排除清单，并能删除单张不想保留的图片（进回收站）

### 1.2 明确的非目标（YAGNI）

- 图片上传给外部 URL 引用（外链图床能力）
- 图片编辑（旋转 / 裁剪 / 滤镜）
- 图片标签 / 收藏 / 智能相册 / 人脸识别
- 多机 / 容器化 / CDN 分发
- 第三方登录（OAuth / SSO）
- PWA / 离线模式
- 定时扫描（仅启动扫 + 手动触发 + 变更触发）
- 幻灯片自动播放
- 多语言（首版仅中文，i18n 结构可留）

## 2. 技术栈

| 层 | 选型 | 备注 |
|---|---|---|
| 后端 | Python 3.11+ / FastAPI | 单进程，同时提供 API 与 SPA 静态托管 |
| 数据库 | SQLite | 单文件，随部署走 |
| 图像处理 | Pillow + pillow-heif + rawpy | RAW 只提取内嵌 JPEG，不做完整解码 |
| 后台任务 | asyncio + `run_in_executor` | 单 worker 串行扫描队列 |
| 认证 | bcrypt 密码散列 + JWT (HS256, HttpOnly cookie) | |
| 前端 | Vue 3 + Vite + `<script setup>` + Pinia + Vue Router | |
| 前端 UI | UnoCSS（推荐）或 Tailwind | 任选其一 |
| 虚拟滚动 | `vue-virtual-scroller` (DynamicScroller) | |
| Lightbox | PhotoSwipe v5 | 内置 PC / 移动手势 |

## 3. 系统架构

### 3.1 部署形态

**单进程 FastAPI 应用**，一条命令启动。生产环境可选择在其前加 nginx 反代（提供 HTTPS / gzip），但非必须。

### 3.2 模块划分

| 模块 | 职责 | 主要依赖 |
|---|---|---|
| `auth` | 登录、密码校验、JWT 签发校验 | DB |
| `access_control` | 依 IP 判 LAN/远程、依角色/图库权限判允许 | DB, request |
| `gallery` | 列目录、列图片、缩略图 / 原图流、下载 | DB, FS |
| `admin` | 用户/图库 CRUD、扫描控制、审计写入 | DB, scanner |
| `scanner` | 后台扫描、增量更新、排除清单命中判定 | DB, FS |
| `thumbnails` | 按需/预生成缩略图，读缓存 | FS |
| `trash` | 单图删除入回收站；恢复；到期清理 | DB, FS |
| `audit` | 关键动作落日志表 | DB |

### 3.3 目录约定

```
<app_root>/
  app.db                        # SQLite 主库
  config.toml                   # 运行时配置
  .cache/
    thumbnails/{sha1[:2]}/{sha1}/{size}.jpg
<root>/.trash/                  # 每个 gallery_root 独立回收站(尽量同盘)
  {gallery_id}/{root_id}/{yyyymmdd}/<original_basename>
```

### 3.4 三条红线约束（架构层强制）

1. **文件夹永不物理删除**：Admin 只能"从图库中排除"某个 Root 或子路径。此类操作只写 `exclusions` 表或删 `gallery_roots` 行，级联清理索引；**代码任何地方不导入 `shutil.rmtree` 用于图库根目录**
2. **单图删除 = 回收站**：`DELETE /api/images/{id}` 走 `os.rename` 到 `.trash/`，不使用 `os.remove`
3. **物理删除只在回收站**：`os.remove` 唯一位点在 `trash.purge()`，路径必须以 `TRASH_DIR` 为前缀，否则抛异常

## 4. 数据模型（SQLite）

所有引用文件系统的字段存**相对路径**（相对所属 root），路径分隔符统一存 `/`。时间统一 Unix 秒。

### 4.1 users

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| username | TEXT UNIQUE | 登录名 |
| password_hash | TEXT | bcrypt 散列 |
| role | TEXT | `admin` \| `viewer` |
| access_scope | TEXT | `lan_only` \| `remote_allowed` |
| enabled | INTEGER | 0/1 |
| created_at | INTEGER | |
| last_login_at | INTEGER NULL | |

### 4.2 user_galleries

| 字段 | 类型 | 说明 |
|---|---|---|
| user_id | INTEGER FK | ON DELETE CASCADE |
| gallery_id | INTEGER FK | ON DELETE CASCADE |
| granted_at | INTEGER | |
| PK | (user_id, gallery_id) | |

### 4.3 galleries

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT UNIQUE | 图库显示名 |
| description | TEXT NULL | |
| created_at | INTEGER | |

### 4.4 gallery_roots

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| gallery_id | INTEGER FK | ON DELETE CASCADE |
| label | TEXT | 显示名 |
| absolute_path | TEXT | 本地绝对路径 |
| enabled | INTEGER | 0/1 |
| last_scan_at | INTEGER NULL | |
| last_scan_status | TEXT NULL | `ok` \| `error` \| `running` |
| last_scan_error | TEXT NULL | |
| UNIQUE (gallery_id, absolute_path) | | |

### 4.5 folders

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| root_id | INTEGER FK | ON DELETE CASCADE |
| relative_path | TEXT | 相对 root；根本身 = `''` |
| parent_id | INTEGER FK NULL | |
| name | TEXT | |
| image_count | INTEGER | 当前层图片数 |
| descendant_count | INTEGER | 含所有子孙的图片数 |
| UNIQUE (root_id, relative_path) | | |
| INDEX (root_id, parent_id) | | |

### 4.6 images

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| root_id | INTEGER FK | ON DELETE CASCADE |
| folder_id | INTEGER FK | ON DELETE CASCADE |
| relative_path | TEXT | |
| filename | TEXT | |
| ext | TEXT | 小写 |
| size_bytes | INTEGER | |
| width | INTEGER NULL | |
| height | INTEGER NULL | |
| sha1 | TEXT | 缩略图缓存 key |
| mtime | INTEGER | 文件系统 mtime |
| taken_at | INTEGER NULL | EXIF DateTimeOriginal 回退 mtime |
| is_raw | INTEGER | 0/1 |
| indexed_at | INTEGER | 首次入库时间 |
| UNIQUE (root_id, relative_path) | | |
| INDEX (folder_id, filename) | | |
| INDEX (sha1) | | |
| INDEX (folder_id, taken_at) | | 支持按拍摄时间排序 |

### 4.7 exclusions

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| root_id | INTEGER FK | ON DELETE CASCADE |
| relative_path | TEXT | 该路径及其子孙全部跳过 |
| excluded_by | INTEGER FK users(id) | |
| excluded_at | INTEGER | |
| reason | TEXT NULL | |
| UNIQUE (root_id, relative_path) | | |

### 4.8 trash

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| gallery_id | INTEGER | 冗余 |
| root_id | INTEGER | |
| original_relative_path | TEXT | 原始位置 |
| trash_relative_path | TEXT | 在 `.trash/…` 下的相对路径 |
| sha1 | TEXT | |
| size_bytes | INTEGER | |
| deleted_by | INTEGER FK users(id) | |
| deleted_at | INTEGER | |
| purge_after | INTEGER | 到期清理时刻 |
| INDEX (deleted_at) | | |
| INDEX (gallery_id, deleted_at) | | |

Root 删除时 `trash` 不 CASCADE，历史条目保留。

### 4.9 audit_log

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | |
| ts | INTEGER | |
| actor_user_id | INTEGER NULL | 未登录事件为 NULL |
| actor_ip | TEXT | |
| action | TEXT | 见下 |
| target | TEXT NULL | 结构化摘要 |
| detail | TEXT NULL | 可选 JSON |
| INDEX (ts DESC) | | |
| INDEX (action, ts DESC) | | |

**action 枚举**：`login_success`, `login_fail`, `user_create`, `user_delete`, `user_disable`, `user_update`, `password_reset`, `gallery_create`, `gallery_delete`, `gallery_update`, `root_add`, `root_remove`, `root_update`, `exclusion_add`, `exclusion_remove`, `image_delete`, `image_restore`, `trash_purge`, `scan_start`, `scan_finish`, `scan_error`, `fs_browse`, `settings_update`。

**保留策略**：默认 180 天，可配置。

### 4.10 表关系

```
users ─┬─< user_galleries >─┬─ galleries ─< gallery_roots ─┬─< folders ─< images
       │                    │                              ├─< exclusions
       │                    │                              └─< trash
       └─< audit_log
```

## 5. 核心流程

### 5.1 扫描流程

**触发**：服务启动（每 root 一次） / Admin 手动 / 新增 root / exclusion 变更。**无定时扫描**。

**并发**：单 worker 协程串行 `asyncio.Queue`；同 root 重复请求去重；CPU 密集丢 `run_in_executor`。

**步骤**（增量语义）：

```
scan(root):
  1. mark root as running; write audit scan_start
  2. build exclusion prefix set
  3. walk root.absolute_path:
     - skip dirs whose relative path hits any exclusion
     - skip hidden dirs (.*), .cache, .trash
     - skip symlinks
     - for each file with allowed extension:
         (root_id, relative_path) as key
         stat = os.stat
         if existing row and mtime==stat.mtime and size==stat.size: skip
         else: compute sha1, extract dimensions/EXIF, upsert images row,
               enqueue thumbnail pregeneration
  4. reconcile: delete images rows under this root not walked or now excluded
  5. rebuild folders rows for this root; recompute counts
  6. mark ok; last_scan_at = now; write audit scan_finish
  on exception: mark error, save error summary, keep old index; write audit scan_error
```

**失败**：单文件读失败跳过并警告；root 不可达标 error 保留旧索引；服务崩溃下次启动重扫最终一致。

### 5.2 权限判定链

FastAPI dependency 链，任一失败立即返回：

1. **Authenticate**：解析 JWT cookie → 缺失/失效返回 401 `unauthenticated`
2. **User active**：`enabled==1`，否则 401
3. **Access scope**：`lan_only` 时校验 client_ip 在私有网段（RFC1918 + 127/8 + IPv6 fc00::/7 + ::1），否则 403 `access_scope_violation`
4. **Role check**：路由声明 `admin`/`viewer` 要求
5. **Gallery/root scope**：Viewer 需在 `user_galleries` 有该 gallery_id；root_id 必须属于该 gallery_id 且 enabled；不满足统一返回 404 防枚举
6. **Path safety**：拒绝含 `..` 段；拼接后 realpath 必须以 root.absolute_path 为前缀
7. **路由处理器**

**IP 获取**：默认 `request.client.host`；配置 `trusted_proxies` 后才读 `X-Forwarded-For`。

### 5.3 单图删除 → 回收站

```
delete_image(image_id, actor):
  transaction:
    img = images.get(image_id)  # 拿 root_id / relative_path / sha1 / size
    src = join(root.absolute_path, img.relative_path)
    trash_rel = "{yyyymmdd}/{basename}"
    if 已存在: trash_rel += "-{short_uuid}"
    dst = join(TRASH_DIR_FOR(root_id), trash_rel)
    os.makedirs(dirname(dst)); os.rename(src, dst)
    insert into trash(...)
    delete from images where id = image_id
    audit_log('image_delete', target=f"image:{image_id}", ...)
```

**跨盘边界**：默认回收站根为 `<root>/.trash/`，与图片同盘。若确因配置跨盘导致 `os.rename` 失败，退回 `shutil.move`。

### 5.4 恢复

```
restore(trash_id):
  dst = join(root.absolute_path, trash.original_relative_path)
  if exists(dst):
      dst = dst + f" (restored {yyyymmdd-HHMMSS})"   # 不覆盖
  os.rename(trash_file, dst)
  delete from trash where id = trash_id
  trigger 轻量扫描其父目录 (让 images 表立即包含它)
  audit_log('image_restore', ...)
```

### 5.5 到期清理（唯一物理删除位点）

**触发时机**：

1. **服务启动时**：应用初始化完成后立即执行一次（覆盖主机长时间关机、错过每日定时点的情况）
2. **每日定时**：默认凌晨 03:17（可配置 `[trash] purge_hour`, `purge_minute`）
3. **手动**：Admin 通过 `POST /api/trash/purge` 触发

三个入口调用同一个 `trash.purge_expired()` 幂等函数：扫 `trash where purge_after < now()`。当 `trash.retention_days = 0` 时新写入的 `purge_after` 设为极大值（等价"从不到期"），任何入口都不会命中：

- 校验 `trash_full_path` 必须以 `TRASH_DIR` 为前缀，否则拒绝
- `os.remove(trash_full_path)`
- 删 `trash` 行；写审计 `trash_purge`

### 5.6 从图库中排除 / 解除

**排除**：写 `exclusions` 行 → 触发受影响 root 扫描（reconcile 阶段清索引）。**无 FS 写。**

**解除**：删 `exclusions` 行 → 触发扫描（重新纳入）。**无 FS 写。**

**移除 Root**：删 `gallery_roots` 行 → 级联清 `folders`/`images`/`exclusions`；`trash` 保留。**无 FS 写。**

### 5.7 缩略图请求

```
GET /api/thumb/{sha1}?size=200|400|1600:
  权限: 校验当前用户至少可见一张 sha1=X 的图 (或 trash 表 fallback)
  cache = f".cache/thumbnails/{sha1[:2]}/{sha1}/{size}.jpg"
  if cache exists: return with immutable ETag
  else:
    src = resolve_any_image_path_for(sha1)   # 先查 images, 再查 trash
    generate_thumb(src, size, cache)          # Pillow / pillow-heif / rawpy.extract_thumb
    return
```

RAW 优先 `rawpy.imread(f).extract_thumb()`；无预览则 `postprocess()`；仍失败返回占位图。

### 5.8 原图下载

```
GET /api/image/{image_id}?download=0|1:
  权限链 + Range 支持
  download=1 → Content-Disposition: attachment
  RAW 的 "原图" 返回从内嵌 JPEG 生成的高清预览 (浏览器无法显 RAW)
```

## 6. API 契约

### 6.1 通用约定

- Base path：`/api`
- 认证：HttpOnly + SameSite=Lax cookie 承载 JWT
- 错误：`{"error": {"code": "...", "message": "..."}}`；code 稳定
- 分页：`?limit=&cursor=`；`next_cursor` 返回不透明串
- 时间戳：Unix 秒整数

### 6.2 认证

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → set-cookie + `{user}` |
| POST | `/api/auth/logout` | 清 cookie → 204 |
| GET | `/api/auth/me` | 当前用户 |
| POST | `/api/auth/change-password` | `{old, new}` |

同 IP 连续 5 次登录失败 → 冷却 15 分钟。

### 6.3 浏览

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/galleries` | 可见图库列表 |
| GET | `/api/galleries/{gid}` | 图库详情 + roots |
| GET | `/api/galleries/{gid}/roots/{rid}/folders?path=` | 子目录 |
| GET | `/api/galleries/{gid}/roots/{rid}/images?path=&sort=&limit=&cursor=` | 当前层图片 |
| GET | `/api/galleries/{gid}/roots/{rid}/breadcrumbs?path=` | 面包屑 |
| GET | `/api/galleries/{gid}/roots/{rid}/search?q=&limit=&cursor=` | 文件名/目录名子串搜（子孙范围） |
| GET | `/api/thumb/{sha1}?size=200\|400\|1600` | 缩略图流 |
| GET | `/api/image/{image_id}?download=0\|1` | 原图流 + Range |
| POST | `/api/download-batch` | `{image_ids: [...]}` → on-the-fly zip |

**sort**：`name_asc`（默认） / `name_desc` / `taken_at_desc` / `taken_at_asc` / `size_desc`。

### 6.4 删除与回收站（Admin）

| Method | Path | 说明 |
|---|---|---|
| DELETE | `/api/images/{image_id}` | 移入回收站 |
| POST | `/api/images/batch-delete` | 批量移入回收站 |
| GET | `/api/trash?gallery_id=&limit=&cursor=` | 回收站列表 |
| POST | `/api/trash/{trash_id}/restore` | 恢复 |
| POST | `/api/trash/batch-restore` | 批量恢复 |
| DELETE | `/api/trash/{trash_id}` | 物理删除单条 |
| POST | `/api/trash/purge` | `{gallery_id?, root_id?, before?, confirm=true}` |

### 6.5 管理端 — 用户

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/admin/users` | 列表 |
| POST | `/api/admin/users` | `{username, password, role, access_scope, gallery_ids}` |
| GET | `/api/admin/users/{uid}` | 详情 + 授权图库 |
| PATCH | `/api/admin/users/{uid}` | 更新属性 |
| POST | `/api/admin/users/{uid}/reset-password` | `{new_password}` |
| DELETE | `/api/admin/users/{uid}` | 删除；最后一个 admin 保护 |

### 6.6 管理端 — 图库与 Root

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/admin/galleries` | 全部图库 |
| POST | `/api/admin/galleries` | 新建 |
| PATCH | `/api/admin/galleries/{gid}` | 改名/描述 |
| DELETE | `/api/admin/galleries/{gid}` | 移除图库（红线：仅清索引） |
| POST | `/api/admin/galleries/{gid}/roots` | `{label, absolute_path}` → 校验路径 + 触发扫描 |
| PATCH | `/api/admin/galleries/{gid}/roots/{rid}` | 改 label / enabled |
| DELETE | `/api/admin/galleries/{gid}/roots/{rid}` | 从图库移除（红线） |
| POST | `/api/admin/galleries/{gid}/roots/{rid}/rescan` | 触发重扫 |
| GET | `/api/admin/galleries/{gid}/roots/{rid}/scan-status` | 扫描状态 |
| GET | `/api/admin/galleries/{gid}/roots/{rid}/exclusions` | 排除清单 |
| POST | `/api/admin/galleries/{gid}/roots/{rid}/exclusions` | 新增排除 |
| DELETE | `/api/admin/galleries/{gid}/roots/{rid}/exclusions/{eid}` | 解除排除 |
| POST | `/api/admin/browse-fs` | `{path?}` → 目录选择器，仅列目录 |

### 6.7 管理端 — 系统 & 审计

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/admin/status` | 概览 |
| POST | `/api/admin/thumb-cache/purge` | 清空缩略图缓存 |
| GET | `/api/admin/audit?action=&actor=&from=&to=&limit=&cursor=` | 审计翻页 |
| GET | `/api/admin/settings` | 配置项 |
| PATCH | `/api/admin/settings` | 修改配置 |

### 6.8 `/api/admin/browse-fs` 安全护栏

1. 仅 `role=admin` **且** 客户端 IP 属私有网段（独立强制，不看用户的 `access_scope`）
2. 只列目录，不列文件
3. Windows 默认返回盘符列表；Linux/macOS 默认 `/`
4. 不解析 symlink
5. 归一化拒绝 `..` 段
6. 结果上限 5000，超出截断
7. 每次调用写审计 `fs_browse`

### 6.9 错误码

`unauthenticated`, `invalid_credentials`, `login_locked`, `password_too_weak`, `access_scope_violation`, `admin_fs_lan_only`, `forbidden`, `not_found`, `path_invalid`, `path_not_readable`, `root_offline`, `last_admin_protected`, `scan_in_progress`, `batch_too_large`, `conflict`, `internal_error`。

### 6.10 HTTP 缓存

- 缩略图：`Cache-Control: public, max-age=31536000, immutable`
- 原图：`Cache-Control: private, max-age=86400`，`ETag = sha1`，支持 `Range`
- 列表 API：`Cache-Control: no-store`
- SPA 打包资源：哈希文件名 `immutable`；`index.html` `no-cache`

## 7. 前端界面

### 7.1 路由

```
/login
/                          → 重定向到 /galleries 或 /login
/galleries                 → 图库卡片列表
/galleries/:gid            → root 卡片列表（单 root 时自动 replace）
/galleries/:gid/r/:rid/*path             → 浏览页
/galleries/:gid/r/:rid/image/:iid        → Lightbox 深链
/admin                     → 概览
/admin/users
/admin/galleries
/admin/galleries/:gid
/admin/trash
/admin/audit
/admin/settings
```

### 7.2 响应式断点

- `< 640px`：手机竖屏
- `640 ~ 1024px`：平板 / 横屏手机
- `> 1024px`：PC

### 7.3 BrowseView（核心浏览页）

**PC 布局**：面包屑 + 工具条（排序、搜索）→ 子目录条（横向滚动，>4 个卡片）→ Justified 密铺图片网格（`vue-virtual-scroller` 虚拟滚动）。

**移动布局**：面包屑折叠为返回按钮 + 当前目录 + 菜单；子目录条改 2 列紧凑卡片；密铺 2~3 行高（行高 160~220px 自适应）；工具条 sticky。

**图片元素**：`<img loading="lazy" srcset="thumb200 200w, thumb400 400w" />`；占位为原比例浅灰块。

**滚动位置保留**：`useBrowseStore` 按 `(gid, rid, path, sort)` 缓存分页 + 滚动位置，LRU 上限 20 组。

**Admin 浮层**：图片悬停右上角小三点 → "移入回收站"（二次确认，含预览与路径）；移动端长按弹出。

### 7.4 Lightbox（PhotoSwipe v5）

**PC**：←→ 或点击切换；滚轮缩放；双击 100%；Esc 关闭；底部信息条（文件名 / 尺寸 / 拍摄时间 / 下载 / 删除）；顶部 `i` 按钮展开 EXIF。

**移动**：左右滑动切换；双指捏合；双击放大；下滑关闭；长按菜单。

**加载策略**：
1. 立即显 thumb 400（列表已缓存）
2. 请求 thumb 1600 替换
3. 100% 或双击时才拉原图 `/api/image/{id}`，支持 Range
4. 相邻图预取 thumb 1600

**URL 与 History**：`router.push` 变 URL 不重刷；切图 `router.replace`；关闭 `router.back`；深链能直接开图。

### 7.5 管理端界面

**AdminOverview**：三张概览卡（图片 / 图库 / 用户）+ 两张空间卡（缩略图缓存 / 回收站）+ 活动扫描列表 + 最近 20 条审计。

**AdminUsers**：表格（用户名 / 角色 / 访问域 / 启用 / 授权图库数 / 最近登录）+ 新建/编辑/重置密码/禁用/删除；最后一个 admin 保护。

**AdminGalleryEdit**：
- 图库名/描述可编辑
- Root 卡片列表：label + 绝对路径 + 图片数 + 上次扫描 + [重扫][禁用][移除]；"移除"红色警示 + 二次确认，弹窗强调"不删除本地文件"
- 加号卡 → 目录选择器（`/api/admin/browse-fs`）
- 排除清单：表格 + 新增排除（复用目录选择器限定该 root）

**AdminTrash**：过滤（图库 / 时间范围）+ 表格（缩略图 / 原路径 / 图库 / 删除人 / 删除时间 / 到期时间 / 恢复 / 立即删除）+ 批量恢复/删除 + 清空（勾选"我理解不可恢复"）。

**AdminAudit**：表格 + 过滤 + 无限滚动 + 导出 CSV。

**AdminSettings**：回收站保留天数（7/30/90/never，默认 30）；登录锁定阈值；trusted_proxies；缩略图预生成尺寸多选；会话过期时间。

### 7.6 Pinia store

| Store | 职责 |
|---|---|
| `useAuthStore` | 当前用户、`isAdmin` |
| `useGalleriesStore` | 图库/root 列表缓存 |
| `useBrowseStore` | 浏览分页、排序、滚动位置（LRU 20 组） |
| `useAdminStore` | 管理端各面板数据 |
| `useToastStore` | 全局通知 |

### 7.7 网络层

- `apiClient` 封装 fetch：自带 cookie；401 自动跳登录；429/5xx 重试 1 次；错误统一 toast
- 缩略图与原图直接 `<img src>`，靠 cookie 认证

### 7.8 无障碍

- 键盘 Tab 顺序合理；Lightbox ←→ 切换 / Esc 关闭
- 图片 `alt = filename`
- 表单错误 `aria-invalid` + 邻近错误文本
- 触屏最小点击 44×44 CSS px
- 深色模式跟随 `prefers-color-scheme`

## 8. 图像格式支持

| 类别 | 扩展名 | 处理方式 |
|---|---|---|
| Web 通用 | jpg, jpeg, png, gif, webp | Pillow 直读 |
| 现代格式 | heic, heif, avif | pillow-heif 插件 |
| RAW | cr2, cr3, nef, arw, dng, orf, rw2, raf, pef | rawpy 提取内嵌 JPEG；失败 postprocess；仍失败占位图 |

未识别扩展名的文件被扫描忽略。

## 9. 配置项

`config.toml` 顶层键：

```toml
[app]
listen_host = "0.0.0.0"
listen_port = 8080
jwt_secret = "<auto-generated on first launch>"
session_hours = 8

[trash]
retention_days = 30              # 允许值: 7 / 30 / 90 / 0 (0 = 从不自动清理)
purge_hour = 3                   # 每日清理触发小时 (0-23)
purge_minute = 17                # 每日清理触发分钟 (0-59)
# 服务启动时无条件执行一次到期清理,无需配置

[thumbnails]
sizes = [200, 400, 1600]

[security]
trusted_proxies = []             # e.g. ["127.0.0.1", "10.0.0.0/8"]
login_lockout_threshold = 5
login_lockout_minutes = 15

[audit]
retention_days = 180

[scan]
# 无定时扫描,只留占位与手动触发相关设置
sha1_buffer_kb = 64
```

## 10. 安全考量

1. **密码**：bcrypt cost=12；密码强度：至少 8 字符，前端与后端双重校验，后端为唯一权威（返回 `password_too_weak` 错误码）
2. **JWT**：HS256，签名密钥文件权限 0600；无 JWT 主动作废（MVP 不做 blacklist）
3. **Cookie**：HttpOnly、SameSite=Lax、生产开 Secure
4. **CSRF**：SameSite=Lax 已阻断跨站表单；对状态变更 API 额外要求 `Content-Type: application/json`
5. **路径遍历**：所有含相对路径的请求归一化 + `..` 拒绝 + realpath 前缀比对
6. **Symlink**：Scanner 和运行时访问都跳过
7. **IP 伪造**：仅在 `trusted_proxies` 配置后信任 `X-Forwarded-For`
8. **枚举防护**：无权访问统一 404，不区分"不存在"与"无权"
9. **批量上限**：批量删除 / 下载最多 500 条
10. **`/api/admin/browse-fs`**：Admin + 私网 IP 双重强制
11. **审计**：登录、用户/图库/root 变更、删除、恢复、排除、清缓存、配置修改必写

## 11. 部署与初始化

**首次启动**：
1. 若 `app.db` 不存在，创建 schema 并写入初始 admin 账号（用户名 `admin`，密码打印到 stdout 一次）
2. 若 `config.toml` 不存在，写入默认模板并生成 jwt_secret
3. **执行一次到期清理** `trash.purge_expired()`（防主机长时间关机漏掉每日定时）
4. 对每个 `enabled=1` 的 gallery_root 入队一次扫描
5. 启动每日定时清理调度器
6. 打印监听地址

**依赖**：Python 3.11+；`pip install -r requirements.txt`（fastapi, uvicorn, sqlalchemy, aiosqlite, bcrypt, python-jose, pillow, pillow-heif, rawpy, python-multipart）

**前端**：`pnpm install && pnpm build` 生成 `dist/`，被 FastAPI 挂载为静态目录

**运行**：`uvicorn app:app --host 0.0.0.0 --port 8080`

**建议**：生产建议 nginx 反代提供 HTTPS，`trusted_proxies = ["127.0.0.1"]`；仅家庭 LAN 使用可裸跑

## 12. 需求可追溯性映射

| 用户原始需求 | 对应设计条款 |
|---|---|
| 后端打开本地文件夹 | §5.1 Scanner |
| 过滤常见图像文件 | §8 图像格式支持 |
| 单张浏览 | §7.4 Lightbox |
| 多张预览 | §7.3 密铺网格 |
| 基本缩放、切换 | §7.4 Lightbox 交互 |
| 管理端用户登录权限管理 | §4.1-4.2、§6.5、§7.5 AdminUsers |
| LAN / 远程访问权限 | §5.2 步骤 3、§4.1 `access_scope` |
| 配置用户允许访问的图库文件夹 | §4.2 user_galleries、§7.5 AdminUsers |
| PC 与移动端 | §7.2 断点、§7.3 移动布局、§7.4 移动手势 |
| 不允许删除本地文件夹，只从图库排除 | §3.4 红线 1、§4.7 exclusions、§5.6 |
| 有权限用户可删单图 | §6.4 DELETE /api/images/{id}、§5.3 |
| 回收站 | §4.8 trash、§5.3-5.5、§7.5 AdminTrash |

## 13. 后续可扩展但不在本轮

- 图片标签 / 收藏 / 相册
- EXIF / 拍摄时间高级搜索
- 时间线视图切换
- 幻灯片 / PWA
- 用户端上传
- 外链分享
- 多语言
- 独立扫描进程 + Redis 队列
- Token 主动作废机制
