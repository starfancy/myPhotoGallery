"""P7: audit_log retention — loader clamp, purge_expired, startup/daily hooks, settings."""
from __future__ import annotations

import asyncio
import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from myphoto.audit import purge_expired
from myphoto.config import load_or_init
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.main import build_app
from myphoto.models import AuditLog


@pytest.mark.parametrize("value,expected", [
    ("30", 30), ("90", 90), ("180", 180), ("365", 365), ("0", 0),
])
def test_loader_accepts_allowed_values(tmp_path, value, expected):
    p = tmp_path / "config.toml"
    p.write_text(
        f'[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        f"[audit]\nretention_days = {value}\n",
        encoding="utf-8",
    )
    assert load_or_init(p).audit_retention_days == expected


def test_loader_default_180_when_section_missing(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n', encoding="utf-8")
    assert load_or_init(p).audit_retention_days == 180


def test_loader_bad_type_falls_back_180(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="x"\n[audit]\nretention_days = "forever"\n',
        encoding="utf-8",
    )
    assert load_or_init(p).audit_retention_days == 180


@pytest.mark.parametrize("raw,expected", [("100", 90), ("999", 365), ("-5", 0), ("200", 180)])
def test_loader_clamps_to_nearest_choice(tmp_path, raw, expected):
    # 最近合法集合 {0,30,90,180,365}；等距时取较小值（实现需稳定）
    p = tmp_path / "config.toml"
    p.write_text(
        f'[app]\njwt_secret="x"\n[audit]\nretention_days = {raw}\n',
        encoding="utf-8",
    )
    assert load_or_init(p).audit_retention_days == expected


def test_generated_template_contains_audit_section(tmp_path):
    p = tmp_path / "config.toml"
    load_or_init(p)
    text = p.read_text(encoding="utf-8")
    assert "[audit]" in text
    assert "retention_days = 180" in text


@pytest.fixture
async def memdb():
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    yield sm
    await engine.dispose()


async def test_purge_deletes_only_expired(memdb):
    now = 1_000_000_000
    async with memdb() as s:
        s.add(AuditLog(ts=now - 181 * 86400, actor_ip="x", action="login_success"))   # 删
        s.add(AuditLog(ts=now - 180 * 86400, actor_ip="x", action="login_success"))   # 保留边界
        s.add(AuditLog(ts=now - 100, actor_ip="x", action="login_success"))           # 保留
        await s.commit()

    async with memdb() as s:
        removed = await purge_expired(s, 180, now=now)
        await s.commit()
        assert removed == 1
        rows = (await s.execute(select(AuditLog))).scalars().all()
        assert len(rows) == 2


async def test_purge_zero_retention_is_noop(memdb):
    async with memdb() as s:
        s.add(AuditLog(ts=1, actor_ip="x", action="login_success"))
        await s.commit()
        assert await purge_expired(s, 0, now=2_000_000_000) == 0
        await s.commit()
        assert len((await s.execute(select(AuditLog))).scalars().all()) == 1


async def test_purge_empty_table(memdb):
    async with memdb() as s:
        assert await purge_expired(s, 30, now=int(time.time())) == 0


@pytest.fixture
def client(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        pw = re.search(r"password=(\S+)", capsys.readouterr().out).group(1)
        r = c.post("/api/auth/login", json={"username": "admin", "password": pw})
        assert r.status_code == 200
        yield c, app, cfg


def test_settings_exposes_audit_retention(client):
    c, _, _ = client
    assert c.get("/api/admin/settings").json()["audit_retention_days"] == 180


@pytest.mark.parametrize("ok", [0, 30, 90, 180, 365])
def test_settings_patch_allowed(client, ok):
    c, _, _ = client
    r = c.patch("/api/admin/settings", json={"audit_retention_days": ok})
    assert r.status_code == 200
    assert r.json()["audit_retention_days"] == ok


@pytest.mark.parametrize("bad", [1, 7, 100, 366, -30])
def test_settings_patch_rejects(client, bad):
    c, _, _ = client
    r = c.patch("/api/admin/settings", json={"audit_retention_days": bad})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


async def test_daily_tick_purges_audit_after_trash(monkeypatch):
    """daily_purge_loop 同一 tick 内先 trash 后 audit；audit 段独立 try。"""
    from myphoto.trash import daily_purge_loop

    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    now = int(time.time())
    async with sm() as s:
        s.add(AuditLog(ts=now - 31 * 86400, actor_ip="x", action="login_fail"))
        s.add(AuditLog(ts=now - 100, actor_ip="x", action="login_success"))
        await s.commit()

    class _Cfg:
        trash_purge_hour = 3
        trash_purge_minute = 30
        audit_retention_days = 30

    sleeps = {"n": 0}

    async def fake_sleep(seconds):
        sleeps["n"] += 1
        if sleeps["n"] == 1:
            return
        raise asyncio.CancelledError

    import myphoto.trash as trash_mod
    monkeypatch.setattr(trash_mod.asyncio, "sleep", fake_sleep)
    task = asyncio.create_task(daily_purge_loop(sm, lambda: _Cfg()))
    with pytest.raises(asyncio.CancelledError):
        await task

    async with sm() as s:
        rows = (await s.execute(select(AuditLog))).scalars().all()
        assert len(rows) == 1
    await engine.dispose()


def test_startup_purges_expired_audit_rows(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[app]\njwt_secret="x"\n[audit]\nretention_days = 30\n',
        encoding="utf-8",
    )
    app = build_app(config_path=str(cfg))
    # 首次启动写默认模板（jwt 缺失会怎样？先 build 一次让它生成模板再覆盖不行——
    # 直接走 TestClient 启动后用 sessionmaker 插旧行再第二次 lifespan 不现实；
    # 改为：第一次启动后插入旧行，关闭；第二次启动验证被清）。
    with TestClient(app) as c:
        capsys.readouterr()
        old = int(time.time()) - 31 * 86400
        fresh = int(time.time()) - 10
        async def _seed():
            async with app.state.sessionmaker() as s:
                s.add(AuditLog(ts=old, actor_ip="x", action="login_fail"))
                s.add(AuditLog(ts=fresh, actor_ip="x", action="login_success"))
                await s.commit()
        c.portal.call(_seed)

    with TestClient(app) as c2:
        async def _check():
            async with app.state.sessionmaker() as s:
                return [(await s.execute(select(AuditLog))).scalars().all()]
        (rows,) = c2.portal.call(_check)
        assert all(r.ts > int(time.time()) - 30 * 86400 for r in rows)
