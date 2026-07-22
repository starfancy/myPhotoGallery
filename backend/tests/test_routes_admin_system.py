from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from myphoto.main import build_app
from myphoto.models import AuditLog


@pytest.fixture
def client_as_admin(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        yield c, tmp_path, pw


@pytest.fixture
def client_unauthed(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        capsys.readouterr()
        yield c


# ---- GET /api/admin/status ----


def test_status_shape_empty(client_as_admin):
    c, _, _ = client_as_admin
    r = c.get("/api/admin/status")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert set(data.keys()) == {"stats", "scan_statuses", "recent_audit"}
    stats = data["stats"]
    assert stats["images"] == 0
    assert stats["galleries"] == 0
    assert stats["roots"] == 0
    assert stats["users"] >= 1  # bootstrap admin
    assert data["scan_statuses"] == []
    # recent_audit will include the login_success not yet — audit wiring is P2-7.
    assert isinstance(data["recent_audit"], list)


def test_status_reflects_created_gallery_and_root(client_as_admin):
    c, tmp_path, _ = client_as_admin
    photos = tmp_path / "photos"
    photos.mkdir()
    gid = c.post("/api/admin/galleries", json={"name": "G"}).json()["id"]
    c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": str(photos),
    })

    r = c.get("/api/admin/status")
    assert r.status_code == 200
    data = r.json()
    assert data["stats"]["galleries"] == 1
    assert data["stats"]["roots"] == 1
    assert len(data["scan_statuses"]) == 1
    s = data["scan_statuses"][0]
    assert s["gallery_id"] == gid
    assert s["label"] == "R"
    assert s["enabled"] is True
    assert s["status"] in ("idle", "queued", "running")


def test_status_non_admin_401(client_unauthed):
    r = client_unauthed.get("/api/admin/status")
    assert r.status_code == 401


def test_status_recent_audit_limited_to_20(client_as_admin):
    c, _, _ = client_as_admin
    app = c.app

    async def _seed(n):
        sm = app.state.sessionmaker
        async with sm() as s:
            for i in range(n):
                s.add(AuditLog(
                    ts=1_000_000 + i,
                    actor_user_id=1,
                    actor_ip="127.0.0.1",
                    action="login_success",
                    target=None,
                    detail=f"seed_{i}",
                ))
            await s.commit()

    c.portal.call(_seed, 30)
    r = c.get("/api/admin/status")
    assert r.status_code == 200
    assert len(r.json()["recent_audit"]) == 20
    # newest first: seed_29 should be at index 0
    assert r.json()["recent_audit"][0]["detail"] == "seed_29"


# ---- POST /api/admin/thumb-cache/purge ----


def test_thumb_cache_purge_removes_files(client_as_admin):
    c, tmp_path, _ = client_as_admin
    cache_dir = tmp_path / ".cache" / "thumbnails"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "aa").mkdir()
    (cache_dir / "aa" / "some.jpg").write_bytes(b"fake")

    r = c.post("/api/admin/thumb-cache/purge")
    assert r.status_code == 204
    # cache dir is recreated empty, not the old contents
    assert cache_dir.exists()
    assert list(cache_dir.iterdir()) == []


def test_thumb_cache_purge_when_dir_missing(client_as_admin):
    c, tmp_path, _ = client_as_admin
    cache_dir = tmp_path / ".cache" / "thumbnails"
    # Ensure it doesn't exist (fresh app may or may not have created it)
    import shutil
    if cache_dir.exists():
        shutil.rmtree(cache_dir)

    r = c.post("/api/admin/thumb-cache/purge")
    assert r.status_code == 204
    assert cache_dir.exists()  # recreated


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


def test_thumb_cache_purge_non_admin_401(client_unauthed):
    r = client_unauthed.post("/api/admin/thumb-cache/purge")
    assert r.status_code == 401


def test_thumb_cache_purge_refuses_symlink(client_as_admin):
    """Redline #1 guard: cache dir must not be a symlink."""
    import shutil as _shutil
    c, tmp_path, _ = client_as_admin
    cache_root = tmp_path / ".cache"
    cache_dir = cache_root / "thumbnails"
    if cache_dir.exists():
        _shutil.rmtree(cache_dir)
    # Replace thumbnails with a symlink pointing elsewhere.
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "sentinel.txt").write_text("do-not-delete")
    cache_root.mkdir(parents=True, exist_ok=True)
    try:
        cache_dir.symlink_to(other, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not supported in this environment")

    r = c.post("/api/admin/thumb-cache/purge")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"
    # Redline #1 held: sentinel outside the cache dir untouched.
    assert (other / "sentinel.txt").exists()


# ---- GET /api/admin/audit ----


def _seed_audits(client, rows):
    app = client.app

    async def _do():
        sm = app.state.sessionmaker
        async with sm() as s:
            # Wipe any pre-existing rows so tests can assert exact counts.
            await s.execute(delete(AuditLog))
            for row in rows:
                s.add(AuditLog(**row))
            await s.commit()

    client.portal.call(_do)


def test_audit_query_returns_newest_first(client_as_admin):
    c, _, _ = client_as_admin
    _seed_audits(c, [
        {"ts": 1000, "actor_user_id": 1, "actor_ip": "127.0.0.1",
         "action": "login_success", "target": None, "detail": "a"},
        {"ts": 2000, "actor_user_id": 1, "actor_ip": "127.0.0.1",
         "action": "login_success", "target": None, "detail": "b"},
        {"ts": 1500, "actor_user_id": 1, "actor_ip": "127.0.0.1",
         "action": "gallery_create", "target": "gallery:1", "detail": "c"},
    ])

    r = c.get("/api/admin/audit")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    tss = [e["ts"] for e in data["entries"]]
    assert tss == sorted(tss, reverse=True)
    assert data["next_cursor"] is None


def test_audit_query_filter_by_action(client_as_admin):
    c, _, _ = client_as_admin
    _seed_audits(c, [
        {"ts": 1000, "actor_user_id": 1, "actor_ip": "127.0.0.1",
         "action": "login_success", "target": None, "detail": None},
        {"ts": 2000, "actor_user_id": 1, "actor_ip": "127.0.0.1",
         "action": "gallery_create", "target": None, "detail": None},
    ])
    r = c.get("/api/admin/audit", params={"action": "login_success"})
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["action"] == "login_success"


def test_audit_query_filter_by_actor(client_as_admin):
    c, _, _ = client_as_admin
    _seed_audits(c, [
        {"ts": 1000, "actor_user_id": 1, "actor_ip": "127.0.0.1",
         "action": "login_success", "target": None, "detail": None},
        {"ts": 2000, "actor_user_id": 2, "actor_ip": "127.0.0.1",
         "action": "login_success", "target": None, "detail": None},
    ])
    r = c.get("/api/admin/audit", params={"actor": 2})
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["actor_user_id"] == 2


def test_audit_query_filter_by_ts_range(client_as_admin):
    c, _, _ = client_as_admin
    _seed_audits(c, [
        {"ts": ts, "actor_user_id": 1, "actor_ip": "127.0.0.1",
         "action": "login_success", "target": None, "detail": None}
        for ts in [500, 1000, 1500, 2000, 2500]
    ])
    r = c.get("/api/admin/audit", params={"from": 1000, "to": 2000})
    assert r.status_code == 200
    tss = [e["ts"] for e in r.json()["entries"]]
    assert set(tss) == {1000, 1500, 2000}


def test_audit_query_pagination_no_duplicates(client_as_admin):
    c, _, _ = client_as_admin
    # 25 rows, all same ts to stress the tie-breaker on id
    same_ts = [
        {"ts": 5000, "actor_user_id": 1, "actor_ip": "127.0.0.1",
         "action": "login_success", "target": None, "detail": f"row_{i}"}
        for i in range(25)
    ]
    _seed_audits(c, same_ts)

    seen: list[int] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict = {"limit": 10}
        if cursor is not None:
            params["cursor"] = cursor
        r = c.get("/api/admin/audit", params=params)
        assert r.status_code == 200
        data = r.json()
        for e in data["entries"]:
            seen.append(e["id"])
        cursor = data["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 25
    assert len(set(seen)) == 25  # no duplicates
    # newest first
    assert seen == sorted(seen, reverse=True)


def test_audit_query_pagination_across_ts_boundary(client_as_admin):
    c, _, _ = client_as_admin
    # Mix of ts values to check tuple cursor spans both dimensions.
    _seed_audits(c, [
        {"ts": ts, "actor_user_id": 1, "actor_ip": "127.0.0.1",
         "action": "login_success", "target": None, "detail": None}
        for ts in [1000, 1000, 2000, 2000, 3000, 3000, 4000]
    ])
    seen: list[int] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        r = c.get("/api/admin/audit", params=params)
        assert r.status_code == 200
        data = r.json()
        for e in data["entries"]:
            seen.append(e["id"])
        cursor = data["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 7
    assert len(set(seen)) == 7


def test_audit_query_bad_cursor_returns_400(client_as_admin):
    c, _, _ = client_as_admin
    r = c.get("/api/admin/audit", params={"cursor": "not-a-cursor"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_audit_query_cursor_rejects_pep515_underscores(client_as_admin):
    """int() accepts 2_3 as 23; guard rejects cursors with extra underscores."""
    c, _, _ = client_as_admin
    r = c.get("/api/admin/audit", params={"cursor": "100_2_3"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_audit_query_limit_validation(client_as_admin):
    c, _, _ = client_as_admin
    r = c.get("/api/admin/audit", params={"limit": 0})
    assert r.status_code == 422
    r = c.get("/api/admin/audit", params={"limit": 10000})
    assert r.status_code == 422


def test_audit_query_non_admin_401(client_unauthed):
    r = client_unauthed.get("/api/admin/audit")
    assert r.status_code == 401
