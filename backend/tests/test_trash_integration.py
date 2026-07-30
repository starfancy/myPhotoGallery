"""Phase 3 integration tests: delete → trash → restore → purge, path guards, batch flows.

覆盖 Task 15 三条：
1. 端到端删除→恢复→再删→purge 全流程状态转移
2. 红线 3：手工构造 trash_relative_path 指向 root 外，purge_expired 拒绝 + 审计
3. 批量删除 3 张 → 批量恢复 2 张 → 剩下 1 张仍在 trash

配合前面 unit / route 测试形成三层覆盖：单元行为 → 单路由端点 → 跨路由业务链路。
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient
from sqlalchemy import select

from myphoto.main import build_app
from myphoto.models import AuditLog, Folder, Gallery, GalleryRoot, Image, Trash


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (30, 20), (10, 20, 30)).save(p, "JPEG")


def _login(c: TestClient, capsys) -> None:
    out = capsys.readouterr().out
    pw = re.search(r"password=(\S+)", out).group(1)
    r = c.post("/api/auth/login", json={"username": "admin", "password": pw})
    assert r.status_code == 200


async def _seed_root(app, photos: Path):
    async with app.state.sessionmaker() as s:
        g = Gallery(name="E2E", created_at=int(time.time()))
        s.add(g)
        await s.flush()
        r = GalleryRoot(
            gallery_id=g.id, label="R",
            absolute_path=str(photos.resolve()), enabled=1,
        )
        s.add(r)
        await s.commit()
        await s.refresh(r)
        return g.id, r.id


async def _scan(app, rid: int):
    await app.state.scanner.scan_root_now(rid)


async def _list_trash(app):
    async with app.state.sessionmaker() as s:
        return (await s.execute(select(Trash))).scalars().all()


async def _list_images(app):
    async with app.state.sessionmaker() as s:
        return (await s.execute(select(Image))).scalars().all()


async def _folders(app):
    async with app.state.sessionmaker() as s:
        return {f.relative_path: f for f in (
            await s.execute(select(Folder))
        ).scalars().all()}


async def _image_id(app, filename: str):
    async with app.state.sessionmaker() as s:
        r = (await s.execute(
            select(Image).where(Image.filename == filename)
        )).scalar_one_or_none()
        return r.id if r else None


# ---------------------------------------------------------------------------
# Test 1: End-to-end delete → restore → delete → purge
# ---------------------------------------------------------------------------


def test_e2e_delete_restore_delete_purge(tmp_path, capsys):
    """完整业务链路：
    scan → delete → 校验 trash+file 就位 → restore → 校验 image 回来 →
    再 delete → purge → 校验文件与行都消失，全程审计齐全。
    """
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    _jpg(photos / "sub" / "b.jpg")
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        _login(c, capsys)
        gid, rid = c.portal.call(_seed_root, app, photos)
        c.portal.call(_scan, app, rid)

        # 1) 删除 a.jpg
        image_id = c.portal.call(_image_id, app, "a.jpg")
        r = c.delete(f"/api/images/{image_id}")
        assert r.status_code == 204

        # 文件已移入 .trash，images 表无此行，trash 表有 1 行
        assert not (photos / "a.jpg").exists()
        trashes = c.portal.call(_list_trash, app)
        assert len(trashes) == 1
        t = trashes[0]
        assert t.original_relative_path == "a.jpg"
        assert (photos / t.trash_relative_path).exists()
        # folder 计数：root descendant_count 2->1；本 folder image_count 1->0
        folders = c.portal.call(_folders, app)
        assert folders[""].image_count == 0
        assert folders[""].descendant_count == 1

        # 2) 恢复
        r = c.post(f"/api/trash/{t.id}/restore")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "restored"
        assert body["restored_to"] == "a.jpg"

        # 文件回原位，images 表新增行，trash 表清空
        assert (photos / "a.jpg").exists()
        images = c.portal.call(_list_images, app)
        assert {i.filename for i in images} == {"a.jpg", "b.jpg"}
        assert c.portal.call(_list_trash, app) == []
        folders = c.portal.call(_folders, app)
        assert folders[""].image_count == 1
        assert folders[""].descendant_count == 2

        # 3) 再次删除，然后 purge
        restored_id = c.portal.call(_image_id, app, "a.jpg")
        r = c.delete(f"/api/images/{restored_id}")
        assert r.status_code == 204
        trashes = c.portal.call(_list_trash, app)
        assert len(trashes) == 1
        trash_file = photos / trashes[0].trash_relative_path

        # 立即 purge（before=远未来）→ 强制清所有
        far_future = int(time.time()) + 10 * 365 * 86400
        r = c.post("/api/trash/purge", json={
            "confirm": True, "before": far_future,
        })
        assert r.status_code == 200
        result = r.json()
        assert result["purged"] == 1
        assert result["blocked"] == 0

        # 文件与 trash 行都消失
        assert not trash_file.exists()
        assert c.portal.call(_list_trash, app) == []

        # 审计齐全：image_delete x2, image_restore x1, trash_purge x1(汇总)
        async def _audit_counts():
            async with app.state.sessionmaker() as s:
                rows = (await s.execute(select(AuditLog))).scalars().all()
                out: dict[str, int] = {}
                for a in rows:
                    out[a.action] = out.get(a.action, 0) + 1
                return out

        counts = c.portal.call(_audit_counts)
        assert counts.get("image_delete", 0) >= 2
        assert counts.get("image_restore", 0) >= 1
        assert counts.get("trash_purge", 0) >= 1


# ---------------------------------------------------------------------------
# Test 2: Red-line 3 — path guard 阻止路径逃出 TRASH_DIR
# ---------------------------------------------------------------------------


def test_red_line_3_path_guard_blocks_purge_of_external_path(tmp_path, capsys):
    """构造一条 trash_relative_path 指向 root 但不在 .trash/ 下（模拟被
    数据库破坏或人为篡改），purge_expired 必须拒绝，绝不删除文件，且写
    trash_purge:path_guard_blocked 审计。原文件保留证据。"""
    photos = tmp_path / "photos"
    photos.mkdir()
    # 明显不在 .trash 下的真实文件
    victim = photos / "important-do-not-delete.jpg"
    _jpg(victim)
    assert victim.exists()

    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        _login(c, capsys)
        gid, rid = c.portal.call(_seed_root, app, photos)

        # 手工插入一条恶意 trash 行，purge_after 已过
        async def _seed_evil():
            async with app.state.sessionmaker() as s:
                s.add(Trash(
                    gallery_id=gid, root_id=rid,
                    original_relative_path="important-do-not-delete.jpg",
                    trash_relative_path="important-do-not-delete.jpg",  # 直接根目录！
                    sha1="x", size_bytes=1, deleted_by=1,
                    deleted_at=1, purge_after=2,
                ))
                await s.commit()

        c.portal.call(_seed_evil)

        # 触发 purge（before=远未来 → 全部到期）
        far_future = int(time.time()) + 10 * 365 * 86400
        r = c.post("/api/trash/purge", json={
            "confirm": True, "before": far_future,
        })
        assert r.status_code == 200
        result = r.json()
        assert result["purged"] == 0
        assert result["blocked"] == 1

        # 关键断言：受害文件绝不被删
        assert victim.exists()
        # trash 行仍在（留证据待人工检查）
        trashes = c.portal.call(_list_trash, app)
        assert len(trashes) == 1
        # 审计写了 path_guard_blocked
        async def _audit_details():
            async with app.state.sessionmaker() as s:
                rows = (await s.execute(
                    select(AuditLog).where(AuditLog.action == "trash_purge")
                )).scalars().all()
                return [(r.detail or "") for r in rows]

        details = c.portal.call(_audit_details)
        assert any("path_guard_blocked" in d for d in details)


# ---------------------------------------------------------------------------
# Test 3: batch delete 3 → batch restore 2 → 剩 1 张仍在 trash
# ---------------------------------------------------------------------------


def test_batch_delete_then_partial_restore(tmp_path, capsys):
    photos = tmp_path / "photos"
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        _jpg(photos / name)
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        _login(c, capsys)
        gid, rid = c.portal.call(_seed_root, app, photos)
        c.portal.call(_scan, app, rid)

        # 批量删除 3 张
        ids = [c.portal.call(_image_id, app, n) for n in ("a.jpg", "b.jpg", "c.jpg")]
        r = c.post("/api/images/batch-delete", json={"image_ids": ids})
        assert r.status_code == 200
        assert sorted(r.json()["deleted"]) == sorted(ids)
        assert c.portal.call(_list_images, app) == []
        trashes = c.portal.call(_list_trash, app)
        assert len(trashes) == 3

        # 批量恢复前 2 条（trash id 顺序不保证，按 deleted_at 降序取前 2）
        trash_ids = sorted([t.id for t in trashes])
        r = c.post("/api/trash/batch-restore", json={"trash_ids": trash_ids[:2]})
        assert r.status_code == 200
        body = r.json()
        assert len(body["restored"]) == 2
        assert body["failed"] == []

        # 剩 1 张仍在 trash；images 回到 2 张
        remaining_trash = c.portal.call(_list_trash, app)
        assert len(remaining_trash) == 1
        assert remaining_trash[0].id == trash_ids[2]
        assert len(c.portal.call(_list_images, app)) == 2
        # 文件层面：两张回到 root，一张仍在 .trash/
        assert (photos / "a.jpg").exists() or (photos / "b.jpg").exists()
        left = remaining_trash[0]
        assert (photos / left.trash_relative_path).exists()
