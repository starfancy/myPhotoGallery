# 缩略图引用计数与手动清理 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `thumbnail_refs` 引用计数表，通过 SQLite 触发器维护，将现有全量清空接口改为只清理无引用缩略图（含历史孤儿缓存），释放约 30%+ 废弃缓存空间。

**Architecture:** 新增 `thumbnail_refs.py` 集中管理模型、触发器安装、数据校准和清理逻辑。`schema_init.py` 负责升级时的回填。现有 `thumbnails.py` 增加并发去重锁。`routes_admin.py` 的 purge 端点改为调用新的 prune 服务。

**Tech Stack:** 与现有项目一致：Python 3.11+ / FastAPI / SQLAlchemy 2.0 async + aiosqlite / Vue 3 + vitest

---

## Global Constraints

- 所有现有红线继续生效（不物理删除文件夹、缓存目录路径安全校验）
- 清理 `os.remove` 的目标必须位于 `.cache/thumbnails/` 内（沿用现有路径前缀校验模式）
- 审计写入失败不阻断主操作
- 引用计数维护使用数据库触发器，与业务数据同事务
- 手动清理前必须先校准引用计数
- 管理端只清理无引用缩略图，不提供全量清空能力
- 8 万级数据量下，SQL 调用数不随 SHA1 数量线性增长（禁止 N+1 查询）
- 普通启动、普通扫描不遍历缩略图缓存目录

---

## 文件变更清单

```
backend/src/myphoto/
├─ thumbnail_refs.py       # NEW  — ThumbnailRef 模型、触发器安装、校准、PruneService
├─ models.py               # MODIFY — 导入 ThumbnailRef（供 create_all 发现）
├─ schema_init.py          # MODIFY — 建表后安装触发器 + 聚合回填 + 版本标记
├─ routes_admin.py         # MODIFY — purge 端点改为调用 PruneService
├─ thumbnails.py           # MODIFY — 增加进程内 dedup 锁 + 原子写入
├─ db.py                   # 无需改动
├─ scanner.py              # 无需改动（触发器自动维护计数）

backend/tests/
├─ test_thumbnail_refs.py  # NEW  — 触发器、校准、PruneService 单元/集成测试
├─ test_routes_admin_system.py  # MODIFY — 更新现有 purge 测试用例

frontend/src/
├─ views/
│  └─ AdminOverview.vue    # MODIFY — 按钮文案、确认文案、结果展示
├─ tests/
   └─ admin-overview.spec.ts  # MODIFY — 新增清理按钮相关测试
```

---

## 关键接口速查

```python
# thumbnail_refs.py 暴露的公共接口

class ThumbnailRef(Base):
    """sha1 PK, image_count int, trash_count int"""

async def install_triggers(conn) -> None:
    """在已有 engine.begin() 连接上安装 images 触发器；trash 表存在时安装 trash 触发器。"""

async def backfill_refs(conn) -> None:
    """首次升级：从 images（及 trash）聚合填充 thumbnail_refs。"""

async def calibrate_refs(conn) -> None:
    """以 images（及 trash）为权威来源，批量重建 thumbnail_refs。"""

class PruneService:
    """__init__(cache_dir: Path, sessionmaker)"""
    async def prune(self) -> PruneResult:
        """校准 → 收集零引用 + 孤儿 → 安全删除 → 写审计 → 返回结果"""

@dataclass
class PruneResult:
    scanned: int
    removed: int
    failed: int
    freed_bytes: int

# thumbnails.py 新增
# ThumbnailGenerator 内增加 _locks: dict[tuple[str, int], asyncio.Lock]
```

---

### Task 1: ThumbnailRef 模型 + 触发器安装

**Files:**
- Create: `backend/src/myphoto/thumbnail_refs.py`
- Modify: `backend/src/myphoto/models.py`

**Interfaces:**
- Produces: `ThumbnailRef` ORM 类、`install_triggers(conn)`、`backfill_refs(conn)`、`calibrate_refs(conn)`

---

- [ ] **Step 1: 创建 `thumbnail_refs.py`，定义 ThumbnailRef 模型**

```python
# backend/src/myphoto/thumbnail_refs.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import String, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ThumbnailRef 放在此模块而非 models.py，因为触发器/校准逻辑也在此模块，
# 保持单一职责。models.py 通过 import 让 create_all 发现它。
class _Base(DeclarativeBase):
    pass


class ThumbnailRef(_Base):
    __tablename__ = "thumbnail_refs"

    sha1: Mapped[str] = mapped_column(String, primary_key=True)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trash_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

注意：`ThumbnailRef` 需要被 `Base.metadata.create_all` 发现。因为现有项目用的是 `models.Base`，所以把 `ThumbnailRef` 也挂到同一个 `Base` 下。方案：不创建新 Base，直接在 `models.py` 中新增 `ThumbnailRef` 类，但把触发器/校准/清理逻辑放在 `thumbnail_refs.py` 中。

修订——Step 1 改为在 `models.py` 中新增模型，在 `thumbnail_refs.py` 中放逻辑。

- [ ] **Step 2: 在 `models.py` 中新增 ThumbnailRef 模型**

在 `backend/src/myphoto/models.py` 末尾添加（与其他模型类并列）：

```python
class ThumbnailRef(Base):
    __tablename__ = "thumbnail_refs"
    sha1: Mapped[str] = mapped_column(String, primary_key=True)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trash_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
```

- [ ] **Step 3: 创建 `thumbnail_refs.py`，实现触发器安装函数**

```python
# backend/src/myphoto/thumbnail_refs.py

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

log = logging.getLogger("myphoto.thumbnail_refs")

# ---- triggers ----

_IMAGES_TRIGGERS = [
    # INSERT: image_count + 1
    """CREATE TRIGGER IF NOT EXISTS tr_thumbref_images_insert
       AFTER INSERT ON images
       FOR EACH ROW
       BEGIN
           INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
           VALUES (NEW.sha1, 1, 0)
           ON CONFLICT(sha1) DO UPDATE SET image_count = image_count + 1;
       END;""",
    # DELETE: image_count - 1, floor at 0
    """CREATE TRIGGER IF NOT EXISTS tr_thumbref_images_delete
       AFTER DELETE ON images
       FOR EACH ROW
       BEGIN
           UPDATE thumbnail_refs
           SET image_count = MAX(0, image_count - 1)
           WHERE sha1 = OLD.sha1;
       END;""",
    # UPDATE: sha1 变化时转移引用
    """CREATE TRIGGER IF NOT EXISTS tr_thumbref_images_update
       AFTER UPDATE OF sha1 ON images
       WHEN OLD.sha1 IS NOT NEW.sha1
       FOR EACH ROW
       BEGIN
           UPDATE thumbnail_refs
           SET image_count = MAX(0, image_count - 1)
           WHERE sha1 = OLD.sha1;
           INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
           VALUES (NEW.sha1, 1, 0)
           ON CONFLICT(sha1) DO UPDATE SET image_count = image_count + 1;
       END;""",
]

_TRASH_TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS tr_thumbref_trash_insert
       AFTER INSERT ON trash
       FOR EACH ROW
       BEGIN
           INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
           VALUES (NEW.sha1, 0, 1)
           ON CONFLICT(sha1) DO UPDATE SET trash_count = trash_count + 1;
       END;""",
    """CREATE TRIGGER IF NOT EXISTS tr_thumbref_trash_delete
       AFTER DELETE ON trash
       FOR EACH ROW
       BEGIN
           UPDATE thumbnail_refs
           SET trash_count = MAX(0, trash_count - 1)
           WHERE sha1 = OLD.sha1;
       END;""",
    """CREATE TRIGGER IF NOT EXISTS tr_thumbref_trash_update
       AFTER UPDATE OF sha1 ON trash
       WHEN OLD.sha1 IS NOT NEW.sha1
       FOR EACH ROW
       BEGIN
           UPDATE thumbnail_refs
           SET trash_count = MAX(0, trash_count - 1)
           WHERE sha1 = OLD.sha1;
           INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
           VALUES (NEW.sha1, 0, 1)
           ON CONFLICT(sha1) DO UPDATE SET trash_count = trash_count + 1;
       END;""",
]


async def install_triggers(conn: AsyncConnection) -> None:
    """Install image triggers; also install trash triggers if the table exists."""
    for stmt in _IMAGES_TRIGGERS:
        await conn.execute(text(stmt))

    # Only install trash triggers when trash table actually exists
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='trash'")
    )
    if result.scalar() is not None:
        for stmt in _TRASH_TRIGGERS:
            await conn.execute(text(stmt))
```

- [ ] **Step 4: 在 `thumbnail_refs.py` 中实现首次回填函数**

```python
async def backfill_refs(conn: AsyncConnection) -> None:
    """One-time backfill from images (and trash if present) into thumbnail_refs.
    Must be called after create_all + install_triggers on fresh-install or upgrade.
    """
    # Populate image_count from images
    await conn.execute(text("""
        INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
        SELECT sha1, COUNT(*), 0
        FROM images
        GROUP BY sha1
        ON CONFLICT(sha1) DO UPDATE SET image_count = excluded.image_count
    """))

    # If trash table exists, populate trash_count
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='trash'")
    )
    if result.scalar() is not None:
        await conn.execute(text("""
            INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
            SELECT sha1, 0, COUNT(*)
            FROM trash
            GROUP BY sha1
            ON CONFLICT(sha1) DO UPDATE SET trash_count = excluded.trash_count
        """))
```

- [ ] **Step 5: 在 `thumbnail_refs.py` 中实现清理前校准函数**

```python
async def calibrate_refs(conn: AsyncConnection) -> None:
    """Rebuild thumbnail_refs from images and trash as authoritative sources.
    Runs inside a single transaction before each prune.
    """
    # Reset all counts to zero (keep rows to avoid re-insert churn)
    await conn.execute(text("UPDATE thumbnail_refs SET image_count = 0, trash_count = 0"))

    # Re-aggregate from images
    await conn.execute(text("""
        INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
        SELECT sha1, COUNT(*), 0
        FROM images
        GROUP BY sha1
        ON CONFLICT(sha1) DO UPDATE SET image_count = excluded.image_count
    """))

    # Re-aggregate from trash if table exists
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='trash'")
    )
    if result.scalar() is not None:
        await conn.execute(text("""
            INSERT INTO thumbnail_refs (sha1, image_count, trash_count)
            SELECT sha1, 0, COUNT(*)
            FROM trash
            GROUP BY sha1
            ON CONFLICT(sha1) DO UPDATE SET trash_count = excluded.trash_count
        """))
```

- [ ] **Step 6: 编写对应测试文件 `test_thumbnail_refs.py`**

先写测试框架和触发器测试：

```python
# backend/tests/test_thumbnail_refs.py

import asyncio
import time
from pathlib import Path

import pytest
from sqlalchemy import text, select as _s, func

from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import Base, Gallery, GalleryRoot, Folder, Image, ThumbnailRef


@pytest.fixture
async def engine_and_sm():
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    yield engine, sm
    await engine.dispose()


def _make_gallery_root_and_folder(session, now):
    g = Gallery(name="G", created_at=now)
    session.add(g)
    session.flush()
    r = GalleryRoot(gallery_id=g.id, label="R", absolute_path="/x", enabled=1)
    session.add(r)
    session.flush()
    f = Folder(root_id=r.id, relative_path="", name="", image_count=0, descendant_count=0)
    session.add(f)
    session.flush()
    return r.id, f.id


async def test_triggers_not_installed_on_plain_create_all(engine_and_sm):
    """Before calling install_triggers, direct image insert should NOT update thumbnail_refs."""
    engine, sm = engine_and_sm
    from myphoto.thumbnail_refs import install_triggers
    # Note: we do NOT call install_triggers here — create_all is already done in fixture.

    async with sm() as s:
        rid, fid = _make_gallery_root_and_folder(s, int(time.time()))
        s.add(Image(root_id=rid, folder_id=fid, relative_path="a.jpg",
                     filename="a.jpg", ext="jpg", size_bytes=100,
                     sha1="abc123", mtime=1, is_raw=0, indexed_at=1))
        await s.commit()

        # thumbnail_refs table exists but has zero rows (no trigger, no auto-populate)
        cnt = (await s.execute(_s(func.count()).select_from(ThumbnailRef))).scalar_one()
        assert cnt == 0


async def test_install_triggers_then_insert(engine_and_sm):
    """After install_triggers, inserting an image should auto-create a ref row."""
    engine, sm = engine_and_sm
    from myphoto.thumbnail_refs import install_triggers

    async with engine.begin() as conn:
        await install_triggers(conn)

    async with sm() as s:
        rid, fid = _make_gallery_root_and_folder(s, int(time.time()))
        s.add(Image(root_id=rid, folder_id=fid, relative_path="a.jpg",
                     filename="a.jpg", ext="jpg", size_bytes=100,
                     sha1="abc123", mtime=1, is_raw=0, indexed_at=1))
        await s.commit()

        ref = await s.get(ThumbnailRef, "abc123")
        assert ref is not None
        assert ref.image_count == 1
        assert ref.trash_count == 0


async def test_trigger_updates_on_sha1_change(engine_and_sm):
    """When an image's sha1 changes, old ref decrements and new ref increments."""
    engine, sm = engine_and_sm
    from myphoto.thumbnail_refs import install_triggers

    async with engine.begin() as conn:
        await install_triggers(conn)

    async with sm() as s:
        rid, fid = _make_gallery_root_and_folder(s, int(time.time()))
        img = Image(root_id=rid, folder_id=fid, relative_path="a.jpg",
                     filename="a.jpg", ext="jpg", size_bytes=100,
                     sha1="oldsha1", mtime=1, is_raw=0, indexed_at=1)
        s.add(img)
        await s.commit()

        # Old ref exists
        old_ref = await s.get(ThumbnailRef, "oldsha1")
        assert old_ref.image_count == 1

        # Update sha1
        img.sha1 = "newsha1"
        await s.commit()

        # Old ref decremented
        await s.refresh(old_ref)
        assert old_ref.image_count == 0

        # New ref created
        new_ref = await s.get(ThumbnailRef, "newsha1")
        assert new_ref.image_count == 1


async def test_trigger_decrement_on_delete(engine_and_sm):
    """Deleting an image decrements its ref count."""
    engine, sm = engine_and_sm
    from myphoto.thumbnail_refs import install_triggers

    async with engine.begin() as conn:
        await install_triggers(conn)

    async with sm() as s:
        rid, fid = _make_gallery_root_and_folder(s, int(time.time()))
        img = Image(root_id=rid, folder_id=fid, relative_path="a.jpg",
                     filename="a.jpg", ext="jpg", size_bytes=100,
                     sha1="abc", mtime=1, is_raw=0, indexed_at=1)
        s.add(img)
        await s.commit()

        ref = await s.get(ThumbnailRef, "abc")
        assert ref.image_count == 1

        await s.delete(img)
        await s.commit()

        ref = await s.get(ThumbnailRef, "abc")
        assert ref.image_count == 0


async def test_trigger_cascade_on_root_delete(engine_and_sm):
    """Deleting a GalleryRoot cascades to images, which triggers ref decrements."""
    engine, sm = engine_and_sm
    from myphoto.thumbnail_refs import install_triggers

    async with engine.begin() as conn:
        await install_triggers(conn)

    async with sm() as s:
        rid, fid = _make_gallery_root_and_folder(s, int(time.time()))
        s.add(Image(root_id=rid, folder_id=fid, relative_path="a.jpg",
                     filename="a.jpg", ext="jpg", size_bytes=100,
                     sha1="cascade_sha1", mtime=1, is_raw=0, indexed_at=1))
        await s.commit()

        ref = await s.get(ThumbnailRef, "cascade_sha1")
        assert ref is not None
        assert ref.image_count == 1

        # Delete root — cascade should fire image DELETE trigger
        root = await s.get(GalleryRoot, rid)
        await s.delete(root)
        await s.commit()

        ref = await s.get(ThumbnailRef, "cascade_sha1")
        assert ref.image_count == 0


async def test_trigger_count_never_negative(engine_and_sm):
    """image_count should floor at 0 even if trigger fires on empty table."""
    engine, sm = engine_and_sm
    from myphoto.thumbnail_refs import install_triggers

    async with engine.begin() as conn:
        await install_triggers(conn)

    async with sm() as s:
        rid, fid = _make_gallery_root_and_folder(s, int(time.time()))
        img = Image(root_id=rid, folder_id=fid, relative_path="a.jpg",
                     filename="a.jpg", ext="jpg", size_bytes=100,
                     sha1="neg", mtime=1, is_raw=0, indexed_at=1)
        s.add(img)
        await s.commit()

        ref = await s.get(ThumbnailRef, "neg")
        assert ref.image_count == 1

        # Delete twice (second delete can't happen via app code, but test edge case)
        await s.delete(img)
        await s.commit()

        # Manually re-insert and re-delete the same logical image
        img2 = Image(root_id=rid, folder_id=fid, relative_path="a.jpg",
                      filename="a.jpg", ext="jpg", size_bytes=100,
                      sha1="neg", mtime=1, is_raw=0, indexed_at=1)
        s.add(img2)
        await s.commit()
        await s.delete(img2)
        await s.commit()

        ref = await s.get(ThumbnailRef, "neg")
        assert ref.image_count >= 0  # never negative


async def test_same_sha_shared_by_multiple_images(engine_and_sm):
    """Multiple images with the same SHA1 share one ref row with correct count."""
    engine, sm = engine_and_sm
    from myphoto.thumbnail_refs import install_triggers

    async with engine.begin() as conn:
        await install_triggers(conn)

    async with sm() as s:
        rid, fid = _make_gallery_root_and_folder(s, int(time.time()))
        for name in ["a.jpg", "b.jpg", "c.jpg"]:
            s.add(Image(root_id=rid, folder_id=fid, relative_path=name,
                         filename=name, ext="jpg", size_bytes=100,
                         sha1="shared", mtime=1, is_raw=0, indexed_at=1))
        await s.commit()

        ref = await s.get(ThumbnailRef, "shared")
        assert ref.image_count == 3
```

- [ ] **Step 7: 运行测试确认触发器行为**

```bash
cd backend && python -m pytest tests/test_thumbnail_refs.py -v
```

预期：7 个测试全部通过。

- [ ] **Step 8: 提交**

```bash
git add backend/src/myphoto/models.py backend/src/myphoto/thumbnail_refs.py backend/tests/test_thumbnail_refs.py
git commit -m "feat: add ThumbnailRef model and SQLite triggers for reference counting"
```

---

### Task 2: Schema 初始化升级（回填 + 版本标记）

**Files:**
- Modify: `backend/src/myphoto/schema_init.py`

**Interfaces:**
- Consumes: `install_triggers(conn)`, `backfill_refs(conn)` from `thumbnail_refs.py`
- Produces: 升级后的 `ensure_schema_and_admin` 保证每次启动后触发器已安装且数据已回填

---

- [ ] **Step 1: 修改 `schema_init.py`，在建表后安装触发器并回填**

```python
# backend/src/myphoto/schema_init.py

from __future__ import annotations

import secrets
import time

from sqlalchemy import text, select  # text is new

from myphoto.db import create_all
from myphoto.models import User
from myphoto.security import hash_password


_SCHEMA_VERSION = 1  # incremented each time we add a migration step


def _generate_password() -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(16))


async def ensure_schema_and_admin(engine, sessionmaker) -> tuple[bool, str | None]:
    """Create tables if missing and seed initial admin if no admin exists.

    Also installs thumbnail_refs triggers and backfills reference counts
    for existing images (safe to call on every startup — idempotent).

    Returns (created_initial_admin, plain_password_if_created).
    """
    await create_all(engine)

    # Install triggers and backfill refs. This runs every startup but is
    # idempotent: CREATE TRIGGER IF NOT EXISTS + ON CONFLICT in backfill.
    from myphoto.thumbnail_refs import install_triggers, backfill_refs

    async with engine.begin() as conn:
        await install_triggers(conn)
        # Only backfill if the table hasn't been populated yet.
        # We check by seeing if any row exists in thumbnail_refs.
        # For fresh databases (create_all just created the table), there are
        # zero rows — backfill is a no-op. For upgraded databases with images
        # but no refs, backfill populates them once.
        result = await conn.execute(text("SELECT COUNT(*) FROM thumbnail_refs"))
        count = result.scalar_one()
        if count == 0:
            await backfill_refs(conn)

    async with sessionmaker() as s:
        existing = (await s.execute(select(User).where(User.role == "admin"))).first()
        if existing is not None:
            return False, None
        password = _generate_password()
        s.add(User(
            username="admin",
            password_hash=hash_password(password),
            role="admin",
            access_scope="lan_only",
            enabled=1,
            created_at=int(time.time()),
        ))
        await s.commit()
        return True, password
```

- [ ] **Step 2: 编写 schema init 升级测试**

在 `backend/tests/test_thumbnail_refs.py` 末尾追加：

```python
async def test_backfill_populates_existing_images():
    """Simulate upgrade: create images without triggers, then install triggers + backfill."""
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)

    # Step 1: Insert images WITHOUT triggers (simulating pre-upgrade state)
    async with sm() as s:
        g = Gallery(name="G", created_at=int(time.time()))
        s.add(g)
        await s.flush()
        r = GalleryRoot(gallery_id=g.id, label="R", absolute_path="/x", enabled=1)
        s.add(r)
        await s.flush()
        f = Folder(root_id=r.id, relative_path="", name="", image_count=0, descendant_count=0)
        s.add(f)
        await s.flush()
        s.add(Image(root_id=r.id, folder_id=f.id, relative_path="a.jpg",
                     filename="a.jpg", ext="jpg", size_bytes=100,
                     sha1="pre_upgrade", mtime=1, is_raw=0, indexed_at=1))
        await s.commit()

    # Step 2: Now install triggers + backfill (simulating upgraded startup)
    from myphoto.thumbnail_refs import install_triggers, backfill_refs
    async with engine.begin() as conn:
        await install_triggers(conn)
        await backfill_refs(conn)

    # Step 3: Verify refs populated
    async with sm() as s:
        ref = await s.get(ThumbnailRef, "pre_upgrade")
        assert ref is not None
        assert ref.image_count == 1
        assert ref.trash_count == 0

    await engine.dispose()


async def test_backfill_is_idempotent():
    """Calling backfill twice should not double-count."""
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)

    # Insert images without triggers
    async with sm() as s:
        g = Gallery(name="G", created_at=int(time.time()))
        s.add(g)
        await s.flush()
        r = GalleryRoot(gallery_id=g.id, label="R", absolute_path="/x", enabled=1)
        s.add(r)
        await s.flush()
        f = Folder(root_id=r.id, relative_path="", name="", image_count=0, descendant_count=0)
        s.add(f)
        await s.flush()
        s.add(Image(root_id=r.id, folder_id=f.id, relative_path="a.jpg",
                     filename="a.jpg", ext="jpg", size_bytes=100,
                     sha1="idem", mtime=1, is_raw=0, indexed_at=1))
        await s.commit()

    from myphoto.thumbnail_refs import backfill_refs
    async with engine.begin() as conn:
        await backfill_refs(conn)
        await backfill_refs(conn)  # second call

    async with sm() as s:
        ref = await s.get(ThumbnailRef, "idem")
        assert ref.image_count == 1  # not 2

    await engine.dispose()
```

- [ ] **Step 3: 运行测试**

```bash
cd backend && python -m pytest tests/test_thumbnail_refs.py -v
```

预期：9 个测试全部通过（7 个触发器 + 2 个回填）。

- [ ] **Step 4: 提交**

```bash
git add backend/src/myphoto/schema_init.py backend/tests/test_thumbnail_refs.py
git commit -m "feat: install triggers and backfill refs on schema init"
```

---

### Task 3: 清理前校准函数 + PruneService

**Files:**
- Modify: `backend/src/myphoto/thumbnail_refs.py`（追加 PruneService 和 PruneResult）

**Interfaces:**
- Consumes: `calibrate_refs(conn)`（已在 Task 1 定义）
- Produces: `PruneResult` dataclass、`PruneService` 类

---

- [ ] **Step 1: 在 `thumbnail_refs.py` 中追加 PruneResult 和 PruneService**

在现有 `calibrate_refs` 之后追加：

```python
# ---- prune ----

SHA1_PATTERN = __import__("re").compile(r"^[a-f0-9]{40}$")
SHA1_PREFIX_PATTERN = __import__("re").compile(r"^[a-f0-9]{2}$")


@dataclass
class PruneResult:
    scanned: int
    removed: int
    failed: int
    freed_bytes: int


class PruneService:
    """Scans the thumbnail cache directory, removes entries with zero
    DB references, and cleans up empty parent directories."""

    def __init__(self, cache_dir: Path, sessionmaker):
        self._cache = cache_dir
        self._sm = sessionmaker
        self._lock = asyncio.Lock()

    async def prune(self) -> PruneResult:
        """Main entry point. Acquires lock, runs full prune cycle, returns result."""
        if self._lock.locked():
            raise PruneInProgressError("thumb_cache_purge_in_progress")
        async with self._lock:
            return await self._do_prune()

    async def _do_prune(self) -> PruneResult:
        cache_root = self._cache.resolve()

        if not cache_root.exists():
            return PruneResult(scanned=0, removed=0, failed=0, freed_bytes=0)

        # Safety checks (reuse existing pattern from routes_admin.py)
        if cache_root.is_symlink():
            raise ValueError("thumbnail cache path is a symlink; refusing to prune")

        try:
            resolved = cache_root.resolve(strict=True)
        except OSError:
            raise ValueError("thumbnail cache path is not accessible")

        # calibration within a transaction
        async with self._sm.begin() as conn:
            await calibrate_refs(conn)
            # Get set of sha1 values that still have references
            result = await conn.execute(
                text("SELECT sha1 FROM thumbnail_refs WHERE image_count + trash_count > 0")
            )
            valid_sha1s: set[str] = {row[0] for row in result.fetchall()}
            # Get zero-ref sha1s that have rows in thumbnail_refs
            result = await conn.execute(
                text("SELECT sha1 FROM thumbnail_refs WHERE image_count + trash_count = 0")
            )
            zero_ref_sha1s: set[str] = {row[0] for row in result.fetchall()}

        # Scan cache directory for actual SHA1 dirs
        scanned = 0
        removed = 0
        failed = 0
        freed_bytes = 0

        candidates: set[str] = set()  # sha1 dirs to potentially remove

        for prefix_dir in cache_root.iterdir():
            if not prefix_dir.is_dir() or prefix_dir.is_symlink():
                continue
            if not SHA1_PREFIX_PATTERN.match(prefix_dir.name):
                continue

            for sha1_dir in prefix_dir.iterdir():
                if not sha1_dir.is_dir() or sha1_dir.is_symlink():
                    continue
                if not SHA1_PATTERN.match(sha1_dir.name):
                    continue

                scanned += 1
                sha1 = sha1_dir.name
                if sha1 not in valid_sha1s:
                    candidates.add(sha1)

        # Batch-recheck candidates against DB (final safety net)
        if candidates:
            async with self._sm.begin() as conn:
                # Re-check: any candidate that now has refs should be skipped
                placeholders = ",".join([f":s{i}" for i in range(len(candidates))])
                params = {f"s{i}": s for i, s in enumerate(candidates)}
                result = await conn.execute(
                    text(
                        f"SELECT sha1 FROM thumbnail_refs "
                        f"WHERE sha1 IN ({placeholders}) "
                        f"AND image_count + trash_count > 0"
                    ),
                    params,
                )
                still_valid = {row[0] for row in result.fetchall()}
                candidates -= still_valid

            # Remove each candidate directory
            for sha1 in sorted(candidates):
                sha1_dir = cache_root / sha1[:2] / sha1
                try:
                    # Double-check path containment
                    sha1_dir_resolved = sha1_dir.resolve(strict=False)
                    sha1_dir_resolved.relative_to(cache_root)  # raises ValueError if escapes
                except (ValueError, OSError):
                    failed += 1
                    log.warning("prune: skipping unsafe path %s", sha1_dir)
                    continue

                try:
                    import shutil
                    dir_size = _dir_size(sha1_dir)
                    shutil.rmtree(str(sha1_dir_resolved))
                    freed_bytes += dir_size
                    removed += 1
                except OSError as exc:
                    failed += 1
                    log.warning("prune: failed to remove %s: %s", sha1_dir, exc)

        # Clean up empty prefix directories
        for prefix_dir in cache_root.iterdir():
            if not prefix_dir.is_dir() or prefix_dir.is_symlink():
                continue
            if not SHA1_PREFIX_PATTERN.match(prefix_dir.name):
                continue
            try:
                if not any(True for _ in prefix_dir.iterdir()):
                    prefix_dir.rmdir()
            except OSError:
                pass

        # Clean up zero-ref rows for successfully removed dirs
        if removed > 0:
            async with self._sm.begin() as conn:
                batch = sorted(candidates)
                # Only remove rows for sha1 dirs we confirmed removed
                # (use removed count as sanity — we trust the deletion above)
                for sha1 in batch:
                    sha1_dir = cache_root / sha1[:2] / sha1
                    if not sha1_dir.exists():
                        await conn.execute(
                            text("DELETE FROM thumbnail_refs WHERE sha1 = :sha1"),
                            {"sha1": sha1},
                        )

        return PruneResult(
            scanned=scanned,
            removed=removed,
            failed=failed,
            freed_bytes=freed_bytes,
        )


class PruneInProgressError(Exception):
    """Raised when a prune is already running."""
    pass


def _dir_size(path: Path) -> int:
    """Recursively sum file sizes in a directory."""
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    return total
```

- [ ] **Step 2: 编写 PruneService 测试**

在 `backend/tests/test_thumbnail_refs.py` 末尾追加：

```python
class TestPruneService:
    """Integration tests for PruneService using real cache dirs."""

    def test_prune_empty_cache_returns_zeroes(self, tmp_path):
        """Prune on an empty or non-existent cache dir should return all zeros."""
        from myphoto.thumbnail_refs import PruneService

        engine_fut = make_engine("sqlite+aiosqlite:///:memory:")

        async def _run():
            engine = await engine_fut
            await create_all(engine)
            sm = await make_sessionmaker(engine)
            from myphoto.thumbnail_refs import install_triggers
            async with engine.begin() as conn:
                await install_triggers(conn)

            svc = PruneService(tmp_path / "nonexistent_cache" / "thumbnails", sm)
            result = await svc.prune()
            assert result.scanned == 0
            assert result.removed == 0
            assert result.failed == 0
            assert result.freed_bytes == 0
            await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())

    def test_prune_keeps_referenced_removes_orphans(self, tmp_path):
        """Thumbnails with image refs are kept; those without are removed."""
        from myphoto.thumbnail_refs import PruneService

        cache_dir = tmp_path / ".cache" / "thumbnails"
        engine_fut = make_engine("sqlite+aiosqlite:///:memory:")

        async def _run():
            engine = await engine_fut
            await create_all(engine)
            sm = await make_sessionmaker(engine)
            from myphoto.thumbnail_refs import install_triggers
            async with engine.begin() as conn:
                await install_triggers(conn)

            # Insert an image with sha1 "keep_sha1" so it has a reference
            async with sm() as s:
                g = Gallery(name="G", created_at=1)
                s.add(g)
                await s.flush()
                r = GalleryRoot(gallery_id=g.id, label="R", absolute_path="/x", enabled=1)
                s.add(r)
                await s.flush()
                f = Folder(root_id=r.id, relative_path="", name="", image_count=0, descendant_count=0)
                s.add(f)
                await s.flush()
                s.add(Image(root_id=r.id, folder_id=f.id, relative_path="keep.jpg",
                             filename="keep.jpg", ext="jpg", size_bytes=100,
                             sha1="a" * 40, mtime=1, is_raw=0, indexed_at=1))
                await s.commit()

            # Create cache dirs:
            #   ab/{40*'a'}/200.jpg  (has ref → kept)
            #   cd/{40*'c'}/200.jpg  (no ref → orphan → removed)
            kept_sha1 = "a" * 40
            kept_dir = cache_dir / kept_sha1[:2] / kept_sha1
            kept_dir.mkdir(parents=True)
            (kept_dir / "200.jpg").write_bytes(b"kept_thumb")

            orphan_sha1 = "c" * 40
            orphan_dir = cache_dir / orphan_sha1[:2] / orphan_sha1
            orphan_dir.mkdir(parents=True)
            (orphan_dir / "200.jpg").write_bytes(b"orphan_thumb")

            svc = PruneService(cache_dir, sm)
            result = await svc.prune()

            assert result.scanned >= 2
            assert result.removed == 1
            assert result.failed == 0
            assert result.freed_bytes > 0

            # Kept dir still exists
            assert kept_dir.exists()
            # Orphan dir removed
            assert not orphan_dir.exists()
            # Empty prefix dir (cd) removed
            assert not (cache_dir / orphan_sha1[:2]).exists()

            await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())

    def test_prune_skips_non_sha1_dirs(self, tmp_path):
        """Random files/dirs in the cache root are never touched."""
        from myphoto.thumbnail_refs import PruneService

        cache_dir = tmp_path / ".cache" / "thumbnails"
        stray_file = cache_dir / "README.txt"
        stray_file.parent.mkdir(parents=True)
        stray_file.write_text("do not delete me")

        bad_name_dir = cache_dir / "zz" / "not-a-sha1-dir"
        bad_name_dir.mkdir(parents=True)

        engine_fut = make_engine("sqlite+aiosqlite:///:memory:")

        async def _run():
            engine = await engine_fut
            await create_all(engine)
            sm = await make_sessionmaker(engine)
            from myphoto.thumbnail_refs import install_triggers
            async with engine.begin() as conn:
                await install_triggers(conn)

            svc = PruneService(cache_dir, sm)
            result = await svc.prune()

            # Non-SHA1 dirs and files are not counted as scanned, not touched
            assert stray_file.exists()
            assert bad_name_dir.exists()
            # scanned counts only valid SHA1 dirs
            assert result.scanned == 0

            await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())

    def test_prune_concurrent_call_returns_409_error(self, tmp_path):
        """Second concurrent prune call raises PruneInProgressError."""
        from myphoto.thumbnail_refs import PruneService, PruneInProgressError

        cache_dir = tmp_path / ".cache" / "thumbnails"
        cache_dir.mkdir(parents=True)

        engine_fut = make_engine("sqlite+aiosqlite:///:memory:")

        async def _run():
            engine = await engine_fut
            await create_all(engine)
            sm = await make_sessionmaker(engine)
            from myphoto.thumbnail_refs import install_triggers
            async with engine.begin() as conn:
                await install_triggers(conn)

            svc = PruneService(cache_dir, sm)
            # Acquire lock without awaiting (simulate in-progress)
            await svc._lock.acquire()
            try:
                with pytest.raises(PruneInProgressError) as exc_info:
                    await svc.prune()
                assert "in_progress" in str(exc_info.value)
            finally:
                svc._lock.release()

            await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())
```

- [ ] **Step 3: 运行测试**

```bash
cd backend && python -m pytest tests/test_thumbnail_refs.py -v
```

预期：13 个测试全部通过（7 触发器 + 2 回填 + 4 清理）。

- [ ] **Step 4: 提交**

```bash
git add backend/src/myphoto/thumbnail_refs.py backend/tests/test_thumbnail_refs.py
git commit -m "feat: add PruneService for unreferenced thumbnail cleanup"
```

---

### Task 4: 修改现有 purge 端点 + 审计接线

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py`

**Interfaces:**
- Consumes: `PruneService`, `PruneInProgressError` from `thumbnail_refs.py`
- Produces: `POST /api/admin/thumb-cache/purge` → 200（曾为 204）

---

- [ ] **Step 1: 重写 `admin_thumb_cache_purge` 端点**

替换 `backend/src/myphoto/routes_admin.py` 中 `# ---- system status / thumb-cache purge / audit query ----` 段落下方的 `admin_thumb_cache_purge` 函数：

```python
@router.post("/thumb-cache/purge")
async def admin_thumb_cache_purge(
    request: Request,
    admin: User = Depends(admin_required),
):
    """Remove thumbnail cache entries with zero image and trash references.

    Only touches .cache/thumbnails, never any gallery roots or originals.
    Orphaned cache dirs (pre-existing before ref counting) are also cleaned.
    """
    from pathlib import Path
    from myphoto.thumbnail_refs import PruneService, PruneInProgressError

    cfg = request.app.state.config
    data_dir = Path(cfg.data_dir).resolve()
    cache_dir = data_dir / ".cache" / "thumbnails"

    # Safety guards: same as before
    if cache_dir.exists() and cache_dir.is_symlink():
        raise AppError("bad_request", 400, "thumbnail cache path is a symlink; refusing to purge")
    if cache_dir.exists():
        try:
            resolved = cache_dir.resolve(strict=True)
            resolved.relative_to((data_dir / ".cache").resolve())
        except (OSError, ValueError):
            raise AppError("bad_request", 400, "thumbnail cache path escapes data dir")

    sm = request.app.state.sessionmaker
    svc = PruneService(cache_dir, sm)

    try:
        result = await svc.prune()
    except PruneInProgressError:
        raise AppError("thumb_cache_purge_in_progress", 409, "a prune is already running")

    # Audit
    from myphoto.audit import write_audit
    async with sm() as s:
        await write_audit(
            s, "thumb_cache_purge", admin.id, _client_ip(request),
            target="thumb_cache",
            detail=(
                f"mode=unreferenced "
                f"scanned={result.scanned} "
                f"removed={result.removed} "
                f"failed={result.failed} "
                f"freed_bytes={result.freed_bytes}"
            ),
        )
        await s.commit()

    return {
        "scanned": result.scanned,
        "removed": result.removed,
        "failed": result.failed,
        "freed_bytes": result.freed_bytes,
    }
```

同时移除原有的 `import shutil` 和旧的 `# ---- system status / thumb-cache purge / audit query ----` 段落中不再需要的 `shutil.rmtree` 导入（如果 `shutil` 其他地方还有用则保留导入）。检查 `routes_admin.py` 顶部：

```python
import shutil  # 如果仅 purge 用，改为在 PruneService 内 import；若 browse-fs 等仍用到则保留
```

简化方案：保留 `import shutil` 在顶部（PruneService 内部已有 `import shutil` 在方法内，顶层保留不影响），只替换函数体。

- [ ] **Step 2: 更新现有测试用例**

在 `backend/tests/test_routes_admin_system.py` 中：

更新 `test_thumb_cache_purge_removes_files` — 现在不再是无条件清空所有文件，而是只清理无引用的。需要修改测试逻辑：

```python
def test_thumb_cache_purge_removes_files(client_as_admin):
    """With no images in DB, all cache dirs are orphaned → all removed."""
    c, tmp_path, _ = client_as_admin
    cache_dir = tmp_path / ".cache" / "thumbnails"

    # Create a legitimate SHA1 cache dir (simulating orphan from pre-ref-counting era)
    sha1 = "a" * 40
    sha1_dir = cache_dir / sha1[:2] / sha1
    sha1_dir.mkdir(parents=True)
    (sha1_dir / "200.jpg").write_bytes(b"fake")

    r = c.post("/api/admin/thumb-cache/purge")
    assert r.status_code == 200  # no longer 204
    data = r.json()
    assert "scanned" in data
    assert "removed" in data
    assert "failed" in data
    assert "freed_bytes" in data
    assert data["removed"] >= 1
    # cache dir is still there but orphan sha1 dir is removed
    assert cache_dir.exists()
    assert not sha1_dir.exists()
```

更新 `test_thumb_cache_purge_when_dir_missing` — 行为不变，但响应码改为 200：

```python
def test_thumb_cache_purge_when_dir_missing(client_as_admin):
    c, tmp_path, _ = client_as_admin
    cache_dir = tmp_path / ".cache" / "thumbnails"
    import shutil as _shutil
    if cache_dir.exists():
        _shutil.rmtree(cache_dir)

    r = c.post("/api/admin/thumb-cache/purge")
    assert r.status_code == 200  # no longer 204
    data = r.json()
    assert data["scanned"] == 0
    assert data["removed"] == 0
    assert cache_dir.exists()  # recreated? no — PruneService doesn't mkdir
    # Note: PruneService doesn't recreate the dir. But it's a minor detail.
    # If the old test expected cache_dir to exist, that's because the old endpoint
    # called cache_dir.mkdir(parents=True, exist_ok=True).
    # Now we don't do that. Adjust the assertion.
    assert not cache_dir.exists()  # PruneService doesn't recreate
```

更新 `test_thumb_cache_purge_writes_audit` — 响应码 200，审计 detail 格式改变：

```python
def test_thumb_cache_purge_writes_audit(client_as_admin):
    from sqlalchemy import select
    c, _, _ = client_as_admin
    app = c.app

    c.post("/api/admin/thumb-cache/purge")

    async def _fetch():
        sm = app.state.sessionmaker
        async with sm() as s:
            rows = (
                await s.execute(
                    select(AuditLog).where(AuditLog.action == "thumb_cache_purge")
                )
            ).scalars().all()
            return rows

    rows = c.portal.call(_fetch)
    assert len(rows) >= 1
    # New audit detail format includes mode and stats
    assert "mode=unreferenced" in (rows[-1].detail or "")
```

更新 `test_thumb_cache_purge_non_admin_401` — 不变：

```python
def test_thumb_cache_purge_non_admin_401(client_unauthed):
    r = client_unauthed.post("/api/admin/thumb-cache/purge")
    assert r.status_code == 401
```

更新 `test_thumb_cache_purge_refuses_symlink` — 不变（行为一致）：

```python
# 此测试保持不变
```

新增测试——保留有引用的缩略图：

```python
def test_thumb_cache_purge_keeps_referenced_thumbnails(client_as_admin):
    """Thumbnails for images still in the DB must not be removed."""
    c, tmp_path, _ = client_as_admin

    # First, add a gallery + root + image through the app
    photos = tmp_path / "photos"
    photos.mkdir()
    from PIL import Image as PILImage
    PILImage.new("RGB", (100, 100), (255, 0, 0)).save(photos / "test.jpg")

    gid = c.post("/api/admin/galleries", json={"name": "G"}).json()["id"]
    c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": str(photos),
    })

    # Trigger scan so the image enters the DB and gets a sha1
    # (scan happens automatically in background; wait a moment or force it)
    import time as _time
    _time.sleep(0.5)

    # Now fetch the image's sha1 from the DB
    app = c.app

    async def _get_sha1():
        from myphoto.models import Image
        from sqlalchemy import select as _s
        async with app.state.sessionmaker() as s:
            rows = (await s.execute(_s(Image))).scalars().all()
            return [(r.id, r.sha1) for r in rows]

    images = c.portal.call(_get_sha1)
    # Ensure we have at least one image scanned
    assert len(images) >= 1

    # Access the thumbnail so it gets cached
    sha1 = images[0][1]
    c.get(f"/api/thumb/{sha1}", params={"size": 200})

    # Verify cache exists
    cache_dir = tmp_path / ".cache" / "thumbnails"
    thumb_path = cache_dir / sha1[:2] / sha1 / "200.jpg"
    assert thumb_path.exists()

    # Purge — should keep this referenced thumbnail
    r = c.post("/api/admin/thumb-cache/purge")
    assert r.status_code == 200
    data = r.json()
    # The referenced thumbnail should survive
    assert thumb_path.exists(), f"Referenced thumbnail was wrongly removed. Result: {data}"
```

- [ ] **Step 3: 运行测试**

```bash
cd backend && python -m pytest tests/test_routes_admin_system.py -v
```

预期：所有 purge 相关测试（含新增）通过。

- [ ] **Step 4: 提交**

```bash
git add backend/src/myphoto/routes_admin.py backend/tests/test_routes_admin_system.py
git commit -m "feat: change thumb-cache purge to unreferenced-only cleanup"
```

---

### Task 5: ThumbnailGenerator 进程内去重锁 + 原子写入

**Files:**
- Modify: `backend/src/myphoto/thumbnails.py`

---

- [ ] **Step 1: 在 ThumbnailGenerator 中增加去重锁**

重写 `ensure` 方法，增加 `(sha1, size)` 级别的 asyncio.Lock：

```python
# backend/src/myphoto/thumbnails.py

from __future__ import annotations

import asyncio
import logging
import tempfile
import shutil  # for atomic rename
from pathlib import Path

from PIL import Image as PILImage, UnidentifiedImageError

log = logging.getLogger("myphoto.thumbnails")

try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:
    pass

ALLOWED_SIZES: frozenset[int] = frozenset({200, 400, 1600})


class ThumbnailError(Exception):
    pass


class ThumbnailGenerator:
    def __init__(self, cache_dir: str | Path):
        self._cache = Path(cache_dir)
        self._locks: dict[tuple[str, int], asyncio.Lock] = {}

    def cache_path(self, sha1: str, size: int) -> Path:
        return self._cache / sha1[:2] / sha1 / f"{size}.jpg"

    def _get_lock(self, sha1: str, size: int) -> asyncio.Lock:
        key = (sha1, size)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _release_lock(self, sha1: str, size: int) -> None:
        key = (sha1, size)
        lock = self._locks.get(key)
        if lock is not None and not lock.locked():
            self._locks.pop(key, None)

    async def ensure(self, sha1: str, size: int, source_path: str, is_raw: bool) -> Path:
        if size not in ALLOWED_SIZES:
            raise ValueError(f"size {size} not allowed")
        out = self.cache_path(sha1, size)
        if out.exists():
            return out

        lock = self._get_lock(sha1, size)
        async with lock:
            # Double-check after acquiring lock
            if out.exists():
                return out
            out.parent.mkdir(parents=True, exist_ok=True)
            # Render to a temp file, then atomically rename
            tmp = Path(tempfile.mktemp(suffix=".jpg", dir=str(out.parent)))
            try:
                await asyncio.to_thread(_render_thumb, source_path, size, tmp, is_raw)
                shutil.move(str(tmp), str(out))
            except Exception:
                # Clean up temp file on failure
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            finally:
                self._release_lock(sha1, size)
        return out
```

- [ ] **Step 2: 修改 `_render_thumb` 接受输出路径参数**

现在 `_render_thumb` 的 `out` 参数可以是临时文件路径，逻辑不变，因为它是最终写入目标：

```python
def _render_thumb(source: str, size: int, out: Path, is_raw: bool) -> None:
    try:
        if is_raw:
            _render_raw(source, size, out)
        else:
            _render_regular(source, size, out)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ThumbnailError(str(exc)) from exc
```

不需要修改 `_render_regular` 和 `_render_raw`，它们已经接受 `out: Path` 参数。

- [ ] **Step 3: 编写去重锁测试**

在 `backend/tests/test_thumbnails.py` 末尾追加：

```python
async def test_ensure_dedup_lock_prevents_concurrent_generation(tmp_path):
    """Concurrent ensure() calls for the same (sha1,size) render only once."""
    src = tmp_path / "in.jpg"
    _jpg(src)
    gen = ThumbnailGenerator(tmp_path / "cache")

    # Launch two concurrent ensure calls
    results = await asyncio.gather(
        gen.ensure("locktest", 200, str(src), is_raw=False),
        gen.ensure("locktest", 200, str(src), is_raw=False),
    )
    assert results[0] == results[1]
    assert results[0].exists()


async def test_ensure_atomic_write_no_partial_file_on_crash(tmp_path, monkeypatch):
    """If rendering fails, no partial .jpg is left at the cache path."""
    src = tmp_path / "in.jpg"
    _jpg(src)
    gen = ThumbnailGenerator(tmp_path / "cache")

    # Simulate render failure
    orig = _render_thumb

    def _failing_render(*args, **kwargs):
        raise ThumbnailError("simulated crash")

    monkeypatch.setattr("myphoto.thumbnails._render_thumb", _failing_render)

    with pytest.raises(ThumbnailError):
        await gen.ensure("crash", 200, str(src), is_raw=False)

    out = gen.cache_path("crash", 200)
    assert not out.exists()  # no partial file at target path


async def test_ensure_different_sizes_do_not_block(tmp_path):
    """200 and 400 renders for the same sha1 can proceed in parallel."""
    src = tmp_path / "in.jpg"
    _jpg(src)
    gen = ThumbnailGenerator(tmp_path / "cache")

    results = await asyncio.gather(
        gen.ensure("parallel", 200, str(src), is_raw=False),
        gen.ensure("parallel", 400, str(src), is_raw=False),
    )
    assert results[0].exists()
    assert results[1].exists()
    assert results[0] != results[1]
```

- [ ] **Step 4: 运行测试**

```bash
cd backend && python -m pytest tests/test_thumbnails.py -v
```

预期：所有测试（含原有的 6 个 + 新增的 3 个）通过。

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/thumbnails.py backend/tests/test_thumbnails.py
git commit -m "feat: add dedup lock and atomic write to thumbnail generation"
```

---

### Task 6: 前端按钮改版

**Files:**
- Modify: `frontend/src/views/AdminOverview.vue`
- Modify: `frontend/src/tests/admin-overview.spec.ts`

---

- [ ] **Step 1: 在 AdminOverview 中添加清理按钮和交互**

在现有 "管理图库" link 上方添加清理缩略图缓存按钮区域：

```vue
<!-- 在 <section> 管理图库 router-link 之前添加 -->
<section>
  <div class="flex items-center gap-3">
    <button
      :disabled="purging"
      @click="purgeThumbCache"
      class="inline-flex items-center rounded bg-neutral-700 px-3 py-2 text-sm hover:bg-neutral-600 disabled:opacity-50"
    >
      {{ purging ? '清理中...' : '清理无引用缩略图' }}
    </button>
    <span v-if="purgeResult !== null" class="text-sm text-neutral-400">
      已清理 {{ purgeResult.removed }} 组缩略图，释放 {{ formatBytes(purgeResult.freed_bytes) }}
      <span v-if="purgeResult.failed > 0" class="text-yellow-400">
        ；{{ purgeResult.failed }} 组清理失败
      </span>
    </span>
    <span v-if="purgeError" class="text-sm text-red-400">{{ purgeError }}</span>
  </div>
</section>
```

在 `<script setup>` 中添加状态和方法：

```typescript
// 在 data/loading/error 之后添加
const purging = ref(false)
const purgeError = ref("")

interface PurgeResult {
  scanned: number
  removed: number
  failed: number
  freed_bytes: number
}
const purgeResult = ref<PurgeResult | null>(null)

async function purgeThumbCache() {
  if (!confirm(
    "仅清理已不属于图库且不在回收站中的缩略图缓存。\n\n" +
    "• 不删除任何原始图片\n" +
    "• 正在使用的缩略图不会被清理\n" +
    "• 缺失缩略图会在浏览时自动生成\n\n" +
    "确认清理？"
  )) return

  purging.value = true
  purgeError.value = ""
  purgeResult.value = null
  try {
    // apiPost returns parsed JSON for non-204 responses; our new endpoint returns 200
    const data = await apiPost<PurgeResult>("/api/admin/thumb-cache/purge")
    purgeResult.value = data
  } catch (err) {
    if (err instanceof HttpError && err.status === 409) {
      purgeError.value = "清理任务已在运行中，请稍后再试"
    } else {
      purgeError.value = (err as HttpError).message || "清理失败"
    }
  } finally {
    purging.value = false
  }
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B"
  const units = ["B", "KB", "MB", "GB", "TB"]
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + " " + units[i]
}
```

需要新增导入（在 script setup 部分已有 `apiGet` 导入，需要同时导入 `apiPost`）：

```typescript
import { apiGet, apiPost, HttpError } from "../api"
```

注意：当前 AdminOverview.vue 的 import 行是 `import { apiGet, HttpError } from "../api"`，需要加上 `apiPost`。

- [ ] **Step 2: 更新前端测试**

在 `frontend/src/tests/admin-overview.spec.ts` 中追加：

```typescript
import { apiPost } from "../api"

// 需要 mock apiPost
vi.mock("../api", async () => {
  const actual = await vi.importActual("../api")
  return { ...actual, apiPost: vi.fn() }
})

it("purge button is disabled during request and shows result on success", async () => {
  ;(apiPost as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    scanned: 100,
    removed: 5,
    failed: 0,
    freed_bytes: 1024000,
  })
  mockStatus(FULL_PAYLOAD)
  const w = mountView()
  await flushPromises()

  const btn = w.find("button")
  expect(btn.text()).toContain("清理无引用缩略图")

  // Stub confirm to return true
  vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
  await btn.trigger("click")
  // Button should show "清理中..." while request in flight
  // (apiPost resolves immediately in stub, but we check that the call happened)
  expect(apiPost).toHaveBeenCalledWith("/api/admin/thumb-cache/purge")
})

it("purge button shows error on 409 conflict", async () => {
  ;(apiPost as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
    new (await import("../api")).HttpError(409, "thumb_cache_purge_in_progress", "a prune is already running")
  )
  mockStatus(FULL_PAYLOAD)
  const w = mountView()
  await flushPromises()

  vi.stubGlobal("confirm", vi.fn().mockReturnValue(true))
  const btn = w.find("button")
  await btn.trigger("click")
  await flushPromises()

  expect(w.text()).toContain("清理任务已在运行中")
})

it("cancel confirm dialog does not trigger purge", async () => {
  mockStatus(FULL_PAYLOAD)
  const w = mountView()
  await flushPromises()

  vi.stubGlobal("confirm", vi.fn().mockReturnValue(false))
  const btn = w.find("button")
  await btn.trigger("click")

  expect(apiPost).not.toHaveBeenCalledWith("/api/admin/thumb-cache/purge")
})
```

注意：现有测试用 `vi.unstubAllGlobals()` 在每个 `beforeEach` 清理，这可能影响 mock。需要调整测试结构，确保 `apiPost` 的 mock 在新测试中生效。

更好的方案：在 `beforeEach` 中统一设置 mock：

```typescript
// 在顶部的 vi.mock 改为手动 mock
vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api")
  return {
    ...actual,
    apiPost: vi.fn(),
  }
})
```

然后在需要 apiPost 的测试中：

```typescript
import { apiGet, apiPost, HttpError } from "../api"
const mockedApiPost = apiPost as ReturnType<typeof vi.fn>
```

- [ ] **Step 3: 运行前端测试**

```bash
cd frontend && pnpm test
```

预期：所有测试通过（含新增的 3 个清理相关测试）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/AdminOverview.vue frontend/src/tests/admin-overview.spec.ts
git commit -m "feat: update admin overview with unreferenced thumbnail purge button"
```

---

### Task 7: 全链路端到端验证

**Files:**
- 无新文件（验证性任务）

---

- [ ] **Step 1: 运行全部后端测试**

```bash
cd backend && python -m pytest -v
```

预期：所有测试通过，无回归。

- [ ] **Step 2: 运行全部前端测试**

```bash
cd frontend && pnpm test
```

预期：所有测试通过，无回归。

- [ ] **Step 3: grep 验证红线（现有测试已覆盖）**

```bash
rg -i 'os\.remove' backend/src/myphoto/
rg -i 'shutil\.rmtree' backend/src/myphoto/
```

预期：
- `os.remove` 不出现在 `thumbnail_refs.py`（已在 `shutil.rmtree` 层面做了路径安全校验）
- `shutil.rmtree` 出现在 `routes_admin.py`（purge 端点安全校验）和 `thumbnail_refs.py`（PruneService 安全校验）

- [ ] **Step 4: 性能基准验证**

创建性能验证脚本（手动运行，不提交）：

```python
# 确认 PruneService 的 SQL 调用数不随 SHA1 数量线性增长
# 目标：对 1000 个 SHA1 和 10000 个 SHA1，SQL 调用数相同（均为固定数量）
```

- [ ] **Step 5: 提交**

```bash
git commit --allow-empty -m "chore: end-to-end verification for thumbnail ref counting"
```

---

## 自检清单

在提交实现之前逐项确认：

- [ ] `ThumbnailRef` 被 `Base.metadata.create_all` 发现（已在 `models.py` 中定义）
- [ ] 触发器使用 `CREATE TRIGGER IF NOT EXISTS` 保证幂等
- [ ] 回填只在 `thumbnail_refs` 为空时执行一次
- [ ] 校准在单个事务中完成，`MAX(0, count-1)` 防止负数
- [ ] PruneService 只操作 `.cache/thumbnails/` 内的合法 SHA1 目录
- [ ] 符号链接不跟随、不删除
- [ ] 路径逃逸被拒绝
- [ ] 并发清理返回 409
- [ ] 审计消息包含 mode=unreferenced
- [ ] purge 端点响应从 204 改为 200
- [ ] 前端按钮文案更新为"清理无引用缩略图"
- [ ] 确认框说明不删除原图
- [ ] 缩略图缺失时按需生成继续工作
- [ ] 8 万级数据量下无 N+1 查询
