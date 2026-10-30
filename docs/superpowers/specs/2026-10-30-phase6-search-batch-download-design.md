# Phase 6 设计：搜索 + 批量下载 + 下载上限配置

日期：2026-10-30
上游需求：`docs/superpowers/specs/2026-07-20-photo-gallery-design.md` §6.3、§6.10（安全 §10.9）、§7.3、§13
Roadmap：`docs/superpowers/plans/2026-07-22-roadmap-p2-p7.md`（P6）

---

## 1. 目标与范围

图库变大后的两项可用性补丁：

1. **搜索**：在某个 root 范围内按文件名/文件夹名子串搜索，图片与文件夹两类结果分页呈现；默认搜当前文件夹子树，可勾选搜整个 root。
2. **批量下载 ZIP**：多选图片（跨翻页/跨搜索结果累积）→ on-the-fly 流式打包下载，服务端零落地；所有登录用户可用。
3. **下载数量上限可配置**（用户新增需求）：`[download] batch_limit`，范围 10–200，默认 100，AdminSettings 可改、热生效。

### 与上游 spec 的偏差（需记录）

- spec §6.3 字面写 `POST /api/download-batch` 直接返回 zip。本站 CSRF 防线要求状态变更请求带 `Content-Type: application/json`，浏览器原生下载（表单/`<a>`）无法带该头；用 `fetch` 取 blob 又会把整个 ZIP 缓冲在标签页内存里（RAW 场景可能数 GB）。**改为票据两步式**：

  ```
  POST /api/download-batch          {image_ids:[...]}  → {ticket, filename}
  GET  /api/download-batch/{ticket}                     → application/zip 流
  ```

  鉴权、数量校验、路径解析、arcname 计算全部在 POST 阶段完成（错误走标准信封）；GET 阶段凭一次性票据走浏览器原生下载。
- spec 搜索契约只有 `q/limit/cursor`，本设计**新增可选 `path` 参数**限定子树；不传 = 整个 root（与 spec "当前 root 子孙范围"一致）。
- spec §10.9 的 500 条批量上限维持硬编码用于批量**删除**；批量**下载**上限改为可配置（10–200，默认 100）。前端选择集硬上限统一为 200。
- 搜索结果图片项在现有 ImageRow 字段外**增加 `relative_path`**（标明所在目录）。

### 明确不做（YAGNI）

- 不做 FTS5 / trigram 全文索引（LIKE 子串对单 root 几十万行足够；spec §13 的 EXIF/日期高级搜索仍是未来项）。
- 不做搜索历史、自动补全、搜索建议。
- 不做跨 root 搜索；搜索严格 per-root。
- ZIP 不落临时文件、不提供 Content-Length、不支持断点续传；票据存内存，不抗进程重启。
- 下载不写审计日志（spec §10.11 列举的必审事件不含下载，单图下载现状也不审计）。
- 批量删除 API 的 500 上限与语义不动。

---

## 2. 后端

### 2.1 搜索 API

```
GET /api/galleries/{gid}/roots/{rid}/search?q=&path=&limit=&cursor=
```

- 鉴权：`Depends(gallery_scope_guard)`，与 folders/images/breadcrumbs 一致；viewer 未授权图库 → 404。
- 参数：
  - `q`：必填，strip 后长度 ≥ 1，否则 400 `bad_request`（"query must not be empty"）。最长 100 字符（超出 400）。
  - `path`：可选，子树根的相对路径，默认 `""`。经 `normalize_relative` 归一化，非法 → 400 `path_invalid`。语义：**该文件夹自身 + 全部子孙**。`path=""` 即整个 root。
  - `limit`：图片结果每页条数，默认 100，范围 1–500。
  - `cursor`：图片结果 keyset 分页不透明串，复用 routes_browse 现有 base64 编解码；固定排序 `filename ASC, id ASC`。非法 cursor → 400 `path_invalid`（沿用现有行为）。
- root 不存在 / disabled → 404（`_get_root_or_404`）；path 指向的 folder 行不存在（已被排除/从未入库）→ 两类结果均为空，不报错（与 list_images 一致）。

**子树过滤**（folder 行 id 集合用 SQL 表达，不预加载）：

- 子树条件（图片与文件夹共用）：`Folder.relative_path = :p OR Folder.relative_path LIKE :p_esc || '/%'`（p 为空时恒真，覆盖整个 root）。
  - LIKE 右值中的 `%`/`_`/`\` 需转义并用 `ESCAPE '\'`，防止 path 本身含这些字符时子树判定失真。

**图片匹配**：

```sql
SELECT images.* FROM images JOIN folders ON images.folder_id = folders.id
WHERE images.root_id = :rid
  AND (folders.relative_path = :p OR folders.relative_path LIKE :p||'/%' ESCAPE '\')
  AND LOWER(images.filename) LIKE :needle ESCAPE '\'
ORDER BY images.filename ASC, images.id ASC
```

- `needle = "%" + escape_like(q.lower()) + "%"`；`LOWER()` 只兜 ASCII 大小写（SQLite LOWER 不处理 Unicode），中文等按原样子串匹配——中文无大小写概念，满足需求。
- cursor 命中后追加 `(filename, id) > (last_filename, last_id)` keyset 条件，取 `limit+1` 判断 next_cursor。
- 响应项 = 现有 list_images ImageRow 全部字段 + `relative_path`（图片相对 root 的完整 posix 路径）。

**文件夹匹配**：

- 条件：root_id 匹配、是子树的**严格后代**（子树根自身不参与匹配——用户已经在该目录里；p="" 时即全部 folder 行）、`name != ""`（root 自身行）、`LOWER(name) LIKE :needle ESCAPE '\'`。
  - 严格后代条件：p 非空时仅 `relative_path LIKE :p_esc || '/%' ESCAPE '\'`；p 为空时恒真。图片结果不受此限制（子树根目录自身的图片正常参与文件名匹配）。
- 排序 `name ASC, id ASC`，**固定上限 50 条**，响应带 `folders_truncated: bool`。
- 响应项复用 list_folders 形状：`{name, relative_path, image_count, descendant_count, cover_thumb_sha1}`。封面取该文件夹自身第一张图（与 list_folders 相同的子查询）；**不做空文件夹借封面 enrich**（N+1，结果页不值得）。
- 文件夹命中不展开其中图片（一个叫 "2024" 的文件夹可能含数千张图）。

**响应**：

```json
{
  "q": "旅行",
  "path": "2024",
  "folders": [{"name": "旅行", "relative_path": "2024/旅行", "image_count": 0,
               "descendant_count": 128, "cover_thumb_sha1": "..."}],
  "folders_truncated": false,
  "images": [{"id": 10, "filename": "IMG_1234.jpg", "relative_path": "2024/旅行/IMG_1234.jpg",
              "width": 4000, "height": 3000, "sha1": "...", "size_bytes": 12345,
              "taken_at": 1710000000, "mtime": 1710000000, "is_raw": false}],
  "next_cursor": null
}
```

`Cache-Control: no-store`。

实现放在 `routes_browse.py`；子树 LIKE 转义与 q 的 LIKE 转义用同一小工具函数，供两处复用。

### 2.2 批量下载（票据两步式）

新模块 `routes_download.py`，prefix `/api`，tag `download`，在 main.py 注册。

#### POST /api/download-batch

请求体 `{"image_ids": [int, ...]}`，Pydantic `min_length=1, max_length=200`（模型硬顶 200；配置值在路由内二次校验）。

流程：

1. `current_user` 鉴权（任何启用用户，viewer 可下载）。
2. 从 `app.state.config.download_batch_limit` 读当前上限；去重保序后数量 > 上限 → 400 `batch_too_large`（"batch exceeds configured limit: N"）。
3. 逐 id 查 `Image`（joinedload `GalleryRoot` 或二次 get）：
   - id 不存在 → 404 `not_found`（整单失败，不做部分成功：选择集来自实时 UI，出现缺失只可能是并发删除，让用户重新选择更明确）。
   - 对每张图 `check_gallery_access(s, user, root.gallery_id)`；viewer 对任一图库无授权 → 404（防枚举）。
4. 解析磁盘路径：`resolve_within_root(root.absolute_path, image.relative_path)`，异常 → 400 `path_invalid`。**此阶段不要求文件存在**（POST→GET 之间可能被删，GET 阶段跳过缺失文件）。
5. 计算 arcname 与条目清单（见 2.3）。
6. 生成 ticket：`secrets.token_urlsafe(16)`；条目存 `app.state.download_tickets`（dict；lifespan 中初始化）：

   ```python
   {"user_id": int, "expires_at": float,
    "filename": "photos-YYYYMMDD-HHMMSS.zip",
    "entries": [{"disk_path": str, "arcname": str, "image_id": int}, ...]}
   ```

   - TTL 300 秒；写入时惰性清理过期项；总量上限 200 条，超出淘汰 `expires_at` 最旧者。
7. 返回 `{"ticket": "...", "filename": "...", "count": n}`。

POST 不写审计。

#### GET /api/download-batch/{ticket}

- `current_user` 鉴权（cookie 随普通导航请求自动携带）。
- 票据不存在 / 已过期 / `user_id` 不匹配 → 一律 404 `not_found`（不区分原因，防枚举）。
- **首次成功读取即从 dict 弹出**（一次性）；随后流在同一响应内产完。
- 响应头：
  - `Content-Type: application/zip`
  - `Content-Disposition: attachment; filename="photos-....zip"; filename*=UTF-8''...`（ASCII filename + RFC 5987 编码；实际 zip 名只含 ASCII 时间戳，保留 filename* 以兜底）
  - `Cache-Control: no-store`
  - 无 Content-Length（流式不可知）。
- 响应体用 `StreamingResponse`，路由声明为**同步 `def`**（FastAPI 自动放线程池，不阻塞事件循环）：
  - 管道：生成器把 ZIP 字节写入一个不可 seek 的 `BytesIO` 风格 sink，外层分块（1 MiB）读出 yield。具体：在 worker 线程内逐文件 `zf.writestr`/`zf.open` 不可行于无缓冲管道，采用「zipfile → 队列/管道」最简实现：用 `os.pipe()`，写线程跑 `zipfile.ZipFile(w, "w", compression=ZIP_STORED, force_zip64=True)`，读侧 generator `read(1MiB)` yield 直到 EOF。
  - 每个 entry：`zinfo = ZipInfo(arcname)`，`zinfo.flag_bits |= 0x800`（UTF-8 文件名），`compress_type=ZIP_STORED`，`force_zip64` 全局开启（500→现 ≤200 张 RAW 仍可能超 4GB/65535 条目边界中的大小边界）。
  - 文件读取时再查存在性：`disk_path` 已消失 → 跳过并记入 missing 列表；不可读（权限）→ 同样跳过。
  - 全部写完后，若 missing 非空，追加 `missing-files.txt`（每行 `image_id  arcname`，UTF-8）。
  - 写线程异常 → 关闭管道；已发出 200 无法改状态码，generator 提前结束（客户端得到损坏 zip 信号），服务器 log exception。此为极端兜底（磁盘错误），不做用户态补偿。
- GET 不写审计。

### 2.3 arcname 规则

1. 去重保序后的条目按 (root_id, image.relative_path) 组织。
2. **单 root**（全部条目同一 root）：arcname = image.relative_path（保留目录树，同目录天然消歧）。
3. **跨 root**：arcname = `{root.label}/{image.relative_path}`。
4. 落盘前对最终 arcname 集合做唯一性校验；理论上 (root, relative_path) 唯一已保证 arcname 唯一，跨 root 时 label 撞名仍可能冲突 → 对后出现者文件名 stem 加 `-{8位hex}` 后缀（与回收站 `_pick_trash_dst` 同款策略）。
5. arcname 一律 posix 分隔符 + UTF-8 标志位；zip 内不带盘符/绝对路径。

### 2.4 下载上限配置

**config.toml 新段**（模板 `_DEFAULT_TEMPLATE` 同步加上）：

```toml
[download]
# 单次批量下载 ZIP 的图片数量上限（10–200），对所有用户生效
batch_limit = 100
```

- `AppConfig.download_batch_limit: int`；loader：缺省 100；`int()` 失败/越界 → **钳到 [10, 200] 区间并 `logging.warning`**（手改非法值不炸启动，同时避开 P5 retention "手改非枚举值后设置页保存必 400" 的别扭——本字段是连续区间，钳制无歧义）。
- `config_writer.py`：`SettingsUpdates.download_batch_limit` + `_FIELD_MAP["download_batch_limit"] = ("download", "batch_limit")`，复用行级 writer（新 section 自动追加）。
- `routes_admin.py` settings：
  - `SettingsPatch.download_batch_limit: int | None`
  - payload/changed 列表带上
  - 校验：非 None 时必须 10 ≤ v ≤ 200，否则 400 `"download_batch_limit must be between 10 and 200"`。
  - PATCH 成功后 reload config（热生效，与现有四项一致）；审计走现有 `settings_update`，changed 自动含该键名。
- 前端要在下载前本地提示上限，但 `/api/admin/settings` 仅 admin 可读。**在 `GET /api/auth/me` 响应中增加 `download_batch_limit`**（从 app.state.config 读；非敏感运行参数），auth store 登录/刷新时已有 me 请求，零额外往返。

### 2.5 错误码

新增 `batch_too_large`（400），加入前端 `api.ts` 的 `ERROR_MSG_ZH`：「一次最多下载 N 张，请减少选择后重试」——错误消息不带 N（N 在前端由 me 的 limit 拼），映射文案保持通用：「超出批量下载数量上限」。

---

## 3. 前端

### 3.1 搜索交互（BrowseView）

- 工具条新增 `components/SearchBox.vue`：文本输入 + 清除（×）按钮 + 「搜索整个 root」勾选框。
  - 在 root 根目录（path === ""）时勾选框隐藏（子树本就等于整个 root）。
  - 输入防抖 300ms 触发；回车立即触发；空 query 不发请求。
- 搜索态写入路由 query：`?q=<enc>&scope=subtree|all`（默认 subtree，省略等同 subtree）。刷新/前进后退保留搜索态；`scope=all` 时后端调用不传 path，否则传当前 path。
- 搜索态下：SubfolderStrip 隐藏；网格区替换为 `components/SearchResults.vue`；PaginationBar 隐藏（搜索用自己的「加载更多」cursor 流）。
- SearchResults：
  - 顶部「匹配的文件夹」区：wrap 网格小卡片（名称 + 图片数，复用文件夹卡片视觉），`folders_truncated` 时末尾显示「仅显示前 50 个文件夹，请细化关键词」。点击卡片 → 跳转该文件夹普通浏览视图（清掉 q）。
  - 图片区：复用现有 JustifiedGrid/MasonryGrid + 用户布局偏好；每张卡片叠加所在目录小字（相对路径去掉文件名那段）。
  - 底部「加载更多」按钮（loading/无 next_cursor 时隐藏）；结果区自身维护已加载 items 与 cursor（**不走 browse store 的分页缓存**，key 语义不同）。
  - 空结果：「未找到匹配的图片或文件夹」。
  - 请求失败：红条 + 中文错误（复用 errorMessage）。
- 点图片 → 在结果视图内打开 ImageLightbox：
  - 数据源 = 当前已加载的全部搜索结果 items（跨文件夹），左右切换即在匹配图片间移动。
  - 路由沿用现有 `.../image/{id}` 形式会与"目录图片"语义冲突；新增查询态 `?q=...&image={id}`（仅前端路由，BrowseView 检测 image query 打开 Lightbox；普通浏览仍用路径段）。切换图片时 replace 更新该 query。
  - Lightbox 头部/底部信息行显示该图所在目录；新增小按钮「在所在文件夹中查看」→ 清 q、跳到该图所在目录（不带 image，定位到页成本高，落在目录第 1 页即可）。
  - ImageLightbox 增加两个**可选** props（普通浏览态不传，行为零变化）：`locationResolver?: (item: ImageRow) => string | null`（返回目录相对路径，非 null 时渲染目录标注行与跳转按钮）、emits `view-in-folder`（payload 当前 item，由 BrowseView 执行路由跳转）。
- 搜索态与多选模式可共存（见 3.2）。

### 3.2 多选模式改造

- 「选择」按钮对 **viewer 也显示**（现状 `auth.isAdmin` 才显示）。
- 选择集跨翻页 / 跨「加载更多」累积，不再因翻页退出；已选项在新批次中回显勾选态（cell 按 selectedIds 渲染，现状机制已支持）。
- 「全选」= 当前已加载批次全部加入；已全选时按钮变「取消全选」（仅清当前批次中的项，保留其他批次选择）。
- **硬上限 200**：继续勾选导致 Set 大小 > 200 时拒绝该项并 toast「一次最多选择 200 张」。
- 清空时机：切换 gid/rid、切换到不同 path（进入子文件夹/面包屑跳转）、搜索词或 scope 变化（含首次发起搜索——结果集合身份变了，避免跨结果集误删误下）、手动退出。翻页和「加载更多」不清空。
- 底部浮动工具条：
  - 所有用户：「下载 ZIP（n）」。
  - admin 额外：「移入回收站」（现有行为，确认弹窗文案沿用）。
- 下载流程：
  1. 已选为空 → 按钮禁用。
  2. 已选数 > me.download_batch_limit → `window.alert`「当前设置单次最多下载 N 张（已选 M 张），请减少选择；管理员可在「设置」中调整，最高 200」，不发请求。
  3. `apiPost("/api/download-batch", {image_ids})` → `{ticket, filename}`；按钮置灰防重复。
  4. 创建临时 `<a href="/api/download-batch/{ticket}" download="{filename}">` 触发点击并移除；浏览器原生下载，cookie 自动携带。不等待下载完成（无法感知），短延迟（~1s）后恢复按钮。
  5. 失败：标准信封 → errorMessage 中文提示（含 batch_too_large 映射）。

### 3.3 AdminSettings

- 新增「批量下载」section（放在「回收站」与「登录安全」之间）：数字输入框 `v-model.number`，min 10 max 200，说明「单次批量下载 ZIP 的图片数量上限，对所有用户生效；范围 10–200」。
- 表单接口 `SettingsForm` 加 `download_batch_limit: number`；normalize/dirty/保存响应重建表单沿用现有模式；空值/非有限数本地拦截，越界交给后端 400 透传（与锁定阈值/会话时长同款处理）。

### 3.4 改动文件

新增：

- `backend/src/myphoto/routes_download.py`
- `frontend/src/components/SearchBox.vue`
- `frontend/src/components/SearchResults.vue`
- 对应后端/前端测试文件

修改：

- `backend`：`routes_browse.py`（search）、`config.py`、`config_writer.py`、`routes_admin.py`（settings）、`routes_auth.py`（me）、`main.py`（注册路由 + lifespan 初始化 tickets）
- `frontend`：`BrowseView.vue`（工具条、搜索态、选择集累积与清空时机、下载动作）、`ImageLightbox.vue`（目录标注/跳转的最小钩子）、`AdminSettings.vue`、`api.ts`（错误码）、`stores/auth.ts`（me 携带 limit）

---

## 4. 安全考量

- 搜索：复用 gallery_scope_guard 与 path 归一化；LIKE 通配符全部转义；no-store。
- 下载：逐图 gallery 授权（viewer 拿不到未授权图库的字节）；`resolve_within_root` 防路径遍历；arcname 去绝对路径/盘符；票据绑定 user_id、一次性、5 分钟过期、不区分失败原因（404 防枚举）。
- GET 票据端依赖 cookie 鉴权，不带 CSRF 头但语义安全（只读、票据一次性、不可跨站构造——攻击者拿不到票据值，SameSite=Lax 下跨站导航也不带状态变更语义）。
- ZIP 炸弹方向：上限 200 个条目；不限制总字节（RAW 图库单张数百 MB 是正常使用），流式处理内存恒定。
- 配置：热生效路径复用 P5 原子 writer；越界值钳制 + warning。

## 5. 测试策略

后端（pytest，基线 461 passed / 6 skipped）：

- 搜索：空 q → 400；q >100 字 → 400；`%`/`_` 按字面量匹配；ASCII 大小写不敏感；中文子串命中；path 子树限定（子孙命中、兄弟不命中）；path 含 `%`/`_` 字符的文件夹正确性；非法 path → 400；被排除目录 → 空结果；图片项含 relative_path；文件夹 50 上限 + truncated；cursor 全量遍历无重复无遗漏；viewer 未授权 → 404；disabled/不存在 root → 404。
- 下载 POST：401；空列表 422；超配置上限 400 batch_too_large（改配置前后）；超 200 条 422；不存在 id → 404；viewer 未授权图库 → 404；去重保序；返回 ticket+filename+count。
- 下载 GET：小图 fixture 走完整 POST→GET，zipfile 读回比对字节；二次 GET/换人 GET/过期 → 404；缺失文件跳过 + missing-files.txt 内容；arcname 单 root 目录树 / 跨 root 前缀 / 撞名后缀；含中文与空格文件名的 arcname UTF-8 标志。
- 配置：settings GET/PATCH 新字段、10–200 校验、审计 changed；config_writer 缺 section 时追加 `[download]` 且 tomllib 自校验通过；loader 缺省 100、非法/越界钳制 + warning；me 带 download_batch_limit。

前端（vitest，基线 203 passed）：

- SearchBox：防抖/回车即时/清除、根目录隐藏勾选、q/scope 同步路由 query。
- SearchResults：文件夹区/图片区渲染、truncated 提示、加载更多、空态、点击开 Lightbox 且 items 为结果全集。
- BrowseView：搜索态隐藏 strip 与分页条；多选跨翻页累积、切 gid/rid/path 与换 q 清空、全选/取消全选语义；200 上限 toast；超 me 上限拦截文案含 N；viewer 工具条只有下载、admin 两个按钮；下载触发 `<a href="/api/download-batch/{ticket}">`（mock POST）。
- Lightbox 结果态：目录标注 + 「在所在文件夹中查看」跳转。
- AdminSettings：新字段加载/脏检查/空值拦截/保存。

## 6. 规模预估

约 11 tasks：后端 4（search、download POST/GET+tickets、config/settings/me、主装配）+ 前端 5（SearchBox、SearchResults、BrowseView 选择/下载、结果 Lightbox 钩子、AdminSettings）+ 测试补齐与收尾 2。与 roadmap 的 ~10 一致。
