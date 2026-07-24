# 缩略图引用计数与手动清理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `thumbnail_refs` 引用计数，通过 SQLite 触发器实时维护，并把现有全量清空接口改为只清理图库和回收站均不再引用的缩略图，包括历史孤儿缓存。

**Architecture:** `models.py` 定义引用表和非负约束；`thumbnail_refs.py` 负责触发器、可恢复回填、校准和安全清理；`schema_init.py` 使用显式迁移标记保证升级可重试；`main.py` 创建应用级单例 `PruneService`，使并发请求共享同一把锁。文件系统扫描、字节统计和删除在线程中执行，数据库操作使用集合 SQL；`ThumbnailGenerator` 使用 `(sha1, size)` 级别任务表去重并通过同目录临时文件加 `os.replace()` 原子发布。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy 2.0 async + aiosqlite / SQLite / Vue 3 / Vitest

## Global Constraints

- 所有现有红线继续生效：不得物理删除图库文件夹或原始图片。
- 清理目标必须严格位于 `<data_dir>/.cache/thumbnails/` 内，且缓存根、候选目录和内部条目的符号链接都不得跟随。
- 只识别两位小写十六进制前缀目录和 40 位小写十六进制 SHA1 目录；非法、符号链接、路径逃逸或不可访问项不删除并计入 `failed`。
- 审计写入失败只记录日志，不得改变已经成功的清理响应。
- 引用计数由数据库触发器维护，与业务数据处于同一事务；`image_count`、`trash_count` 具有数据库级 `>= 0` 约束。
- 手动清理前必须在单个事务中以 `images` 和存在时的 `trash` 为权威来源执行批量校准。
- 管理端只清理无引用缩略图，不保留全量清空模式。
- 8 万级数据量下禁止逐 SHA1 查询或删除引用行；使用固定数量集合查询或单次 executemany 临时表操作。
- 普通启动只检查迁移标记和安装幂等触发器；迁移完成后不得重复聚合 8 万行，也不得遍历缓存目录。
- 普通扫描和普通浏览不得遍历整个缩略图缓存目录。
- 文件系统扫描、字节统计和删除必须经 `asyncio.to_thread()` 执行，不阻塞 FastAPI 事件循环。
- 成功响应固定为 `200`，字段固定为 `scanned`、`removed`、`failed`、`freed_bytes`；并发第二个请求固定返回 `409` 和错误码 `thumb_cache_purge_in_progress`。
- 审计 action 固定为 `thumb_cache_purge`，detail 至少为 `mode=unreferenced scanned=<n> removed=<n> failed=<n> freed_bytes=<n>`。

---

## 文件职责

```text
backend/src/myphoto/models.py
  ThumbnailRef ORM 模型和数据库非负约束。

backend/src/myphoto/thumbnail_refs.py
  触发器 SQL、首次回填、清理前校准、PruneService、无符号链接文件树检查和批量引用复核/删除。

backend/src/myphoto/schema_init.py
  在 create_all 后执行可恢复迁移：安装触发器、按迁移标记回填、最后写标记。

backend/src/myphoto/main.py
  创建应用生命周期内唯一的 PruneService，供所有 purge 请求共享互斥锁。

backend/src/myphoto/routes_admin.py
  管理 API、错误映射、结果响应和容错审计。

backend/src/myphoto/thumbnails.py
  同一 (sha1, size) 的生成去重、同目录临时文件和原子替换。

backend/tests/test_thumbnail_refs.py
  模型约束、images/trash 触发器、迁移、校准、清理、安全、集合 SQL 和并发测试。

backend/tests/test_routes_admin_system.py
  purge API、权限、共享互斥、审计和引用保护集成测试。

backend/tests/test_thumbnails.py
  并发只渲染一次、不同键并行、失败清理临时文件和锁表回收测试。

frontend/src/views/AdminOverview.vue
  清理确认、请求状态、结果/零结果/409 展示。

frontend/src/tests/admin-overview.spec.ts
  真实 pending Promise 驱动的禁用状态、确认文案、结果和错误测试。
```

---

### Task 1: 引用模型、images/trash 触发器与校准

**Files:**
- Modify: `backend/src/myphoto/models.py`
- Create: `backend/src/myphoto/thumbnail_refs.py`
- Create: `backend/tests/test_thumbnail_refs.py`

**Interfaces:**
- Produces: `ThumbnailRef`、`install_triggers(conn) -> None`、`backfill_refs(conn, *, include_images: bool, include_trash: bool) -> None`、`calibrate_refs(conn) -> None`、`trash_table_exists(conn) -> bool`。
- `conn` 必须同时兼容 SQLAlchemy `AsyncConnection` 和具有 `execute()` 的 `AsyncSession`。

- [ ] **Step 1: 先写模型、约束和 images 触发器失败测试**

在 `backend/tests/test_thumbnail_refs.py` 建立异步内存数据库 fixture，并创建 `Gallery -> GalleryRoot -> Folder -> Image` 的辅助函数。测试必须覆盖：

```python
async def test_thumbnail_ref_rejects_negative_counts(engine_and_sm):
    async with engine_and_sm.sessionmaker() as session:
        session.add(ThumbnailRef(sha1="a" * 40, image_count=-1, trash_count=0))
        with pytest.raises(IntegrityError):
            await session.commit()

async def test_image_triggers_insert_update_delete_and_shared_sha(engine_and_sm):
    # install_triggers 后插入两个同 SHA1 图片 => image_count == 2
    # 更新其中一个 sha1 => 旧值 1、新值 1
    # 删除旧值图片 => 旧行保留且 image_count == 0

async def test_image_trigger_count_never_becomes_negative(engine_and_sm):
    # 人工把计数校正到 0 后删除 image；触发器使用 MAX(0, image_count - 1)
```

Run: `python -m pytest backend/tests/test_thumbnail_refs.py -v`
Expected: FAIL，因为 `ThumbnailRef` 和 `install_triggers` 尚不存在。

- [ ] **Step 2: 定义具有数据库非负约束的模型**

在 `backend/src/myphoto/models.py` 添加：

```python
from sqlalchemy import CheckConstraint

class ThumbnailRef(Base):
    __tablename__ = "thumbnail_refs"
    sha1: Mapped[str] = mapped_column(String, primary_key=True)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trash_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        CheckConstraint("image_count >= 0", name="ck_thumbnail_refs_image_count_nonnegative"),
        CheckConstraint("trash_count >= 0", name="ck_thumbnail_refs_trash_count_nonnegative"),
    )
```

- [ ] **Step 3: 实现 images 触发器和表检测**

在 `thumbnail_refs.py` 中定义三个 `CREATE TRIGGER IF NOT EXISTS` 语句：

```sql
-- INSERT
INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
VALUES (NEW.sha1, 1, 0)
ON CONFLICT(sha1) DO UPDATE SET image_count = image_count + 1;

-- DELETE
UPDATE thumbnail_refs
SET image_count = MAX(0, image_count - 1)
WHERE sha1 = OLD.sha1;

-- UPDATE OF sha1, WHEN OLD.sha1 IS NOT NEW.sha1
UPDATE thumbnail_refs SET image_count = MAX(0, image_count - 1) WHERE sha1 = OLD.sha1;
INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
VALUES (NEW.sha1, 1, 0)
ON CONFLICT(sha1) DO UPDATE SET image_count = image_count + 1;
```

实现：

```python
async def trash_table_exists(conn) -> bool:
    result = await conn.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trash'"
    ))
    return result.scalar_one_or_none() is not None

async def install_triggers(conn) -> None:
    for statement in _IMAGE_TRIGGER_SQL:
        await conn.execute(text(statement))
    if await trash_table_exists(conn):
        for statement in _TRASH_TRIGGER_SQL:
            await conn.execute(text(statement))
```

- [ ] **Step 4: 先写 trash 触发器失败测试**

测试中用原始 SQL 创建最小 `trash(id INTEGER PRIMARY KEY, sha1 TEXT NOT NULL)` 表，再调用 `install_triggers()`。覆盖：

测试函数使用 `engine_and_sm` fixture，并分别执行以下明确断言：

- `test_trash_triggers_install_only_when_table_exists`：安装前查询 `sqlite_master` 确认无 `tr_thumbref_trash_*`；创建 trash 表并再次安装后确认三个触发器均存在。
- `test_trash_triggers_insert_update_delete`：INSERT 后旧 SHA 的 `trash_count == 1`；UPDATE SHA 后旧值为 0、新值为 1；DELETE 后新值为 0。
- `test_move_restore_and_permanent_delete_counts`：同事务 DELETE image + INSERT trash 后为 image 0/trash 1；同事务 DELETE trash + INSERT image 后为 trash 0/image 1；再次移入并永久 DELETE trash 后两项均为 0。

Run: `python -m pytest backend/tests/test_thumbnail_refs.py -k trash -v`
Expected: FAIL，直到 trash SQL 完成。

- [ ] **Step 5: 实现 trash 触发器、首次回填和权威校准**

trash 三个触发器与 images 对称，分别修改 `trash_count`。实现集合 SQL：

```python
async def backfill_refs(conn, *, include_images: bool, include_trash: bool) -> None:
    if include_images:
        await conn.execute(text("""
            INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
            SELECT sha1, COUNT(*), 0 FROM images GROUP BY sha1
            ON CONFLICT(sha1) DO UPDATE SET image_count = excluded.image_count
        """))
    if include_trash and await trash_table_exists(conn):
        await conn.execute(text("""
            INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
            SELECT sha1, 0, COUNT(*) FROM trash GROUP BY sha1
            ON CONFLICT(sha1) DO UPDATE SET trash_count = excluded.trash_count
        """))

async def calibrate_refs(conn) -> None:
    await conn.execute(text(
        "UPDATE thumbnail_refs SET image_count = 0, trash_count = 0"
    ))
    await backfill_refs(
        conn,
        include_images=True,
        include_trash=await trash_table_exists(conn),
    )
```

追加校准测试：故意写错多个计数，调用一次 `calibrate_refs()` 后断言它们与 `images`/`trash` 的 GROUP BY 结果完全一致，且两项为零的旧行仍保留。

- [ ] **Step 6: 运行测试并提交**

Run: `python -m pytest backend/tests/test_thumbnail_refs.py -v`
Expected: 全部 PASS，输出无 warning。

```bash
git add backend/src/myphoto/models.py backend/src/myphoto/thumbnail_refs.py backend/tests/test_thumbnail_refs.py
git commit -m "feat: add thumbnail reference counting"
```

---

### Task 2: 可恢复 Schema 迁移与显式版本标记

**Files:**
- Modify: `backend/src/myphoto/schema_init.py`
- Modify: `backend/tests/test_thumbnail_refs.py`

**Interfaces:**
- Consumes: Task 1 的 `install_triggers()`、`backfill_refs()`、`trash_table_exists()`。
- Produces: `ensure_thumbnail_ref_schema(engine) -> None`；`ensure_schema_and_admin()` 每次返回前保证引用 schema 已就绪。
- 迁移标记固定为 `thumbnail_refs_images_v1` 和 `thumbnail_refs_trash_v1`。

- [ ] **Step 1: 写可恢复升级和一次性回填失败测试**

测试必须覆盖：

测试函数分别执行以下明确步骤：

- `test_schema_upgrade_backfills_existing_images_once`：`create_all` 后、不安装触发器时插入两个相同 SHA 图片；调用 `ensure_thumbnail_ref_schema` 后断言聚合为 2 且存在 images marker；清空 SQL 事件记录后再次调用，断言记录中没有 `FROM images GROUP BY sha1`。
- `test_schema_upgrade_retries_when_marker_missing`：预先创建一条错误计数的 ref 行但不写 marker；启动后断言计数被权威回填覆盖且 marker 存在，证明不能以“表存在/有行”判断迁移完成。
- `test_schema_upgrade_backfills_trash_when_table_appears_later`：先完成 images marker，再创建并预置两条相同 SHA trash；下一次启动后断言三个 trash 触发器存在、`trash_count == 2` 且 trash marker 存在。

Run: `python -m pytest backend/tests/test_thumbnail_refs.py -k schema_upgrade -v`
Expected: FAIL，因为迁移函数尚不存在。

- [ ] **Step 2: 实现迁移标记事务**

在 `schema_init.py` 中实现：

```python
_IMAGE_REFS_MIGRATION = "thumbnail_refs_images_v1"
_TRASH_REFS_MIGRATION = "thumbnail_refs_trash_v1"

async def ensure_thumbnail_ref_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY
            )
        """))
        await install_triggers(conn)

        completed = set((await conn.execute(
            text("SELECT name FROM schema_migrations WHERE name IN (:images, :trash)"),
            {"images": _IMAGE_REFS_MIGRATION, "trash": _TRASH_REFS_MIGRATION},
        )).scalars())

        if _IMAGE_REFS_MIGRATION not in completed:
            await backfill_refs(conn, include_images=True, include_trash=False)
            await conn.execute(text(
                "INSERT INTO schema_migrations(name) VALUES (:name)"
            ), {"name": _IMAGE_REFS_MIGRATION})

        if await trash_table_exists(conn) and _TRASH_REFS_MIGRATION not in completed:
            await backfill_refs(conn, include_images=False, include_trash=True)
            await conn.execute(text(
                "INSERT INTO schema_migrations(name) VALUES (:name)"
            ), {"name": _TRASH_REFS_MIGRATION})
```

`ensure_schema_and_admin()` 的顺序固定为：`await create_all(engine)` → `await ensure_thumbnail_ref_schema(engine)` → 管理员检查/创建。标记必须在对应回填成功后、同一 `engine.begin()` 事务中写入；异常时整个迁移事务回滚。

- [ ] **Step 3: 测试事务中断可重试**

monkeypatch `backfill_refs` 第一次抛出异常，断言 marker 未写入；第二次恢复真实函数并运行，断言计数和 marker 正确。

Run: `python -m pytest backend/tests/test_thumbnail_refs.py -k schema_upgrade -v`
Expected: 全部 PASS；第二次普通启动没有 8 万行聚合路径。

- [ ] **Step 4: 提交**

```bash
git add backend/src/myphoto/schema_init.py backend/tests/test_thumbnail_refs.py
git commit -m "feat: add recoverable thumbnail ref migration"
```

---

### Task 3: 安全、批量且非阻塞的 PruneService

**Files:**
- Modify: `backend/src/myphoto/thumbnail_refs.py`
- Modify: `backend/tests/test_thumbnail_refs.py`

**Interfaces:**
- Produces: `PruneResult(scanned, removed, failed, freed_bytes)`、`PruneInProgressError`、`PruneService(cache_dir: Path, sessionmaker)`、`await PruneService.prune()`。
- `PruneService` 实例必须长生命周期共享；Task 4 负责把它放到 `app.state`。

- [ ] **Step 1: 写清理语义失败测试**

覆盖以下真实目录场景：

新增以下测试，每个测试都建立真实的 `sha1[:2]/sha1/` 目录并断言完整 `PruneResult`：

- `test_prune_keeps_any_image_or_trash_reference`：一个 image 引用目录和一个 trash 引用目录都保留。
- `test_prune_removes_zero_ref_and_historical_orphan_dirs`：引用表中的零引用目录及没有引用行的合法孤儿目录都删除。
- `test_prune_removes_all_sizes_and_reports_actual_bytes`：同一 SHA 的 200/400/1600 三个文件全部删除，`freed_bytes` 等于三者字节和。
- `test_prune_empty_or_missing_cache_returns_zeroes`：不存在和空缓存根均返回四个 0。
- `test_prune_failure_keeps_zero_ref_row_and_continues`：monkeypatch 一个候选删除抛 `OSError`，该行保留，同时另一候选成功删除。
- `test_prune_success_deletes_zero_ref_rows_in_one_set_operation`：成功项的零引用行消失，失败项和仍有引用行保留。

合法目录必须使用 `sha1[:2]/sha1/{200,400,1600}.jpg`。`scanned` 只计合法 SHA1 目录；`removed` 计成功删除或删除前已消失的候选；`freed_bytes` 只计实际成功删除的普通文件字节。

Run: `python -m pytest backend/tests/test_thumbnail_refs.py -k prune -v`
Expected: FAIL，因为 `PruneService` 尚不存在。

- [ ] **Step 2: 写路径安全失败测试**

覆盖：缓存根 symlink；两位前缀 symlink；SHA1 目录 symlink；候选内部 symlink；非法前缀；非法 SHA1；不可访问目录；一个失败候选不阻断另一个成功候选。断言所有外部 sentinel 均存在，危险项未删除且 `failed` 增加。

- [ ] **Step 3: 实现数据库阶段和应用内互斥**

`prune()` 必须先立即拒绝已锁定实例，再进入锁：

```python
async def prune(self) -> PruneResult:
    if self._lock.locked():
        raise PruneInProgressError("thumb_cache_purge_in_progress")
    async with self._lock:
        return await self._prune_locked()
```

`_prune_locked()` 的数据库阶段：

1. `async with self._sessionmaker.begin() as session:` 调用 `calibrate_refs(session)`；
2. 一次查询得到 `image_count + trash_count > 0` 的有效 SHA1 集合；
3. 在线程中扫描缓存树并得到合法目录、候选和安全失败数；
4. 候选删除前在单个事务中创建 TEMP 表 `prune_candidates(sha1 TEXT PRIMARY KEY)`，用一次 executemany 写入全部候选，再用 JOIN 一次查询复核仍有效 SHA1；不得拼接无限参数 `IN (...)`，不得逐 SHA1 查询；
5. 从候选中移除复核后有效项。

TEMP 表的 SQL 固定为：

```sql
CREATE TEMP TABLE IF NOT EXISTS prune_candidates (sha1 TEXT PRIMARY KEY);
DELETE FROM prune_candidates;
INSERT OR IGNORE INTO prune_candidates(sha1) VALUES (:sha1); -- executemany
SELECT r.sha1
FROM thumbnail_refs AS r
JOIN prune_candidates AS c ON c.sha1 = r.sha1
WHERE r.image_count + r.trash_count > 0;
```

- [ ] **Step 4: 实现不跟随 symlink 的线程内文件阶段**

用 `os.scandir()` 和 `DirEntry.is_dir(follow_symlinks=False)` / `is_file(follow_symlinks=False)` 实现私有同步函数。规则：

- 在任何 `resolve()` 之前先检查缓存根 `is_symlink()`；根不安全时抛 `ValueError`，不删除任何目录。
- 非法目录、任意层级 symlink、解析后不在缓存根内、stat/scandir 失败：候选不删除，`failed += 1`，记录 warning。
- 内部树预检成功后才统计普通文件大小并 `shutil.rmtree()`；预检不跟随 symlink。
- 整个 `_scan_cache_tree()` 和 `_delete_candidates()` 分别由 `await asyncio.to_thread(...)` 调用。
- 删除成功后尝试删除空的合法前缀目录；失败只记录日志，不改变已完成 SHA1 删除结果。

- [ ] **Step 5: 批量删除成功项引用行并验证无 N+1**

把成功或已不存在 SHA1 用 TEMP 表一次 executemany 写入，单条集合 DELETE：

```sql
DELETE FROM thumbnail_refs
WHERE image_count + trash_count = 0
  AND sha1 IN (SELECT sha1 FROM prune_deleted);
```

测试用 SQLAlchemy `before_cursor_execute` 记录语句数，分别对 10 和 1000 个候选执行清理；断言数据库语句数相同（executemany 视为一次调用），且不存在按 SHA1 重复 SELECT/DELETE。

- [ ] **Step 6: 验证并提交**

Run: `python -m pytest backend/tests/test_thumbnail_refs.py -v`
Expected: 全部 PASS，安全测试平台不支持 symlink 时只允许明确 skip。

```bash
git add backend/src/myphoto/thumbnail_refs.py backend/tests/test_thumbnail_refs.py
git commit -m "feat: prune unreferenced thumbnail caches safely"
```

---

### Task 4: 应用级单例、管理 API 与容错审计

**Files:**
- Modify: `backend/src/myphoto/main.py`
- Modify: `backend/src/myphoto/routes_admin.py`
- Modify: `backend/tests/test_routes_admin_system.py`

**Interfaces:**
- Consumes: Task 3 的 `PruneService` 和 `PruneInProgressError`。
- Produces: `app.state.thumbnail_pruner`；`POST /api/admin/thumb-cache/purge -> 200`。

- [ ] **Step 1: 先改 API 测试为新契约**

更新/新增以下测试，并使用现有 `client_as_admin` / `client_unauthed` fixture：

- `test_thumb_cache_purge_removes_only_orphan_sha_dirs`：无 DB 引用的合法 SHA1 目录被删；非法普通文件保留；响应四字段和值准确。
- `test_thumb_cache_purge_keeps_referenced_thumbnails`：直接在 DB 建 image 引用并创建缓存，purge 后仍存在。
- `test_thumb_cache_purge_missing_dir_returns_200_zero_result`：响应 200 且四字段均为 0，不创建缓存根。
- `test_thumb_cache_purge_non_admin_401`：未认证请求返回 401。
- `test_thumb_cache_purge_refuses_cache_root_symlink_without_deleting_target`：返回 400/bad_request，外部 sentinel 保留。
- `test_thumb_cache_purge_second_concurrent_request_returns_409`：monkeypatch `app.state.thumbnail_pruner` 的线程阶段等待 `threading.Event`；第一个请求未完成时发第二个请求，断言状态 409 且 code 为 `thumb_cache_purge_in_progress`。

Run: `python -m pytest backend/tests/test_routes_admin_system.py -k thumb_cache -v`
Expected: FAIL，旧接口仍返回 204 且全量清空。

- [ ] **Step 2: 在应用生命周期创建唯一 PruneService**

在 `main.py` 初始化 state 时添加：

```python
cache_dir = Path(cfg.data_dir) / ".cache" / "thumbnails"
app.state.thumbnails = ThumbnailGenerator(cache_dir)
app.state.thumbnail_pruner = PruneService(cache_dir, sm)
```

不得在路由函数内创建新 `PruneService`，否则不同请求不会共享锁。

- [ ] **Step 3: 重写 purge 路由**

路由不接收客户端文件路径，只调用 `request.app.state.thumbnail_pruner.prune()`。映射：

```python
try:
    result = await request.app.state.thumbnail_pruner.prune()
except PruneInProgressError as exc:
    raise AppError(
        "thumb_cache_purge_in_progress", 409,
        "a thumbnail cache prune is already running",
    ) from exc
except ValueError as exc:
    raise AppError("bad_request", 400, str(exc)) from exc
```

返回：

```python
return {
    "scanned": result.scanned,
    "removed": result.removed,
    "failed": result.failed,
    "freed_bytes": result.freed_bytes,
}
```

删除旧的缓存根 `shutil.rmtree()` 全量清空实现和 `status_code=204`。

- [ ] **Step 4: 写并实现审计测试**

覆盖成功 detail 的全部字段，以及审计失败不改变 200 响应：

- `test_thumb_cache_purge_writes_summary_audit`：取最后一条 audit，断言 `action == "thumb_cache_purge"`、`target == "thumb_cache"`，并断言 detail 精确等于 `mode=unreferenced scanned=1 removed=1 failed=0 freed_bytes=4`。
- `test_thumb_cache_purge_audit_failure_does_not_fail_cleanup`：monkeypatch `routes_admin.write_audit` 抛异常，断言响应仍为 200、候选已删除、`caplog` 含 audit failure。

路由把审计放在清理完成后独立 session 中，并用外层 `try/except Exception: log.exception(...)` 包住 `write_audit + commit`，以覆盖 `write_audit` 本身容错之外的 commit 失败。

- [ ] **Step 5: 验证并提交**

Run: `python -m pytest backend/tests/test_routes_admin_system.py -k thumb_cache -v`
Expected: 全部 PASS。

```bash
git add backend/src/myphoto/main.py backend/src/myphoto/routes_admin.py backend/tests/test_routes_admin_system.py
git commit -m "feat: expose unreferenced thumbnail purge API"
```

---

### Task 5: ThumbnailGenerator 并发去重与原子发布

**Files:**
- Modify: `backend/src/myphoto/thumbnails.py`
- Modify: `backend/tests/test_thumbnails.py`

**Interfaces:**
- `ThumbnailGenerator.ensure()` 签名不变。
- 内部 `_inflight: dict[tuple[str, int], asyncio.Task[Path]]`；任务完成后无论成功失败都从表移除。

- [ ] **Step 1: 写能证明真实去重和清理的失败测试**

新增四个明确测试：

- `test_concurrent_same_key_renders_once(tmp_path, monkeypatch)`：包装 `_render_thumb`，计数并用 `threading.Event` 阻塞；`asyncio.gather` 两次同键 ensure，断言 `render_calls == 1`、结果相同。
- `test_different_sizes_can_render_concurrently(tmp_path, monkeypatch)`：包装函数记录 200 和 400 都进入后才释放，断言两个尺寸在释放前均已开始，证明没有全局锁串行化。
- `test_failed_render_leaves_no_target_or_temp_and_releases_inflight(tmp_path, monkeypatch)`：第一次向临时路径写部分内容后抛 `ThumbnailError`；断言目标和 `*.tmp` 均不存在；第二次恢复渲染成功并断言 `_inflight == {}`。
- `test_success_releases_inflight_entry(tmp_path)`：ensure 返回后断言 `_inflight == {}`。

Run: `python -m pytest backend/tests/test_thumbnails.py -v`
Expected: FAIL，因为当前会重复渲染且直接写最终文件。

- [ ] **Step 2: 实现共享任务去重**

使用事件循环内无 await 的字典读写：第一个调用创建任务，后续调用 await 同一任务；仅任务创建者在 `finally` 中按 identity 删除条目：

```python
async def ensure(
    self,
    sha1: str,
    size: int,
    source_path: str,
    is_raw: bool,
) -> Path:
    if size not in ALLOWED_SIZES:
        raise ValueError(f"size {size} not allowed")
    out = self.cache_path(sha1, size)
    if out.exists():
        return out

    key = (sha1, size)
    task = self._inflight.get(key)
    if task is None:
        task = asyncio.create_task(
            self._generate(out, source_path, size, is_raw)
        )
        self._inflight[key] = task
        owner = True
    else:
        owner = False
    try:
        return await asyncio.shield(task)
    finally:
        if owner and task.done() and self._inflight.get(key) is task:
            self._inflight.pop(key, None)
```

`_generate()` 在任务内再次检查 `out.exists()`，防止创建任务前后的竞态。

- [ ] **Step 3: 实现安全临时文件和原子发布**

在 `out.parent` 中用 `tempfile.mkstemp(prefix=f".{size}.", suffix=".tmp", dir=out.parent)` 创建唯一文件，立即关闭 fd；线程渲染到该路径，成功后 `os.replace(tmp_path, out)`。任何异常在 `finally` 中 `tmp_path.unlink(missing_ok=True)`。不得使用 `tempfile.mktemp()` 或 `shutil.move()`。

- [ ] **Step 4: 验证并提交**

Run: `python -m pytest backend/tests/test_thumbnails.py -v`
Expected: 全部 PASS，render 次数断言为 1，成功和失败后 `_inflight` 均为空。

```bash
git add backend/src/myphoto/thumbnails.py backend/tests/test_thumbnails.py
git commit -m "feat: deduplicate thumbnail generation atomically"
```

---

### Task 6: 管理端无引用清理交互

**Files:**
- Modify: `frontend/src/views/AdminOverview.vue`
- Modify: `frontend/src/tests/admin-overview.spec.ts`

**Interfaces:**
- Consumes: `apiPost<PurgeResult>("/api/admin/thumb-cache/purge")`。
- UI 文案固定包含“清理无引用缩略图”“不删除任何原始图片”“正在使用的缩略图不会被主动清理”“缺失缩略图会在浏览时自动生成”。

- [ ] **Step 1: 先写确认和 pending 状态失败测试**

用 fetch mock 区分 `/api/admin/status` 和 purge；purge 返回手动 resolve 的 Promise，而不是立即 resolved mock：

```typescript
it("confirms scope and disables the purge button while pending", async () => {
  let resolvePurge!: (value: Response) => void
  const pending = new Promise<Response>((resolve) => { resolvePurge = resolve })
  // status 返回 FULL_PAYLOAD；purge 返回 pending
  vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
  const w = mountView()
  await flushPromises()
  const button = w.get('[data-testid="purge-thumbnails"]')
  await button.trigger("click")
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining("不删除任何原始图片"))
  expect(button.attributes("disabled")).toBeDefined()
  expect(button.text()).toContain("清理中")
  resolvePurge(jsonResponse({scanned: 10, removed: 2, failed: 0, freed_bytes: 1024}))
  await flushPromises()
  expect(button.attributes("disabled")).toBeUndefined()
})
```

另写取消确认不发送 POST 的测试。

- [ ] **Step 2: 写结果、零结果、部分失败和 409 失败测试**

固定断言：

```typescript
expect(w.text()).toContain("已清理 2 组缩略图")
expect(w.text()).toContain("1.0 KB")
expect(w.text()).toContain("1 组清理失败")
expect(w.text()).toContain("没有可清理的无引用缩略图") // removed == 0
expect(w.text()).toContain("清理任务已在运行中，请稍后再试") // 409
```

Run: `pnpm --dir frontend test -- admin-overview.spec.ts`
Expected: FAIL，因为按钮和状态尚不存在。

- [ ] **Step 3: 实现组件状态与交互**

添加 `PurgeResult`、`purging`、`purgeResult`、`purgeError`，并导入 `apiPost`。按钮使用 `data-testid="purge-thumbnails"` 和 `:disabled="purging"`。`purgeThumbCache()`：确认后清空旧结果/错误、设置 pending、POST、按 409 映射文案、finally 恢复按钮。

结果分支必须互斥：

```vue
<span v-if="purgeResult?.removed === 0 && purgeResult.failed === 0">
  没有可清理的无引用缩略图
</span>
<span v-else-if="purgeResult">
  已清理 {{ purgeResult.removed }} 组缩略图，释放 {{ formatBytes(purgeResult.freed_bytes) }}
  <template v-if="purgeResult.failed > 0">；{{ purgeResult.failed }} 组清理失败。</template>
</span>
```

`formatBytes()` 使用 1024 进位，0 返回 `0 B`，非 B 单位保留一位小数。

- [ ] **Step 4: 验证并提交**

Run: `pnpm --dir frontend test -- admin-overview.spec.ts`
Expected: 全部 PASS。

```bash
git add frontend/src/views/AdminOverview.vue frontend/src/tests/admin-overview.spec.ts
git commit -m "feat: add unreferenced thumbnail cleanup UI"
```

---

### Task 7: 全链路验证与性能红线

**Files:**
- Modify only if verification exposes a defect; do not create or commit benchmark artifacts.

- [ ] **Step 1: 运行完整后端测试**

Run: `python -m pytest backend/tests -v`
Expected: 全部 PASS；只允许项目已有、已说明的 skip，无新增 warning。

- [ ] **Step 2: 运行完整前端测试和构建**

Run: `pnpm --dir frontend test`
Expected: 全部 PASS。

Run: `pnpm --dir frontend build`
Expected: `vue-tsc --noEmit` 和 Vite build 成功。

- [ ] **Step 3: 验证删除红线**

Run: `rg -n "os\.remove|shutil\.rmtree" backend/src/myphoto`
Expected:
- 不出现 `os.remove`；原子发布只使用 `os.replace`。
- `routes_admin.py` 不再出现 purge 的 `shutil.rmtree`。
- `thumbnail_refs.py` 最多只在通过缓存根、合法名称、containment、无 symlink 和可访问性检查后的候选删除函数中出现 `shutil.rmtree`。

- [ ] **Step 4: 验证启动/扫描不遍历缓存**

Run: `rg -n "iterdir|scandir|rglob|walk" backend/src/myphoto/main.py backend/src/myphoto/schema_init.py backend/src/myphoto/scanner.py`
Expected: 新实现没有在启动和 scanner 路径增加缩略图缓存遍历。

- [ ] **Step 5: 运行固定 SQL 调用数性能测试**

Run: `python -m pytest backend/tests/test_thumbnail_refs.py -k "sql_call_count" -v`
Expected: 10 与 1000 候选的数据库语句数相同；无逐 SHA1 SELECT/DELETE。

- [ ] **Step 6: 提交验证标记**

仅在工作树干净且上述命令全部成功后：

```bash
git commit --allow-empty -m "chore: verify thumbnail reference cleanup"
```

---

## 最终自检

- [ ] `ThumbnailRef` 由 `Base.metadata.create_all()` 创建，并有两个数据库非负约束。
- [ ] images 和存在时的 trash 均有 INSERT/DELETE/UPDATE 触发器。
- [ ] 回填以显式迁移标记控制；中断不留 marker，重启可重试；普通启动不重复聚合。
- [ ] 手动清理先在一个事务中校准，再使用集合查询；候选复核和成功行删除无 N+1。
- [ ] 应用生命周期只有一个 `PruneService`，并发第二个请求立即 409。
- [ ] 缓存根和所有候选都执行名称、containment、symlink、可访问性检查；危险项不删除并计入失败。
- [ ] 文件系统扫描、统计和删除在线程中执行。
- [ ] API 返回 200 和四个准确字段；审计失败不阻断结果。
- [ ] `ThumbnailGenerator` 同键只渲染一次，任务表可回收，失败无半成品，成功用 `os.replace()` 原子发布。
- [ ] 前端确认文案、pending 禁用、成功、零结果、部分失败和 409 均有行为测试。
- [ ] 全量测试、前端构建、删除红线和固定 SQL 调用数测试全部通过。
