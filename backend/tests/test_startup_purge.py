"""Integration test for startup purge_expired hook in main.build_app lifespan."""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient
from sqlalchemy import select

from myphoto.main import build_app
from myphoto.models import AuditLog, Trash


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (30, 20), (0, 0, 0)).save(p, "JPEG")


def _admin_creds_from_capsys(capsys) -> str:
    out = capsys.readouterr().out
    m = re.search(r"password=(\S+)", out)
    assert m is not None
    return m.group(1)


async def _seed(app, photos, expired: bool):
    """建 gallery/root/trash 行 + 落盘一个 .trash 文件。"""
    from myphoto.models import Gallery, GalleryRoot

    async with app.state.sessionmaker() as s:
        g = Gallery(name="G", created_at=int(time.time()))
        s.add(g)
        await s.flush()
        r = GalleryRoot(
            gallery_id=g.id, label="R",
            absolute_path=str(photos.resolve()), enabled=1,
        )
        s.add(r)
        await s.commit()
        await s.refresh(r)
        rid, gid = r.id, g.id

    tdir = photos / f".trash/{gid}/{rid}/20260101"
    tdir.mkdir(parents=True, exist_ok=True)
    trash_file = tdir / "expired.jpg"
    trash_file.write_bytes(b"x")

    now = int(time.time())
    async with app.state.sessionmaker() as s:
        s.add(Trash(
            gallery_id=gid, root_id=rid,
            original_relative_path="expired.jpg",
            trash_relative_path=f".trash/{gid}/{rid}/20260101/expired.jpg",
            sha1="s", size_bytes=1, deleted_by=1,
            deleted_at=now - 86400,
            # expired: purge_after 已过；否则 30 天后
            purge_after=(now - 100) if expired else (now + 30 * 86400),
        ))
        await s.commit()


async def _list_trash(app):
    async with app.state.sessionmaker() as s:
        return (await s.execute(select(Trash))).scalars().all()


def test_startup_purges_expired_entries(tmp_path, capsys):
    """启动 lifespan 完成后，过期的 trash 行 + 文件应该已被清理。"""
    photos = tmp_path / "photos"
    photos.mkdir()
    cfg = tmp_path / "config.toml"

    # 第一次启动：只是为了创建 config + admin，然后种数据
    app1 = build_app(config_path=str(cfg))
    with TestClient(app1) as c:
        _ = _admin_creds_from_capsys(capsys)
        c.portal.call(_seed, app1, photos, True)
        trash_file_path = photos / ".trash"
        # 确认种下后文件+行都存在
        assert list(trash_file_path.rglob("expired.jpg"))
        assert len(c.portal.call(_list_trash, app1)) == 1

    # 第二次启动：新 app 实例，同一 config 同一 db；启动 hook 应清理
    app2 = build_app(config_path=str(cfg))
    with TestClient(app2):
        # 让 lifespan 完成 —— 只要进入 with 块，startup 就已经跑过
        pass

    # 断言：文件已消失、trash 表已空
    app3 = build_app(config_path=str(cfg))
    with TestClient(app3) as c:
        assert list((photos / ".trash").rglob("expired.jpg")) == []
        assert c.portal.call(_list_trash, app3) == []


def test_startup_leaves_fresh_entries_alone(tmp_path, capsys):
    photos = tmp_path / "photos"
    photos.mkdir()
    cfg = tmp_path / "config.toml"

    app1 = build_app(config_path=str(cfg))
    with TestClient(app1) as c:
        _admin_creds_from_capsys(capsys)
        c.portal.call(_seed, app1, photos, False)  # 未过期
        assert len(c.portal.call(_list_trash, app1)) == 1

    # 重启
    app2 = build_app(config_path=str(cfg))
    with TestClient(app2) as c:
        remaining = c.portal.call(_list_trash, app2)
        assert len(remaining) == 1
        assert remaining[0].original_relative_path == "expired.jpg"


def test_startup_purge_uses_retention_from_config(tmp_path, capsys):
    """DELETE /api/images/{id} 生成的 trash 行 purge_after = now + retention_days*86400。"""
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        '[trash]\nretention_days=7\n',
        encoding="utf-8",
    )

    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        pw = _admin_creds_from_capsys(capsys)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})

        from myphoto.models import Gallery, GalleryRoot

        async def _seed_root():
            async with app.state.sessionmaker() as s:
                g = Gallery(name="G", created_at=int(time.time()))
                s.add(g)
                await s.flush()
                r = GalleryRoot(
                    gallery_id=g.id, label="R",
                    absolute_path=str(photos.resolve()), enabled=1,
                )
                s.add(r)
                await s.commit()
                await s.refresh(r)
                return r.id

        async def _scan(rid):
            await app.state.scanner.scan_root_now(rid)

        rid = c.portal.call(_seed_root)
        c.portal.call(_scan, rid)

        from myphoto.models import Image

        async def _find_image_id():
            async with app.state.sessionmaker() as s:
                r = (await s.execute(select(Image))).scalar_one()
                return r.id

        image_id = c.portal.call(_find_image_id)
        r = c.delete(f"/api/images/{image_id}")
        assert r.status_code == 204

        trashes = c.portal.call(_list_trash, app)
        assert len(trashes) == 1
        t = trashes[0]
        # 允许几秒容差
        assert abs(t.purge_after - t.deleted_at - 7 * 86400) <= 5
