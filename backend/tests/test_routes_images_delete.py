"""Tests for [routes_images.py]: DELETE /api/images/{id}, POST /api/images/batch-delete."""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient
from sqlalchemy import select

from myphoto.main import build_app
from myphoto.models import AuditLog, Folder, Image, Trash


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (40, 30), (10, 20, 30)).save(p, "JPEG")


async def _seed(app, photos):
    from myphoto.models import Gallery, GalleryRoot

    async with app.state.sessionmaker() as s:
        g = Gallery(name="G", created_at=int(time.time()))
        s.add(g)
        await s.flush()
        r = GalleryRoot(
            gallery_id=g.id,
            label="R",
            absolute_path=str(photos.resolve()),
            enabled=1,
        )
        s.add(r)
        await s.commit()
        await s.refresh(r)
        return g.id, r.id


async def _scan(app, rid):
    await app.state.scanner.scan_root_now(rid)


async def _add_viewer(app):
    """建一个 viewer 账号；返回 (username, password)。"""
    from myphoto.models import User
    from myphoto.security import hash_password

    async with app.state.sessionmaker() as s:
        s.add(User(
            username="viewer",
            password_hash=hash_password("viewerpw"),
            role="viewer",
            access_scope="lan_only",
            enabled=1,
            created_at=int(time.time()),
        ))
        await s.commit()
    return "viewer", "viewerpw"


async def _all_folders(app):
    async with app.state.sessionmaker() as s:
        return {f.relative_path: f for f in (
            await s.execute(select(Folder))
        ).scalars().all()}


async def _get_trash(app):
    async with app.state.sessionmaker() as s:
        return (await s.execute(select(Trash))).scalars().all()


async def _get_image_by_filename(app, filename):
    async with app.state.sessionmaker() as s:
        return (await s.execute(
            select(Image).where(Image.filename == filename)
        )).scalar_one_or_none()


async def _get_last_audit(app, action):
    async with app.state.sessionmaker() as s:
        rows = (await s.execute(
            select(AuditLog).where(AuditLog.action == action)
            .order_by(AuditLog.id.desc()).limit(1)
        )).scalars().all()
        return rows[0] if rows else None


@pytest.fixture
def admin_client(tmp_path, capsys):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    _jpg(photos / "sub" / "b.jpg")
    _jpg(photos / "sub" / "c.jpg")
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        gid, rid = c.portal.call(_seed, app, photos)
        c.portal.call(_scan, app, rid)
        yield c, app, gid, rid, photos


# ---------- DELETE /api/images/{id} ----------


def test_delete_moves_file_to_trash_and_updates_db(admin_client):
    c, app, gid, rid, photos = admin_client
    img = c.portal.call(_get_image_by_filename, app, "a.jpg")
    assert img is not None
    image_id = img.id

    r = c.delete(f"/api/images/{image_id}")
    assert r.status_code == 204, r.text

    # 原文件消失，DB image 行消失
    assert not (photos / "a.jpg").exists()
    assert c.portal.call(_get_image_by_filename, app, "a.jpg") is None

    # trash 表新增一行；文件移到 .trash/{gallery_id}/{root_id}/YYYYMMDD/
    trashes = c.portal.call(_get_trash, app)
    assert len(trashes) == 1
    t = trashes[0]
    assert t.original_relative_path == "a.jpg"
    assert t.trash_relative_path.startswith(f".trash/{gid}/{rid}/")
    assert t.trash_relative_path.endswith("/a.jpg")
    assert (photos / t.trash_relative_path).exists()
    assert t.sha1 == img.sha1
    assert t.purge_after > t.deleted_at

    # 目录 count 更新：root folder image_count 1->0，descendant_count 3->2
    folders = c.portal.call(_all_folders, app)
    assert folders[""].image_count == 0
    assert folders[""].descendant_count == 2
    assert folders["sub"].image_count == 2
    assert folders["sub"].descendant_count == 2

    # 审计写入
    audit = c.portal.call(_get_last_audit, app, "image_delete")
    assert audit is not None
    assert f"image:{image_id}" == audit.target
    assert "trash=" in (audit.detail or "")


def test_delete_returns_404_for_missing_image(admin_client):
    c, *_ = admin_client
    r = c.delete("/api/images/9999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_delete_disambiguates_name_when_target_exists(admin_client):
    """同一天连续删两个同名文件时 trash 目标不重名。"""
    c, app, gid, rid, photos = admin_client
    # 两张同名 a.jpg 无法建（unique constraint），构造两张同名 b.jpg 也不行；
    # 走另一种路径：先删 sub/b.jpg，再手动新建一个同名文件重新入库删掉它。
    b1 = c.portal.call(_get_image_by_filename, app, "b.jpg")
    r1 = c.delete(f"/api/images/{b1.id}")
    assert r1.status_code == 204

    # 再新建一张 b.jpg 到 sub/ 并 rescan，然后删
    _jpg(photos / "sub" / "b.jpg")
    c.portal.call(_scan, app, rid)
    b2 = c.portal.call(_get_image_by_filename, app, "b.jpg")
    r2 = c.delete(f"/api/images/{b2.id}")
    assert r2.status_code == 204

    trashes = c.portal.call(_get_trash, app)
    assert len(trashes) == 2
    paths = [t.trash_relative_path for t in trashes]
    # 两条路径不重复
    assert len(set(paths)) == 2


def test_delete_forbidden_for_viewer(admin_client):
    c, app, *_ = admin_client
    # 建 viewer 账号并登录（先登出 admin）
    c.portal.call(_add_viewer, app)
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "viewer", "password": "viewerpw"})
    assert r.status_code == 200

    img = c.portal.call(_get_image_by_filename, app, "a.jpg")
    r = c.delete(f"/api/images/{img.id}")
    assert r.status_code == 403


def test_delete_requires_auth(tmp_path):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        r = c.delete("/api/images/1")
        assert r.status_code == 401


# ---------- POST /api/images/batch-delete ----------


def test_batch_delete_moves_all_and_reports_deleted(admin_client):
    c, app, gid, rid, photos = admin_client
    ids = []
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        img = c.portal.call(_get_image_by_filename, app, name)
        ids.append(img.id)

    r = c.post("/api/images/batch-delete", json={"image_ids": ids})
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(body["deleted"]) == sorted(ids)
    assert body["failed"] == []

    # 所有 3 张移到 trash，images 表清空
    trashes = c.portal.call(_get_trash, app)
    assert len(trashes) == 3
    folders = c.portal.call(_all_folders, app)
    assert folders[""].descendant_count == 0
    assert folders["sub"].image_count == 0


def test_batch_delete_partial_reports_failed(admin_client):
    c, app, *_ = admin_client
    ok = c.portal.call(_get_image_by_filename, app, "a.jpg").id
    r = c.post("/api/images/batch-delete", json={"image_ids": [ok, 999999]})
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == [ok]
    assert body["failed"] == [{"id": 999999, "error": "not_found"}]


def test_batch_delete_over_limit_rejected(admin_client):
    c, *_ = admin_client
    r = c.post("/api/images/batch-delete", json={"image_ids": list(range(1, 502))})
    assert r.status_code == 422


def test_batch_delete_empty_rejected(admin_client):
    c, *_ = admin_client
    r = c.post("/api/images/batch-delete", json={"image_ids": []})
    assert r.status_code == 422


def test_batch_delete_forbidden_for_viewer(admin_client):
    c, app, *_ = admin_client
    c.portal.call(_add_viewer, app)
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "viewer", "password": "viewerpw"})
    r = c.post("/api/images/batch-delete", json={"image_ids": [1]})
    assert r.status_code == 403
