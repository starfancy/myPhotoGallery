"""Tests for [routes_trash.py]: list/restore/batch-restore/delete-one/purge."""
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


async def _list_trash(app):
    async with app.state.sessionmaker() as s:
        return (await s.execute(select(Trash))).scalars().all()


async def _folders(app):
    async with app.state.sessionmaker() as s:
        return {f.relative_path: f for f in (
            await s.execute(select(Folder))
        ).scalars().all()}


async def _images(app):
    async with app.state.sessionmaker() as s:
        return (await s.execute(select(Image))).scalars().all()


async def _last_audit(app, action):
    async with app.state.sessionmaker() as s:
        rows = (await s.execute(
            select(AuditLog).where(AuditLog.action == action)
            .order_by(AuditLog.id.desc()).limit(1)
        )).scalars().all()
        return rows[0] if rows else None


async def _image_id(app, filename):
    async with app.state.sessionmaker() as s:
        r = (await s.execute(
            select(Image).where(Image.filename == filename)
        )).scalar_one_or_none()
        return r.id if r else None


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


def _delete_all_three(c, app):
    """辅助：把 3 张图都删到 trash，返回 trash ids（按 deleted_at_desc 顺序）。"""
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        image_id = c.portal.call(_image_id, app, name)
        r = c.delete(f"/api/images/{image_id}")
        assert r.status_code == 204
    trashes = c.portal.call(_list_trash, app)
    return sorted([t.id for t in trashes], reverse=True)


# ---------- GET /api/trash ----------


def test_list_trash_desc_and_filter(admin_client):
    c, app, gid, rid, _ = admin_client
    _delete_all_three(c, app)

    r = c.get("/api/trash")
    assert r.status_code == 200
    body = r.json()
    assert len(body["entries"]) == 3
    # 每条形状
    e = body["entries"][0]
    assert set(e.keys()) >= {
        "id", "gallery_id", "root_id", "original_relative_path",
        "trash_relative_path", "sha1", "size_bytes",
        "deleted_by", "deleted_at", "purge_after",
    }
    # 过滤：gallery_id
    r = c.get("/api/trash", params={"gallery_id": gid})
    assert len(r.json()["entries"]) == 3
    r = c.get("/api/trash", params={"gallery_id": 9999})
    assert r.json()["entries"] == []
    # 过滤：root_id
    r = c.get("/api/trash", params={"root_id": rid})
    assert len(r.json()["entries"]) == 3


def test_list_trash_pagination(admin_client):
    c, app, *_ = admin_client
    _delete_all_three(c, app)
    r1 = c.get("/api/trash", params={"limit": 2})
    body1 = r1.json()
    assert len(body1["entries"]) == 2
    assert body1["next_cursor"] is not None
    r2 = c.get("/api/trash", params={"limit": 2, "cursor": body1["next_cursor"]})
    body2 = r2.json()
    assert len(body2["entries"]) == 1
    assert body2["next_cursor"] is None
    # 无重复
    ids1 = {e["id"] for e in body1["entries"]}
    ids2 = {e["id"] for e in body2["entries"]}
    assert ids1.isdisjoint(ids2)


def test_list_trash_requires_admin(admin_client):
    c, app, *_ = admin_client
    _delete_all_three(c, app)
    c.portal.call(_add_viewer, app)
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "viewer", "password": "viewerpw"})
    assert c.get("/api/trash").status_code == 403


def test_list_trash_requires_auth(tmp_path):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        assert c.get("/api/trash").status_code == 401


# ---------- POST /api/trash/{id}/restore ----------


def test_restore_moves_file_back_and_recreates_image_row(admin_client):
    c, app, _gid, rid, photos = admin_client
    image_id = c.portal.call(_image_id, app, "b.jpg")
    r = c.delete(f"/api/images/{image_id}")
    assert r.status_code == 204
    assert not (photos / "sub" / "b.jpg").exists()

    t = c.portal.call(_list_trash, app)[0]
    r = c.post(f"/api/trash/{t.id}/restore")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "restored"
    assert body["restored_to"] == "sub/b.jpg"
    assert body["image_id"] is not None

    # 文件回原位；trash 行消失；images 有新行
    assert (photos / "sub" / "b.jpg").exists()
    assert c.portal.call(_list_trash, app) == []
    images = c.portal.call(_images, app)
    assert any(i.filename == "b.jpg" for i in images)

    # 目录 counts：sub image_count 2 -> 1 (删后) -> 2 (恢复后)
    folders = c.portal.call(_folders, app)
    assert folders["sub"].image_count == 2
    assert folders[""].descendant_count == 3

    # 审计
    audit = c.portal.call(_last_audit, app, "image_restore")
    assert audit is not None
    assert audit.target == f"trash:{t.id}"


def test_restore_disambiguates_when_original_occupied(admin_client):
    c, app, _gid, rid, photos = admin_client
    image_id = c.portal.call(_image_id, app, "a.jpg")
    c.delete(f"/api/images/{image_id}")

    # 原位重新写入一张同名文件（模拟并发新增）
    _jpg(photos / "a.jpg")

    t = c.portal.call(_list_trash, app)[0]
    r = c.post(f"/api/trash/{t.id}/restore")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "restored"
    # 恢复到重命名后的路径
    assert body["restored_to"] != "a.jpg"
    assert re.match(r"a \(restored \d{8}-\d{6}\)\.jpg", body["restored_to"])
    assert (photos / body["restored_to"]).exists()
    # 原位那张仍然存在
    assert (photos / "a.jpg").exists()


def test_restore_missing_source_returns_404(admin_client):
    c, app, *_ = admin_client
    image_id = c.portal.call(_image_id, app, "a.jpg")
    c.delete(f"/api/images/{image_id}")

    t = c.portal.call(_list_trash, app)[0]
    # 手动把 trash 里的文件删掉（模拟外部误删）
    root_dir = Path(t.trash_relative_path)
    # 从 admin_client 拿到 photos
    _c, _app, _gid, _rid, photos = admin_client
    (photos / t.trash_relative_path).unlink()

    r = c.post(f"/api/trash/{t.id}/restore")
    assert r.status_code == 404
    # trash 行未清理（留证据）
    trashes = c.portal.call(_list_trash, app)
    assert len(trashes) == 1


def test_restore_404_when_trash_id_unknown(admin_client):
    c, *_ = admin_client
    r = c.post("/api/trash/99999/restore")
    assert r.status_code == 404


def test_batch_restore_success_and_partial(admin_client):
    c, app, *_ = admin_client
    _delete_all_three(c, app)
    trashes = c.portal.call(_list_trash, app)
    ok_ids = [t.id for t in trashes[:2]]

    r = c.post("/api/trash/batch-restore", json={"trash_ids": ok_ids + [99999]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["restored"]) == 2
    assert body["failed"] == [{"id": 99999, "error": "not_found"}]

    # 两张恢复；一张仍在 trash
    remaining = c.portal.call(_list_trash, app)
    assert len(remaining) == 1
    images = c.portal.call(_images, app)
    assert len(images) == 2


def test_batch_restore_over_limit_and_empty(admin_client):
    c, *_ = admin_client
    assert c.post("/api/trash/batch-restore", json={"trash_ids": []}).status_code == 422
    assert c.post(
        "/api/trash/batch-restore", json={"trash_ids": list(range(1, 502))}
    ).status_code == 422


def test_restore_requires_admin(admin_client):
    c, app, *_ = admin_client
    image_id = c.portal.call(_image_id, app, "a.jpg")
    c.delete(f"/api/images/{image_id}")
    t = c.portal.call(_list_trash, app)[0]

    c.portal.call(_add_viewer, app)
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "viewer", "password": "viewerpw"})
    assert c.post(f"/api/trash/{t.id}/restore").status_code == 403
    assert c.post("/api/trash/batch-restore", json={"trash_ids": [t.id]}).status_code == 403


# ---------- DELETE /api/trash/{id} ----------


def test_delete_trash_entry_removes_file_and_row(admin_client):
    c, app, *_, photos = admin_client
    image_id = c.portal.call(_image_id, app, "a.jpg")
    c.delete(f"/api/images/{image_id}")
    t = c.portal.call(_list_trash, app)[0]
    trash_file = photos / t.trash_relative_path
    assert trash_file.exists()

    r = c.delete(f"/api/trash/{t.id}")
    assert r.status_code == 204
    assert not trash_file.exists()
    assert c.portal.call(_list_trash, app) == []


def test_delete_trash_entry_404_when_missing(admin_client):
    c, *_ = admin_client
    r = c.delete("/api/trash/99999")
    assert r.status_code == 404


def test_delete_trash_entry_path_guard_blocks(admin_client):
    """构造一条 trash_relative_path 指向 root 外的行，验证 delete 被护栏拒绝。"""
    c, app, gid, rid, _ = admin_client

    from myphoto.models import Trash

    async def _seed_evil():
        async with app.state.sessionmaker() as s:
            s.add(Trash(
                gallery_id=gid, root_id=rid,
                original_relative_path="a.jpg",
                trash_relative_path="not-trash/../evil.jpg",
                sha1="x", size_bytes=1,
                deleted_by=1, deleted_at=1, purge_after=2,
            ))
            await s.commit()

    c.portal.call(_seed_evil)
    t = c.portal.call(_list_trash, app)[0]
    r = c.delete(f"/api/trash/{t.id}")
    assert r.status_code == 403
    # trash 行未清理
    assert len(c.portal.call(_list_trash, app)) == 1
    # 护栏审计
    audit = c.portal.call(_last_audit, app, "trash_purge")
    assert audit is not None
    assert "path_guard_blocked" in (audit.detail or "")


def test_delete_trash_entry_requires_admin(admin_client):
    c, app, *_ = admin_client
    image_id = c.portal.call(_image_id, app, "a.jpg")
    c.delete(f"/api/images/{image_id}")
    t = c.portal.call(_list_trash, app)[0]
    c.portal.call(_add_viewer, app)
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "viewer", "password": "viewerpw"})
    assert c.delete(f"/api/trash/{t.id}").status_code == 403


# ---------- POST /api/trash/purge ----------


def test_purge_requires_confirm(admin_client):
    c, *_ = admin_client
    r = c.post("/api/trash/purge", json={})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "confirmation_required"


def test_purge_removes_expired_only(admin_client):
    c, app, gid, rid, photos = admin_client

    # 手工插入两条：一条已过期，一条未过期，都在 TRASH_DIR 内
    from myphoto.models import Trash

    async def _seed():
        tdir = photos / f".trash/{gid}/{rid}/20260101"
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "expired.jpg").write_bytes(b"x")
        (tdir / "fresh.jpg").write_bytes(b"y")
        async with app.state.sessionmaker() as s:
            s.add(Trash(
                gallery_id=gid, root_id=rid,
                original_relative_path="expired.jpg",
                trash_relative_path=f".trash/{gid}/{rid}/20260101/expired.jpg",
                sha1="a", size_bytes=1, deleted_by=1,
                deleted_at=1000, purge_after=2000,
            ))
            s.add(Trash(
                gallery_id=gid, root_id=rid,
                original_relative_path="fresh.jpg",
                trash_relative_path=f".trash/{gid}/{rid}/20260101/fresh.jpg",
                sha1="b", size_bytes=1, deleted_by=1,
                deleted_at=5000, purge_after=9999999999,
            ))
            await s.commit()

    c.portal.call(_seed)

    r = c.post("/api/trash/purge", json={"confirm": True, "before": 3000})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["purged"] == 1
    assert result["blocked"] == 0

    # 剩下 1 条 未过期
    remaining = c.portal.call(_list_trash, app)
    assert len(remaining) == 1
    assert remaining[0].original_relative_path == "fresh.jpg"
    # 汇总审计
    audit = c.portal.call(_last_audit, app, "trash_purge")
    assert audit is not None
    assert "purged=1" in (audit.detail or "")


def test_purge_requires_admin(admin_client):
    c, app, *_ = admin_client
    c.portal.call(_add_viewer, app)
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "viewer", "password": "viewerpw"})
    assert c.post("/api/trash/purge", json={"confirm": True}).status_code == 403


# ---------- GET /api/trash/{id}/thumb ----------


def test_trash_thumb_returns_jpeg(admin_client):
    c, app, *_ = admin_client
    image_id = c.portal.call(_image_id, app, "a.jpg")
    r = c.delete(f"/api/images/{image_id}")
    assert r.status_code == 204
    t = c.portal.call(_list_trash, app)[0]

    r = c.get(f"/api/trash/{t.id}/thumb", params={"size": 200})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["etag"] == t.sha1
    assert r.content[:3] == b"\xff\xd8\xff"  # JPEG magic


def test_trash_thumb_supports_multiple_sizes(admin_client):
    c, app, *_ = admin_client
    image_id = c.portal.call(_image_id, app, "a.jpg")
    c.delete(f"/api/images/{image_id}")
    t = c.portal.call(_list_trash, app)[0]

    for size in (200, 400, 1600):
        r = c.get(f"/api/trash/{t.id}/thumb", params={"size": size})
        assert r.status_code == 200, f"size {size}: {r.text}"


def test_trash_thumb_rejects_disallowed_size(admin_client):
    c, app, *_ = admin_client
    image_id = c.portal.call(_image_id, app, "a.jpg")
    c.delete(f"/api/images/{image_id}")
    t = c.portal.call(_list_trash, app)[0]

    r = c.get(f"/api/trash/{t.id}/thumb", params={"size": 999})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_trash_thumb_404_when_unknown_trash_id(admin_client):
    c, *_ = admin_client
    r = c.get("/api/trash/99999/thumb")
    assert r.status_code == 404


def test_trash_thumb_404_when_file_missing_on_disk(admin_client):
    c, app, gid, rid, photos = admin_client
    image_id = c.portal.call(_image_id, app, "a.jpg")
    c.delete(f"/api/images/{image_id}")
    t = c.portal.call(_list_trash, app)[0]
    # 手工把 trash 文件删掉，模拟外部误删
    (photos / t.trash_relative_path).unlink()

    r = c.get(f"/api/trash/{t.id}/thumb")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_trash_thumb_path_guard_blocks_external_path(admin_client):
    """红线护栏：trash_relative_path 指向 root 外时，thumb 端点 403，
    绝不读取任意文件内容。"""
    c, app, gid, rid, photos = admin_client

    async def _seed_evil():
        async with app.state.sessionmaker() as s:
            s.add(Trash(
                gallery_id=gid, root_id=rid,
                original_relative_path="a.jpg",
                trash_relative_path="../outside-file.jpg",  # 逃出 root
                sha1="x", size_bytes=1,
                deleted_by=1, deleted_at=1, purge_after=2,
            ))
            await s.commit()

    c.portal.call(_seed_evil)
    t = c.portal.call(_list_trash, app)[0]
    r = c.get(f"/api/trash/{t.id}/thumb")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_trash_thumb_requires_admin(admin_client):
    c, app, *_ = admin_client
    image_id = c.portal.call(_image_id, app, "a.jpg")
    c.delete(f"/api/images/{image_id}")
    t = c.portal.call(_list_trash, app)[0]

    c.portal.call(_add_viewer, app)
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "viewer", "password": "viewerpw"})
    assert c.get(f"/api/trash/{t.id}/thumb").status_code == 403


def test_trash_thumb_requires_auth(tmp_path):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        r = c.get("/api/trash/1/thumb")
        assert r.status_code == 401
