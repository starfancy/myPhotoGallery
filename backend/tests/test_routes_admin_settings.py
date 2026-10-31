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
        "download_batch_limit": 100,
        "audit_retention_days": 180,
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
