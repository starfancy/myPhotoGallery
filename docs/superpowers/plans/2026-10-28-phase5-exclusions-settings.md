# Phase 5 实现计划：排除清单 + AdminSettings + 每日定时清理

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** admin 可按 root 排除子目录（纯 DB 清索引、不碰文件系统），可在 AdminSettings 页面集中配置四项运行参数并热生效；补齐每日回收站定时清理与 `retention_days=0`（永不清理）语义。

**Architecture:** 新表 `exclusions` 由 `create_all` 自动建；scanner 在 walk 阶段按排除集合剪枝并新增 `request_rescan` 的 dirty 重跑；新模块 `config_writer.py` 行级更新 config.toml（保留注释/未知键、原子替换）；settings PATCH 后热替换 `app.state.config`；lifespan 起一个每日清理 asyncio 任务。前端新增 AdminSettings 页，AdminGalleryEdit root 卡片加排除面板，DirectoryChooser 支持可选 `rootId` 限定。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy 2.0 async + aiosqlite / pytest（asyncio_mode=auto）；Vue 3 + Vite + Pinia + vue-router + UnoCSS / vitest + @vue/test-utils。

设计依据：`docs/superpowers/specs/2026-10-28-phase5-exclusions-settings-design.md`

---

## Global Constraints

- 所有 P1-P4 Global Constraints 继续生效（三条红线、审计写失败不传播、最后 admin 保护、权限链步骤 1-5）。
- **排除全流程零 FS 写**：exclusions POST/DELETE 只写 DB；索引清理靠 scanner reconcile 既有逻辑（只删 DB 行）。新代码不得出现 `os.remove`/`os.rename`/`shutil`。
- 路径安全双端：browse-fs 的 root 限定只是防呆；POST exclusions 必须服务端权威校验（`resolve()` 后段级 `relative_to`，禁止字符串前缀判断）。
- 错误码全部复用 spec §6.9 既有集合，**不新增错误码**。
- 审计事件只用 spec §4.9 枚举内的 `exclusion_add` / `exclusion_remove` / `settings_update` / `trash_purge`。
- 新表由 `create_all` 自动建；本期不做列迁移（`trash.purge_after` 不动结构，永不清理用哨兵值）。
- 测试命令：后端 `.venv/Scripts/python.exe -m pytest backend/tests/<file> -q`（仓库根执行）；前端 `cd frontend && pnpm test -- --run`。
- 每个任务节奏：写测试 → 跑（红）→ 实现 → 跑（绿）→ 跑相关回归 → 提交。提交信息沿用 `feat(p5): ...` 风格。
- 后端 TestClient 需要 LAN 来源的测试固定用 `TestClient(app, client=("127.0.0.1", 12345))`（browse-fs 护栏要求私网 IP）。

---

## 文件结构

```
backend/src/myphoto/
├─ models.py            # MODIFY: +Exclusion ORM
├─ scanner.py           # MODIFY: _walk_root 剪枝；request_rescan + _redirty
├─ routes_admin.py      # MODIFY: exclusions 3 端点；browse-fs root_id；settings GET/PATCH
├─ routes_auth.py       # MODIFY: 锁定阈值/时长读 config
├─ routes_images.py     # MODIFY: retention=0 → 哨兵 purge_after
├─ trash.py             # MODIFY: NEVER_PURGE_TS；next_daily_run；daily_purge_loop
├─ main.py              # MODIFY: app.state.config_path；启动每日清理任务
├─ config_writer.py     # NEW: 行级 config.toml 更新器
backend/tests/
├─ test_models.py                          # MODIFY
├─ test_scanner.py                         # MODIFY
├─ test_routes_admin_exclusions.py         # NEW
├─ test_routes_admin_browse_fs.py          # MODIFY
├─ test_config_writer.py                   # NEW
├─ test_routes_admin_settings.py           # NEW
├─ test_routes_auth.py                     # MODIFY（阈值热生效）
├─ test_routes_images_delete.py            # MODIFY（retention=0 哨兵）
├─ test_daily_purge.py                     # NEW
└─ test_p5_e2e.py                          # NEW（Task 10）
frontend/src/
├─ api.ts                                 # MODIFY: +path_invalid/path_not_readable 中文映射
├─ router.ts                              # MODIFY: /admin/settings
├─ components/AppHeader.vue               # MODIFY: 菜单加「设置」
├─ components/DirectoryChooser.vue        # MODIFY: 可选 rootId prop
├─ views/AdminSettings.vue                # NEW
├─ views/AdminGalleryEdit.vue             # MODIFY: 排除面板
├─ views/AdminTrash.vue                   # MODIFY: 到期「永不」
├─ utils/datetime.ts                      # MODIFY: +formatPurgeAfter
frontend/src/tests/
├─ admin-settings.spec.ts                 # NEW
├─ exclusions-panel.spec.ts               # NEW
└─ datetime.spec.ts                       # MODIFY
```

## Task 概览

| # | 主题 | 端 |
|---|---|---|
| 1 | Exclusion ORM + 建表 | BE |
| 2 | scanner walk 剪枝 + request_rescan dirty 重跑 | BE |
| 3 | exclusions 三个 API + 审计 | BE |
| 4 | browse-fs 可选 root_id 限定 | BE |
| 5 | config_writer 行级更新器 | BE |
| 6 | settings GET/PATCH + 锁定接线 + retention=0 哨兵 | BE |
| 7 | 每日定时清理 | BE |
| 8 | AdminSettings 页 + 路由 + 菜单 | FE |
| 9 | 排除面板 + DirectoryChooser rootId + 回收站「永不」 | FE |
| 10 | 后端 e2e 集成测试 | BE |
| 11 | 全量验证 + 红线 grep + tag | Full |

---

### Task 1: Exclusion ORM + 建表

**Files:**
- Modify: `backend/src/myphoto/models.py`
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `Exclusion` ORM（`id, root_id, relative_path, excluded_by, excluded_at, reason`），表名 `exclusions`，UNIQUE `(root_id, relative_path)`，索引 `ix_exclusion_root`。

- [ ] **Step 1: 写失败测试** — 在 `backend/tests/test_models.py` 末尾追加：

```python
async def test_exclusion_cascades_when_root_deleted(session):
    now = int(time.time())
    g = Gallery(name="ExG", created_at=now)
    session.add(g)
    await session.flush()
    r = GalleryRoot(gallery_id=g.id, label="l", absolute_path="/x", enabled=1)
    session.add(r)
    await session.flush()
    session.add(Exclusion(
        root_id=r.id, relative_path="tmp",
        excluded_by=None, excluded_at=now, reason=None,
    ))
    await session.commit()

    await session.delete(r)
    await session.commit()

    from sqlalchemy import select as _select
    assert (await session.execute(_select(Exclusion))).scalars().all() == []


async def test_exclusion_excluded_by_set_null_when_user_deleted(session):
    from sqlalchemy import select as _select
    now = int(time.time())
    u = User(username="ex-admin", password_hash="x", role="admin",
             access_scope="lan_only", enabled=1, created_at=now)
    session.add(u)
    g = Gallery(name="ExG2", created_at=now)
    session.add(g)
    await session.flush()
    r = GalleryRoot(gallery_id=g.id, label="l", absolute_path="/x", enabled=1)
    session.add(r)
    await session.flush()
    ex = Exclusion(root_id=r.id, relative_path="tmp",
                   excluded_by=u.id, excluded_at=now, reason=None)
    session.add(ex)
    await session.commit()
    ex_id = ex.id

    await session.delete(u)
    await session.commit()

    remaining = (await session.execute(
        _select(Exclusion).where(Exclusion.id == ex_id)
    )).scalar_one()
    assert remaining.excluded_by is None
    assert remaining.relative_path == "tmp"


async def test_exclusion_unique_path_per_root(session):
    now = int(time.time())
    g = Gallery(name="ExG3", created_at=now)
    session.add(g)
    await session.flush()
    r = GalleryRoot(gallery_id=g.id, label="l", absolute_path="/x", enabled=1)
    session.add(r)
    await session.flush()
    session.add(Exclusion(root_id=r.id, relative_path="dup",
                          excluded_by=None, excluded_at=now))
    session.add(Exclusion(root_id=r.id, relative_path="dup",
                          excluded_by=None, excluded_at=now))
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        await session.commit()
```

并把 `Exclusion` 加入文件顶部 import：`from myphoto.models import ..., Exclusion`（改在 Step 3 一起做；此刻先跑确认红）。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'Exclusion'`

- [ ] **Step 3: 实现 ORM** — 在 `backend/src/myphoto/models.py` 末尾追加：

```python
class Exclusion(Base):
    """P5: 扫描时整体跳过的 root 子目录（spec §4.7）。

    - relative_path 为相对 root 的 posix 路径；该目录及其子孙全部跳过
    - 删 root 级联删除；删用户把 excluded_by 置空（排除规则保留）
    """
    __tablename__ = "exclusions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_id: Mapped[int] = mapped_column(
        ForeignKey("gallery_roots.id", ondelete="CASCADE"), nullable=False,
    )
    relative_path: Mapped[str] = mapped_column(String, nullable=False)
    excluded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    excluded_at: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    __table_args__ = (
        UniqueConstraint("root_id", "relative_path",
                         name="uq_exclusion_path_per_root"),
        Index("ix_exclusion_root", "root_id"),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_models.py backend/tests/test_db.py -q`
Expected: PASS（含既有迁移/建表测试）

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/models.py backend/tests/test_models.py
git commit -m "feat(p5): Exclusion ORM + create_all table"
```

---

### Task 2: scanner walk 剪枝 + request_rescan dirty 重跑

**Files:**
- Modify: `backend/src/myphoto/scanner.py`
- Test: `backend/tests/test_scanner.py`

**Interfaces:**
- Consumes: `Exclusion` ORM（Task 1）。
- Produces:
  - `_walk_root(root: Path, excluded_rel_paths: set[str] | None = None) -> tuple[set[str], dict[str, _WalkedFile]]`
  - `Scanner.request_rescan(root_id: int) -> None`（协程）；内部新增 `self._redirty: set[int]`。
- 既有 `enqueue` / `scan_root_now` 签名不变。

- [ ] **Step 1: 写失败测试** — 在 `backend/tests/test_scanner.py` 顶部 import 行加入 `Exclusion` 与 sqlalchemy `delete`：

```python
from sqlalchemy import delete, select
```

（把现有 `from sqlalchemy import select` 改为这一行。）models import 改为：

```python
from myphoto.models import Exclusion, Folder, Gallery, GalleryRoot, Image
```

文件末尾追加：

```python
# ---------- P5: exclusions pruning ----------


async def _add_exclusion(sm, root_id: int, rel: str) -> None:
    async with sm() as session:
        session.add(Exclusion(root_id=root_id, relative_path=rel,
                              excluded_by=None, excluded_at=int(time.time())))
        await session.commit()


async def test_excluded_directory_pruned_from_index(env):
    root_dir, sm, root_id = env
    _jpg(root_dir / "keep.jpg")
    _jpg(root_dir / "a" / "b" / "x.jpg")
    _jpg(root_dir / "a" / "bc" / "y.jpg")
    _jpg(root_dir / "a" / "b" / "deep" / "z.jpg")

    await Scanner(sm).scan_root_now(root_id)

    await _add_exclusion(sm, root_id, "a/b")
    await Scanner(sm).scan_root_now(root_id)

    async with sm() as session:
        rels = sorted(
            row.relative_path
            for row in (await session.execute(select(Image))).scalars()
        )
        assert rels == ["a/bc/y.jpg", "keep.jpg"]
        folder_rels = {
            row.relative_path
            for row in (await session.execute(select(Folder))).scalars()
        }
        assert "a/b" not in folder_rels
        assert "a/b/deep" not in folder_rels
        assert "a/bc" in folder_rels and "a" in folder_rels


async def test_unexclude_restores_on_rescan(env):
    root_dir, sm, root_id = env
    _jpg(root_dir / "a" / "b" / "x.jpg")
    scanner = Scanner(sm)
    await scanner.scan_root_now(root_id)
    await _add_exclusion(sm, root_id, "a/b")
    await scanner.scan_root_now(root_id)
    async with sm() as session:
        assert (await session.execute(select(Image))).scalars().all() == []

    async with sm() as session:
        await session.execute(delete(Exclusion).where(Exclusion.root_id == root_id))
        await session.commit()
    await Scanner(sm).scan_root_now(root_id)
    async with sm() as session:
        rels = [row.relative_path for row in (
            await session.execute(select(Image))).scalars()]
        assert rels == ["a/b/x.jpg"]


async def test_exclusion_for_missing_directory_is_harmless(env):
    root_dir, sm, root_id = env
    _jpg(root_dir / "keep.jpg")
    await _add_exclusion(sm, root_id, "no/such/dir")
    await Scanner(sm).scan_root_now(root_id)
    async with sm() as session:
        rels = [row.relative_path for row in (
            await session.execute(select(Image))).scalars()]
        assert rels == ["keep.jpg"]


async def test_request_rescan_while_idle_enqueues(env):
    _root_dir, sm, root_id = env
    scanner = Scanner(sm)
    await scanner.request_rescan(root_id)
    assert scanner.get_status(root_id)["status"] == "queued"


async def test_request_rescan_while_running_marks_redirty(env, monkeypatch):
    root_dir, sm, root_id = env
    for n in range(2):
        _jpg(root_dir / f"{n}.jpg")

    import myphoto.scanner as sc
    gate = threading.Event()
    real_process = sc._process_file

    def gated(path, is_raw):
        gate.wait(timeout=5)
        return real_process(path, is_raw)

    monkeypatch.setattr(sc, "_process_file", gated)

    scanner = Scanner(sm)
    runs = 0
    original = scanner.scan_root_now

    async def counting(rid):
        nonlocal runs
        runs += 1
        return await original(rid)

    scanner.scan_root_now = counting  # instance attr shadows bound method

    await scanner.start()
    await scanner.enqueue(root_id)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if scanner.get_status(root_id)["status"] == "running":
            break
        await asyncio.sleep(0.01)
    assert scanner.get_status(root_id)["status"] == "running"

    # 3 requests while running must collapse into exactly one extra run.
    await scanner.request_rescan(root_id)
    await scanner.request_rescan(root_id)
    await scanner.request_rescan(root_id)
    gate.set()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if runs >= 2 and scanner.get_status(root_id)["status"] == "idle":
            break
        await asyncio.sleep(0.02)
    await scanner.stop()
    assert runs == 2
    assert scanner.get_status(root_id)["status"] == "idle"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_scanner.py -q -k "exclusion or redirty or request_rescan"`
Expected: FAIL — `Scanner` 无 `request_rescan`；排除不生效。

- [ ] **Step 3: 实现剪枝** — `scanner.py`：

(a) import 加入 `Exclusion`：

```python
from myphoto.models import Exclusion, Folder, GalleryRoot, Image
```

（在现有 models import 行上加 `Exclusion`。）

(b) `_scan_transaction` 中读 root 的 session 块改为同时加载排除集合：

```python
        async with self._sm() as session:
            root = await session.get(GalleryRoot, root_id)
            if root is None:
                raise RuntimeError(f"root {root_id} not found")
            absolute_root = Path(root.absolute_path)
            excluded_rel_paths = set(
                (await session.execute(
                    select(Exclusion.relative_path).where(
                        Exclusion.root_id == root_id
                    )
                )).scalars().all()
            )
```

walk 调用改为：

```python
        walked_dirs, walked_files = await asyncio.to_thread(
            _walk_root, absolute_root, excluded_rel_paths,
        )
```

(c) `_walk_root` 整体替换为（新增第二参数与段级剪枝，注意先算 `relative_dir` 再过滤 `dirnames`）：

```python
def _walk_root(
    root: Path, excluded_rel_paths: set[str] | None = None
) -> tuple[set[str], dict[str, _WalkedFile]]:
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"root path missing: {root}")

    excluded: set[str] = excluded_rel_paths or set()
    walked_dirs: set[str] = {""}
    walked_files: dict[str, _WalkedFile] = {}
    walk_errors: list[OSError] = []

    def onerror(exc: OSError) -> None:
        walk_errors.append(exc)
        log.warning("skipping unreadable directory %s: %s", exc.filename, exc)

    for dirpath, dirnames, filenames in os.walk(
        root, topdown=True, onerror=onerror, followlinks=False
    ):
        current = Path(dirpath)
        relative_dir = current.relative_to(root).as_posix()
        if relative_dir == ".":
            relative_dir = ""

        def _kept(dirname: str) -> bool:
            # P5: exact segment match — excluding "a/b" must not touch "a/bc".
            child_rel = f"{relative_dir}/{dirname}" if relative_dir else dirname
            if child_rel in excluded:
                return False
            if dirname.startswith(".") or dirname == "__pycache__":
                return False
            if (current / dirname).is_symlink():
                return False
            return True

        dirnames[:] = [dirname for dirname in dirnames if _kept(dirname)]
        walked_dirs.add(relative_dir)

        for filename in filenames:
            if not is_supported(filename):
                continue
            path = current / filename
            try:
                if path.is_symlink():
                    continue
                stat = path.stat()
            except OSError as exc:
                log.warning("skipping unreadable file %s: %s", path, exc)
                continue
            relative_path = (
                f"{relative_dir}/{filename}" if relative_dir else filename
            )
            walked_files[relative_path] = _WalkedFile(
                path=path,
                filename=filename,
                relative_path=relative_path,
                relative_dir=relative_dir,
                mtime=int(stat.st_mtime),
                size_bytes=stat.st_size,
            )

    root_string = os.fspath(root)
    if walk_errors and any(
        Path(exc.filename or root_string) == root for exc in walk_errors
    ):
        raise RuntimeError(f"root path unreadable: {root}") from walk_errors[0]
    return walked_dirs, walked_files
```

- [ ] **Step 4: 实现 request_rescan + dirty 重跑** — `Scanner.__init__` 在 `self._status: dict[int, _RootStatus] = {}` 后加：

```python
        self._redirty: set[int] = set()
```

`enqueue` 方法之后新增：

```python
    async def request_rescan(self, root_id: int) -> None:
        """P5: 排除变更触发的重扫请求。

        - root 空闲/排队：等同 enqueue（排队中由 _enqueued 去重）
        - 扫描进行中：打 redirty 标记，本轮 worker 结束后自动再跑一遍，
          避免 enqueue 的进行中去重把变更静默吞掉。
        """
        async with self._lock:
            status = self._status.get(root_id)
            running = status is not None and status.status == "running"
        if running:
            async with self._lock:
                self._redirty.add(root_id)
        else:
            await self.enqueue(root_id)
```

`_loop` 的 finally 块改为：

```python
            finally:
                async with self._lock:
                    self._enqueued.discard(root_id)
                    needs_rerun = root_id in self._redirty
                    if needs_rerun:
                        self._redirty.discard(root_id)
                self._queue.task_done()
                if needs_rerun:
                    await self.enqueue(root_id)
```

- [ ] **Step 5: 跑 scanner 全套测试**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_scanner.py -q`
Expected: PASS（全部，含新增 5 个；gate 测试可能耗时数秒）

- [ ] **Step 6: 提交**

```bash
git add backend/src/myphoto/scanner.py backend/tests/test_scanner.py
git commit -m "feat(p5): scanner exclusion pruning + request_rescan dirty rerun"
```

---

### Task 3: exclusions 三个 API + 审计

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py`
- Test: `backend/tests/test_routes_admin_exclusions.py`（新建）

**Interfaces:**
- Consumes: `Scanner.request_rescan`（Task 2）、`Exclusion`（Task 1）、`write_audit`。
- Produces:
  - `GET    /api/admin/galleries/{gid}/roots/{rid}/exclusions` → `{root_id, entries:[{id, relative_path, reason, excluded_by, excluded_by_username, excluded_at}]}`
  - `POST   /api/admin/galleries/{gid}/roots/{rid}/exclusions` body `{absolute_path, reason?}` → 201 + 单条目
  - `DELETE /api/admin/galleries/{gid}/roots/{rid}/exclusions/{eid}` → 204

- [ ] **Step 1: 写失败测试** — 新建 `backend/tests/test_routes_admin_exclusions.py`：

```python
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from myphoto.main import build_app
from sqlalchemy import select

from myphoto.models import AuditLog


@pytest.fixture
def env_client(tmp_path, capsys):
    photos = tmp_path / "photos"
    photos.mkdir()
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        pw = re.search(r"password=(\S+)", capsys.readouterr().out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        gid = c.post("/api/admin/galleries", json={"name": "G"}).json()["id"]
        rid = c.post(
            f"/api/admin/galleries/{gid}/roots",
            json={"label": "R", "absolute_path": str(photos)},
        ).json()["id"]
        yield c, app, gid, rid, photos


def _wait_idle(c, gid, rid, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status").json()
        if st["status"] == "idle":
            return
        time.sleep(0.05)
    raise AssertionError("scan did not become idle")


def _ex_url(gid, rid, tail=""):
    return f"/api/admin/galleries/{gid}/roots/{rid}/exclusions{tail}"


def test_list_empty(env_client):
    c, _app, gid, rid, _photos = env_client
    r = c.get(_ex_url(gid, rid))
    assert r.status_code == 200
    assert r.json() == {"root_id": rid, "entries": []}
    assert r.headers["cache-control"] == "no-store"


def test_create_exclusion_201_and_list(env_client):
    c, app, gid, rid, photos = env_client
    target = photos / "exports"
    target.mkdir()

    r = c.post(_ex_url(gid, rid), json={
        "absolute_path": str(target), "reason": "临时文件",
    })
    assert r.status_code == 201
    e = r.json()
    assert e["relative_path"] == "exports"
    assert e["reason"] == "临时文件"
    assert e["excluded_by_username"] == "admin"
    assert isinstance(e["excluded_at"], int)

    listed = c.get(_ex_url(gid, rid)).json()["entries"]
    assert [x["relative_path"] for x in listed] == ["exports"]

    with pytest.MonkeyPatch().context() as _:
        pass
    # audit row written
    async def _check_audit():
        async with app.state.sessionmaker() as s:
            return (await s.execute(
                select(AuditLog).where(AuditLog.action == "exclusion_add")
            )).scalars().all()
    rows = c.portal.call(_check_audit)
    assert len(rows) == 1
    assert rows[0].target == f"exclusion:{e['id']}"
    assert "exports" in (rows[0].detail or "")


def test_duplicate_exclusion_conflict(env_client):
    c, _app, gid, rid, photos = env_client
    target = photos / "exports"
    target.mkdir()
    body = {"absolute_path": str(target)}
    assert c.post(_ex_url(gid, rid), json=body).status_code == 201
    r = c.post(_ex_url(gid, rid), json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_exclude_path_outside_root_rejected(env_client, tmp_path):
    c, _app, gid, rid, photos = env_client
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    r = c.post(_ex_url(gid, rid), json={"absolute_path": str(outside)})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_exclude_root_itself_rejected(env_client):
    c, _app, gid, rid, photos = env_client
    r = c.post(_ex_url(gid, rid), json={"absolute_path": str(photos)})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_exclude_nonexistent_path_rejected(env_client):
    c, _app, gid, rid, photos = env_client
    r = c.post(_ex_url(gid, rid), json={"absolute_path": str(photos / "nope")})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_not_readable"


def test_exclude_path_with_dotdot_rejected(env_client):
    c, _app, gid, rid, photos = env_client
    target = photos / "sub"
    target.mkdir()
    r = c.post(_ex_url(gid, rid), json={
        "absolute_path": str(target / ".." / "elsewhere"),
    })
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


@pytest.mark.skipif(sys.platform == "win32",
                    reason="symlink creation needs privileges on Windows")
def test_exclude_symlink_rejected(env_client):
    c, _app, gid, rid, photos = env_client
    outside = photos.parent / "outside"
    outside.mkdir()
    link = photos / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create symlink")
    r = c.post(_ex_url(gid, rid), json={"absolute_path": str(link)})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_root_wrong_gallery_404(env_client):
    c, _app, gid, rid, photos = env_client
    gid2 = c.post("/api/admin/galleries", json={"name": "G2"}).json()["id"]
    r = c.get(f"/api/admin/galleries/{gid2}/roots/{rid}/exclusions")
    assert r.status_code == 404


def test_delete_exclusion(env_client):
    c, app, gid, rid, photos = env_client
    target = photos / "exports"
    target.mkdir()
    eid = c.post(_ex_url(gid, rid), json={"absolute_path": str(target)}).json()["id"]

    r = c.delete(_ex_url(gid, rid, f"/{eid}"))
    assert r.status_code == 204
    assert c.get(_ex_url(gid, rid)).json()["entries"] == []

    async def _check_audit():
        async with app.state.sessionmaker() as s:
            return (await s.execute(
                select(AuditLog).where(AuditLog.action == "exclusion_remove")
            )).scalars().all()
    rows = c.portal.call(_check_audit)
    assert len(rows) == 1
    assert rows[0].target == f"exclusion:{eid}"


def test_delete_nonexistent_exclusion_404(env_client):
    c, _app, gid, rid, _photos = env_client
    r = c.delete(_ex_url(gid, rid, "/9999"))
    assert r.status_code == 404


def test_exclusion_triggers_rescan(env_client):
    c, _app, gid, rid, photos = env_client
    _wait_idle(c, gid, rid)
    target = photos / "exports"
    target.mkdir()
    assert c.post(_ex_url(gid, rid),
                  json={"absolute_path": str(target)}).status_code == 201
    _wait_idle(c, gid, rid)  # request_rescan queued and completed
    st = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status").json()
    assert st["status"] == "idle"
```

注意：`test_create_exclusion_201_and_list` 里有一段无用的 `MonkeyPatch` 残留，写文件时删掉（计划审查已发现，实现时不要保留）。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_routes_admin_exclusions.py -q`
Expected: FAIL — 全部 404/405（端点不存在）。

- [ ] **Step 3: 实现端点** — `routes_admin.py`：

(a) 顶部 import 区，`from myphoto.models import ...` 行加入 `Exclusion`，并补 `import time`（文件已有 `import time`，确认即可）：

```python
from myphoto.models import AuditLog, Exclusion, Gallery, GalleryRoot, Image, User, UserGallery
```

(b) 在 Root CRUD 段（`admin_scan_status` 之后、`# ---- browse-fs` 注释之前）插入：

```python
# ---- exclusions (P5) ----


class ExclusionCreate(BaseModel):
    absolute_path: str = Field(min_length=1, max_length=4096)
    reason: str | None = Field(None, max_length=500)


async def _get_root_or_404(s, gid: int, rid: int) -> GalleryRoot:
    r = (
        await s.execute(
            select(GalleryRoot).where(
                GalleryRoot.id == rid, GalleryRoot.gallery_id == gid
            )
        )
    ).scalar_one_or_none()
    if r is None:
        raise AppError("not_found", 404, "root not found")
    return r


def _exclusion_payload(e: Exclusion, username: str | None) -> dict:
    return {
        "id": e.id,
        "relative_path": e.relative_path,
        "reason": e.reason,
        "excluded_by": e.excluded_by,
        "excluded_by_username": username,
        "excluded_at": e.excluded_at,
    }


def _validate_path_within_root(raw_path: str, root: GalleryRoot) -> tuple[Path, str]:
    """Resolve an admin-supplied path and enforce it is a real directory
    strictly inside the root. Returns (resolved, posix relative path)."""
    raw = Path(raw_path)
    try:
        if raw.is_symlink():
            raise AppError("path_invalid", 400, "symlinks are not permitted")
    except OSError:
        raise AppError("path_not_readable", 400, f"path not readable: {raw_path}")
    root_p = Path(root.absolute_path).resolve()
    p = raw.resolve()
    if p == root_p:
        raise AppError("path_invalid", 400, "cannot exclude the root itself")
    try:
        rel = p.relative_to(root_p)
    except ValueError:
        raise AppError("path_invalid", 400, "path is outside the root")
    if not p.exists() or not p.is_dir():
        raise AppError("path_not_readable", 400, f"path not readable: {raw_path}")
    return p, rel.as_posix()


@router.get("/galleries/{gid}/roots/{rid}/exclusions")
async def admin_list_exclusions(
    gid: int,
    rid: int,
    request: Request,
    response: Response,
    _admin: User = Depends(admin_required),
):
    response.headers["Cache-Control"] = "no-store"
    sm = request.app.state.sessionmaker
    async with sm() as s:
        await _get_root_or_404(s, gid, rid)
        rows = (
            await s.execute(
                select(Exclusion, User.username)
                .join(User, User.id == Exclusion.excluded_by, isouter=True)
                .where(Exclusion.root_id == rid)
                .order_by(Exclusion.id)
            )
        ).all()
        return {
            "root_id": rid,
            "entries": [_exclusion_payload(e, username) for e, username in rows],
        }


@router.post("/galleries/{gid}/roots/{rid}/exclusions", status_code=201)
async def admin_create_exclusion(
    gid: int,
    rid: int,
    body: ExclusionCreate,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        root = await _get_root_or_404(s, gid, rid)
        _, rel_posix = _validate_path_within_root(body.absolute_path, root)

        dup = (
            await s.execute(
                select(Exclusion).where(
                    Exclusion.root_id == rid,
                    Exclusion.relative_path == rel_posix,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise AppError("conflict", 409, "this directory is already excluded")

        reason = body.reason.strip() if body.reason and body.reason.strip() else None
        e = Exclusion(
            root_id=rid,
            relative_path=rel_posix,
            excluded_by=admin.id,
            excluded_at=int(time.time()),
            reason=reason,
        )
        s.add(e)
        await s.flush()
        detail = f"root={rid} path={rel_posix}"
        if reason:
            detail += f" reason={reason}"
        await write_audit(
            s, "exclusion_add", admin.id, _client_ip(request),
            target=f"exclusion:{e.id}", detail=detail[:200],
        )
        await s.commit()
        payload = _exclusion_payload(e, admin.username)

    await request.app.state.scanner.request_rescan(rid)
    return payload


@router.delete("/galleries/{gid}/roots/{rid}/exclusions/{eid}", status_code=204)
async def admin_delete_exclusion(
    gid: int,
    rid: int,
    eid: int,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        await _get_root_or_404(s, gid, rid)
        e = (
            await s.execute(
                select(Exclusion).where(
                    Exclusion.id == eid, Exclusion.root_id == rid
                )
            )
        ).scalar_one_or_none()
        if e is None:
            raise AppError("not_found", 404, "exclusion not found")
        rel_posix = e.relative_path
        await write_audit(
            s, "exclusion_remove", admin.id, _client_ip(request),
            target=f"exclusion:{eid}",
            detail=f"root={rid} path={rel_posix}"[:200],
        )
        await s.delete(e)
        await s.commit()

    await request.app.state.scanner.request_rescan(rid)
```

- [ ] **Step 4: 跑新测试 + 回归**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_routes_admin_exclusions.py backend/tests/test_routes_admin_roots.py -q`
Expected: PASS（symlink 用例在 Windows skip）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/routes_admin.py backend/tests/test_routes_admin_exclusions.py
git commit -m "feat(p5): exclusions CRUD endpoints with audit + rescan trigger"
```

---

### Task 4: browse-fs 可选 root_id 限定

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py`
- Test: `backend/tests/test_routes_admin_browse_fs.py`

**Interfaces:**
- Consumes: Gallery/GalleryRoot。
- Produces: `POST /api/admin/browse-fs` body 新增可选 `root_id: int | None`；带参时空路径默认定位该 root、逃逸路径 400。不带参行为完全不变。

- [ ] **Step 1: 写失败测试** — 在 `backend/tests/test_routes_admin_browse_fs.py` 末尾追加（该文件 fixture 名为 `client_as_admin`，不含图库；本用例自建 root）：

```python
def _make_root(c, photos):
    gid = c.post("/api/admin/galleries", json={"name": "G"}).json()["id"]
    rid = c.post(
        f"/api/admin/galleries/{gid}/roots",
        json={"label": "R", "absolute_path": str(photos)},
    ).json()["id"]
    return gid, rid


def test_browse_fs_with_root_id_defaults_to_root(client_as_admin, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "child").mkdir()
    _gid, rid = _make_root(client_as_admin, photos)

    r = client_as_admin.post("/api/admin/browse-fs", json={"path": "", "root_id": rid})
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == str(photos.resolve())
    assert [e["name"] for e in data["entries"]] == ["child"]


def test_browse_fs_with_root_id_allows_descendant(client_as_admin, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    child = photos / "child"
    child.mkdir()
    _gid, rid = _make_root(client_as_admin, photos)

    r = client_as_admin.post(
        "/api/admin/browse-fs",
        json={"path": str(child), "root_id": rid},
    )
    assert r.status_code == 200


def test_browse_fs_with_root_id_rejects_escape(client_as_admin, tmp_path):
    photos = tmp_path / "photos"
    photos.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _gid, rid = _make_root(client_as_admin, photos)

    r = client_as_admin.post(
        "/api/admin/browse-fs",
        json={"path": str(outside), "root_id": rid},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_browse_fs_with_root_id_dotdot_escape_rejected(client_as_admin, tmp_path):
    photos = tmp_path / "photos" / "deep"
    photos.mkdir(parents=True)
    _gid, rid = _make_root(client_as_admin, photos.parent)

    r = client_as_admin.post(
        "/api/admin/browse-fs",
        json={"path": str(photos / ".." / ".." / "outside"), "root_id": rid},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_browse_fs_with_unknown_root_id_404(client_as_admin, tmp_path):
    r = client_as_admin.post(
        "/api/admin/browse-fs", json={"path": str(tmp_path), "root_id": 9999}
    )
    assert r.status_code == 404


def test_browse_fs_without_root_id_unchanged(client_as_admin, tmp_path):
    """不带 root_id 仍可浏览 root 之外（添加根目录场景，仅受 LAN 护栏）。"""
    outside = tmp_path / "anywhere"
    outside.mkdir()
    r = client_as_admin.post("/api/admin/browse-fs", json={"path": str(outside)})
    assert r.status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_routes_admin_browse_fs.py -q -k root_id`
Expected: FAIL（root_id 被忽略，逃逸用例返回 200）。

- [ ] **Step 3: 实现** — `routes_admin.py`：

(a) 请求模型加字段：

```python
class BrowseFsRequest(BaseModel):
    path: str = ""
    root_id: int | None = None
```

(b) `admin_browse_fs` 改造。把函数开头到返回之间替换为以下逻辑（保留原有 `_write_audit` 嵌套与审计行为；`audit_target` 在 path 归一化后取值）：

```python
    response.headers["Cache-Control"] = "no-store"
    raw = body.path or ""
    sm = request.app.state.sessionmaker

    # P5: optional root confinement (defense-in-depth UX; POST /exclusions
    # remains the authority). None = whole-machine browsing (add-root flow).
    root_p: Path | None = None
    if body.root_id is not None:
        async with sm() as s:
            rr = await s.get(GalleryRoot, body.root_id)
        if rr is None:
            raise AppError("not_found", 404, "root not found")
        root_p = Path(rr.absolute_path).resolve()
        if not raw:
            raw = str(root_p)

    audit_target = raw or "<root>"
    audit_detail: str | None = None

    async def _write_audit(detail: str | None) -> None:
        async with sm() as s:
            await write_audit(
                s, "fs_browse", admin.id, _client_ip(request),
                target=audit_target, detail=detail,
            )
            await s.commit()

    try:
        # Rule 5: reject any '..' segment (checked before resolution / normalization)
        if raw:
            norm_for_check = raw.replace("\\", "/")
            parts = [p for p in norm_for_check.split("/") if p]
            if any(p == ".." for p in parts):
                raise AppError("path_invalid", 400, "path must not contain '..' segments")

        if not raw:
            # Default root
            if sys.platform == "win32":
                entries = await asyncio.to_thread(_list_drive_letters)
                truncated = False
                result_path = ""
            else:
                root = Path("/")
                entries, truncated = _list_directories(root)
                result_path = str(root)
        else:
            p = Path(raw)
            # Rule 4: reject symlinks (do not resolve)
            try:
                if p.is_symlink():
                    raise AppError("path_invalid", 400, "symlinks are not permitted")
            except OSError:
                raise AppError("path_not_readable", 400, f"path not readable: {raw}")

            if not p.exists() or not p.is_dir():
                raise AppError("path_not_readable", 400, f"path not readable: {raw}")

            if root_p is not None:
                try:
                    p.resolve().relative_to(root_p)
                except ValueError:
                    raise AppError("path_invalid", 400, "path is outside the root")

            try:
                entries, truncated = _list_directories(p)
            except OSError:
                raise AppError("path_not_readable", 400, f"path not readable: {raw}")
            result_path = str(p)
    except AppError as e:
        audit_detail = f"error={e.code}"
        if body.root_id is not None:
            audit_detail += f" root={body.root_id}"
        await _write_audit(audit_detail)
        raise

    audit_detail = f"count={len(entries)}"
    if truncated:
        audit_detail += " truncated=1"
    if body.root_id is not None:
        audit_detail += f" root={body.root_id}"
    await _write_audit(audit_detail)

    return {"path": result_path, "entries": entries, "truncated": truncated}
```

- [ ] **Step 4: 跑全文件测试**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_routes_admin_browse_fs.py -q`
Expected: PASS（既有全部 + 6 个新增）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/routes_admin.py backend/tests/test_routes_admin_browse_fs.py
git commit -m "feat(p5): confine browse-fs to a root via optional root_id"
```

---

### Task 5: config.toml 行级 writer

**Files:**
- Create: `backend/src/myphoto/config_writer.py`
- Test: `backend/tests/test_config_writer.py`（新建）

**Interfaces:**
- Produces:
  - `@dataclass SettingsUpdates`（4 个可选字段：`trash_retention_days: int | None`、`login_lockout_threshold: int | None`、`trusted_proxies: list[str] | None`、`session_hours: int | None`）
  - `update_settings_file(path: str | Path, updates: SettingsUpdates) -> None`：行级替换/插入受管键，保留其他一切；渲染结果先过 `tomllib` 自校验，再临时文件 + `os.replace` 原子落盘。
- 不做语义校验（值域/IP 合法）——那是 Task 6 路由层的职责。

- [ ] **Step 1: 写失败测试** — 新建 `backend/tests/test_config_writer.py`：

```python
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from myphoto.config import load_or_init
from myphoto.config_writer import SettingsUpdates, update_settings_file


def _cfg(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def test_updates_roundtrip_via_load_or_init(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)  # create default template

    update_settings_file(path, SettingsUpdates(
        trash_retention_days=90,
        login_lockout_threshold=3,
        trusted_proxies=["127.0.0.1", "10.0.0.0/8"],
        session_hours=24,
    ))

    cfg = load_or_init(path)
    assert cfg.trash_retention_days == 90
    assert cfg.login_lockout_threshold == 3
    assert cfg.trusted_proxies == ["127.0.0.1", "10.0.0.0/8"]
    assert cfg.session_hours == 24


def test_preserves_comments_blank_lines_and_unknown_keys(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)
    text = path.read_text(encoding="utf-8")
    assert "# myPhotoGallery config" in text
    # add an unknown managed-section key and a custom section
    path.write_text(
        text + '\n[custom]\nfoo = "bar"\nsession_hours_note = "keep me"\n',
        encoding="utf-8",
    )

    update_settings_file(path, SettingsUpdates(session_hours=12))

    after = path.read_text(encoding="utf-8")
    assert "# myPhotoGallery config" in after
    assert 'foo = "bar"' in after
    assert 'session_hours_note = "keep me"' in after
    # scanner default-template comment must survive
    assert "hash_workers" in after
    parsed = tomllib.loads(after)
    assert parsed["app"]["session_hours"] == 12
    assert parsed["custom"]["foo"] == "bar"


def test_none_fields_leave_file_unchanged(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)
    before = path.read_text(encoding="utf-8")
    update_settings_file(path, SettingsUpdates())
    assert path.read_text(encoding="utf-8") == before


def test_inserts_key_into_existing_section(tmp_path):
    path = _cfg(tmp_path)
    # [security] exists but without the lockout key (simulate hand-edited file)
    path.write_text(
        '[app]\njwt_secret = "abcdef"\nsession_hours = 8\n\n'
        '[trash]\nretention_days = 30\n\n'
        '[security]\ntrusted_proxies = []\n',
        encoding="utf-8",
    )
    update_settings_file(path, SettingsUpdates(login_lockout_threshold=7))
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["security"]["login_lockout_threshold"] == 7
    assert parsed["security"]["trusted_proxies"] == []


def test_appends_missing_section(tmp_path):
    path = _cfg(tmp_path)
    path.write_text(
        '[app]\njwt_secret = "abcdef"\nsession_hours = 8\n',
        encoding="utf-8",
    )
    update_settings_file(path, SettingsUpdates(trash_retention_days=7))
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["trash"]["retention_days"] == 7
    assert parsed["app"]["session_hours"] == 8


def test_crlf_line_endings_preserved(tmp_path):
    path = _cfg(tmp_path)
    path.write_bytes(
        b'[app]\r\njwt_secret = "abcdef"\r\nsession_hours = 8\r\n'
        b'[trash]\r\nretention_days = 30\r\n'
    )
    update_settings_file(path, SettingsUpdates(session_hours=2))
    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")


def test_empty_proxy_list_renders_inline_array(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)
    update_settings_file(path, SettingsUpdates(trusted_proxies=[]))
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["security"]["trusted_proxies"] == []


def test_idempotent_update(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)
    upd = SettingsUpdates(trash_retention_days=0, session_hours=1)
    update_settings_file(path, upd)
    once = path.read_text(encoding="utf-8")
    update_settings_file(path, upd)
    assert path.read_text(encoding="utf-8") == once


def test_quotes_in_string_value_escaped(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)
    update_settings_file(path, SettingsUpdates(trusted_proxies=['10.0.0.1", "bad']))
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["security"]["trusted_proxies"] == ['10.0.0.1", "bad']
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_config_writer.py -q`
Expected: FAIL — `ModuleNotFoundError: myphoto.config_writer`

- [ ] **Step 3: 实现** — 新建 `backend/src/myphoto/config_writer.py`：

```python
"""P5: 行级更新 config.toml 中 AdminSettings 受管的少量键。

不使用 tomli_w：它会重排文件并丢失注释（config.toml 是给人看的运维文档）。
本模块按行替换 `key = value`，保留注释、空行、未知键与既有行尾；
渲染结果先过 tomllib 自校验，再用临时文件 + os.replace 原子落盘。
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*=")

# settings 字段 → (toml section, toml key)
_FIELD_MAP: dict[str, tuple[str, str]] = {
    "trash_retention_days": ("trash", "retention_days"),
    "login_lockout_threshold": ("security", "login_lockout_threshold"),
    "trusted_proxies": ("security", "trusted_proxies"),
    "session_hours": ("app", "session_hours"),
}


@dataclass
class SettingsUpdates:
    trash_retention_days: int | None = None
    login_lockout_threshold: int | None = None
    trusted_proxies: list[str] | None = None
    session_hours: int | None = None


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _render(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(f'"{_toml_escape(v)}"' for v in value) + "]"
    return str(int(value))


def update_settings_file(path: str | Path, updates: SettingsUpdates) -> None:
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    ends_newline = raw.endswith("\n")
    lines = raw.splitlines()

    wanted: dict[tuple[str, str], str] = {}
    for field, value in vars(updates).items():
        if value is not None:
            wanted[_FIELD_MAP[field]] = _render(value)
    if not wanted:
        return

    # Map section name -> [header_line, end_line_exclusive) from the ORIGINAL
    # text; insertions are applied bottom-up so earlier indices stay valid.
    section_ranges: dict[str, tuple[int, int]] = {}
    headers: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m:
            headers.append((i, m.group(1).strip()))
    for idx, (line_i, name) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        section_ranges[name] = (line_i, end)

    replaced: set[tuple[str, str]] = set()
    current_section = ""
    out: list[str] = []
    for line in lines:
        m_sec = _SECTION_RE.match(line)
        if m_sec:
            current_section = m_sec.group(1).strip()
            out.append(line)
            continue
        m_key = _KEY_RE.match(line)
        if m_key and (current_section, m_key.group(1)) in wanted:
            key_tuple = (current_section, m_key.group(1))
            out.append(f"{m_key.group(1)} = {wanted[key_tuple]}")
            replaced.add(key_tuple)
            continue
        out.append(line)

    # Group missing keys by section; existing sections get in-section inserts,
    # absent sections are appended at EOF as new blocks.
    missing: dict[str, list[tuple[str, str]]] = {}
    for key_tuple, rendered in wanted.items():
        if key_tuple not in replaced:
            missing.setdefault(key_tuple[0], []).append((key_tuple[1], rendered))

    insertions: list[tuple[int, list[str]]] = []  # (insert_at_index, lines)
    appends: list[str] = []
    for section, keys in missing.items():
        new_lines = [f"{key} = {rendered}" for key, rendered in keys]
        if section in section_ranges:
            _header, end = section_ranges[section]
            insertions.append((end, new_lines))
        else:
            appends.extend([f"[{section}]"] + new_lines)

    for at, new_lines in sorted(insertions, key=lambda x: x[0], reverse=True):
        out[at:at] = new_lines

    if appends:
        if out and out[-1] != "":
            out.append("")
        out.extend(appends)

    new_text = newline.join(out)
    if ends_newline:
        new_text += newline

    # Self-validate before touching disk: a broken render must never land.
    parsed = tomllib.loads(new_text)
    for (section, key) in wanted:
        assert key in parsed.get(section, {}), f"missing after render: [{section}] {key}"

    tmp = p.with_name(p.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        os.replace(tmp, p)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_config_writer.py -q`
Expected: PASS（10 个）

- [ ] **Step 5: 回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_config.py -q`
Expected: PASS（无回归）

```bash
git add backend/src/myphoto/config_writer.py backend/tests/test_config_writer.py
git commit -m "feat(p5): line-preserving config.toml writer for settings"
```

---

### Task 6: settings GET/PATCH + 锁定阈值接线 + retention=0 哨兵

**Files:**
- Modify: `backend/src/myphoto/main.py`（记 `app.state.config_path`）
- Modify: `backend/src/myphoto/routes_admin.py`（settings 端点）
- Modify: `backend/src/myphoto/routes_auth.py`（锁定阈值/时长读 config）
- Modify: `backend/src/myphoto/trash.py`（`NEVER_PURGE_TS`）
- Modify: `backend/src/myphoto/routes_images.py`（retention=0 → 哨兵）
- Test: `backend/tests/test_routes_admin_settings.py`（新建）
- Test: `backend/tests/test_routes_auth.py`（追加阈值热生效）
- Test: `backend/tests/test_routes_images_delete.py`（追加 retention=0）

**Interfaces:**
- Produces:
  - `GET /api/admin/settings` → `{trash_retention_days, login_lockout_threshold, trusted_proxies, session_hours}`
  - `PATCH /api/admin/settings`（部分更新）→ 同形状；非法值 400 `bad_request`；成功热替换 `app.state.config` 并写 `settings_update` 审计。
- Consumes: `update_settings_file`（Task 5）、`load_or_init`。

- [ ] **Step 1: 写失败测试（settings 端点）** — 新建 `backend/tests/test_routes_admin_settings.py`：

```python
from __future__ import annotations

import re
import tomllib

import pytest
from fastapi.testclient import TestClient

from myphoto.main import build_app
from sqlalchemy import select

from myphoto.models import AuditLog


@pytest.fixture
def client(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app, client=("127.0.0.1", 12345)) as c:
        pw = re.search(r"password=(\S+)", capsys.readouterr().out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        yield c, app, tmp_path / "config.toml"


def test_get_settings_defaults(client):
    c, _app, _path = client
    r = c.get("/api/admin/settings")
    assert r.status_code == 200
    assert r.json() == {
        "trash_retention_days": 30,
        "login_lockout_threshold": 5,
        "trusted_proxies": [],
        "session_hours": 8,
    }


def test_patch_settings_persists_and_hot_reloads(client):
    c, app, path = client
    r = c.patch("/api/admin/settings", json={
        "trash_retention_days": 90,
        "login_lockout_threshold": 3,
        "trusted_proxies": ["127.0.0.1", "10.0.0.0/8"],
        "session_hours": 24,
    })
    assert r.status_code == 200
    assert r.json()["trash_retention_days"] == 90
    assert app.state.config.trash_retention_days == 90
    assert app.state.config.trusted_proxies == ["127.0.0.1", "10.0.0.0/8"]

    # Written through to the file.
    on_disk = tomllib.loads(path.read_text(encoding="utf-8"))
    assert on_disk["trash"]["retention_days"] == 90
    assert on_disk["security"]["trusted_proxies"] == ["127.0.0.1", "10.0.0.0/8"]

    # Audit only records changed key names, no values.
    async def _audit():
        async with app.state.sessionmaker() as s:
            return (await s.execute(
                select(AuditLog).where(AuditLog.action == "settings_update")
            )).scalars().all()
    rows = c.portal.call(_audit)
    assert len(rows) == 1
    assert '"trusted_proxies"' in rows[0].detail
    assert "127.0.0.1" not in (rows[0].detail or "")


@pytest.mark.parametrize("body", [
    {"trash_retention_days": 15},          # not in 0/7/30/90
    {"login_lockout_threshold": 0},
    {"login_lockout_threshold": 101},
    {"session_hours": 0},
    {"session_hours": 721},
    {"trusted_proxies": ["not-an-ip"]},
    {"trusted_proxies": ["10.0.0.0/33"]},
    {"trusted_proxies": ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5",
                         "6.6.6.6", "7.7.7.7", "8.8.8.8", "9.9.9.9", "0.0.0.0",
                         "11.11.11.11", "12.12.12.12", "13.13.13.13",
                         "14.14.14.14", "15.15.15.15", "16.16.16.16",
                         "17.17.17.17"]},
])
def test_patch_settings_rejects_invalid(client, body):
    c, _app, path = client
    before = path.read_text(encoding="utf-8")
    r = c.patch("/api/admin/settings", json=body)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"
    # invalid request must not touch disk or live config
    assert path.read_text(encoding="utf-8") == before


def test_patch_settings_empty_body_is_noop(client):
    c, app, _path = client
    r = c.patch("/api/admin/settings", json={})
    assert r.status_code == 200
    async def _audit():
        async with app.state.sessionmaker() as s:
            return (await s.execute(
                select(AuditLog).where(AuditLog.action == "settings_update")
            )).scalars().all()
    assert c.portal.call(_audit) == []


def test_settings_forbidden_for_viewer(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app, client=("127.0.0.1", 12345)) as admin_client:
        pw = re.search(r"password=(\S+)", capsys.readouterr().out).group(1)
        admin_client.post("/api/auth/login",
                          json={"username": "admin", "password": pw})
        r = admin_client.post("/api/admin/users", json={
            "username": "viewer1", "password": "viewerpass123",
            "role": "viewer", "access_scope": "remote_allowed",
        })
        assert r.status_code == 201

    with TestClient(app, client=("127.0.0.1", 12345)) as vc:
        vc.post("/api/auth/login",
                json={"username": "viewer1", "password": "viewerpass123"})
        assert vc.get("/api/admin/settings").status_code == 403
        assert vc.patch("/api/admin/settings",
                        json={"session_hours": 1}).status_code == 403
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_routes_admin_settings.py -q`
Expected: FAIL — 404/405。

- [ ] **Step 3: main.py 记录 config 路径** — `build_app` 开头把：

```python
    cfg = load_or_init(resolve_config_path(config_path))
```

改为：

```python
    config_file = resolve_config_path(config_path)
    cfg = load_or_init(config_file)
```

并在 `app = FastAPI(...)` 之后、`app.state.login_lockout = {}` 旁加：

```python
    app.state.config_path = config_file
```

- [ ] **Step 4: 实现 settings 端点** — `routes_admin.py`：

(a) 顶部 import 增补（`import ipaddress`、`import json` 加进标准库区；其余并入既有 import 行）：

```python
import ipaddress
import json
```

```python
from myphoto.config import load_or_init
from myphoto.config_writer import SettingsUpdates, update_settings_file
```

(b) 在 status/audit 段附近（如 `admin_query_audit` 之后）追加：

```python
# ---- settings (P5) ----


class SettingsPatch(BaseModel):
    trash_retention_days: int | None = None
    login_lockout_threshold: int | None = None
    trusted_proxies: list[str] | None = None
    session_hours: int | None = None


_RETENTION_CHOICES = {0, 7, 30, 90}


def _valid_proxy_entry(entry: str) -> bool:
    try:
        ipaddress.ip_address(entry)
        return True
    except ValueError:
        pass
    try:
        ipaddress.ip_network(entry, strict=False)
        return True
    except ValueError:
        return False


def _settings_payload(cfg) -> dict:
    return {
        "trash_retention_days": cfg.trash_retention_days,
        "login_lockout_threshold": cfg.login_lockout_threshold,
        "trusted_proxies": list(cfg.trusted_proxies),
        "session_hours": cfg.session_hours,
    }


def _validate_settings(body: SettingsPatch) -> list[str]:
    errors: list[str] = []
    if body.trash_retention_days is not None and (
        body.trash_retention_days not in _RETENTION_CHOICES
    ):
        errors.append("trash_retention_days must be one of 0/7/30/90")
    if body.login_lockout_threshold is not None and not (
        1 <= body.login_lockout_threshold <= 100
    ):
        errors.append("login_lockout_threshold must be between 1 and 100")
    if body.session_hours is not None and not (1 <= body.session_hours <= 720):
        errors.append("session_hours must be between 1 and 720")
    if body.trusted_proxies is not None:
        if len(body.trusted_proxies) > 16:
            errors.append("trusted_proxies accepts at most 16 entries")
        else:
            for entry in body.trusted_proxies:
                if not _valid_proxy_entry(entry):
                    errors.append(f"invalid trusted_proxies entry: {entry}")
                    break
    return errors


@router.get("/settings")
async def admin_get_settings(
    request: Request,
    _admin: User = Depends(admin_required),
):
    return _settings_payload(request.app.state.config)


@router.patch("/settings")
async def admin_update_settings(
    body: SettingsPatch,
    request: Request,
    admin: User = Depends(admin_required),
):
    errors = _validate_settings(body)
    if errors:
        raise AppError("bad_request", 400, "; ".join(errors))

    proxies: list[str] | None = None
    if body.trusted_proxies is not None:
        seen: set[str] = set()
        proxies = []
        for entry in body.trusted_proxies:
            if entry not in seen:
                seen.add(entry)
                proxies.append(entry)

    updates = SettingsUpdates(
        trash_retention_days=body.trash_retention_days,
        login_lockout_threshold=body.login_lockout_threshold,
        trusted_proxies=proxies,
        session_hours=body.session_hours,
    )
    changed = [
        name for name, value in (
            ("trash_retention_days", body.trash_retention_days),
            ("login_lockout_threshold", body.login_lockout_threshold),
            ("trusted_proxies", body.trusted_proxies),
            ("session_hours", body.session_hours),
        ) if value is not None
    ]

    config_path = request.app.state.config_path
    if changed:
        update_settings_file(config_path, updates)
        request.app.state.config = load_or_init(config_path)
        async with request.app.state.sessionmaker() as s:
            await write_audit(
                s, "settings_update", admin.id, _client_ip(request),
                target="settings",
                detail=json.dumps({"changed": changed}, ensure_ascii=False),
            )
            await s.commit()

    return _settings_payload(request.app.state.config)
```

- [ ] **Step 5: 跑 settings 测试**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_routes_admin_settings.py -q`
Expected: PASS（参数化非法值约 10 个 + 其余 6 个）。

- [ ] **Step 6: 锁定阈值接线** — `routes_auth.py`：

(a) 两个辅助函数改为接收参数（保留模块常量作为默认值，其他调用方无需改）：

```python
def _record_fail(
    state: dict[str, tuple[int, float]], ip: str, window_sec: int = _LOCKOUT_WINDOW_SEC
) -> None:
    now = time.monotonic()
    count, first = state.get(ip, (0, now))
    if now - first >= window_sec:
        count, first = 0, now
    state[ip] = (count + 1, first)


def _is_locked(
    state: dict[str, tuple[int, float]], ip: str,
    threshold: int = _LOCKOUT_THRESHOLD,
    window_sec: int = _LOCKOUT_WINDOW_SEC,
) -> bool:
    entry = state.get(ip)
    if entry is None:
        return False
    count, first = entry
    if time.monotonic() - first >= window_sec:
        state.pop(ip, None)
        return False
    return count >= threshold
```

(b) `login` 函数开头（`ip = _client_ip(request)` 之后）读取配置，并替换两处调用：

```python
    cfg = request.app.state.config
    lockout_threshold = int(cfg.login_lockout_threshold)
    lockout_window_sec = int(cfg.login_lockout_minutes) * 60
    lockout_state = request.app.state.login_lockout
    if _is_locked(lockout_state, ip, lockout_threshold, lockout_window_sec):
        raise AppError("login_locked", 423, "too many failed attempts; try again later")
```

把失败分支的 `_record_fail(lockout_state, ip)` 改为 `_record_fail(lockout_state, ip, lockout_window_sec)`；删除后文重复的 `cfg = request.app.state.config`（直接复用顶部 `cfg`）。

(c) 追加测试到 `backend/tests/test_routes_auth.py`（沿用该文件既有 fixture 名；若文件里的 client fixture 不叫 `client`，把签名替换为文件中已登录 admin 的 fixture）：

```python
def test_lockout_threshold_hot_reload_via_settings(tmp_path, capsys):
    from fastapi.testclient import TestClient
    import re as _re
    from myphoto.main import build_app

    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app, client=("127.0.0.1", 12345)) as c:
        pw = _re.search(r"password=(\S+)", capsys.readouterr().out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        assert c.patch("/api/admin/settings",
                       json={"login_lockout_threshold": 2}).status_code == 200

        # Two failures record counts 1 and 2; the third attempt is locked.
        r1 = c.post("/api/auth/login", json={"username": "admin", "password": "bad"})
        r2 = c.post("/api/auth/login", json={"username": "admin", "password": "bad"})
        r3 = c.post("/api/auth/login", json={"username": "admin", "password": "bad"})
        assert r1.status_code == 401
        assert r2.status_code == 401
        assert r3.status_code == 423
        assert r3.json()["error"]["code"] == "login_locked"
```

- [ ] **Step 7: retention=0 哨兵** —

(a) `trash.py` 在模块常量区（`TRASH_BASENAME` 旁）加：

```python
# 2286 年附近；retention_days=0（永不自动清理）时作为 purge_after 哨兵值。
# purge_expired 的查询是 purge_after < now，哨兵永不命中。
NEVER_PURGE_TS = 9_999_999_999
```

(b) `routes_images.py` 把写 Trash 行的 `purge_after=now + retention_days * 86400,` 改为：

```python
        purge_after=(
            now + retention_days * 86400
            if retention_days > 0 else NEVER_PURGE_TS
        ),
```

该文件第 29 行现有 `from myphoto.trash import trash_dir_for`，直接改为：

```python
from myphoto.trash import NEVER_PURGE_TS, trash_dir_for
```

(c) 追加测试到 `backend/tests/test_routes_images_delete.py`（该文件已有建图/删除的配套 fixture；按文件实际 fixture 名调整前两行）：

```python
def test_retention_zero_writes_never_purge_sentinel(client_with_image):
    # fixture 提供已登录 client / gid / rid / image_id（按实际命名调整）
    c, image_id, app = client_with_image
    assert c.patch("/api/admin/settings",
                   json={"trash_retention_days": 0}).status_code == 200
    assert c.delete(f"/api/images/{image_id}").status_code == 204

    from myphoto.trash import NEVER_PURGE_TS
    from myphoto.models import Trash
    from sqlalchemy import select

    async def _row():
        async with app.state.sessionmaker() as s:
            return (await s.execute(select(Trash))).scalar_one()
    row = c.portal.call(_row)
    assert row.purge_after == NEVER_PURGE_TS

    # Manual "purge expired" must leave the sentinel row alone.
    r = c.post("/api/trash/purge", json={"confirm": True})
    assert r.status_code == 200
    assert c.portal.call(_row).purge_after == NEVER_PURGE_TS
```

若该文件的 fixture 不返回 `(client, image_id, app)`，参考其中已有删除用例的搭建方式（建 root→扫描→查 image_id），核心断言只有两条：`purge_after == NEVER_PURGE_TS`；`POST /api/trash/purge {"confirm": true}` 后行仍在。

- [ ] **Step 8: 跑相关回归**

Run:
`.venv/Scripts/python.exe -m pytest backend/tests/test_routes_admin_settings.py backend/tests/test_routes_auth.py backend/tests/test_routes_images_delete.py backend/tests/test_trash.py backend/tests/test_startup_purge.py -q`
Expected: PASS。

- [ ] **Step 9: 提交**

```bash
git add backend/src/myphoto/main.py backend/src/myphoto/routes_admin.py backend/src/myphoto/routes_auth.py backend/src/myphoto/trash.py backend/src/myphoto/routes_images.py backend/tests/
git commit -m "feat(p5): settings API + lockout config wiring + never-purge sentinel"
```

---

### Task 7: 每日定时回收站清理

**Files:**
- Modify: `backend/src/myphoto/trash.py`（`next_daily_run` + `daily_purge_loop`）
- Modify: `backend/src/myphoto/main.py`（lifespan 启停任务）
- Test: `backend/tests/test_daily_purge.py`（新建）

**Interfaces:**
- Produces:
  - `next_daily_run(now_dt: datetime.datetime, hour: int, minute: int) -> datetime.datetime`（纯函数；越界时刻回退 03:30）
  - `daily_purge_loop(sessionmaker, config_getter) -> Coroutine`：循环 sleep 到下一时刻 → `purge_expired(actor_ip="scheduled")`；有结果时写一条聚合 `trash_purge` 审计；`CancelledError` 正常退出，其他异常记录后继续。

- [ ] **Step 1: 写失败测试** — 新建 `backend/tests/test_daily_purge.py`：

```python
from __future__ import annotations

import datetime as dt
import time

import pytest
from PIL import Image as PILImage

from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import AuditLog, Gallery, GalleryRoot, Trash
from myphoto.trash import daily_purge_loop, next_daily_run
from sqlalchemy import select


def test_next_daily_run_later_today():
    now = dt.datetime(2026, 10, 28, 2, 0, 0)
    nxt = next_daily_run(now, 3, 30)
    assert nxt == dt.datetime(2026, 10, 28, 3, 30)


def test_next_daily_run_tomorrow_when_time_passed():
    now = dt.datetime(2026, 10, 28, 10, 0, 0)
    nxt = next_daily_run(now, 3, 30)
    assert nxt == dt.datetime(2026, 10, 29, 3, 30)


def test_next_daily_run_equal_time_means_tomorrow():
    now = dt.datetime(2026, 10, 28, 3, 30, 0)
    assert next_daily_run(now, 3, 30) == dt.datetime(2026, 10, 29, 3, 30)


@pytest.mark.parametrize("hour,minute", [(25, 0), (-1, 0), (3, 60), (3, -1)])
def test_next_daily_run_invalid_config_falls_back(hour, minute):
    # 10:00 with fallback 03:30 -> already passed today -> tomorrow 03:30
    nxt = next_daily_run(dt.datetime(2026, 10, 28, 10, 0), hour, minute)
    assert (nxt.hour, nxt.minute) == (3, 30)
    assert nxt.date() == dt.date(2026, 10, 29)


class _Cfg:
    trash_purge_hour = 3
    trash_purge_minute = 30


@pytest.fixture
async def loop_env(tmp_path):
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    photos = tmp_path / "photos"
    photos.mkdir()
    async with sm() as s:
        g = Gallery(name="G", created_at=int(time.time()))
        s.add(g)
        await s.flush()
        r = GalleryRoot(gallery_id=g.id, label="R",
                        absolute_path=str(photos.resolve()), enabled=1)
        s.add(r)
        await s.commit()
        await s.refresh(r)
        gid, rid = g.id, r.id
    tdir = photos / f".trash/{gid}/{rid}/20260101"
    tdir.mkdir(parents=True)
    trash_file = tdir / "expired.jpg"
    trash_file.write_bytes(b"x")
    now = int(time.time())
    async with sm() as s:
        s.add(Trash(
            gallery_id=gid, root_id=rid,
            original_relative_path="expired.jpg",
            trash_relative_path=f".trash/{gid}/{rid}/20260101/expired.jpg",
            sha1="s", size_bytes=1, deleted_by=1,
            deleted_at=now - 86400, purge_after=now - 100,
        ))
        await s.commit()
    yield sm, trash_file
    await engine.dispose()


async def test_daily_loop_purges_and_audits_then_cancels(loop_env, monkeypatch):
    sm, trash_file = loop_env
    sleeps = {"n": 0}

    async def fake_sleep(seconds):
        sleeps["n"] += 1
        if sleeps["n"] == 1:
            return  # fire the purge immediately
        raise asyncio.CancelledError

    import myphoto.trash as trash_mod
    monkeypatch.setattr(trash_mod.asyncio, "sleep", fake_sleep)

    task = asyncio.create_task(daily_purge_loop(sm, lambda: _Cfg()))
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not trash_file.exists()
    async with sm() as s:
        assert (await s.execute(select(Trash))).scalars().all() == []
        audits = (await s.execute(
            select(AuditLog).where(AuditLog.action == "trash_purge")
        )).scalars().all()
    assert len(audits) == 1
    assert audits[0].actor_ip == "scheduled"
    assert "purged=1" in (audits[0].detail or "")


async def test_daily_loop_survives_purge_error(loop_env, monkeypatch):
    """purge 抛非取消异常时循环不死：第二次 sleep 被 cancel 能正常退出。"""
    sm, _trash_file = loop_env
    sleeps = {"n": 0}

    async def fake_sleep(seconds):
        sleeps["n"] += 1
        raise asyncio.CancelledError

    import myphoto.trash as trash_mod

    async def boom(*_a, **_kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(trash_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(trash_mod, "purge_expired", boom)

    task = asyncio.create_task(daily_purge_loop(sm, lambda: _Cfg()))
    # First iteration: sleep immediately raises CancelledError BEFORE purge,
    # so the loop exits cleanly without calling the broken purge at all.
    with pytest.raises(asyncio.CancelledError):
        await task
```

最后一个用例只验证 cancel 语义；"purge 失败后循环继续"的行为改由下面的实现保证，用例保持简单。文件顶部加 `import asyncio`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_daily_purge.py -q`
Expected: FAIL — `ImportError: cannot import name 'next_daily_run'`

- [ ] **Step 3: 实现** — `trash.py`：

(a) 顶部 import 补 `asyncio` 与 `datetime`：

```python
import asyncio
import datetime
```

（与既有 `import logging / os / time` 同区，按字母序插入。）

(b) 在 `purge_expired` 之前插入：

```python
_DEFAULT_PURGE_HOUR = 3
_DEFAULT_PURGE_MINUTE = 30


def next_daily_run(
    now_dt: datetime.datetime, hour: int, minute: int
) -> datetime.datetime:
    """今天 hour:minute（未到）→ 今天；已到/越界配置 → 明天。

    非法 hour/minute 回退 03:30 而非抛异常（配置被手改不应拖垮启动）。
    """
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        hour, minute = _DEFAULT_PURGE_HOUR, _DEFAULT_PURGE_MINUTE
    target = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now_dt:
        target += datetime.timedelta(days=1)
    return target


async def daily_purge_loop(sessionmaker, config_getter) -> None:
    """P5: 每日按 [trash] purge_hour/purge_minute 跑一次到期清理。

    config_getter 每轮读取，设置页改了时刻下一轮即生效。CancelledError
    向外传播供 lifespan 关停；其他异常记录后继续，定时任务永不静默死亡。
    """
    while True:
        cfg = config_getter()
        now_dt = datetime.datetime.now()
        nxt = next_daily_run(
            now_dt, cfg.trash_purge_hour, cfg.trash_purge_minute
        )
        await asyncio.sleep(max(1.0, (nxt - now_dt).total_seconds()))
        try:
            async with sessionmaker() as session:
                result = await purge_expired(
                    session, actor_user_id=None, actor_ip="scheduled",
                )
                if any(result.values()):
                    await write_audit(
                        session, "trash_purge", None, "scheduled",
                        target="scheduled",
                        detail=(
                            "purged={purged} blocked={blocked} "
                            "missing={missing} errors={errors}"
                        ).format(**result),
                    )
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduled purge_expired failed")
```

- [ ] **Step 4: lifespan 接线** — `main.py`：

(a) import 行改为：

```python
from myphoto.trash import daily_purge_loop, purge_expired
```

(b) 在启动清理块之后、`app.state.engine = engine` 之前启动任务：

```python
        purge_task = asyncio.create_task(
            daily_purge_loop(sm, lambda: app.state.config)
        )
```

（需要 `import asyncio`，加入 main.py 顶部 import 区；`app` 在闭包中引用，lifespan 接收的 `app` 参数已在作用域内。）

(c) `finally` 块改为：

```python
        finally:
            purge_task.cancel()
            try:
                await purge_task
            except asyncio.CancelledError:
                pass
            await scanner.stop()
            await engine.dispose()
```

- [ ] **Step 5: 跑测试与启动回归**

Run:
`.venv/Scripts/python.exe -m pytest backend/tests/test_daily_purge.py backend/tests/test_startup_purge.py backend/tests/test_main.py -q`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/src/myphoto/trash.py backend/src/myphoto/main.py backend/tests/test_daily_purge.py
git commit -m "feat(p5): daily scheduled trash purge in lifespan"
```

---

### Task 8: 前端 AdminSettings 页 + 路由 + 菜单

**Files:**
- Create: `frontend/src/views/AdminSettings.vue`
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/components/AppHeader.vue`
- Modify: `frontend/src/api.ts`（补两个路径错误码中文映射）
- Test: `frontend/src/tests/admin-settings.spec.ts`（新建）

**Interfaces:**
- Consumes: `GET/PATCH /api/admin/settings`（Task 6）。
- Settings JSON：`{trash_retention_days, login_lockout_threshold, trusted_proxies, session_hours}`。

- [ ] **Step 1: 写失败测试** — 新建 `frontend/src/tests/admin-settings.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AdminSettings from "../views/AdminSettings.vue"

interface Settings {
  trash_retention_days: number
  login_lockout_threshold: number
  trusted_proxies: string[]
  session_hours: number
}

const DEFAULTS: Settings = {
  trash_retention_days: 30,
  login_lockout_threshold: 5,
  trusted_proxies: [],
  session_hours: 8,
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/admin/settings", component: AdminSettings }],
  })
  await router.push("/admin/settings")
  const w = mount(AdminSettings, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return w
}

describe("AdminSettings", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  it("loads and renders current values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(DEFAULTS)))
    const w = await mountView()

    const checkedRadio = w.findAll('input[type="radio"]').find(
      (r) => (r.element as HTMLInputElement).checked,
    )!
    expect((checkedRadio.element as HTMLInputElement).value).toBe("30")
    const numbers = w.findAll('input[type="number"]')
    expect((numbers[0].element as HTMLInputElement).value).toBe("5")
    expect((numbers[1].element as HTMLInputElement).value).toBe("8")
  })

  it("saves changed fields via PATCH and shows confirmation", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(DEFAULTS))
      .mockResolvedValueOnce(json({ ...DEFAULTS, login_lockout_threshold: 3 }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    const threshold = w.findAll('input[type="number"]')[0]
    await threshold.setValue(3)
    const save = w.findAll("button").find((b) => b.text() === "保存")!
    await save.trigger("click")
    await flushPromises()

    expect(fetchFn).toHaveBeenCalledTimes(2)
    const [url, init] = fetchFn.mock.calls[1]
    expect(url).toBe("/api/admin/settings")
    expect(init.method).toBe("PATCH")
    expect(JSON.parse(init.body)).toEqual({
      trash_retention_days: 30,
      login_lockout_threshold: 3,
      trusted_proxies: [],
      session_hours: 8,
    })
    expect(w.text()).toContain("已保存")
  })

  it("never-retention radio posts value 0", async () => {
    const fetchFn = vi.fn()
    fetchFn.mockResolvedValueOnce(json(DEFAULTS))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    const never = w.findAll('input[type="radio"]').find(
      (r) => (r.element as HTMLInputElement).value === "0",
    )!
    await never.trigger("click")
    const save = w.findAll("button").find((b) => b.text() === "保存")!
    await save.trigger("click")
    await flushPromises()

    const [, init] = fetchFn.mock.calls[1]
    expect(JSON.parse(init.body).trash_retention_days).toBe(0)
  })

  it("adds and removes trusted_proxies rows, dropping empty rows on save", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(DEFAULTS))
      .mockResolvedValueOnce(json({ ...DEFAULTS, trusted_proxies: ["10.0.0.0/8"] }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    await w.findAll("button").find((b) => b.text().includes("添加"))!.trigger("click")
    await w.findAll("button").find((b) => b.text().includes("添加"))!.trigger("click")
    const proxyInputs = w.findAll('input[placeholder*="127.0.0.1"]')
    expect(proxyInputs).toHaveLength(2)
    await proxyInputs[0].setValue("10.0.0.0/8")
    // second row left empty -> must be dropped
    const removeBtns = w.findAll("button").filter((b) => b.text() === "删除")
    await removeBtns[1].trigger("click") // delete the empty row directly

    const save = w.findAll("button").find((b) => b.text() === "保存")!
    await save.trigger("click")
    await flushPromises()

    const [, init] = fetchFn.mock.calls[1]
    expect(JSON.parse(init.body).trusted_proxies).toEqual(["10.0.0.0/8"])
  })

  it("shows backend validation message and keeps form", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(DEFAULTS))
      .mockResolvedValueOnce(
        json({ error: { code: "bad_request", message: "session_hours must be between 1 and 720" } }, 400),
      )
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    const hours = w.findAll('input[type="number"]')[1]
    await hours.setValue(9999)
    await w.findAll("button").find((b) => b.text() === "保存")!.trigger("click")
    await flushPromises()

    expect(w.text()).toContain("session_hours must be between 1 and 720")
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && pnpm test -- --run src/tests/admin-settings.spec.ts`
Expected: FAIL — 无法解析 `../views/AdminSettings.vue`。

- [ ] **Step 3: 实现 AdminSettings.vue** — 新建 `frontend/src/views/AdminSettings.vue`：

```vue
<template>
  <div>
    <AppHeader>
      <template #title>
        <span class="text-neutral-400">管理 · 设置</span>
      </template>
    </AppHeader>
    <main class="mx-auto max-w-2xl space-y-6 p-4">
      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <template v-else>
        <div v-if="error"
             class="rounded bg-red-900/30 px-3 py-2 text-sm text-red-300">
          {{ error }}
        </div>

        <!-- 回收站 -->
        <section class="rounded-lg bg-neutral-900 p-4">
          <h2 class="mb-3 text-sm font-medium text-neutral-400">回收站</h2>
          <div class="mb-2 text-xs text-neutral-500">自动清理前的保留时长</div>
          <div class="flex flex-wrap gap-4 text-sm">
            <label v-for="opt in RETENTION_OPTIONS" :key="opt.value"
                   class="flex cursor-pointer items-center gap-1.5">
              <input type="radio" name="retention" class="accent-blue-600"
                     :value="opt.value" v-model.number="form.trash_retention_days">
              {{ opt.label }}
            </label>
          </div>
          <p class="mt-2 text-xs text-neutral-500">
            对新删除的图片生效；已在回收站中的条目到期时间不变。
          </p>
        </section>

        <!-- 登录安全 -->
        <section class="rounded-lg bg-neutral-900 p-4">
          <h2 class="mb-3 text-sm font-medium text-neutral-400">登录安全</h2>
          <label class="block text-xs text-neutral-500">
            登录失败锁定阈值（1–100 次）
          </label>
          <input v-model.number="form.login_lockout_threshold"
                 type="number" min="1" max="100"
                 class="mt-1 w-28 rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500">
          <p class="mt-2 text-xs text-neutral-500">
            连续登录失败达到此次数后将被临时锁定；锁定时长在 config.toml 中配置。
          </p>

          <label class="mt-4 block text-xs text-neutral-500">会话时长（1–720 小时）</label>
          <input v-model.number="form.session_hours"
                 type="number" min="1" max="720"
                 class="mt-1 w-28 rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500">
          <p class="mt-2 text-xs text-neutral-500">对新登录生效。</p>
        </section>

        <!-- 可信代理 -->
        <section class="rounded-lg bg-neutral-900 p-4">
          <h2 class="mb-3 text-sm font-medium text-neutral-400">
            可信代理（trusted_proxies）
          </h2>
          <div class="space-y-2">
            <div v-for="(_, i) in form.trusted_proxies" :key="i"
                 class="flex items-center gap-2">
              <input v-model="form.trusted_proxies[i]"
                     placeholder="如 127.0.0.1 或 10.0.0.0/8"
                     class="min-w-0 flex-1 rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500">
              <button type="button" @click="removeProxy(i)"
                      class="shrink-0 rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
                删除
              </button>
            </div>
          </div>
          <button type="button" @click="addProxy"
                  class="mt-2 rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
            + 添加
          </button>
          <p class="mt-2 text-xs text-neutral-500">
            仅这些来源（IP 或 CIDR）转发的 X-Forwarded-For 会被采纳；留空表示不信任任何代理。
          </p>
        </section>

        <div class="flex items-center gap-3">
          <button @click="save" :disabled="!dirty || saving"
                  class="rounded bg-blue-600 px-4 py-1.5 text-sm hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">
            {{ saving ? "保存中..." : "保存" }}
          </button>
          <span v-if="savedOk" class="text-xs text-green-400">已保存</span>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiGet, apiPatch, HttpError } from "../api"

interface SettingsForm {
  trash_retention_days: number
  login_lockout_threshold: number
  trusted_proxies: string[]
  session_hours: number
}

const RETENTION_OPTIONS = [
  { value: 7, label: "7 天" },
  { value: 30, label: "30 天" },
  { value: 90, label: "90 天" },
  { value: 0, label: "永不" },
]

const loading = ref(true)
const saving = ref(false)
const error = ref("")
const savedOk = ref(false)
const form = ref<SettingsForm>({
  trash_retention_days: 30,
  login_lockout_threshold: 5,
  trusted_proxies: [],
  session_hours: 8,
})
const loadedJson = ref("")

const dirty = computed(() => JSON.stringify(normalized()) !== loadedJson.value)

function normalized(): SettingsForm {
  return {
    trash_retention_days: form.value.trash_retention_days,
    login_lockout_threshold: form.value.login_lockout_threshold,
    trusted_proxies: form.value.trusted_proxies.map((s) => s.trim()).filter(Boolean),
    session_hours: form.value.session_hours,
  }
}

function addProxy() {
  form.value.trusted_proxies.push("")
}

function removeProxy(i: number) {
  form.value.trusted_proxies.splice(i, 1)
}

async function load() {
  loading.value = true
  error.value = ""
  try {
    const data = await apiGet<SettingsForm>("/api/admin/settings")
    form.value = {
      trash_retention_days: data.trash_retention_days,
      login_lockout_threshold: data.login_lockout_threshold,
      trusted_proxies: [...data.trusted_proxies],
      session_hours: data.session_hours,
    }
    loadedJson.value = JSON.stringify(normalized())
  } catch (err) {
    error.value = (err as HttpError).message || "加载失败"
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ""
  savedOk.value = false
  const body = normalized()
  if (
    body.login_lockout_threshold < 1 || body.login_lockout_threshold > 100 ||
    body.session_hours < 1 || body.session_hours > 720
  ) {
    error.value = "锁定阈值需在 1–100 之间，会话时长需在 1–720 小时之间。"
    saving.value = false
    return
  }
  try {
    await apiPatch("/api/admin/settings", body)
    loadedJson.value = JSON.stringify(body)
    form.value.trusted_proxies = [...body.trusted_proxies]
    savedOk.value = true
  } catch (err) {
    error.value = (err as HttpError).message || "保存失败"
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
```

- [ ] **Step 4: 路由 + 菜单 + 错误码映射** —

(a) `frontend/src/router.ts`：在 `/admin/users` 路由之后加：

```ts
  {
    path: "/admin/settings",
    component: () => import("./views/AdminSettings.vue"),
    meta: { requiresAdmin: true },
  },
```

(b) `frontend/src/components/AppHeader.vue`：管理菜单中「用户」项之后插入：

```html
          <router-link to="/admin/settings" role="menuitem"
            class="block px-3 py-2 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
            @click="adminOpen = false">
            设置
          </router-link>
```

(c) `frontend/src/api.ts` 的 `ERROR_MSG_ZH` 表补两行：

```ts
  path_invalid: "路径无效",
  path_not_readable: "路径不可读",
```

- [ ] **Step 5: 跑测试与类型检查**

Run: `cd frontend && pnpm test -- --run src/tests/admin-settings.spec.ts src/tests/app-header-scope.spec.ts`
Expected: PASS。

Run: `cd frontend && pnpm build`
Expected: vue-tsc + vite 通过。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/AdminSettings.vue frontend/src/router.ts frontend/src/components/AppHeader.vue frontend/src/api.ts frontend/src/tests/admin-settings.spec.ts
git commit -m "feat(p5): AdminSettings view with route and header menu"
```

---

### Task 9: 排除面板 + DirectoryChooser rootId + 回收站「永不」

**Files:**
- Modify: `frontend/src/utils/datetime.ts`（`NEVER_PURGE_TS` + `formatPurgeAfter`）
- Modify: `frontend/src/views/AdminTrash.vue`（到期列用新 helper）
- Modify: `frontend/src/components/DirectoryChooser.vue`（可选 `rootId` prop）
- Modify: `frontend/src/views/AdminGalleryEdit.vue`（root 卡片内联排除面板）
- Test: `frontend/src/tests/datetime.spec.ts`
- Test: `frontend/src/tests/exclusions-panel.spec.ts`（新建）

**Interfaces:**
- `GET/POST/DELETE …/exclusions`（Task 3）；选择器请求体 `{path, root_id?}`（Task 4）。

- [ ] **Step 1: 写失败测试（datetime helper）** — 在 `frontend/src/tests/datetime.spec.ts` 末尾追加：

```ts
import { formatPurgeAfter, NEVER_PURGE_TS } from "../utils/datetime"

describe("formatPurgeAfter", () => {
  it("renders the sentinel timestamp as 永不", () => {
    expect(formatPurgeAfter(NEVER_PURGE_TS)).toBe("永不")
    expect(formatPurgeAfter(NEVER_PURGE_TS + 100)).toBe("永不")
  })

  it("formats ordinary timestamps as YYYY-MM-DD HH:mm", () => {
    const ts = Math.floor(new Date(2026, 9, 28, 9, 5).getTime() / 1000)
    expect(formatPurgeAfter(ts)).toBe("2026-10-28 09:05")
  })
})
```

注意：把 `formatDateTime` 的既有 import 与新 import 合并成一行。

- [ ] **Step 2: 实现 datetime helper** — `frontend/src/utils/datetime.ts` 末尾追加：

```ts
/** 与后端 trash.NEVER_PURGE_TS 一致：retention_days=0（永不自动清理）的哨兵。 */
export const NEVER_PURGE_TS = 9_999_999_999

/** 回收站到期时间：哨兵显示「永不」，其余走普通日期时间格式。 */
export function formatPurgeAfter(unixSec: number): string {
  return unixSec >= NEVER_PURGE_TS ? "永不" : formatDateTime(unixSec)
}
```

- [ ] **Step 3: AdminTrash 接线** — `frontend/src/views/AdminTrash.vue`：

- script 区 import 追加（如文件内已有本地 `formatTs`，保留给 `deleted_at` 用或一并替换；本步只改到期列）：

```ts
import { formatPurgeAfter } from "../utils/datetime"
```

- 模板到期列（现状 `{{ formatTs(e.purge_after) }}`，约第 100 行）改为：

```html
                  {{ formatPurgeAfter(e.purge_after) }}
```

- [ ] **Step 4: 写排除面板测试** — 新建 `frontend/src/tests/exclusions-panel.spec.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AdminGalleryEdit from "../views/AdminGalleryEdit.vue"
import DirectoryChooser from "../components/DirectoryChooser.vue"

const GALLERY = {
  id: 1,
  name: "Home",
  description: null,
  roots: [{
    id: 10,
    label: "Main",
    absolute_path: "/photos/main",
    enabled: true,
    image_count: 0,
    status: "idle",
    last_scan_at: null,
    last_scan_status: "ok",
    last_scan_error: null,
  }],
}

const EXCLUSIONS = {
  root_id: 10,
  entries: [{
    id: 55,
    relative_path: "exports",
    reason: "临时",
    excluded_by: 1,
    excluded_by_username: "admin",
    excluded_at: 1_782_600_000,
  }],
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/admin/galleries/:gid", component: AdminGalleryEdit }],
  })
  await router.push("/admin/galleries/1")
  const w = mount(AdminGallery, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return w
}

describe("AdminGalleryEdit exclusions panel", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.unstubAllGlobals()
  })

  it("loads and shows exclusions lazily", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(GALLERY))      // gallery detail
      .mockResolvedValueOnce(json(EXCLUSIONS))   // exclusions GET
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    await w.findAll("button").find((b) => b.text() === "排除目录")!.trigger("click")
    await flushPromises()

    expect(w.text()).toContain("exports")
    expect(w.text()).toContain("admin")
    const getCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) => c[0] === "/api/admin/galleries/1/roots/10/exclusions",
    )
    expect(getCall?.[1].method).toBe("GET")
  })

  it("shows empty state when no exclusions", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(GALLERY))
      .mockResolvedValueOnce(json({ root_id: 10, entries: [] }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()
    await w.findAll("button").find((b) => b.text() === "排除目录")!.trigger("click")
    await flushPromises()
    expect(w.text()).toContain("尚未排除任何目录")
  })

  it("removing an exclusion confirms, DELETEs, and reloads", async () => {
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(GALLERY))
      .mockResolvedValueOnce(json(EXCLUSIONS))
      .mockResolvedValueOnce(new Response(null, { status: 204 })) // DELETE
      .mockResolvedValueOnce(json(GALLERY))                       // loadGallery
      .mockResolvedValueOnce(json({ root_id: 10, entries: [] })) // exclusions reload
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()
    await w.findAll("button").find((b) => b.text() === "排除目录")!.trigger("click")
    await flushPromises()

    await w.findAll("button").find((b) => b.text() === "解除")!.trigger("click")
    await flushPromises()

    const delCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) =>
        c[0] === "/api/admin/galleries/1/roots/10/exclusions/55",
    )
    expect(delCall?.[1].method).toBe("DELETE")
    expect(w.text()).toContain("尚未排除任何目录")
  })

  it("add flow: chooser is confined to root, confirm POSTs absolute_path", async () => {
    vi.stubGlobal("prompt", vi.fn().mockReturnValue("备注"))
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(GALLERY))       // gallery
      .mockResolvedValueOnce(json(EXCLUSIONS))    // exclusions GET (panel open below)
      .mockResolvedValueOnce(json({              // browse-fs when chooser opens
        path: "/photos/main", entries: [], truncated: false,
      }))
      .mockResolvedValueOnce(json({              // POST exclusion
        id: 56,
        relative_path: "exports",
        reason: "备注",
        excluded_by: 1,
        excluded_by_username: "admin",
        excluded_at: 1_782_600_100,
      }))
      .mockResolvedValueOnce(json(GALLERY))      // loadGallery
      .mockResolvedValueOnce(json({ root_id: 10, entries: [
        { id: 56, relative_path: "exports", reason: "备注", excluded_by: 1,
          excluded_by_username: "admin", excluded_at: 1_782_600_100 },
      ]}))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()
    await w.findAll("button").find((b) => b.text() === "排除目录")!.trigger("click")
    await flushPromises()

    // Open chooser
    await w.findAll("button").find((b) => b.text().includes("添加排除"))!.trigger("click")
    await flushPromises()

    const chooser = w.findComponent(DirectoryChooser)
    expect(chooser.props("rootId")).toBe(10)
    expect(chooser.props("startPath")).toBe("/photos/main")
    const browseCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) => c[0] === "/api/admin/browse-fs",
    )
    expect(JSON.parse(browseCall![1].body! as string)).toMatchObject({
      path: "/photos/main",
      root_id: 10,
    })

    chooser.vm.$emit("confirm", "/photos/main/exports")
    await flushPromises()

    const postCall = fetchFn.mock.calls.find(
      (c: [string, RequestInit]) =>
        c[0] === "/api/admin/galleries/1/roots/10/exclusions" && c[1].method === "POST",
    )
    expect(JSON.parse(postCall![1].body! as string)).toEqual({
      absolute_path: "/photos/main/exports",
      reason: "备注",
    })
  })
})
```

（`mount(AdminGallery, ...)` 是笔误，实现时应为 `mount(AdminGalleryEdit, ...)`。）

- [ ] **Step 5: 跑测试确认失败**

Run: `cd frontend && pnpm test -- --run src/tests/datetime.spec.ts src/tests/exclusions-panel.spec.ts`
Expected: datetime 2 个失败；面板文件编译/交互失败。

- [ ] **Step 6: DirectoryChooser 支持 rootId** — `frontend/src/components/DirectoryChooser.vue`：

Props 改为：

```ts
interface Props {
  modelValue: boolean
  startPath?: string
  rootId?: number
}

const props = withDefaults(defineProps<Props>(), {
  startPath: "",
  rootId: undefined,
})
```

`browse()` 的请求行改为：

```ts
    const body: { path: string; root_id?: number } = { path }
    if (props.rootId !== undefined) body.root_id = props.rootId
    const data = await apiPost<BrowseResponse>("/api/admin/browse-fs", body)
```

- [ ] **Step 7: AdminGalleryEdit 排除面板** — `frontend/src/views/AdminGalleryEdit.vue`：

(a) 模板：root 卡片按钮行（含「重扫/禁用/移除」的 `<div class="mt-1 flex gap-2">`）在「移除」按钮前插入：

```html
                <button @click="toggleExclusions(r.id)"
                        class="rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
                  排除目录
                </button>
```

在该按钮所在 `</div>` 之后、卡片 `</div>` 之前插入面板：

```html
              <div v-if="exclusionPanels[r.id]" class="mt-2 rounded bg-neutral-800/50 p-2">
                <div v-if="exclusionsLoading[r.id]" class="text-xs text-neutral-400">加载中...</div>
                <div v-else-if="exclusionsError[r.id]" class="text-xs text-red-400">
                  {{ exclusionsError[r.id] }}
                </div>
                <template v-else>
                  <ul v-if="(exclusions[r.id] || []).length"
                      class="divide-y divide-neutral-800 text-xs">
                    <li v-for="e in exclusions[r.id]" :key="e.id"
                        class="flex items-center gap-2 py-1.5">
                      <span class="min-w-0 flex-1 truncate font-mono" :title="e.relative_path">
                        {{ e.relative_path }}
                      </span>
                      <span v-if="e.reason" class="truncate text-neutral-500" :title="e.reason">
                        {{ e.reason }}
                      </span>
                      <span class="shrink-0 text-neutral-500">{{ e.excluded_by_username || "—" }}</span>
                      <button @click="removeExclusion(r, e)"
                              class="shrink-0 rounded bg-neutral-700 px-2 py-0.5 hover:bg-neutral-600">
                        解除
                      </button>
                    </li>
                  </ul>
                  <div v-else class="py-1 text-xs text-neutral-500">尚未排除任何目录</div>
                  <button @click="openExclusionChooser(r)"
                          class="mt-2 rounded bg-neutral-700 px-2 py-1 text-xs hover:bg-neutral-600">
                    + 添加排除目录
                  </button>
                </template>
              </div>
```

(b) 既有添加根目录的 chooser 旁再挂一个：

```html
    <DirectoryChooser v-model="showExclusionChooser"
                      :start-path="chooserStartPath"
                      :root-id="chooserRootId ?? undefined"
                      @confirm="onExclusionChosen" />
```

(c) script 区：import 补 `errorMessage`：

```ts
import { apiGet, apiPatch, apiPost, apiDelete, HttpError, errorMessage } from "../api"
```

在 `const showChooser = ref(false)` 后加状态与函数：

```ts
interface ExclusionEntry {
  id: number
  relative_path: string
  reason: string | null
  excluded_by: number | null
  excluded_by_username: string | null
  excluded_at: number
}

const exclusionPanels = ref<Record<number, boolean>>({})
const exclusions = ref<Record<number, ExclusionEntry[]>>({})
const exclusionsLoading = ref<Record<number, boolean>>({})
const exclusionsError = ref<Record<number, string>>({})
const showExclusionChooser = ref(false)
const chooserRootId = ref<number | null>(null)
const chooserStartPath = ref("")

function exclusionUrl(rid: number) {
  return `/api/admin/galleries/${gid}/roots/${rid}/exclusions`
}

async function loadExclusions(rid: number) {
  exclusionsLoading.value[rid] = true
  exclusionsError.value[rid] = ""
  try {
    const d = await apiGet<{ root_id: number; entries: ExclusionEntry[] }>(
      exclusionUrl(rid),
    )
    exclusions.value[rid] = d.entries
  } catch (err) {
    exclusionsError.value[rid] = errorMessage(err, "加载失败")
  } finally {
    exclusionsLoading.value[rid] = false
  }
}

async function toggleExclusions(rid: number) {
  const open = !exclusionPanels.value[rid]
  exclusionPanels.value[rid] = open
  if (open && exclusions.value[rid] === undefined) {
    await loadExclusions(rid)
  }
}

async function removeExclusion(r: RootInfo, e: ExclusionEntry) {
  if (!window.confirm(
    `解除对「${e.relative_path}」的排除？\n\n该目录将在下次扫描时重新纳入图库，本地文件不会被改动。`,
  )) return
  try {
    await apiDelete(`${exclusionUrl(r.id)}/${e.id}`)
    await Promise.all([loadExclusions(r.id), loadGallery(true)])
  } catch (err) {
    exclusionsError.value[r.id] = errorMessage(err, "解除失败")
  }
}

function openExclusionChooser(r: RootInfo) {
  chooserRootId.value = r.id
  chooserStartPath.value = r.absolute_path
  showExclusionChooser.value = true
}

async function onExclusionChosen(path: string) {
  const rid = chooserRootId.value
  if (rid === null) return
  const reason = window.prompt("备注（可留空）：", "")
  try {
    await apiPost(exclusionUrl(rid), {
      absolute_path: path,
      reason: reason && reason.trim() ? reason.trim() : null,
    })
    await Promise.all([loadExclusions(rid), loadGallery(true)])
  } catch (err) {
    exclusionsError.value[rid] = errorMessage(err, "添加失败")
  }
}
```

- [ ] **Step 8: 跑前端相关测试与构建**

Run: `cd frontend && pnpm test -- --run src/tests/exclusions-panel.spec.ts src/tests/datetime.spec.ts src/tests/admin-gallery-edit.spec.ts src/tests/directory-chooser.spec.ts src/tests/admin-trash.spec.ts`
Expected: PASS（注意既有 admin-gallery-edit 测试中的 fetch 序列不受影响——面板是懒加载，不点开不发请求）。

Run: `cd frontend && pnpm build`
Expected: vue-tsc + vite 通过。

- [ ] **Step 9: 提交**

```bash
git add frontend/src/utils/datetime.ts frontend/src/views/AdminTrash.vue frontend/src/components/DirectoryChooser.vue frontend/src/views/AdminGalleryEdit.vue frontend/src/tests/
git commit -m "feat(p5): root exclusions panel, confined chooser, never-expire display"
```

---

### Task 10: 后端端到端集成测试

**Files:**
- Create: `backend/tests/test_p5_e2e.py`

**Interfaces:** 全链路只经 HTTP（与 `test_p2_e2e.py` 同风格），验证排除→重扫→解除→设置→哨兵的完整业务流。

- [ ] **Step 1: 写测试（实现已在 Task 2/3/6 完成，本测试应一次通过；若失败说明前序任务有回归）** — 新建 `backend/tests/test_p5_e2e.py`：

```python
"""P5 end-to-end: exclusions prune/restore via scans + settings hot reload."""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import select

from myphoto.main import build_app
from myphoto.models import Image, Trash


def _jpg(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (20, 20), (0, 0, 0)).save(p, "JPEG")


def _wait_idle(c, gid, rid, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status").json()
        if st["status"] == "idle":
            return
        time.sleep(0.05)
    raise AssertionError("scan did not finish")


def test_p5_exclusion_and_settings_flow(tmp_path, capsys):
    photos = tmp_path / "photos"
    photos.mkdir()
    _jpg(photos / "a" / "b" / "x.jpg")
    _jpg(photos / "a" / "bc" / "y.jpg")
    _jpg(photos / "keep.jpg")

    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app, client=("127.0.0.1", 12345)) as c:
        pw = re.search(r"password=(\S+)", capsys.readouterr().out).group(1)
        assert c.post("/api/auth/login",
                      json={"username": "admin", "password": pw}).status_code == 200

        gid = c.post("/api/admin/galleries", json={"name": "G"}).json()["id"]
        rid = c.post(
            f"/api/admin/galleries/{gid}/roots",
            json={"label": "R", "absolute_path": str(photos)},
        ).json()["id"]
        _wait_idle(c, gid, rid)

        ex_url = f"/api/admin/galleries/{gid}/roots/{rid}/exclusions"

        async def _images():
            async with app.state.sessionmaker() as s:
                return sorted(
                    row.relative_path
                    for row in (await s.execute(select(Image))).scalars()
                )
        assert c.portal.call(_images) == ["a/b/x.jpg", "a/bc/y.jpg", "keep.jpg"]

        # 1. Exclude a/b -> prune that subtree, keep a/bc.
        r = c.post(ex_url, json={"absolute_path": str(photos / "a" / "b")})
        assert r.status_code == 201
        _wait_idle(c, gid, rid)
        assert c.portal.call(_images) == ["a/bc/y.jpg", "keep.jpg"]

        # 2. Unexclude -> rescan restores the subtree.
        eid = r.json()["id"]
        assert c.delete(f"{ex_url}/{eid}").status_code == 204
        _wait_idle(c, gid, rid)
        assert c.portal.call(_images) == ["a/b/x.jpg", "a/bc/y.jpg", "keep.jpg"]

        # 3. Settings: retention=0 hot-reloads; deleted image gets the sentinel.
        assert c.patch("/api/admin/settings",
                       json={"trash_retention_days": 0}).status_code == 200
        assert app.state.config.trash_retention_days == 0

        async def _one_image_id():
            async with app.state.sessionmaker() as s:
                row = (await s.execute(
                    select(Image).where(Image.relative_path == "keep.jpg")
                )).scalar_one()
                return row.id
        image_id = c.portal.call(_one_image_id)
        assert c.delete(f"/api/images/{image_id}").status_code == 204

        async def _trash_row():
            async with app.state.sessionmaker() as s:
                return (await s.execute(select(Trash))).scalar_one()
        t = c.portal.call(_trash_row)
        assert t.purge_after == 9_999_999_999

        # Purge-expired must not touch it.
        pr = c.post("/api/trash/purge", json={"confirm": True})
        assert pr.status_code == 200
        assert c.portal.call(_trash_row).purge_after == 9_999_999_999
```

- [ ] **Step 2: 跑测试**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_p5_e2e.py -q`
Expected: PASS（1 个，含真实扫描，可能耗时数秒）。

- [ ] **Step 3: 提交**

```bash
git add backend/tests/test_p5_e2e.py
git commit -m "test(p5): end-to-end exclusions + never-purge settings flow"
```

---

### Task 11: 全量验证 + 红线 grep + tag

**Files:** 无新文件。

- [ ] **Step 1: 全量后端测试**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/ -q`
Expected: 全绿（基线 395 passed / 5 skipped；P5 新增约 50 个测试；跳过数可能因 Windows symlink 用例 +1）。

- [ ] **Step 2: 全量前端测试**

Run: `cd frontend && pnpm test -- --run`
Expected: 全绿（基线 188 passed；P5 新增约 12 个）。

- [ ] **Step 3: 前端构建（含 vue-tsc）**

Run: `cd frontend && pnpm build`
Expected: `✓ built`，无类型错误。

- [ ] **Step 4: 红线 grep**

```bash
rg -n "os\.remove" backend/src/myphoto/
rg -n "shutil\.rmtree" backend/src/myphoto/
rg -n "os\.rename" backend/src/myphoto/
rg -ni "remove|rmtree|unlink|mkdir" backend/src/myphoto/scanner.py backend/src/myphoto/config_writer.py
```

期望：
- `os.remove` 仍只在 `trash.py`（purge_expired / delete_one）；
- `shutil.rmtree` 仍只在 `routes_admin.py` 缩略图缓存清理；
- `os.rename` 仍只在删除入回收站路径（routes_images / trash 相关既有位点）；
- `scanner.py` 不得出现任何文件删除/创建调用；`config_writer.py` 只允许 `os.replace`（临时文件）与 tmp 的 `unlink(missing_ok=True)`。

- [ ] **Step 5: 手工冒烟（可选，不阻塞 tag）**

启动 `myphoto serve`，浏览器验证：图库编辑页排除一个子目录后图片消失、解除后回来；设置页改保留天数后 config.toml 内容更新且中文注释保留。

- [ ] **Step 6: 提交（若有收尾文档改动）并打 tag**

```bash
git status
# 如有未提交的收尾改动：
git add -A && git commit -m "chore(p5): phase 5 finalization"
git tag -a phase5-exclusions-settings -m "P5: exclusions + admin settings + daily purge"
git log --oneline -1
```

- [ ] **Step 7: 更新 roadmap 状态** — 把 `docs/superpowers/plans/2026-07-22-roadmap-p2-p7.md` 状态表中 P5 行改为 ✅（tag `phase5-exclusions-settings` + 计划链接），并在 P4 之后的增强说明中补一句 P5；提交：

```bash
git add docs/superpowers/plans/2026-07-22-roadmap-p2-p7.md
git commit -m "docs: mark P5 complete on roadmap"
```

---

## Self-Review（计划作者已核对）

**Spec 覆盖：**
- §2.1 Exclusion 模型/级联/SET NULL/unique → Task 1
- §2.2 哨兵 purge_after → Task 6 Step 7
- §3.1 exclusions 三端点 + 8 条校验顺序 + 审计 → Task 3
- §3.2 browse-fs root_id（默认定位/逃逸 404/审计 detail）→ Task 4
- §3.3 settings GET/PATCH、值域、writer、热替换、changed-only 审计 → Task 5/6
- §4.1 walk 段级剪枝（a/b vs a/bc）+ reconcile → Task 2
- §4.2 request_rescan dirty 重跑（多次合并为一次）→ Task 2
- §5 config_writer（保留注释/未知键、CRLF、原子替换、自校验）→ Task 5
- §6 锁定阈值/时长接线 → Task 6 Step 6
- §7 每日定时（next_daily_run 纯函数 + 循环 + 越界回退 + 关停 cancel）→ Task 7
- §8.1 AdminSettings（radio/数字/proxy 编辑器/脏检查/错误展示）→ Task 8
- §8.2 排除面板（懒加载/解除确认/选择器 rootId + startPath/原因 prompt）→ Task 9
- §8.3 DirectoryChooser rootId → Task 9 Step 6
- §8.4 AdminTrash「永不」→ Task 9 Step 1-3
- §9 红线 grep → Task 11
- §10 测试矩阵各条 → Task 1-10 对应覆盖
- 与上游 spec 的两处偏差（砍缩略图尺寸多选、锁定时长不进 UI）已在设计文档 §1 记录。

**类型/命名一致性：** `Exclusion`、`request_rescan`、`SettingsUpdates/update_settings_file`、`NEVER_PURGE_TS=9_999_999_999`（前后端一致）、`next_daily_run/daily_purge_loop`、JSON 字段名（`excluded_by_username`、`trash_retention_days`、`root_id`）在后端端点、测试与前端 interface 中逐一对齐。

