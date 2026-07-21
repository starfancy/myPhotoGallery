from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from myphoto.main import build_app


@pytest.fixture
def client_as_admin(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        yield c, pw


def test_list_galleries_empty(client_as_admin):
    c, _ = client_as_admin
    r = c.get("/api/admin/galleries")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.json() == []


def test_create_gallery(client_as_admin):
    c, _ = client_as_admin
    r = c.post("/api/admin/galleries", json={"name": "Test", "description": "desc"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Test"
    assert data["description"] == "desc"
    assert data["id"] >= 1


def test_create_duplicate_gallery_conflict(client_as_admin):
    c, _ = client_as_admin
    c.post("/api/admin/galleries", json={"name": "Dup"})
    r = c.post("/api/admin/galleries", json={"name": "Dup"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_update_gallery(client_as_admin):
    c, _ = client_as_admin
    gid = c.post("/api/admin/galleries", json={"name": "Old"}).json()["id"]
    r = c.patch(f"/api/admin/galleries/{gid}", json={"name": "New"})
    assert r.status_code == 200
    assert r.json()["name"] == "New"


def test_update_nonexistent_gallery_404(client_as_admin):
    c, _ = client_as_admin
    r = c.patch("/api/admin/galleries/999", json={"name": "X"})
    assert r.status_code == 404


def test_delete_gallery(client_as_admin):
    c, _ = client_as_admin
    gid = c.post("/api/admin/galleries", json={"name": "DelMe"}).json()["id"]
    r = c.delete(f"/api/admin/galleries/{gid}")
    assert r.status_code == 204
    assert c.get("/api/admin/galleries").json() == []


def test_delete_nonexistent_gallery_404(client_as_admin):
    c, _ = client_as_admin
    r = c.delete("/api/admin/galleries/999")
    assert r.status_code == 404


def test_non_admin_blocked(client_as_admin):
    c, _ = client_as_admin
    c.post("/api/auth/logout")
    r = c.get("/api/admin/galleries")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_list_galleries_with_counts(client_as_admin):
    c, _ = client_as_admin
    c.post("/api/admin/galleries", json={"name": "G1"})
    c.post("/api/admin/galleries", json={"name": "G2"})
    r = c.get("/api/admin/galleries")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert all("root_count" in g for g in data)
    assert all("image_count" in g for g in data)


def test_gallery_name_conflict_on_update(client_as_admin):
    c, _ = client_as_admin
    c.post("/api/admin/galleries", json={"name": "First"})
    gid2 = c.post("/api/admin/galleries", json={"name": "Second"}).json()["id"]
    r = c.patch(f"/api/admin/galleries/{gid2}", json={"name": "First"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_update_description_only(client_as_admin):
    c, _ = client_as_admin
    gid = c.post("/api/admin/galleries", json={"name": "DescTest"}).json()["id"]
    r = c.patch(f"/api/admin/galleries/{gid}", json={"description": "new desc"})
    assert r.status_code == 200
    assert r.json()["name"] == "DescTest"
    assert r.json()["description"] == "new desc"


def test_create_gallery_without_description(client_as_admin):
    c, _ = client_as_admin
    r = c.post("/api/admin/galleries", json={"name": "NoDesc"})
    assert r.status_code == 201
    assert r.json()["description"] is None
