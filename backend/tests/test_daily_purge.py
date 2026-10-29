"""Task 7 (P5): next_daily_run pure fn + daily_purge_loop scheduled purge."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time

import pytest
from sqlalchemy import select

from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import AuditLog, Gallery, GalleryRoot, Trash, User
from myphoto.trash import daily_purge_loop, next_daily_run


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
        # Trash.deleted_by 有 users.id 外键，fixture 需要一个真实用户（id=1）
        s.add(User(
            username="admin", password_hash="x", role="admin",
            access_scope="lan_only", enabled=1, created_at=int(time.time()),
        ))
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


async def test_daily_loop_survives_purge_error(loop_env, monkeypatch, caplog):
    """purge 抛非取消异常时循环不死：记录异常后进入下一轮，第二次 sleep 才退出。

    加强版（相对 brief 的退化版）：第一次 sleep 正常返回，让循环真的走到
    purge_expired（被 monkeypatch 成抛 RuntimeError）；第二次 sleep 抛
    CancelledError。由此证明：(a) RuntimeError 被捕获并记录，(b) 循环没有
    死在第一轮 —— CancelledError 只可能来自第二次 sleep。
    """
    sm, _trash_file = loop_env
    sleeps = {"n": 0}

    async def fake_sleep(seconds):
        sleeps["n"] += 1
        if sleeps["n"] == 1:
            return  # 第一轮：放行到 purge 路径
        raise asyncio.CancelledError  # 第二轮：关停

    import myphoto.trash as trash_mod

    async def boom(*_a, **_kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(trash_mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(trash_mod, "purge_expired", boom)

    caplog.set_level(logging.ERROR, logger="myphoto.trash")
    task = asyncio.create_task(daily_purge_loop(sm, lambda: _Cfg()))
    with pytest.raises(asyncio.CancelledError):
        await task

    # CancelledError 来自第二次 sleep —— 循环在第一轮 RuntimeError 后存活了
    assert sleeps["n"] == 2
    # RuntimeError 被 log.exception 记录（带 traceback）
    matched = [
        r for r in caplog.records
        if "scheduled purge_expired failed" in r.getMessage()
        and r.exc_info is not None
        and issubclass(r.exc_info[0], RuntimeError)
    ]
    assert len(matched) == 1, [r.getMessage() for r in caplog.records]
