# 后端 LUT 库 + 管理后台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把硬编码在 `frontend/public/filters/` 的 LUT 迁到后端管理：磁盘文件 + DB 元数据 + admin 后台勾选启用 + viewer 前端从 API 按需加载。

**Architecture:** 新增 `luts` 表；启动时扫描 `backend/data/luts/<group>/*.cube` 自动发现（默认 disabled）；`routes_lut.py` 提供 viewer 和 admin 两套 API；前端 `AdminLuts.vue` 做分组勾选页，`FilterPreviewView.vue` 数据源从静态 JSON 切到 API。

**Tech Stack:** FastAPI + SQLAlchemy (aiosqlite) + pytest + Vue 3 + TypeScript + vitest。

**Spec:** [docs/superpowers/specs/2026-11-09-backend-lut-library-design.md](../specs/2026-11-09-backend-lut-library-design.md)

## Global Constraints

- **Python 测试命令**：`cd backend && pytest tests/<file>.py -v`（用 `pytest` 而非 `python -m pytest`）
- **前端测试命令**：`cd frontend && npx vitest run src/tests/<file>.spec.ts`
- **类型检查**：`cd frontend && npx vue-tsc --noEmit`
- **不新增 Python/前端依赖**（SQLAlchemy/FastAPI/pytest 已有）
- **`backend/data/luts/` 目录**：首次运行时自动 mkdir，gitignore；不进版本控制（除种子脚本外）
- **admin 鉴权**：用现有 `myphoto.deps.admin_required`；viewer 用 `current_user`
- **错误格式**：`AppError(code, http_status, message)`（参照 `routes_admin.py` 现有用法）
- **每 Task 结束 commit 一次**，conventional 前缀

---

## File Structure

| 文件 | 责任 |
|---|---|
| `backend/src/myphoto/models.py` (mod) | 加 `Lut` 模型 |
| `backend/src/myphoto/lut_scanner.py` (new) | 扫描 `backend/data/luts/`、upsert DB |
| `backend/src/myphoto/routes_lut.py` (new) | viewer + admin API |
| `backend/src/myphoto/main.py` (mod) | lifespan 里挂 scanner、include_router |
| `backend/scripts/seed_luts.py` (new) | 一次性种子脚本（合成预设 + 5 支富士） |
| `backend/tests/test_lut_scanner.py` (new) | scanner 单测 |
| `backend/tests/test_routes_lut.py` (new) | API 测试 |
| `frontend/src/views/AdminLuts.vue` (new) | admin 页面 |
| `frontend/src/lib/lutGroups.ts` (new) | group 中文名映射 |
| `frontend/src/views/FilterPreviewView.vue` (mod) | 数据源从静态 JSON 切到 API |
| `frontend/src/router.ts` (mod) | 加 `/admin/luts` 路由 |
| `frontend/src/AppHeader.vue` (mod) 或 `AdminOverview.vue` (mod) | 加入口链接 |
| `frontend/src/tests/admin-luts.spec.ts` (new) | admin 页面测试 |
| `frontend/src/tests/filter-preview-view.spec.ts` (mod) | 改 mock 为新 API |
| **删除** `frontend/public/filters/`、`frontend/scripts/gen-builtin-luts.mjs`、`frontend/src/tests/filter-assets.spec.ts` | 迁移到后端 |

---

## Task 1: `Lut` 模型 + 建表

**Files:**
- Modify: `backend/src/myphoto/models.py`
- Test: `backend/tests/test_models.py`（追加，不新建文件）

**Interfaces:**
- Produces: `class Lut(Base)` with columns `id, slug, label, group, file_path, enabled, sort_order, source, license, created_at`; table name `"luts"`.

- [ ] **Step 1: 在 models.py 末尾追加 Lut 类**

```python
class Lut(Base):
    __tablename__ = "luts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    group: Mapped[str] = mapped_column(String, nullable=False, default="")
    file_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String, nullable=False, default="")
    license: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
```

- [ ] **Step 2: 追加测试到 test_models.py**

```python
def test_lut_model_roundtrip(tmp_path):
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine
    from myphoto.models import Base, Lut

    async def go():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.ext.asyncio import AsyncSession
        sm = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with sm() as s:
            s.add(Lut(
                slug="velvia", label="富士 Velvia", group="fujifilm",
                file_path="fujifilm/velvia.cube", enabled=1, sort_order=1,
                source="https://example.com", license="MIT", created_at=100,
            ))
            await s.commit()
        async with sm() as s:
            from sqlalchemy import select
            row = (await s.execute(select(Lut).where(Lut.slug == "velvia"))).scalar_one()
            assert row.label == "富士 Velvia"
            assert row.enabled == 1
        await engine.dispose()

    asyncio.run(go())
```

- [ ] **Step 3: 跑测试**

Run: `cd backend && pytest tests/test_models.py::test_lut_model_roundtrip -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/myphoto/models.py backend/tests/test_models.py
git commit -m "feat(lut): Lut model for backend LUT library"
```

---

## Task 2: `lut_scanner.py` — 磁盘扫描

**Files:**
- Create: `backend/src/myphoto/lut_scanner.py`
- Test: `backend/tests/test_lut_scanner.py`

**Interfaces:**
- Consumes: `Lut` model from `models.py`
- Produces: `async def scan_luts(sessionmaker, luts_dir: Path) -> ScanResult`
  - `ScanResult` 是 dataclass：`{ discovered: list[str], skipped_existing: list[str], soft_deleted: list[str] }`（都是 file_path 列表）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_lut_scanner.py`:

```python
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, sessionmaker

from myphoto.lut_scanner import scan_luts
from myphoto.models import Base, Lut


@pytest.fixture
async def sm(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _write_cube(d: Path, rel: str):
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n")


def test_scan_discovers_new_files(tmp_path, sm):
    luts_dir = tmp_path / "luts"
    _write_cube(luts_dir, "fujifilm/velvia.cube")
    _write_cube(luts_dir, "synthetic/warm.cube")

    result = asyncio.run(scan_luts(sm, luts_dir))
    assert sorted(result.discovered) == ["fujifilm/velvia.cube", "synthetic/warm.cube"]

    async def check():
        async with sm() as s:
            from sqlalchemy import select
            rows = (await s.execute(select(Lut))).scalars().all()
            by_path = {r.file_path: r for r in rows}
            assert by_path["fujifilm/velvia.cube"].group == "fujifilm"
            assert by_path["fujifilm/velvia.cube"].slug == "velvia"
            assert by_path["fujifilm/velvia.cube"].enabled == 0  # 默认 disabled
            assert by_path["synthetic/warm.cube"].group == "synthetic"
    asyncio.run(check())


def test_scan_skips_existing_keeps_admin_changes(tmp_path, sm):
    luts_dir = tmp_path / "luts"
    _write_cube(luts_dir, "velvia.cube")
    async def seed():
        async with sm() as s:
            s.add(Lut(
                slug="velvia", label="自定义名", group="",
                file_path="velvia.cube", enabled=1, sort_order=5,
                source="", license="", created_at=int(time.time()),
            ))
            await s.commit()
    asyncio.run(seed())

    result = asyncio.run(scan_luts(sm, luts_dir))
    assert result.discovered == []
    assert "velvia.cube" in result.skipped_existing

    async def check():
        async with sm() as s:
            from sqlalchemy import select
            row = (await s.execute(select(Lut).where(Lut.slug == "velvia"))).scalar_one()
            assert row.label == "自定义名"  # 不覆盖
            assert row.enabled == 1
            assert row.sort_order == 5
    asyncio.run(check())


def test_scan_soft_deletes_missing_files(tmp_path, sm):
    luts_dir = tmp_path / "luts"
    _write_cube(luts_dir, "keep.cube")
    async def seed():
        async with sm() as s:
            s.add(Lut(
                slug="keep", label="keep", group="", file_path="keep.cube",
                enabled=1, sort_order=0, source="", license="", created_at=int(time.time()),
            ))
            s.add(Lut(
                slug="gone", label="gone", group="", file_path="gone.cube",
                enabled=1, sort_order=0, source="", license="", created_at=int(time.time()),
            ))
            await s.commit()
    asyncio.run(seed())

    result = asyncio.run(scan_luts(sm, luts_dir))
    assert "gone.cube" in result.soft_deleted

    async def check():
        async with sm() as s:
            from sqlalchemy import select
            gone = (await s.execute(select(Lut).where(Lut.slug == "gone"))).scalar_one()
            assert gone.enabled == 0  # 软删
            keep = (await s.execute(select(Lut).where(Lut.slug == "keep"))).scalar_one()
            assert keep.enabled == 1
    asyncio.run(check())


def test_scan_creates_dir_if_missing(tmp_path, sm):
    luts_dir = tmp_path / "nonexistent"
    result = asyncio.run(scan_luts(sm, luts_dir))
    assert result.discovered == []
    assert luts_dir.exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_lut_scanner.py -v`
Expected: FAIL — `No module named myphoto.lut_scanner`

- [ ] **Step 3: 实现 scanner**

`backend/src/myphoto/lut_scanner.py`:

```python
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from myphoto.models import Lut

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    discovered: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    soft_deleted: list[str] = field(default_factory=list)


def _slug_from_path(p: Path) -> str:
    stem = p.stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "lut"


async def scan_luts(
    sessionmaker: async_sessionmaker[AsyncSession],
    luts_dir: Path,
) -> ScanResult:
    luts_dir.mkdir(parents=True, exist_ok=True)
    # 收集磁盘上所有 .cube 文件（一层子目录）
    disk_files: set[str] = set()
    for p in luts_dir.rglob("*.cube"):
        rel = p.relative_to(luts_dir).as_posix()
        # 只允许一层子目录：若 rel 含两个或更多 "/"，跳过
        if rel.count("/") > 1:
            log.warning("lut_scanner: skipping nested file %s (only 1 group level allowed)", rel)
            continue
        disk_files.add(rel)

    result = ScanResult()
    async with sessionmaker() as s:
        # 拿 DB 里所有行
        db_rows = (await s.execute(select(Lut))).scalars().all()
        db_by_path = {r.file_path: r for r in db_rows}

        # 1. 磁盘上有、DB 没有 → 插入
        for rel in sorted(disk_files):
            if rel in db_by_path:
                result.skipped_existing.append(rel)
                continue
            p = luts_dir / rel
            group = p.parent.relative_to(luts_dir).as_posix() if p.parent != luts_dir else ""
            slug = _slug_from_path(p)
            # slug 冲突兜底：加序号
            base_slug = slug
            n = 2
            while any(r.slug == slug for r in db_rows):
                slug = f"{base_slug}_{n}"
                n += 1
            s.add(Lut(
                slug=slug,
                label=slug,
                group=group,
                file_path=rel,
                enabled=0,
                sort_order=0,
                source="",
                license="",
                created_at=int(time.time()),
            ))
            result.discovered.append(rel)

        # 2. DB 里有、磁盘上没有 → 软删（enabled=0）
        for rel, row in db_by_path.items():
            if rel not in disk_files and row.enabled != 0:
                row.enabled = 0
                result.soft_deleted.append(rel)

        await s.commit()
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/test_lut_scanner.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/myphoto/lut_scanner.py backend/tests/test_lut_scanner.py
git commit -m "feat(lut): scan_luts discovers files and soft-deletes missing"
```

---

## Task 3: 挂到启动 lifespan + `/api/luts` viewer API

**Files:**
- Modify: `backend/src/myphoto/main.py`（lifespan 里调 scan_luts）
- Create: `backend/src/myphoto/routes_lut.py`
- Test: `backend/tests/test_routes_lut.py`（viewer 部分）

**Interfaces:**
- Consumes: `scan_luts` from Task 2
- Produces:
  - `GET /api/luts` → `[{ group, items: [{slug, label, sort_order}] }, ...]`（仅 enabled=1）
  - `GET /api/luts/{slug}/cube` → `text/plain` 响应 `.cube` 内容（仅 enabled=1）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_routes_lut.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from myphoto.main import build_app


def _write_cube(d: Path, rel: str):
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("LUT_3D_SIZE 2\n0 0 0\n1 0 0\n")


@pytest.fixture
def client_with_luts(tmp_path, capsys):
    # 预置 luts 目录（build_app 之前写好）
    luts_dir = tmp_path / "data" / "luts"
    _write_cube(luts_dir, "fujifilm/velvia.cube")
    _write_cube(luts_dir, "synthetic/warm.cube")
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        yield c, tmp_path


def test_list_enabled_luts_grouped(client_with_luts):
    c, _ = client_with_luts
    # 两个 LUT 默认 disabled，先空列表
    r = c.get("/api/luts")
    assert r.status_code == 200
    assert r.json() == []

    # admin 启用两支
    c.patch("/api/admin/luts/velvia", json={"enabled": 1})
    c.patch("/api/admin/luts/warm", json={"enabled": 1})

    r = c.get("/api/luts")
    data = r.json()
    groups = {g["group"]: [i["slug"] for i in g["items"]] for g in data}
    assert groups == {"fujifilm": ["velvia"], "synthetic": ["warm"]}


def test_get_cube_text_enabled_only(client_with_luts):
    c, _ = client_with_luts
    # 未启用 → 404
    r = c.get("/api/luts/velvia/cube")
    assert r.status_code == 404

    c.patch("/api/admin/luts/velvia", json={"enabled": 1})
    r = c.get("/api/luts/velvia/cube")
    assert r.status_code == 200
    assert "LUT_3D_SIZE 2" in r.text


def test_get_cube_unknown_slug_404(client_with_luts):
    c, _ = client_with_luts
    r = c.get("/api/luts/nonexistent/cube")
    assert r.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_routes_lut.py -v`
Expected: FAIL — 404 on `/api/luts`

- [ ] **Step 3: 实现 routes_lut.py**

`backend/src/myphoto/routes_lut.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from myphoto.deps import admin_required, current_user
from myphoto.errors import AppError
from myphoto.models import Lut, User

router = APIRouter(prefix="/api", tags=["luts"])


def _luts_dir(request: Request) -> Path:
    cfg = request.app.state.config
    return Path(cfg.data_dir) / "luts"


@router.get("/luts")
async def list_enabled_luts(
    request: Request,
    _user: User = Depends(current_user),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        rows = (
            await s.execute(
                select(Lut).where(Lut.enabled == 1).order_by(Lut.group, Lut.sort_order, Lut.slug)
            )
        ).scalars().all()
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r.group, []).append({
            "slug": r.slug, "label": r.label, "sort_order": r.sort_order,
        })
    # group="" 排最前，其他按字母
    def group_key(g: str) -> str:
        return f"0~{g}" if g == "" else f"1~{g}"
    return [{"group": g, "items": items} for g, items in sorted(grouped.items(), key=lambda kv: group_key(kv[0]))]


@router.get("/luts/{slug}/cube")
async def get_lut_cube(
    slug: str,
    request: Request,
    _user: User = Depends(current_user),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        row = (await s.execute(select(Lut).where(Lut.slug == slug))).scalar_one_or_none()
        if row is None or row.enabled != 1:
            raise AppError("not_found", 404, "lut not found")
        rel = row.file_path
    cube_path = _luts_dir(request) / rel
    if not cube_path.exists():
        raise AppError("not_found", 404, "lut file missing")
    return PlainTextResponse(cube_path.read_text(encoding="utf-8"))


# ---- admin 部分在 Task 4 加，这里先占位让文件可挂载 ----

@router.get("/admin/luts")
async def list_all_luts(
    request: Request,
    _admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        rows = (await s.execute(select(Lut).order_by(Lut.group, Lut.sort_order, Lut.slug))).scalars().all()
    return [{
        "slug": r.slug, "label": r.label, "group": r.group,
        "enabled": r.enabled, "sort_order": r.sort_order,
        "source": r.source, "license": r.license,
        "file_path": r.file_path, "created_at": r.created_at,
    } for r in rows]


@router.patch("/admin/luts/{slug}")
async def update_lut(
    slug: str,
    request: Request,
    payload: dict,
    _admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        row = (await s.execute(select(Lut).where(Lut.slug == slug))).scalar_one_or_none()
        if row is None:
            raise AppError("not_found", 404, "lut not found")
        if "enabled" in payload:
            row.enabled = 1 if payload["enabled"] else 0
        if "label" in payload:
            row.label = str(payload["label"])[:100]
        if "sort_order" in payload:
            row.sort_order = int(payload["sort_order"])
        await s.commit()
        return {
            "slug": row.slug, "label": row.label, "enabled": row.enabled,
            "sort_order": row.sort_order,
        }
```

- [ ] **Step 4: 挂到 main.py**

在 `main.py` 的 lifespan 里，找到 `app.state.sessionmaker = sm` 之后、`app.state.scanner = scanner` 附近，加：

```python
        # LUT 库启动扫描
        try:
            from myphoto.lut_scanner import scan_luts
            luts_dir = Path(cfg.data_dir) / "luts"
            result = await scan_luts(sm, luts_dir)
            log.info(
                "startup lut scan: discovered=%d skipped=%d soft_deleted=%d",
                len(result.discovered), len(result.skipped_existing), len(result.soft_deleted),
            )
        except Exception:
            log.exception("startup lut scan failed")
```

在文件末尾路由挂载区（其他 `app.include_router` 旁边）加：

```python
    from myphoto.routes_lut import router as lut_router
    app.include_router(lut_router)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && pytest tests/test_routes_lut.py -v`
Expected: 3 tests PASS（admin patch 已经能用因为 routes_lut 里也定义了）

- [ ] **Step 6: Commit**

```bash
git add backend/src/myphoto/main.py backend/src/myphoto/routes_lut.py backend/tests/test_routes_lut.py
git commit -m "feat(lut): /api/luts viewer endpoints + startup scan"
```

---

## Task 4: `/api/admin/luts/rescan` 端点

**Files:**
- Modify: `backend/src/myphoto/routes_lut.py`
- Test: `backend/tests/test_routes_lut.py`（追加）

- [ ] **Step 1: 追加测试**

```python
def test_admin_rescan_discover_new_file(client_with_luts):
    c, tmp_path = client_with_luts
    # 运行时往 luts 目录丢新文件
    _write_cube(tmp_path / "data" / "luts", "fujifilm/astia.cube")
    r = c.post("/api/admin/luts/rescan")
    assert r.status_code == 200
    data = r.json()
    assert "fujifilm/astia.cube" in data["discovered"]

    # 立即出现在 admin 列表（默认 disabled）
    r = c.get("/api/admin/luts")
    slugs = [x["slug"] for x in r.json()]
    assert "astia" in slugs
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/test_routes_lut.py::test_admin_rescan_discover_new_file -v`
Expected: FAIL — 404

- [ ] **Step 3: 加端点**

在 `routes_lut.py` 末尾加：

```python
@router.post("/admin/luts/rescan")
async def rescan_luts(
    request: Request,
    _admin: User = Depends(admin_required),
):
    from myphoto.lut_scanner import scan_luts
    sm = request.app.state.sessionmaker
    result = await scan_luts(sm, _luts_dir(request))
    return {
        "discovered": result.discovered,
        "skipped_existing": result.skipped_existing,
        "soft_deleted": result.soft_deleted,
    }
```

- [ ] **Step 4: 跑测试确认通过 + Commit**

```bash
cd backend && pytest tests/test_routes_lut.py -v   # 4 tests PASS
git add backend/src/myphoto/routes_lut.py backend/tests/test_routes_lut.py
git commit -m "feat(lut): POST /api/admin/luts/rescan"
```

---

## Task 5: 种子脚本 + 迁移现有 3 支合成预设

**Files:**
- Create: `backend/scripts/seed_luts.py`
- Delete: `frontend/public/filters/` 整个目录、`frontend/scripts/gen-builtin-luts.mjs`、`frontend/src/tests/filter-assets.spec.ts`

- [ ] **Step 1: 写种子脚本**

`backend/scripts/seed_luts.py`:

```python
"""一次性种子脚本：把现有 3 支合成预设从 frontend/public/filters/ 拷到
backend/data/luts/synthetic/，并预填 DB 元数据（enabled=1）。

富士 5 支（provia/velvia/astia/classic_chrome/acros）需从
https://github.com/YahiaAngelo/Film-Luts 手动下载到 backend/data/luts/fujifilm/
后再次运行本脚本（幂等：已存在的 file_path 跳过）。

用法：
    cd backend
    python -m scripts.seed_luts
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

# 让脚本能 import myphoto
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from myphoto.config import load_or_init, resolve_config_path  # noqa: E402
from myphoto.db import make_engine, make_sessionmaker  # noqa: E402
from myphoto.lut_scanner import scan_luts  # noqa: E402
from myphoto.schema_init import ensure_schema_and_admin  # noqa: E402


SYNTHETIC_PRESETS = [
    # (source_rel_in_frontend, target_filename_in_luts_dir, label)
    ("warm.cube", "warm.cube", "暖色调"),
    ("cool.cube", "cool.cube", "冷色调"),
    ("mono.cube", "mono.cube", "黑白"),
]


async def main() -> int:
    config_path = resolve_config_path(None)
    cfg = load_or_init(config_path)
    luts_dir = Path(cfg.data_dir) / "luts"
    luts_dir.mkdir(parents=True, exist_ok=True)

    # 1. 拷合成预设
    src_dir = ROOT.parent / "frontend" / "public" / "filters"
    synth_dir = luts_dir / "synthetic"
    synth_dir.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name, _label in SYNTHETIC_PRESETS:
        src = src_dir / src_name
        dst = synth_dir / dst_name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
            print(f"copied {src_name} -> synthetic/{dst_name}")
        elif dst.exists():
            print(f"skip existing synthetic/{dst_name}")
        else:
            print(f"WARN: source missing {src}")

    # 2. 跑一次扫描（自动发现）
    engine = await make_engine(f"sqlite+aiosqlite:///{Path(cfg.data_dir) / 'app.db'}")
    sm = await make_sessionmaker(engine)
    await ensure_schema_and_admin(engine, sm)
    result = await scan_luts(sm, luts_dir)
    print(f"scan: discovered={len(result.discovered)} skipped={len(result.skipped_existing)}")

    # 3. 把 synthetic/* 的 enabled 改为 1（首次种子时打开）
    from sqlalchemy import select, update
    from myphoto.models import Lut
    async with sm() as s:
        for slug in ["warm", "cool", "mono"]:
            row = (await s.execute(select(Lut).where(Lut.slug == slug))).scalar_one_or_none()
            if row:
                row.enabled = 1
                if not row.label or row.label == row.slug:
                    row.label = next(lbl for src, fn, lbl in SYNTHETIC_PRESETS if fn.startswith(slug))
        await s.commit()
    await engine.dispose()
    print("done.")
    return 0


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: 跑种子脚本（前端文件还没删）**

Run: `cd backend && python -m scripts.seed_luts`
Expected: 输出 "copied warm/cool/mono" + "scan: discovered=3"

- [ ] **Step 3: 验证 DB 里 3 支合成预设 enabled=1**

Run: `cd backend && python -c "import asyncio; from myphoto.config import load_or_init, resolve_config_path; from myphoto.db import make_engine, make_sessionmaker; from sqlalchemy import select; from myphoto.models import Lut; 
async def go():
    cfg = load_or_init(resolve_config_path(None))
    eng = await make_engine(f'sqlite+aiosqlite:///{cfg.data_dir}/app.db')
    sm = await make_sessionmaker(eng)
    async with sm() as s:
        rows = (await s.execute(select(Lut))).scalars().all()
        for r in rows: print(r.slug, r.enabled, r.label)
    await eng.dispose()
asyncio.run(go())"`
Expected: `warm 1 暖色调` / `cool 1 冷色调` / `mono 1 黑白`

- [ ] **Step 4: 删除旧前端文件**

```bash
rm -rf frontend/public/filters/
rm frontend/scripts/gen-builtin-luts.mjs
rm frontend/src/tests/filter-assets.spec.ts
# 如果 frontend/public/ 空了也一并删
rmdir frontend/public 2>/dev/null || true
```

- [ ] **Step 5: 确认前端旧测试不再被引用**

Run: `cd frontend && npx vitest run 2>&1 | tail -5`
Expected: 除 `filter-preview-view.spec.ts` 里引用 `/filters/manifest.json` 的测试会失败外，其他都过——那些测试 Task 6 会改。

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/seed_luts.py
git commit -m "feat(lut): seed script migrates synthetic presets to backend"
git rm -r frontend/public/filters frontend/scripts/gen-builtin-luts.mjs frontend/src/tests/filter-assets.spec.ts
git commit -m "chore(preview): remove static filter assets now served by backend"
```

---

## Task 6: 前端切数据源到 `/api/luts` + group 映射

**Files:**
- Create: `frontend/src/lib/lutGroups.ts`
- Modify: `frontend/src/views/FilterPreviewView.vue`
- Modify: `frontend/src/tests/filter-preview-view.spec.ts`

- [ ] **Step 1: 写 group 映射**

`frontend/src/lib/lutGroups.ts`:

```ts
/** 后端 group → 中文显示名。未映射的 group 直接显示原文。 */
export const LUT_GROUP_LABELS: Record<string, string> = {
  fujifilm: "富士胶片",
  kodak: "柯达",
  cinematic: "电影感",
  synthetic: "合成预设",
}

export function groupLabel(g: string): string {
  return LUT_GROUP_LABELS[g] ?? g || "未分组"
}
```

- [ ] **Step 2: 改 FilterPreviewView.vue 数据加载段**

把 onMounted 里 step 3（manifest fetch）整段改为：

```ts
  // 3. 从后端 /api/luts 拿已启用列表（按 group 分组）
  interface LutEntry { slug: string; label: string; sort_order: number }
  interface LutGroup { group: string; items: LutEntry[] }
  let groups: LutGroup[] = []
  try {
    const res = await fetch("/api/luts")
    if (cancelled) return
    groups = await res.json()
  } catch {
    if (!cancelled) groups = []
  }
  // 拍平成 filters 列表（保持现有 filter 数据结构兼容）
  filters.value = groups.flatMap(g => g.items.map(it => ({
    id: it.slug, label: it.label, slug: it.slug,
  }))) as any
  // 4. 对每支 LUT 拉 cube 文本
  for (const f of filters.value) {
    if (cancelled) return
    try {
      const cubeText = await (await fetch(`/api/luts/${f.id}/cube`)).text()
      if (cancelled) return
      lutCache.set(f.id, parseCube(cubeText))
    } catch {
      if (cancelled) return
      filters.value = filters.value.filter(x => x.id !== f.id)
    }
  }
```

同时把 template 里的小样条 section 改为按 group 分块：

```vue
    <section class="fp-strip">
      <div v-for="g in groups" :key="g.group" class="fp-group">
        <div class="fp-group-label">{{ groupLabel(g.group) }}</div>
        <div class="fp-group-items">
          <button
            v-for="f in g.items" :key="f.slug"
            class="fp-thumb" :class="{ active: f.slug === activeId }"
            :disabled="!rendererReady"
            @click="pick({ id: f.slug, label: f.label, slug: f.slug })"
          >
            <img v-if="thumbs[f.slug]" :src="thumbs[f.slug]" :alt="f.label" />
            <span class="fp-thumb-label">{{ f.label }}</span>
          </button>
        </div>
      </div>
    </section>
```

script 里加：
```ts
import { groupLabel } from "../lib/lutGroups"
// 模板里要用的 groups 也要暴露
const groups = ref<{ group: string; items: { slug: string; label: string; sort_order: number }[] }[]>([])
```

（注意：把原来的 `filters` ref 拆成 `groups` + 派生视图，或保留 `filters` 用于小样缓存，具体实现时保持简洁。）

- [ ] **Step 3: 改测试 mock**

把 `filter-preview-view.spec.ts` 里 `vi.stubGlobal("fetch", ...)` 的 mock 从返回静态 manifest 改成：

```ts
vi.stubGlobal("fetch", vi.fn(async (url: string) => {
  if (url === "/api/luts") {
    return { ok: true, json: async () => [{
      group: "synthetic",
      items: [{ slug: "warm", label: "暖色调", sort_order: 0 }],
    }]}
  }
  if (url.includes("/cube")) {
    return { ok: true, text: async () => "LUT_3D_SIZE 1\n0.1 0.2 0.3" }
  }
  return { ok: false, status: 404, text: async () => "", json: async () => ({}) }
}))
```

- [ ] **Step 4: 跑测试**

Run: `cd frontend && npx vitest run src/tests/filter-preview-view.spec.ts`
Expected: 所有测试仍 PASS（mock 已对齐新 API）

- [ ] **Step 5: vue-tsc + Commit**

```bash
cd frontend && npx vue-tsc --noEmit
git add frontend/src/lib/lutGroups.ts frontend/src/views/FilterPreviewView.vue frontend/src/tests/filter-preview-view.spec.ts
git commit -m "feat(preview): load LUTs from /api/luts, group thumb strip"
```

---

## Task 7: AdminLuts.vue 页面 + 路由 + 入口

**Files:**
- Create: `frontend/src/views/AdminLuts.vue`
- Modify: `frontend/src/router.ts`（加 `/admin/luts`）
- Modify: `frontend/src/AppHeader.vue` 或 `AdminOverview.vue`（加入口链接）
- Test: `frontend/src/tests/admin-luts.spec.ts`

- [ ] **Step 1: 写测试**

`frontend/src/tests/admin-luts.spec.ts`:

```ts
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.stubGlobal("fetch", vi.fn(async (url: string, opts?: any) => {
  if (url === "/api/admin/luts" && opts?.method === "PATCH") {
    return { ok: true, json: async () => ({}) }
  }
  if (url === "/api/admin/luts") {
    return { ok: true, json: async () => [
      { slug: "velvia", label: "富士 Velvia", group: "fujifilm", enabled: 1,
        sort_order: 1, source: "https://x", license: "MIT",
        file_path: "fujifilm/velvia.cube", created_at: 1 },
      { slug: "warm", label: "暖色调", group: "synthetic", enabled: 0,
        sort_order: 0, source: "", license: "", file_path: "synthetic/warm.cube", created_at: 1 },
    ]}
  }
  if (url === "/api/admin/luts/rescan" && opts?.method === "POST") {
    return { ok: true, json: async () => ({ discovered: [], skipped_existing: [], soft_deleted: [] }) }
  }
  return { ok: false, json: async () => ({}) }
}))

import AdminLuts from "../views/AdminLuts.vue"

describe("AdminLuts", () => {
  beforeEach(() => setActivePinia(createPinia()))

  it("renders LUTs grouped, toggles PATCH on click", async () => {
    const w = mount(AdminLuts)
    await flushPromises()
    expect(w.text()).toContain("富士 Velvia")
    expect(w.text()).toContain("暖色调")
    // 找 warm 的 toggle，点它
    const toggles = w.findAll('button[aria-label="toggle-enabled"]')
    expect(toggles.length).toBe(2)
    await toggles[1].trigger("click")
    await flushPromises()
    // 应有 PATCH /api/admin/luts/warm
    const patchCalls = (fetch as any).mock.calls.filter(
      (c: any[]) => c[1]?.method === "PATCH" && c[0].includes("/warm"),
    )
    expect(patchCalls.length).toBe(1)
  })

  it("rescan button triggers POST", async () => {
    const w = mount(AdminLuts)
    await flushPromises()
    await w.find('button[data-test="rescan"]').trigger("click")
    await flushPromises()
    const postCalls = (fetch as any).mock.calls.filter(
      (c: any[]) => c[1]?.method === "POST" && c[0].includes("/rescan"),
    )
    expect(postCalls.length).toBe(1)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/tests/admin-luts.spec.ts`
Expected: FAIL — AdminLuts.vue 不存在

- [ ] **Step 3: 写 AdminLuts.vue**

```vue
<template>
  <div class="al-page">
    <header class="al-head">
      <h2>滤镜 LUT 管理</h2>
      <button data-test="rescan" @click="onRescan" :disabled="scanning">
        {{ scanning ? "扫描中..." : "重新扫描磁盘" }}
      </button>
    </header>
    <p class="al-hint">
      新增 .cube 文件需放到 <code>backend/data/luts/&lt;group&gt;/</code> 后点"重新扫描"。
    </p>

    <div v-for="g in grouped" :key="g.group" class="al-group">
      <h3>{{ groupLabel(g.group) }}</h3>
      <table>
        <thead>
          <tr><th>启用</th><th>名称</th><th>排序</th><th>文件</th><th>来源 / 许可</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in g.items" :key="row.slug" :class="{ disabled: !row.enabled }">
            <td>
              <button
                aria-label="toggle-enabled"
                @click="onToggle(row)"
              >{{ row.enabled ? "✓" : "·" }}</button>
            </td>
            <td>
              <input v-model="row.label" @change="onLabel(row)" />
            </td>
            <td>
              <input type="number" v-model.number="row.sort_order" @change="onSort(row)" style="width:70px" />
            </td>
            <td><code>{{ row.file_path }}</code></td>
            <td class="al-meta">{{ row.source || "—" }} {{ row.license ? "· " + row.license : "" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { groupLabel } from "../lib/lutGroups"

interface LutRow {
  slug: string; label: string; group: string
  enabled: number; sort_order: number
  source: string; license: string; file_path: string; created_at: number
}

const rows = ref<LutRow[]>([])
const scanning = ref(false)

const grouped = computed(() => {
  const m = new Map<string, LutRow[]>()
  for (const r of rows.value) {
    if (!m.has(r.group)) m.set(r.group, [])
    m.get(r.group)!.push(r)
  }
  return Array.from(m.entries()).map(([group, items]) => ({ group, items }))
})

async function load() {
  const res = await fetch("/api/admin/luts")
  rows.value = await res.json()
}

async function patch(slug: string, body: Record<string, unknown>) {
  await fetch(`/api/admin/luts/${slug}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  })
}

function onToggle(row: LutRow) {
  row.enabled = row.enabled ? 0 : 1
  void patch(row.slug, { enabled: row.enabled })
}
function onLabel(row: LutRow) {
  void patch(row.slug, { label: row.label })
}
function onSort(row: LutRow) {
  void patch(row.slug, { sort_order: row.sort_order })
}

async function onRescan() {
  scanning.value = true
  try {
    await fetch("/api/admin/luts/rescan", { method: "POST" })
    await load()
  } finally {
    scanning.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.al-page { padding: 20px; color: #eee; background: #111; min-height: 100vh; }
.al-head { display: flex; justify-content: space-between; align-items: center; }
.al-hint { color: #999; font-size: 13px; }
.al-group { margin-top: 20px; }
.al-group h3 { font-size: 14px; color: #ccc; }
table { width: 100%; border-collapse: collapse; margin-top: 8px; }
td, th { padding: 6px 8px; border-bottom: 1px solid #222; text-align: left; font-size: 13px; }
tr.disabled { opacity: 0.45; }
.al-meta { color: #888; font-size: 12px; }
button { cursor: pointer; }
</style>
```

- [ ] **Step 4: 加路由**

在 `router.ts` 其他 `/admin/*` 路由旁边加：

```ts
  {
    path: "/admin/luts",
    component: () => import("./views/AdminLuts.vue"),
    meta: { requiresAdmin: true },
  },
```

- [ ] **Step 5: 加入口链接**

打开 `frontend/src/views/AdminOverview.vue`（或 `AppHeader.vue`），在现有 admin 导航链接列表加一行：

```vue
<router-link to="/admin/luts">滤镜 LUT</router-link>
```

参照旁边现有的链接样式。

- [ ] **Step 6: 跑测试 + vue-tsc + Commit**

```bash
cd frontend && npx vitest run src/tests/admin-luts.spec.ts   # 2 tests PASS
cd frontend && npx vue-tsc --noEmit
git add frontend/src/views/AdminLuts.vue frontend/src/router.ts frontend/src/AppHeader.vue frontend/src/tests/admin-luts.spec.ts
git commit -m "feat(admin): LUT management page with enable toggle"
```

---

## Task 8: 全量回归 + 手工验收

- [ ] **Step 1: 后端全测**

Run: `cd backend && pytest tests/ -v 2>&1 | tail -20`
Expected: 全过（含新增 test_lut_scanner.py + test_routes_lut.py）

- [ ] **Step 2: 前端全测 + 类型 + 构建**

```bash
cd frontend && npx vitest run 2>&1 | tail -5
cd frontend && npx vue-tsc --noEmit
cd frontend && npx vite build
```
Expected: 全过；build 输出无 `/filters/` 相关引用残留。

- [ ] **Step 3: 手工验收清单**

启动前后端后逐条：
1. 后端启动日志有 `startup lut scan: discovered=3 skipped=0`
2. 访问 `/admin/luts`：看到 3 支合成预设（暖色调/冷色调/黑白）已启用
3. 点 toggle 禁用 warm → 访问 `/filter-preview?sha1=...&name=...`：小样条里没有"暖色调"
4. 手工往 `backend/data/luts/fujifilm/` 丢一个 `.cube` 文件，回 admin 点"重新扫描"：新文件出现（默认 disabled）
5. 在 admin 启用它，回预览页：新 LUT 出现并可切换
6. 改 label / sort_order，预览页立即反映
7. 删除 `backend/data/luts/synthetic/warm.cube`，回 admin 重新扫描：warm 行变 disabled（软删）

- [ ] **Step 4: Commit（如手工验收有小修正）**

```bash
git add -A
git commit -m "chore(lut): manual acceptance fixes" --allow-empty
```
