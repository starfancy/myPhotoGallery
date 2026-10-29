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


def test_duplicate_exclusion_race_integrityerror_maps_to_409(env_client, monkeypatch):
    """Loser of a concurrent-create race: the pre-check SELECT misses but the
    INSERT hits uq_exclusion_path_per_root -> IntegrityError must surface as
    409 conflict, not 500, and must not trigger a rescan."""
    import myphoto.routes_admin as ra

    c, app, gid, rid, photos = env_client
    target = photos / "exports"
    target.mkdir()
    body = {"absolute_path": str(target)}
    assert c.post(_ex_url(gid, rid), json=body).status_code == 201

    # Deterministically blind only the duplicate pre-check. In this endpoint
    # select(Exclusion) with Exclusion as the sole entity is unique to the
    # dup lookup (_get_root_or_404 selects GalleryRoot; write_audit issues no
    # SELECT). A bare duck-typed statement is rejected by SQLAlchemy 2.0's
    # session.execute, so hand back a real, executable SELECT that is
    # guaranteed to return zero rows; the handler chains its own WHERE on top.
    real_select = ra.select

    def fake_select(*entities, **kw):
        if entities and entities[0] is ra.Exclusion:
            return real_select(ra.Exclusion).where(ra.Exclusion.id < 0)
        return real_select(*entities, **kw)

    monkeypatch.setattr(ra, "select", fake_select)

    rescans: list[int] = []
    real_request_rescan = app.state.scanner.request_rescan

    async def _spy_request_rescan(root_id):
        rescans.append(root_id)
        return await real_request_rescan(root_id)

    monkeypatch.setattr(app.state.scanner, "request_rescan", _spy_request_rescan)

    r = c.post(_ex_url(gid, rid), json=body)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "conflict"
    assert err["message"] == "this directory is already excluded"
    assert rescans == []


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
