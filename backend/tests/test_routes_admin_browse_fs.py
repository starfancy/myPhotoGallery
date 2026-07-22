from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from myphoto.main import build_app


@pytest.fixture
def client_as_admin(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app, client=("127.0.0.1", 12345)) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        yield c


def test_browse_fs_lists_subdirectories(client_as_admin, tmp_path):
    (tmp_path / "sub_a").mkdir()
    (tmp_path / "sub_b").mkdir()
    r = client_as_admin.post("/api/admin/browse-fs", json={"path": str(tmp_path)})
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == str(tmp_path)
    assert data["truncated"] is False
    names = [e["name"] for e in data["entries"]]
    assert "sub_a" in names
    assert "sub_b" in names
    for e in data["entries"]:
        assert e["is_root"] is False


def test_browse_fs_excludes_files(client_as_admin, tmp_path):
    (tmp_path / "sub_dir").mkdir()
    (tmp_path / "regular.txt").write_text("hi")
    r = client_as_admin.post("/api/admin/browse-fs", json={"path": str(tmp_path)})
    assert r.status_code == 200
    names = [e["name"] for e in r.json()["entries"]]
    assert "sub_dir" in names
    assert "regular.txt" not in names


def test_browse_fs_skips_hidden(client_as_admin, tmp_path):
    (tmp_path / "visible").mkdir()
    (tmp_path / ".hidden").mkdir()
    r = client_as_admin.post("/api/admin/browse-fs", json={"path": str(tmp_path)})
    assert r.status_code == 200
    names = [e["name"] for e in r.json()["entries"]]
    assert "visible" in names
    assert ".hidden" not in names


def test_browse_fs_rejects_double_dot(client_as_admin, tmp_path):
    (tmp_path / "sub").mkdir()
    r = client_as_admin.post(
        "/api/admin/browse-fs",
        json={"path": f"{tmp_path}/sub/.."},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_browse_fs_nonexistent_returns_400(client_as_admin, tmp_path):
    r = client_as_admin.post(
        "/api/admin/browse-fs",
        json={"path": str(tmp_path / "does_not_exist")},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_not_readable"


def test_browse_fs_default_returns_root(client_as_admin):
    r = client_as_admin.post("/api/admin/browse-fs", json={"path": ""})
    assert r.status_code == 200
    data = r.json()
    if sys.platform == "win32":
        # Windows: drive letters, path == ""
        assert data["path"] == ""
        for e in data["entries"]:
            assert e["is_root"] is True
            # e.g. "C:" as name, "C:\\" as path
            assert re.fullmatch(r"[A-Z]:", e["name"])
    else:
        assert data["path"] == "/"
        for e in data["entries"]:
            assert e["is_root"] is False


def test_browse_fs_omitted_path_treated_as_root(client_as_admin):
    r = client_as_admin.post("/api/admin/browse-fs", json={})
    assert r.status_code == 200


def test_browse_fs_unauthenticated_returns_401(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app, client=("127.0.0.1", 12345)) as c:
        capsys.readouterr()  # drain admin password print
        r = c.post("/api/admin/browse-fs", json={"path": str(tmp_path)})
    assert r.status_code == 401


def test_browse_fs_non_lan_ip_returns_403(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app, client=("8.8.8.8", 12345)) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        # Login from non-LAN is allowed (login doesn't require LAN)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        r = c.post("/api/admin/browse-fs", json={"path": str(tmp_path)})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "admin_fs_lan_only"


def test_browse_fs_writes_fs_browse_audit(client_as_admin, tmp_path):
    from sqlalchemy import select

    from myphoto.models import AuditLog

    (tmp_path / "sub").mkdir()
    app = client_as_admin.app
    r = client_as_admin.post("/api/admin/browse-fs", json={"path": str(tmp_path)})
    assert r.status_code == 200

    async def _fetch():
        sm = app.state.sessionmaker
        async with sm() as s:
            rows = (
                await s.execute(
                    select(AuditLog).where(AuditLog.action == "fs_browse")
                )
            ).scalars().all()
            return rows

    rows = client_as_admin.portal.call(_fetch)
    assert len(rows) >= 1
    assert rows[-1].target == str(tmp_path)
    assert rows[-1].actor_ip == "127.0.0.1"


def test_browse_fs_rejects_backslash_dotdot(client_as_admin, tmp_path):
    r = client_as_admin.post(
        "/api/admin/browse-fs",
        json={"path": r"C:\Users\..\Windows"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_browse_fs_skips_symlink(client_as_admin, tmp_path):
    (tmp_path / "real").mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(tmp_path / "real", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not supported in this environment")
    r = client_as_admin.post("/api/admin/browse-fs", json={"path": str(tmp_path)})
    assert r.status_code == 200
    names = [e["name"] for e in r.json()["entries"]]
    assert "real" in names
    assert "link" not in names


def test_browse_fs_truncates_beyond_cap(client_as_admin, tmp_path, monkeypatch):
    from myphoto import routes_admin

    monkeypatch.setattr(routes_admin, "BROWSE_FS_MAX_ENTRIES", 3)
    for i in range(5):
        (tmp_path / f"dir_{i}").mkdir()

    r = client_as_admin.post("/api/admin/browse-fs", json={"path": str(tmp_path)})
    assert r.status_code == 200
    data = r.json()
    assert data["truncated"] is True
    assert len(data["entries"]) == 3


def test_browse_fs_exact_cap_not_truncated(client_as_admin, tmp_path, monkeypatch):
    from myphoto import routes_admin

    monkeypatch.setattr(routes_admin, "BROWSE_FS_MAX_ENTRIES", 3)
    for i in range(3):
        (tmp_path / f"dir_{i}").mkdir()

    r = client_as_admin.post("/api/admin/browse-fs", json={"path": str(tmp_path)})
    assert r.status_code == 200
    data = r.json()
    assert data["truncated"] is False
    assert len(data["entries"]) == 3


def test_browse_fs_response_has_no_store_header(client_as_admin, tmp_path):
    r = client_as_admin.post("/api/admin/browse-fs", json={"path": str(tmp_path)})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


def test_browse_fs_failed_call_still_audits(client_as_admin, tmp_path):
    from sqlalchemy import select

    from myphoto.models import AuditLog

    app = client_as_admin.app
    bad_path = str(tmp_path / "nope")
    r = client_as_admin.post("/api/admin/browse-fs", json={"path": bad_path})
    assert r.status_code == 400

    async def _fetch():
        sm = app.state.sessionmaker
        async with sm() as s:
            rows = (
                await s.execute(
                    select(AuditLog)
                    .where(AuditLog.action == "fs_browse")
                    .order_by(AuditLog.id.desc())
                )
            ).scalars().all()
            return rows

    rows = client_as_admin.portal.call(_fetch)
    assert len(rows) >= 1
    latest = rows[0]
    assert latest.target == bad_path
    assert "error=" in (latest.detail or "")
