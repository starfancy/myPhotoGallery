"""Tests for P4 /api/admin/users* endpoints."""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from myphoto.main import build_app
from myphoto.models import User, UserGallery


async def _add_viewer(app, username="viewer", password="viewerpw",
                     role="viewer", access_scope="remote_allowed",
                     enabled=1, gallery_ids=None):
    from myphoto.security import hash_password

    async with app.state.sessionmaker() as s:
        u = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
            access_scope=access_scope,
            enabled=enabled,
            created_at=int(time.time()),
        )
        s.add(u)
        await s.flush()
        if gallery_ids:
            for gid in gallery_ids:
                s.add(UserGallery(user_id=u.id, gallery_id=gid, granted_at=int(time.time())))
        await s.commit()
        return u.id


async def _add_viewer_with_gids(app, username, gids):
    """portal.call 兼容版：gids 是位置参数。"""
    return await _add_viewer(app, username, gallery_ids=gids)


async def _add_gallery(app, name):
    from myphoto.models import Gallery

    async with app.state.sessionmaker() as s:
        g = Gallery(name=name, created_at=int(time.time()))
        s.add(g)
        await s.commit()
        return g.id


async def _get_user(app, uid):
    async with app.state.sessionmaker() as s:
        return await s.get(User, uid)


async def _count_user_galleries(app, uid):
    async with app.state.sessionmaker() as s:
        rows = (await s.execute(
            select(UserGallery).where(UserGallery.user_id == uid)
        )).scalars().all()
        return len(rows)


# ---- fixture ----

@pytest.fixture
def admin_client(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        yield c, app, pw


# ---- list users ----

def test_list_users_includes_admin(admin_client):
    c, _, _ = admin_client
    r = c.get("/api/admin/users")
    assert r.status_code == 200
    data = r.json()
    assert any(u["username"] == "admin" and u["role"] == "admin" for u in data)


def test_list_users_includes_viewer(admin_client):
    c, app, _ = admin_client
    c.portal.call(_add_viewer, app, "v1")
    r = c.get("/api/admin/users")
    assert r.status_code == 200
    data = r.json()
    viewers = [u for u in data if u["username"] == "v1"]
    assert len(viewers) == 1
    assert viewers[0]["role"] == "viewer"
    assert viewers[0]["access_scope"] == "remote_allowed"


def test_list_users_viewer_gallery_count(admin_client):
    c, app, _ = admin_client
    gid = c.portal.call(_add_gallery, app, "G")
    c.portal.call(_add_viewer_with_gids, app, "v2", [gid])
    r = c.get("/api/admin/users")
    assert r.status_code == 200
    v = next(u for u in r.json() if u["username"] == "v2")
    assert v["gallery_count"] == 1


def test_list_users_admin_gallery_count_is_total(admin_client):
    c, app, _ = admin_client
    c.portal.call(_add_gallery, app, "G1")
    c.portal.call(_add_gallery, app, "G2")
    r = c.get("/api/admin/users")
    assert r.status_code == 200
    admin_u = next(u for u in r.json() if u["username"] == "admin")
    assert admin_u["gallery_count"] == 2


def test_list_users_requires_admin(admin_client):
    c, app, _ = admin_client
    c.portal.call(_add_viewer, app, "v3")
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "v3", "password": "viewerpw"})
    r = c.get("/api/admin/users")
    assert r.status_code == 403


def test_list_users_requires_auth(tmp_path):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        r = c.get("/api/admin/users")
        assert r.status_code == 401


# ---- create user ----

def test_create_viewer_success(admin_client):
    c, app, _ = admin_client
    r = c.post("/api/admin/users", json={
        "username": "newviewer",
        "role": "viewer",
        "access_scope": "lan_only",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "newviewer"
    assert body["role"] == "viewer"
    assert body["access_scope"] == "lan_only"
    assert "initial_password" in body
    assert len(body["initial_password"]) == 12


def test_create_user_with_explicit_password(admin_client):
    c, app, _ = admin_client
    r = c.post("/api/admin/users", json={
        "username": "withpw",
        "password": "explicit123",
        "role": "admin",
        "access_scope": "remote_allowed",
    })
    assert r.status_code == 201
    body = r.json()
    assert "initial_password" not in body


def test_create_viewer_with_gallery_ids(admin_client):
    c, app, _ = admin_client
    gid = c.portal.call(_add_gallery, app, "GX")
    r = c.post("/api/admin/users", json={
        "username": "vwithg",
        "role": "viewer",
        "access_scope": "remote_allowed",
        "gallery_ids": [gid],
    })
    assert r.status_code == 201
    assert r.json()["gallery_ids"] == [gid]
    # verify DB
    uid = r.json()["id"]
    count = c.portal.call(_count_user_galleries, app, uid)
    assert count == 1


def test_create_admin_ignores_gallery_ids(admin_client):
    c, app, _ = admin_client
    gid = c.portal.call(_add_gallery, app, "GY")
    r = c.post("/api/admin/users", json={
        "username": "admin2",
        "password": "adminpw123",
        "role": "admin",
        "access_scope": "remote_allowed",
        "gallery_ids": [gid],
    })
    assert r.status_code == 201
    uid = r.json()["id"]
    count = c.portal.call(_count_user_galleries, app, uid)
    assert count == 0  # admin doesn't get user_galleries rows


def test_create_duplicate_username_409(admin_client):
    c, app, _ = admin_client
    c.portal.call(_add_viewer, app, "dup")
    r = c.post("/api/admin/users", json={
        "username": "dup",
        "role": "viewer",
        "access_scope": "lan_only",
    })
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_create_requires_admin(admin_client):
    c, app, _ = admin_client
    c.portal.call(_add_viewer, app, "v4")
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "v4", "password": "viewerpw"})
    r = c.post("/api/admin/users", json={
        "username": "nope",
        "role": "viewer",
        "access_scope": "lan_only",
    })
    assert r.status_code == 403


# ---- get user ----

def test_get_user_detail(admin_client):
    c, app, _ = admin_client
    gid = c.portal.call(_add_gallery, app, "GZ")
    uid = c.portal.call(_add_viewer_with_gids, app, "vdetail", [gid])
    r = c.get(f"/api/admin/users/{uid}")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "vdetail"
    assert body["role"] == "viewer"
    assert body["gallery_ids"] == [gid]


def test_get_admin_returns_all_gallery_ids(admin_client):
    c, app, _ = admin_client
    g1 = c.portal.call(_add_gallery, app, "GA")
    g2 = c.portal.call(_add_gallery, app, "GB")
    # admin id is 1
    r = c.get("/api/admin/users/1")
    assert r.status_code == 200
    assert set(r.json()["gallery_ids"]) == {g1, g2}


def test_get_user_404(admin_client):
    c, _, _ = admin_client
    r = c.get("/api/admin/users/99999")
    assert r.status_code == 404


def test_get_user_requires_admin(admin_client):
    c, app, _ = admin_client
    c.portal.call(_add_viewer, app, "v5")
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "v5", "password": "viewerpw"})
    r = c.get("/api/admin/users/1")
    assert r.status_code == 403


# ---- update user ----

def test_update_user_role(admin_client):
    c, app, _ = admin_client
    uid = c.portal.call(_add_viewer, app, "topromote")
    r = c.patch(f"/api/admin/users/{uid}", json={"role": "admin"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_update_user_access_scope(admin_client):
    c, app, _ = admin_client
    uid = c.portal.call(_add_viewer, app, "tolock")
    r = c.patch(f"/api/admin/users/{uid}", json={"access_scope": "lan_only"})
    assert r.status_code == 200
    assert r.json()["access_scope"] == "lan_only"


def test_update_user_disable(admin_client):
    c, app, _ = admin_client
    uid = c.portal.call(_add_viewer, app, "todisable")
    r = c.patch(f"/api/admin/users/{uid}", json={"enabled": 0})
    assert r.status_code == 200
    assert r.json()["enabled"] == 0
    # verify disabled user can't login
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "todisable", "password": "viewerpw"})
    assert r.status_code == 401


def test_update_user_gallery_ids_sync(admin_client):
    c, app, _ = admin_client
    g1 = c.portal.call(_add_gallery, app, "sync1")
    g2 = c.portal.call(_add_gallery, app, "sync2")
    uid = c.portal.call(_add_viewer_with_gids, app, "vsync", [g1])

    # replace with [g2]
    r = c.patch(f"/api/admin/users/{uid}", json={"gallery_ids": [g2]})
    assert r.status_code == 200
    assert r.json()["gallery_ids"] == [g2]
    count = c.portal.call(_count_user_galleries, app, uid)
    assert count == 1


def test_update_last_admin_role_rejected(admin_client):
    """不能把最后一个 admin 降级为 viewer（通过降级 admin2，保留 admin1 活跃）。"""
    c, app, _ = admin_client
    # 创建 admin2，然后尝试把 admin2 降级 → 应成功（admin1 仍是活跃 admin）
    r = c.post("/api/admin/users", json={
        "username": "admin2", "password": "admin2pw!!",
        "role": "admin", "access_scope": "remote_allowed",
    })
    assert r.status_code == 201
    admin2_id = r.json()["id"]

    # 降级 admin2 → 成功（admin1 仍在）
    r = c.patch(f"/api/admin/users/{admin2_id}", json={"role": "viewer"})
    assert r.status_code == 200

    # 现在只剩 admin1 是活跃 admin，降级 admin1 → 应 409
    r = c.patch("/api/admin/users/1", json={"role": "viewer"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "last_admin_protected"


def test_update_last_admin_disable_rejected(admin_client):
    """不能禁用最后一个活跃 admin。"""
    c, _, _ = admin_client
    r = c.patch("/api/admin/users/1", json={"enabled": 0})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "last_admin_protected"


def test_update_user_404(admin_client):
    c, _, _ = admin_client
    r = c.patch("/api/admin/users/99999", json={"role": "viewer"})
    assert r.status_code == 404


# ---- reset password ----

def test_reset_password_explicit(admin_client):
    c, app, _ = admin_client
    uid = c.portal.call(_add_viewer, app, "resetme")
    r = c.post(f"/api/admin/users/{uid}/reset-password", json={
        "new_password": "newpass123",
    })
    assert r.status_code == 200
    assert r.json()["new_password"] == "newpass123"
    # verify new password works
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "resetme", "password": "newpass123"})
    assert r.status_code == 200


def test_reset_password_auto_generated(admin_client):
    c, app, _ = admin_client
    uid = c.portal.call(_add_viewer, app, "autopw")
    r = c.post(f"/api/admin/users/{uid}/reset-password", json={})
    assert r.status_code == 200
    pw = r.json()["new_password"]
    assert len(pw) == 12
    # verify new password works
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "autopw", "password": pw})
    assert r.status_code == 200


def test_reset_password_404(admin_client):
    c, _, _ = admin_client
    r = c.post("/api/admin/users/99999/reset-password", json={"new_password": "x" * 8})
    assert r.status_code == 404


# ---- delete user ----

def test_delete_viewer_success(admin_client):
    c, app, _ = admin_client
    uid = c.portal.call(_add_viewer, app, "todelete")
    r = c.delete(f"/api/admin/users/{uid}")
    assert r.status_code == 204
    # verify user is gone
    user = c.portal.call(_get_user, app, uid)
    assert user is None


def test_delete_last_admin_rejected(admin_client):
    """不能删除最后一个活跃 admin。"""
    c, _, _ = admin_client
    r = c.delete("/api/admin/users/1")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "last_admin_protected"


def test_delete_non_last_admin_succeeds(admin_client):
    """有两个 admin 时可以删除其中之一。"""
    c, app, _ = admin_client
    r = c.post("/api/admin/users", json={
        "username": "admin_extra", "password": "extra123!",
        "role": "admin", "access_scope": "remote_allowed",
    })
    assert r.status_code == 201
    extra_id = r.json()["id"]

    # 删除初始 admin 应该成功（还有 admin_extra）
    r = c.delete("/api/admin/users/1")
    assert r.status_code == 204


def test_delete_404(admin_client):
    c, _, _ = admin_client
    r = c.delete("/api/admin/users/99999")
    assert r.status_code == 404


# ---- edge cases ----

def test_admin_can_disable_self_when_another_admin_exists(admin_client):
    """admin 可以禁用自己，只要有另一个活跃 admin。"""
    c, app, _ = admin_client
    r = c.post("/api/admin/users", json={
        "username": "admin_backup", "password": "backup12!",
        "role": "admin", "access_scope": "remote_allowed",
    })
    assert r.status_code == 201

    # admin(uid=1) 禁用自己 → 成功（admin_backup 还在）
    r = c.patch("/api/admin/users/1", json={"enabled": 0})
    assert r.status_code == 200
    assert r.json()["enabled"] == 0


def test_admin_promoting_viewer_preserves_active_count(admin_client):
    """将 viewer 提升为 admin 后，最后一个 admin 保护仍需生效。"""
    c, app, _ = admin_client
    uid = c.portal.call(_add_viewer, app, "future_admin")
    # 提升为 admin
    r = c.patch(f"/api/admin/users/{uid}", json={"role": "admin"})
    assert r.status_code == 200
    # 现在有 2 个 admin，删除初始 admin 应该成功
    r = c.delete("/api/admin/users/1")
    assert r.status_code == 204
