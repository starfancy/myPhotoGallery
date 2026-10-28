# Phase 5 设计：排除清单 + AdminSettings + 每日定时清理

日期：2026-07-28 立项骨架，2026-10-28 完善设计
上游需求：`docs/superpowers/specs/2026-07-20-photo-gallery-design.md` §4.7、§5.6、§6.6、§6.7、§7.5、§9
Roadmap：`docs/superpowers/plans/2026-07-22-roadmap-p2-p7.md`（P5）

---

## 1. 目标与范围

两件事一次性上线：

1. **排除清单（exclusions）**：admin 可以把某个 root 下的子目录从图库中排除——该目录及其子孙在扫描时整体跳过，已入索引的内容在 reconcile 阶段清掉。**全程无文件系统写操作**（spec §5.6，红线）。解除排除后重扫即恢复。
2. **AdminSettings 完整版**：集中配置四项运行参数，写回 `config.toml`，热生效无需重启。

另含两个闭环修补：

3. **每日定时回收站清理**：`[trash] purge_hour/purge_minute` 早已解析但从未使用（main.py 注释"定时器延后"），本期补上每日 asyncio 定时任务。
4. **`retention_days = 0`（永不自动清理）语义修复**：现有删除逻辑写 `purge_after = now + 0`，会导致下次清理立刻物理删除，与 spec §9「0 = 从不自动清理」矛盾。

### 与上游 spec 的偏差（需记录）

- **砍掉 AdminSettings 的"缩略图预生成尺寸多选"**。现状是缩略图全部按需懒生成（扫描不预生成），懒生成天然保证"不请求就不生成、不占磁盘"；让尺寸可配在没有预生成的前提下价值很低，还会逼前端三个硬编码尺寸点（PhotoCell 200/400、SubfolderStrip 200、ImageLightbox 400/1600）全部动态化。经用户确认 YAGNI，`ALLOWED_SIZES = {200,400,1600}` 维持硬编码。
- **登录锁定时长（`login_lockout_minutes`）不进 UI**，留在 `config.toml`；设置页只暴露阈值。
- 审计保留天数 `[audit] retention_days`（spec §9 有键，但当前代码既不解析也无清理任务）不在本期范围。

### 明确不做（YAGNI）

- 不做排除规则的 glob/通配模式，只支持精确目录。
- 不做单文件排除，只支持目录（目录及其子孙整体跳过）。
- 不做排除变更的扫描进度特殊展示，复用既有扫描状态轮询。
- 不做设置变更的审计 diff 详情，只记录变更的键名。
- 不做 config.toml 写并发锁（admin 低频操作 + 原子替换已足够）。

---

## 2. 数据模型

### 2.1 新表 `exclusions`（spec §4.7）

| 字段 | 类型 | 约束 |
|---|---|---|
| id | INTEGER | PK |
| root_id | INTEGER | FK → gallery_roots.id，ON DELETE CASCADE |
| relative_path | TEXT | 相对 root 的 posix 路径，目录；该路径及其子孙全部跳过 |
| excluded_by | INTEGER NULL | FK → users.id，ON DELETE SET NULL |
| excluded_at | INTEGER | epoch 秒 |
| reason | TEXT NULL | 可选备注，最长 500 |

- `UNIQUE (root_id, relative_path)`，约束名 `uq_exclusion_path_per_root`。
- 索引：`Index("ix_exclusion_root", "root_id")`（扫描开头按 root 加载）。
- `excluded_by` 可空 + SET NULL：删用户不能被历史排除行的外键卡住，排除规则本身保留。
- `relative_path` 永远存 posix 形式（`"2024/临时导出"`），root 自身用 `""`，但 API 禁止排除 root 本身。
- `create_all` 自动建表（同 P4 user_galleries），无需迁移。

### 2.2 `trash.purge_after` 的"永不"哨兵

不做表结构迁移（现有轻量迁移只支持 ADD COLUMN，SQLite 无法直接放宽 NOT NULL，表重建成本不值）。

在 `trash.py` 定义模块常量：

```python
# 2286-11-20 左右；retention_days=0（永不自动清理）时作为 purge_after 哨兵。
# purge_expired 的查询是 purge_after < now，哨兵永不命中。
NEVER_PURGE_TS = 9_999_999_999
```

`routes_images.delete` 写回收站行时（现状是无条件 `now + retention_days*86400`）：

```python
purge_after = now + retention_days * 86400 if retention_days > 0 else NEVER_PURGE_TS
```

batch-delete 路径走同一删除逻辑，一并生效。

AdminTrash 前端到期时间列：`purge_after >= NEVER_PURGE_TS`（前端常量 9_999_999_999）显示"永不"。

---

## 3. 后端 API

全部挂在既有 `routes_admin.py`，前缀 `/api/admin`，鉴权 `admin_required`（步骤 1-3 自动继承）。错误码全部复用 §6.9 既有集合，不新增。

### 3.1 排除清单（spec §6.6）

```text
GET    /api/admin/galleries/{gid}/roots/{rid}/exclusions
POST   /api/admin/galleries/{gid}/roots/{rid}/exclusions
DELETE /api/admin/galleries/{gid}/roots/{rid}/exclusions/{eid}
```

**GET 200**：

```json
{
  "root_id": 3,
  "entries": [
    {
      "id": 12,
      "relative_path": "2024/临时导出",
      "reason": null,
      "excluded_by": 1,
      "excluded_by_username": "admin",
      "excluded_at": 1782600000
    }
  ]
}
```

root 不属于 gid / 不存在 → 404 `not_found`。`Cache-Control: no-store`（与其他管理端列表一致）。LEFT JOIN users 取用户名；`excluded_by` 为 NULL 时用户名也是 null。

**POST** 请求体（收**绝对路径**，与 DirectoryChooser 的 confirm 形态一致）：

```json
{ "absolute_path": "D:\\Photos\\2024\\临时导出", "reason": "可选，最长500" }
```

服务端校验顺序（全部权威，不信任前端）：

1. root 存在且 `root.gallery_id == gid`，否则 404。
2. `p = Path(absolute_path).resolve()`；`root_p = Path(root.absolute_path).resolve()`。
3. `p == root_p`（排除 root 自身）→ 400 `path_invalid`。
4. `p` 不在 root 之内（POSIX 段级 `relative_to`，禁止盘符/前缀花招）→ 400 `path_invalid`。
5. `p.is_symlink()` → 400 `path_invalid`（与 browse-fs 护栏一致，不解析符号链接）。
6. 不存在或不是目录 → 400 `path_not_readable`。
7. `(root_id, relative_path)` 已存在 → 409 `conflict`。
8. reason 非空时 strip 后截断/拒绝超长（>500 → 422 由 pydantic 约束）。

落库（relative_path 用 `p.relative_to(root_p).as_posix()`），写审计：

- action `exclusion_add`，target `exclusion:{id}`，detail 形如 `root={rid} path={relative_path}`（有 reason 时追加 `reason=...`，整体截断到 200 字符）。

提交后调 `scanner.request_rescan(rid)`（见 §4.2），返回 201 + 新行（同 GET 条目形状）。

**DELETE**：校验 exclusion 存在且属于该 root（跨 gid/rid 访问 → 404，防枚举）→ 审计 `exclusion_remove`（target/detail 同上）→ 删行 → `request_rescan(rid)` → 204。

### 3.2 browse-fs 限定 root（防呆，非安全边界）

`POST /api/admin/browse-fs` 请求体增加**可选**字段：

```json
{ "path": "D:\\Photos", "root_id": 3 }
```

- 不带 `root_id`：行为与现状完全一致（添加根目录场景，可浏览整机，LAN 护栏 + fs_browse 审计不变）。
- 带 `root_id`：
  1. root 必须存在，否则 404；
  2. `path` 为空时默认定位到该 root 的 `absolute_path`（而不是盘符列表 / `/`）；
  3. 任何目标路径 resolve 后不在 root 之内 → 400 `path_invalid`（含手输路径逃逸、`..`——`..` 仍先走既有 rule 5）；
  4. symlink / 不可读等既有护栏不变；
  5. 审计 detail 追加 `root={rid}`。

### 3.3 设置（spec §6.7）

```text
GET   /api/admin/settings
PATCH /api/admin/settings
```

**GET 200**：

```json
{
  "trash_retention_days": 30,
  "login_lockout_threshold": 5,
  "trusted_proxies": [],
  "session_hours": 8
}
```

**PATCH** 请求体（所有字段可选，部分更新）：

```json
{
  "trash_retention_days": 90,
  "login_lockout_threshold": 5,
  "trusted_proxies": ["127.0.0.1", "10.0.0.0/8"],
  "session_hours": 8
}
```

校验规则（语义校验失败统一 400 `bad_request`，message 说明具体字段；pydantic 形状错误仍走默认 422）：

| 字段 | 规则 |
|---|---|
| trash_retention_days | 仅允许 `0 / 7 / 30 / 90`（0 = 永不自动清理） |
| login_lockout_threshold | 整数 1–100 |
| trusted_proxies | 字符串数组，≤16 条；每条必须能被 `ipaddress.ip_address(x)` 或 `ip_network(x, strict=False)` 解析；去重后存；空列表合法 |
| session_hours | 整数 1–720 |

**写盘流程**（§5 详述 writer）：

1. 校验全部通过；
2. 调 config_writer 更新 `config.toml`（原子替换：临时文件 + `os.replace`）；
3. writer 已保证"渲染结果先过 tomllib 自校验才原子落盘"（见 §5），落盘失败（磁盘满/权限）时原文件不受影响，返回 500 `internal_error` 且不替换 `app.state.config`；成功后重新 `load_or_init` 并热替换 `app.state.config`；
4. 写审计 `settings_update`，target 固定 `"settings"`，detail 记录变更键名数组，如 `{"changed": ["trash_retention_days"]}`；不记录值（trusted_proxies 属网络拓扑信息，避免进日志）。
5. 返回 GET 同形状。

热生效说明（全部调用点本来就逐请求读 `app.state.config`）：

- trusted_proxies：下一个请求的 IP 解析即生效；
- 锁定阈值：下一次登录失败计数判定即生效（§6 接线）；
- session_hours：下一次登录签发 cookie 的 max_age 生效，既有会话不变；
- trash_retention_days：下一次删除图片的 purge_after 生效；既有回收站行不回刷。
- `jwt_secret` 不在可写字段中，会话不会因保存设置而失效。

---

## 4. 扫描器改动（`scanner.py`）

### 4.1 walk 剪枝

`_walk_root(root)` 签名扩展为 `_walk_root(root, excluded_rel_paths: set[str])`。

在 `os.walk(topdown=True)` 循环中，得到当前目录相对路径 `relative_dir` 后过滤 `dirnames`：

```python
def _is_excluded(rel_dir: str, name: str) -> bool:
    child_rel = f"{rel_dir}/{name}" if rel_dir else name
    return child_rel in excluded_rel_paths

dirnames[:] = [d for d in dirnames if <既有三条规则> and not _is_excluded(relative_dir, d)]
```

- 按**路径段精确匹配**，不能用字符串前缀：排除 `a/b` 不得误伤 `a/bc`。
- os.walk topdown 从 dirnames 移除目录即不会下降，其子孙文件天然不进入 walked_files——被排除目录里**已入库**的图片因不在 `indexed_paths` 中，走既有 Phase 3c reconcile 被删、空文件夹被 `_remove_unwalked_folders` 清理。纯 DB 操作。
- 排除行指向的目录在磁盘上已不存在时：walk 永不命中，无副作用。

`_scan_transaction` 在 walk 之前开一个短只读 session 加载 `select(Exclusion.relative_path).where(root_id==rid)`，随 root 信息一起读出，然后释放连接。

### 4.2 request_rescan 与 dirty 重跑

现有 `enqueue` 对运行中的 root 静默去重，排除变更可能被吞掉。新增：

```python
async def request_rescan(self, root_id: int) -> None:
    async with self._lock:
        status = self._status.get(root_id)
        running = status is not None and status.status == "running"
    if running:
        async with self._lock:
            self._redirty.add(root_id)
    else:
        await self.enqueue(root_id)  # queued 情况由 enqueued 去重覆盖
```

- `self._redirty: set[int]`，`__init__` 初始化。
- worker `_loop` 在 `finally` 中（discard enqueued 之后）检查：`root_id in _redirty` → 移除标记并再次 `enqueue`。状态经历 running → queued → running，前端轮询天然可见。
- 连续多次变更只重跑一次（set 语义）。

### 4.3 启动入队不变

lifespan 现有"启动时为所有 enabled root 入队"保留；排除表在扫描开头读取，自动生效。

---

## 5. config.toml 行级 writer（新模块 `config_writer.py`）

不引入 tomli_w（会重排文件、丢光中文注释——config.toml 是给人看的运维文档）。

接口：

```python
def update_settings_file(path: Path, updates: SettingsUpdates) -> None
```

其中 `SettingsUpdates` 是本期四个字段的 dataclass（可选值，None 表示不动）。

算法：

1. 先 `tomllib.loads` 现有文件，定位每个受管 key 所属 section（`[app] session_hours`、`[trash] retention_days`、`[security] trusted_proxies / login_lockout_threshold`）。
2. 逐行扫描：识别当前 section（`[xxx]` 行）与 `key = ...` 行；命中受管键则**整行替换**为新渲染值，其余行（注释、空行、未知键如 `hash_workers`、purge_hour/minute）原样保留。
3. section 存在但键缺失 → 在该 section 末尾插入；section 缺失 → 在文件末尾追加整个 section。
4. 渲染：int 直接 `str(int)`；字符串列表渲染为单行内联数组 `["127.0.0.1", "10.0.0.0/8"]`（双引号 + 转义）。
5. **全部渲染在内存完成 → `tomllib.loads(渲染结果)` 自校验通过 → 临时文件 `config.toml.tmp` + `os.replace` 原子落盘**。tmp 文件始终清理（finally unlink，不存在忽略）。
6. 文件编码 utf-8；按"保留行尾"处理：读入时检测原文件是否含 CRLF（Python 在 Windows 上 `write_text` 生成的默认模板是 CRLF），渲染时用检测到的行尾拼接，以 `newline=""` 落盘，避免整文件行尾翻转造成无意义 diff。

`config.toml` 默认模板 `_DEFAULT_TEMPLATE` 无需改动（四个键都已存在）。

---

## 6. 登录锁定阈值接线（`routes_auth.py`）

现状：`_LOCKOUT_THRESHOLD = 5`、`_LOCKOUT_WINDOW_SEC = 15*60` 模块常量，config 里的 `login_lockout_threshold/minutes` 解析了却没用。

改动：

- `_is_locked(state, ip, threshold)` / `_record_fail(state, ip, window_sec)` 改为接收参数；
- login handler 从 `request.app.state.config` 读 `login_lockout_threshold` 与 `login_lockout_minutes*60` 传入；
- 既有测试默认值（5 / 15min）不变。

锁定计数结构是进程内 dict（重启清空），本期不持久化（维持现状）。

---

## 7. 每日定时清理（lifespan）

`main.py` lifespan 在启动清理之后起一个后台任务 `_daily_purge_loop`，shutdown 时 cancel：

```python
async def _daily_purge_loop(sm, config_getter):
    while True:
        cfg = config_getter()  # 每次读 app.state.config，设置改时刻也能跟上
        now_dt = datetime.datetime.now()
        nxt = next_daily_run(now_dt, cfg.trash_purge_hour, cfg.trash_purge_minute)
        await asyncio.sleep(max(1.0, (nxt - now_dt).total_seconds()))
        try:
            async with sm() as session:
                result = await purge_expired(session, actor_user_id=None, actor_ip="scheduled")
                if any([result["purged"], result["blocked"], result["missing"], result["errors"]]):
                    await write_audit(session, "trash_purge", None, "scheduled",
                                      target="scheduled",
                                      detail=f"purged={result['purged']} blocked={result['blocked']} "
                                             f"missing={result['missing']} errors={result['errors']}")
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduled purge_expired failed")
```

纯函数放在 `trash.py`（或小工具模块）供单测：

```python
def next_daily_run(now_dt: datetime.datetime, hour: int, minute: int) -> datetime.datetime
```

- 当天 `hour:minute` 已过 → 次日同一时刻；未到 → 今天；
- hour/minute 越界（被手改配置）回退 03:30 并记 warning（防御，不抛异常）。

哨兵行（purge_after=NEVER_PURGE_TS）天然不被 `purge_after < now` 命中。

---

## 8. 前端

### 8.1 AdminSettings 视图（新）

- 路由 `/admin/settings`（requiresAdmin），懒加载；AppHeader「管理」菜单在「用户」之后加「设置」。
- `onMounted` GET 填充；表单：
  - **回收站保留天数**：radio 四选一 `7 / 30 / 90 / 永不`（值分别 7/30/90/0），下方灰色说明"对新删除的图片生效；已在回收站中的条目不受影响"。
  - **登录锁定阈值**：number input（min 1 max 100），灰字说明"连续登录失败达到此次数后将被临时锁定；锁定时长在 config.toml 中配置"。文案不写死分钟数。
  - **trusted_proxies**：列表编辑器，每行一个文本输入 + 删除按钮，底部 [+ 添加]；占位符 `127.0.0.1` / `10.0.0.0/8`；空行保存时忽略。
  - **会话时长**：number input（1–720）单位"小时"，说明"对新登录生效"。
- [保存]：脏检查（无变更禁用），PATCH 全量四项；成功 toast "设置已保存"，失败显示后端 message（错误码中文映射沿用 api.ts；`bad_request` 已有通用文案，后端 message 作为补充直接展示在表单顶部）。
- 不做"放弃更改"之外的复杂状态；离开页面不拦截（YAGNI）。

### 8.2 排除清单面板（AdminGalleryEdit 改造）

- 每张 root 卡片按钮行在「重扫/禁用/移除」之外加 **[排除目录]**。
- 点击展开卡片内联面板（同一卡片区域向下展开）：
  - 首次展开懒加载 `GET …/exclusions`；之后随卡片 2s 轮询之外不自动刷新（操作后局部刷新）。
  - 表格：相对路径 / 原因 / 操作人 / 排除时间；空态文字"尚未排除任何目录"。
  - 每行 [解除]：`window.confirm` 二次确认，文案"解除后该目录将在下次扫描时重新纳入图库，本地文件不会被改动。"
  - 底部 [+ 添加排除目录]：打开 DirectoryChooser，props `:start-path="r.absolute_path"` 与新增的 `:root-id="r.id"`；确认选择后 `window.prompt` 询问备注（可留空，沿用添加 root 时 prompt 标签的交互风格），POST absolute_path + reason；成功后关闭面板重开刷新 + loadGallery（触发扫描状态刷新）。
- 扫描进行中不禁用添加/解除（dirty 重跑保证最终生效），按钮旁不做特殊提示。

### 8.3 DirectoryChooser 改造

- 新增可选 prop `rootId?: number`；`browse()` 请求体在 rootId 存在时带 `root_id`。
- 其他逻辑零改动（400 path_invalid 时错误显示已有）。

### 8.4 AdminTrash 到期列

`purge_after >= 9_999_999_999` 显示"永不"。

---

## 9. 红线与安全

1. **排除全流程零 FS 写**：POST/DELETE exclusions 只写 DB；索引清理靠扫描 reconcile 既有逻辑（只删 DB 行）。实现完成后 grep 确认 exclusions 路径下无 `os.remove/rename/shutil`。
2. 路径校验双端：browse-fs 限定只是防呆，POST 服务端校验是唯一权威；统一用 `resolve()` 后的段级 `relative_to`，禁止字符串前缀。
3. settings 写盘不碰 `jwt_secret`；原子替换；写前 TOML 自校验。
4. trusted_proxies 非法值拒绝保存，防止写出导致启动失败/IP 解析异常的配置。
5. 权限：所有新端点 admin_required；exclusions 操作与 settings 全部进审计。
6. 红线 grep 收尾：
   - `os.remove` 仍只在 `trash.py`；
   - `shutil.rmtree` 仍只在 routes_admin 缩略图缓存清理；
   - 新代码无其他文件删除位点。

---

## 10. 测试策略

### 后端（pytest，沿用 TestClient + 文件 DB 既有模式）

1. **models**：exclusions 建表；删 root 级联删 exclusion；删 user → excluded_by SET NULL；unique 冲突。
2. **scanner 剪枝**：构造 root 含 `a/b/img.jpg`、`a/bc/img.jpg`、`a/b/c/img.jpg`；排除 `a/b` 后：`a/b` 整棵消失、`a/bc` 保留（段匹配边界）；解除后重扫全部回来；排除不存在的目录无副作用；folder counts 正确。
3. **request_rescan dirty**：模拟扫描执行中调用 request_rescan → 结束后自动再入队一次；空闲调用等同 enqueue；多次调用只重跑一次。
4. **exclusions API**：GET 列表含用户名；POST 成功 201 + 审计 + 扫描入队；重复 409；逃逸 root / root 自身 / symlink / 不存在路径各 400；跨 gid/rid 404；DELETE 成功 204 + 审计 + 重扫；viewer 403。
5. **browse-fs root_id**：空路径默认 root；root 内浏览正常；逃逸 400；不带 root_id 行为不变（既有测试不破）。
6. **config_writer**：替换值保留注释/空行/未知键/hash_workers；缺 section 追加； trusted_proxies 数组渲染往返；非法更新不落地（先校验）；幂等。
7. **settings API**：GET 形状；PATCH 各项合法/非法（400 逐字段）；写盘 + 热替换 state.config；审计只含键名；未变更键保持；jwt_secret 不出现在响应/写盘。
8. **锁定阈值接线**：config threshold=2 时两次失败即锁（既有锁定测试用默认 5 不破）。
9. **retention=0**：删除图片 purge_after=NEVER_PURGE_TS；purge_expired 不删哨兵行；retention=7 正常计算。
10. **next_daily_run**：当天未到/已过/越界回退；定时循环本身用可注入的 sleep/session 做轻量测试或仅测纯函数（倾向只测纯函数 + 一次 lifespan 冒烟）。

### 前端（vitest，沿用组件挂载既有模式）

11. **AdminSettings**：初始加载填充四项；修改后保存发 PATCH 且 body 正确；非法阈值按钮/错误展示；radio 永不=0。
12. **排除面板**：懒加载列表；添加走 DirectoryChooser（断言 root_id/startPath props 与 POST body）；解除 confirm 后 DELETE；空态。
13. **DirectoryChooser rootId**：请求体带 root_id。
14. AdminTrash 哨兵显示"永不"。

### 收尾

15. 全量后端 pytest + 前端 vitest 全绿；`pnpm build`（vue-tsc）通过；红线 grep；tag `phase5-exclusions-settings`。

---

## 11. 规模与任务拆分

约 11 个任务（与 roadmap 预估 P2 的 60-70% 一致）：

1. Exclusion ORM + 建表
2. scanner 剪枝 + request_rescan dirty 重跑
3. exclusions 三个 API + 审计
4. browse-fs root_id 限定
5. config_writer 行级更新器
6. settings GET/PATCH + 锁定阈值接线 + retention=0 哨兵
7. 每日定时清理
8. 前端：api/router/菜单 + AdminSettings 页
9. 前端：root 卡片排除面板 + DirectoryChooser rootId
10. 前后端补充测试（AdminTrash 哨兵显示）
11. 全量验证 + 红线 grep + tag
