from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from myphoto.main import build_app


@pytest.fixture
def client_with_gallery(tmp_path, capsys):
    photos = tmp_path / "photos"
    photos.mkdir()
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        gid = c.post("/api/admin/galleries", json={"name": "G"}).json()["id"]
        yield c, gid, photos, pw


def test_add_root(client_with_gallery):
    c, gid, photos, _ = client_with_gallery
    r = c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": str(photos),
    })
    assert r.status_code == 201
    data = r.json()
    assert data["label"] == "R"
    assert data["absolute_path"] == str(photos.resolve())
    assert data["enabled"] is True


def test_add_root_bad_path(client_with_gallery):
    c, gid, _, _ = client_with_gallery
    r = c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": "/nonexistent/path",
    })
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_not_readable"


def test_add_duplicate_root_conflict(client_with_gallery):
    c, gid, photos, _ = client_with_gallery
    c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R1", "absolute_path": str(photos),
    })
    r = c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R2", "absolute_path": str(photos),
    })
    assert r.status_code == 409


def test_add_root_nonexistent_gallery(client_with_gallery):
    c, _, photos, _ = client_with_gallery
    r = c.post("/api/admin/galleries/999/roots", json={
        "label": "R", "absolute_path": str(photos),
    })
    assert r.status_code == 404


def test_update_root_label(client_with_gallery):
    c, gid, photos, _ = client_with_gallery
    rid = c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "Old", "absolute_path": str(photos),
    }).json()["id"]
    r = c.patch(f"/api/admin/galleries/{gid}/roots/{rid}", json={"label": "New"})
    assert r.status_code == 200
    assert r.json()["label"] == "New"


def test_update_root_enabled_toggle(client_with_gallery):
    c, gid, photos, _ = client_with_gallery
    rid = c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": str(photos),
    }).json()["id"]
    r = c.patch(f"/api/admin/galleries/{gid}/roots/{rid}", json={"enabled": 0})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_update_nonexistent_root_404(client_with_gallery):
    c, gid, _, _ = client_with_gallery
    r = c.patch(f"/api/admin/galleries/{gid}/roots/999", json={"label": "X"})
    assert r.status_code == 404


def test_delete_root(client_with_gallery):
    c, gid, photos, _ = client_with_gallery
    rid = c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": str(photos),
    }).json()["id"]
    r = c.delete(f"/api/admin/galleries/{gid}/roots/{rid}")
    assert r.status_code == 204


def test_delete_nonexistent_root_404(client_with_gallery):
    c, gid, _, _ = client_with_gallery
    r = c.delete(f"/api/admin/galleries/{gid}/roots/999")
    assert r.status_code == 404


def test_rescan_root(client_with_gallery):
    c, gid, photos, _ = client_with_gallery
    rid = c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": str(photos),
    }).json()["id"]

    # Wait for the initial scan (triggered by root creation) to finish
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        sr = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status")
        if sr.json()["status"] == "idle":
            break
        time.sleep(0.2)

    r = c.post(f"/api/admin/galleries/{gid}/roots/{rid}/rescan")
    assert r.status_code == 200
    assert r.json()["status"] == "queued"


def test_scan_status(client_with_gallery):
    c, gid, photos, _ = client_with_gallery
    rid = c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": str(photos),
    }).json()["id"]
    r = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status")
    assert r.status_code == 200
    assert "status" in r.json()
    assert "last_scan_at" in r.json()


def test_root_not_in_wrong_gallery(client_with_gallery):
    c, gid, photos, _ = client_with_gallery
    rid = c.post(f"/api/admin/galleries/{gid}/roots", json={
        "label": "R", "absolute_path": str(photos),
    }).json()["id"]
    gid2 = c.post("/api/admin/galleries", json={"name": "G2"}).json()["id"]
    r = c.get(f"/api/admin/galleries/{gid2}/roots/{rid}/scan-status")
    assert r.status_code == 404
