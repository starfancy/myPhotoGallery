"""Tests for [trash.py] — TRASH_DIR resolver, path guard, purge_expired.

保护红线 3：`os.remove` 唯一位点 + 路径前缀护栏。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from myphoto.audit import write_audit  # noqa: F401  (import 校验)
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import AuditLog, Gallery, GalleryRoot, Trash, User
from myphoto.trash import (
    TRASH_BASENAME,
    is_under_trash_dir,
    purge_expired,
    trash_dir_for,
)


@pytest.fixture
async def session():
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def gallery_and_root(session, tmp_path):
    """建一个真实存在的 root 目录 + 已入库的 gallery/root/user。"""
    now = int(time.time())
    root_dir = tmp_path / "photos"
    root_dir.mkdir()

    session.add(User(
        username="admin",
        password_hash="x",
        role="admin",
        access_scope="lan_only",
        enabled=1,
        created_at=now,
    ))
    g = Gallery(name="G", created_at=now)
    session.add(g)
    await session.flush()
    root = GalleryRoot(
        gallery_id=g.id,
        label="l",
        absolute_path=str(root_dir),
        enabled=1,
    )
    session.add(root)
    await session.flush()
    admin = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()
    return {"gallery": g, "root": root, "admin": admin, "root_dir": root_dir}


# ---------- trash_dir_for + is_under_trash_dir ----------


def test_trash_dir_for_layout(tmp_path):
    root = GalleryRoot(id=7, gallery_id=3, label="l", absolute_path=str(tmp_path), enabled=1)
    got = trash_dir_for(root)
    # <root>/.trash/{gallery_id}/{root_id}/
    expected = tmp_path / TRASH_BASENAME / "3" / "7"
    assert got == expected


def test_is_under_trash_dir_accepts_nested_file(tmp_path):
    root = GalleryRoot(id=1, gallery_id=1, label="l", absolute_path=str(tmp_path), enabled=1)
    tdir = trash_dir_for(root)
    tdir.mkdir(parents=True)
    inside = tdir / "20260722" / "a.jpg"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"x")
    assert is_under_trash_dir(inside, root) is True


def test_is_under_trash_dir_rejects_outside(tmp_path):
    root = GalleryRoot(id=1, gallery_id=1, label="l", absolute_path=str(tmp_path), enabled=1)
    # 图库内、但不在 .trash 下
    outside = tmp_path / "not-trash" / "a.jpg"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"x")
    assert is_under_trash_dir(outside, root) is False


def test_is_under_trash_dir_rejects_dotdot(tmp_path):
    root = GalleryRoot(id=1, gallery_id=1, label="l", absolute_path=str(tmp_path), enabled=1)
    tdir = trash_dir_for(root)
    tdir.mkdir(parents=True)
    # 花招路径：.trash/1/1/../../../evil.jpg 逃出 root
    evil = tdir / ".." / ".." / ".." / "evil.jpg"
    assert is_under_trash_dir(evil, root) is False


def test_is_under_trash_dir_missing_file_ok(tmp_path):
    root = GalleryRoot(id=1, gallery_id=1, label="l", absolute_path=str(tmp_path), enabled=1)
    tdir = trash_dir_for(root)
    tdir.mkdir(parents=True)
    ghost = tdir / "gone.jpg"  # 不存在
    # strict=False 允许判断不存在的路径
    assert is_under_trash_dir(ghost, root) is True


# ---------- purge_expired ----------


async def _make_trashed_file(root_dir: Path, rel: str, content: bytes = b"x") -> Path:
    p = root_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


async def test_purge_expired_removes_expired_only(gallery_and_root, session):
    root = gallery_and_root["root"]
    admin = gallery_and_root["admin"]
    root_dir = gallery_and_root["root_dir"]
    tdir_rel = f"{TRASH_BASENAME}/{root.gallery_id}/{root.id}"

    # 过期
    exp_rel = f"{tdir_rel}/20260701/expired.jpg"
    await _make_trashed_file(root_dir, exp_rel)
    session.add(Trash(
        gallery_id=root.gallery_id, root_id=root.id,
        original_relative_path="a/expired.jpg", trash_relative_path=exp_rel,
        sha1="s1", size_bytes=1, deleted_by=admin.id,
        deleted_at=1000, purge_after=2000,
    ))
    # 未过期
    fresh_rel = f"{tdir_rel}/20260722/fresh.jpg"
    await _make_trashed_file(root_dir, fresh_rel)
    session.add(Trash(
        gallery_id=root.gallery_id, root_id=root.id,
        original_relative_path="a/fresh.jpg", trash_relative_path=fresh_rel,
        sha1="s2", size_bytes=1, deleted_by=admin.id,
        deleted_at=5000, purge_after=9999999999,
    ))
    await session.commit()

    result = await purge_expired(session, now=3000)
    await session.commit()

    assert result == {"purged": 1, "blocked": 0, "missing": 0, "errors": 0}
    # 文件层面
    assert not (root_dir / exp_rel).exists()
    assert (root_dir / fresh_rel).exists()
    # DB 层面
    rows = (await session.execute(select(Trash))).scalars().all()
    assert len(rows) == 1
    assert rows[0].trash_relative_path == fresh_rel


async def test_purge_expired_path_guard_blocks_and_audits(gallery_and_root, session):
    """红线 3：trash_relative_path 若不在 TRASH_DIR 下，绝不删除文件，写审计。"""
    root = gallery_and_root["root"]
    admin = gallery_and_root["admin"]
    root_dir = gallery_and_root["root_dir"]

    # 恶意条目：路径逃出 .trash
    evil_rel = "not-trash/dont-touch-me.jpg"
    victim = await _make_trashed_file(root_dir, evil_rel, b"important")
    session.add(Trash(
        gallery_id=root.gallery_id, root_id=root.id,
        original_relative_path="whatever.jpg", trash_relative_path=evil_rel,
        sha1="s", size_bytes=len(b"important"), deleted_by=admin.id,
        deleted_at=1000, purge_after=2000,
    ))
    await session.commit()

    result = await purge_expired(session, now=3000)
    await session.commit()

    assert result == {"purged": 0, "blocked": 1, "missing": 0, "errors": 0}
    # 文件绝不被删
    assert victim.exists()
    assert victim.read_bytes() == b"important"
    # DB 行仍在（不清理，等待人工检查）
    assert (await session.execute(select(Trash))).scalars().all()
    # 审计 trash_purge / path_guard_blocked 已写
    audits = (await session.execute(
        select(AuditLog).where(AuditLog.action == "trash_purge")
    )).scalars().all()
    assert len(audits) == 1
    assert "path_guard_blocked" in (audits[0].detail or "")


async def test_purge_expired_missing_file_still_cleans_db(gallery_and_root, session):
    root = gallery_and_root["root"]
    admin = gallery_and_root["admin"]
    tdir_rel = f"{TRASH_BASENAME}/{root.gallery_id}/{root.id}"

    ghost_rel = f"{tdir_rel}/20260701/gone.jpg"  # 未创建文件
    session.add(Trash(
        gallery_id=root.gallery_id, root_id=root.id,
        original_relative_path="a/gone.jpg", trash_relative_path=ghost_rel,
        sha1="s", size_bytes=1, deleted_by=admin.id,
        deleted_at=1000, purge_after=2000,
    ))
    await session.commit()

    result = await purge_expired(session, now=3000)
    await session.commit()

    assert result == {"purged": 0, "blocked": 0, "missing": 1, "errors": 0}
    assert (await session.execute(select(Trash))).scalars().all() == []


async def test_purge_expired_idempotent_when_no_expired(gallery_and_root, session):
    root = gallery_and_root["root"]
    admin = gallery_and_root["admin"]
    tdir_rel = f"{TRASH_BASENAME}/{root.gallery_id}/{root.id}"
    fresh_rel = f"{tdir_rel}/20260722/fresh.jpg"
    await _make_trashed_file(gallery_and_root["root_dir"], fresh_rel)
    session.add(Trash(
        gallery_id=root.gallery_id, root_id=root.id,
        original_relative_path="a/fresh.jpg", trash_relative_path=fresh_rel,
        sha1="s", size_bytes=1, deleted_by=admin.id,
        deleted_at=1000, purge_after=9999999999,
    ))
    await session.commit()

    # 反复调用，行为不变
    for _ in range(3):
        result = await purge_expired(session, now=3000)
        await session.commit()
        assert result == {"purged": 0, "blocked": 0, "missing": 0, "errors": 0}
    assert len((await session.execute(select(Trash))).scalars().all()) == 1


async def test_purge_expired_filters_by_gallery_and_root(gallery_and_root, session, tmp_path):
    """gallery_id/root_id 过滤：只清匹配的行。"""
    root_a = gallery_and_root["root"]
    admin = gallery_and_root["admin"]

    # 建第二个 gallery/root
    now = int(time.time())
    g2 = Gallery(name="G2", created_at=now)
    session.add(g2)
    await session.flush()
    root_dir_b = tmp_path / "photos2"
    root_dir_b.mkdir()
    root_b = GalleryRoot(gallery_id=g2.id, label="l2", absolute_path=str(root_dir_b), enabled=1)
    session.add(root_b)
    await session.flush()

    tdir_a_rel = f"{TRASH_BASENAME}/{root_a.gallery_id}/{root_a.id}/e/a.jpg"
    tdir_b_rel = f"{TRASH_BASENAME}/{root_b.gallery_id}/{root_b.id}/e/b.jpg"
    await _make_trashed_file(gallery_and_root["root_dir"], tdir_a_rel)
    await _make_trashed_file(root_dir_b, tdir_b_rel)

    session.add(Trash(
        gallery_id=root_a.gallery_id, root_id=root_a.id,
        original_relative_path="a.jpg", trash_relative_path=tdir_a_rel,
        sha1="s", size_bytes=1, deleted_by=admin.id,
        deleted_at=1000, purge_after=2000,
    ))
    session.add(Trash(
        gallery_id=root_b.gallery_id, root_id=root_b.id,
        original_relative_path="b.jpg", trash_relative_path=tdir_b_rel,
        sha1="s", size_bytes=1, deleted_by=admin.id,
        deleted_at=1000, purge_after=2000,
    ))
    await session.commit()

    # 只清 gallery A
    result = await purge_expired(session, gallery_id=root_a.gallery_id, now=3000)
    await session.commit()
    assert result["purged"] == 1

    rows = (await session.execute(select(Trash))).scalars().all()
    assert len(rows) == 1
    assert rows[0].gallery_id == root_b.gallery_id
    # A 的文件消失，B 的还在
    assert not (gallery_and_root["root_dir"] / tdir_a_rel).exists()
    assert (root_dir_b / tdir_b_rel).exists()


async def test_purge_expired_before_overrides_now(gallery_and_root, session):
    """`before` 参数允许手动 purge 指定时间点之前的条目。"""
    root = gallery_and_root["root"]
    admin = gallery_and_root["admin"]
    tdir_rel = f"{TRASH_BASENAME}/{root.gallery_id}/{root.id}"

    r1 = f"{tdir_rel}/20260101/a.jpg"
    r2 = f"{tdir_rel}/20260601/b.jpg"
    await _make_trashed_file(gallery_and_root["root_dir"], r1)
    await _make_trashed_file(gallery_and_root["root_dir"], r2)
    session.add(Trash(
        gallery_id=root.gallery_id, root_id=root.id,
        original_relative_path="a.jpg", trash_relative_path=r1,
        sha1="s", size_bytes=1, deleted_by=admin.id,
        deleted_at=1000, purge_after=2000,
    ))
    session.add(Trash(
        gallery_id=root.gallery_id, root_id=root.id,
        original_relative_path="b.jpg", trash_relative_path=r2,
        sha1="s", size_bytes=1, deleted_by=admin.id,
        deleted_at=1000, purge_after=5000,
    ))
    await session.commit()

    # before=3000 → 只清 purge_after < 3000 的，也就是 r1
    result = await purge_expired(session, before=3000, now=10000)
    await session.commit()
    assert result["purged"] == 1
    remaining = (await session.execute(select(Trash))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].trash_relative_path == r2
