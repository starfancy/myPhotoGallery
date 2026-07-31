import re
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient

from myphoto.main import build_app


def _jpg(p: Path, size=(200, 150), color=(200, 100, 50)):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", size, color).save(p, "JPEG")


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
        return r.id


async def _scan(app, rid):
    await app.state.scanner.scan_root_now(rid)


async def _fetch_one(app):
    from myphoto.models import Image
    from sqlalchemy import select as _s

    async with app.state.sessionmaker() as s:
        row = (await s.execute(_s(Image))).scalars().first()
        return row.id, row.sha1


@pytest.fixture
def env(tmp_path, capsys):
    # Deviation from brief: asyncio.get_event_loop().run_until_complete is
    # deprecated on 3.12 and cannot re-enter the loop TestClient is running
    # in; use TestClient.portal.call(...) as established in test_routes_browse.py.
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        rid = c.portal.call(_seed, app, photos)
        c.portal.call(_scan, app, rid)
        iid, sha1 = c.portal.call(_fetch_one, app)
        yield c, iid, sha1


def test_thumb_returns_jpeg(env):
    c, _, sha1 = env
    r = c.get(f"/api/thumb/{sha1}", params={"size": 200})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert "immutable" in r.headers["cache-control"]
    assert r.headers["etag"] == sha1


def test_thumb_rejects_bad_size(env):
    c, _, sha1 = env
    r = c.get(f"/api/thumb/{sha1}", params={"size": 999})
    assert r.status_code == 400


def test_thumb_unknown_sha1_404(env):
    c, _, _ = env
    r = c.get("/api/thumb/deadbeef", params={"size": 200})
    assert r.status_code == 404


def test_image_stream(env):
    c, iid, sha1 = env
    r = c.get(f"/api/image/{iid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert r.headers["etag"] == sha1


def test_image_download_disposition(env):
    c, iid, _ = env
    r = c.get(f"/api/image/{iid}", params={"download": 1})
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")


def test_image_range(env):
    c, iid, _ = env
    full = c.get(f"/api/image/{iid}").content
    r = c.get(f"/api/image/{iid}", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    assert r.content == full[:10]


# ---- P4: viewer gallery access (check_gallery_access) ----


async def _seed_two_galleries(app, photos1, photos2):
    """两个图库各含一个根目录；返回 ((g1, r1), (g2, r2))。"""
    from myphoto.models import Gallery, GalleryRoot

    async with app.state.sessionmaker() as s:
        g1 = Gallery(name="G1", created_at=int(time.time()))
        g2 = Gallery(name="G2", created_at=int(time.time()))
        s.add(g1)
        s.add(g2)
        await s.flush()
        r1 = GalleryRoot(
            gallery_id=g1.id, label="R1",
            absolute_path=str(photos1.resolve()), enabled=1,
        )
        r2 = GalleryRoot(
            gallery_id=g2.id, label="R2",
            absolute_path=str(photos2.resolve()), enabled=1,
        )
        s.add(r1)
        s.add(r2)
        await s.commit()
        await s.refresh(r1)
        await s.refresh(r2)
        return (g1.id, r1.id), (g2.id, r2.id)


async def _add_viewer_with_galleries(app, username, password, gallery_ids):
    """创建 viewer 并授权指定的 gallery_ids。"""
    from myphoto.models import User, UserGallery
    from myphoto.security import hash_password

    async with app.state.sessionmaker() as s:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role="viewer",
            access_scope="remote_allowed",
            enabled=1,
            created_at=int(time.time()),
        )
        s.add(user)
        await s.flush()
        for gid in gallery_ids:
            s.add(UserGallery(
                user_id=user.id, gallery_id=gid, granted_at=int(time.time()),
            ))
        await s.commit()


async def _fetch_images_by_root(app):
    """返回 {root_id: (image_id, sha1)} 映射。"""
    from myphoto.models import Image
    from sqlalchemy import select as _s

    async with app.state.sessionmaker() as s:
        rows = (await s.execute(_s(Image))).scalars().all()
        return {r.root_id: (r.id, r.sha1) for r in rows}


@pytest.fixture
def client_two_galleries(tmp_path, capsys):
    """两个图库各含一张图片，admin 已登录。yields (c, app, g1, g2, r1, r2, imgs_by_root)。"""
    photos1 = tmp_path / "photos1"
    photos2 = tmp_path / "photos2"
    _jpg(photos1 / "a1.jpg", color=(200, 100, 50))   # 不同颜色 → 不同 sha1
    _jpg(photos2 / "a2.jpg", color=(50, 100, 200))
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        (g1, r1), (g2, r2) = c.portal.call(
            _seed_two_galleries, app, photos1, photos2,
        )
        c.portal.call(_scan, app, r1)
        c.portal.call(_scan, app, r2)
        imgs = c.portal.call(_fetch_images_by_root, app)
        yield c, app, g1, g2, r1, r2, imgs


# ---- thumb 访问控制 ----

def test_thumb_viewer_authorized_gallery_200(client_two_galleries):
    """viewer 可访问已授权图库图片的缩略图。"""
    c, app, g1, _, r1, _, imgs = client_two_galleries
    _iid, sha1_g1 = imgs[r1]

    c.portal.call(_add_viewer_with_galleries, app, "v1", "vpw1", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v1", "password": "vpw1"})
    assert r.status_code == 200

    r = c.get(f"/api/thumb/{sha1_g1}", params={"size": 200})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"


def test_thumb_viewer_unauthorized_gallery_404(client_two_galleries):
    """viewer 访问未授权图库的缩略图返回 404（防枚举）。"""
    c, app, g1, g2, _, r2, imgs = client_two_galleries
    _iid, sha1_g2 = imgs[r2]

    # viewer 只授权 g1，无权访问 g2
    c.portal.call(_add_viewer_with_galleries, app, "v2", "vpw2", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v2", "password": "vpw2"})
    assert r.status_code == 200

    r = c.get(f"/api/thumb/{sha1_g2}", params={"size": 200})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ---- image 访问控制 ----

def test_image_viewer_authorized_gallery_200(client_two_galleries):
    """viewer 可访问已授权图库的原图。"""
    c, app, g1, _, r1, _, imgs = client_two_galleries
    img_id_g1, _sha1 = imgs[r1]

    c.portal.call(_add_viewer_with_galleries, app, "v3", "vpw3", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v3", "password": "vpw3"})
    assert r.status_code == 200

    r = c.get(f"/api/image/{img_id_g1}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_image_viewer_unauthorized_gallery_404(client_two_galleries):
    """viewer 访问未授权图库的原图返回 404（防枚举）。"""
    c, app, g1, g2, _, r2, imgs = client_two_galleries
    img_id_g2, _sha1 = imgs[r2]

    # viewer 只授权 g1，无权访问 g2
    c.portal.call(_add_viewer_with_galleries, app, "v4", "vpw4", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v4", "password": "vpw4"})
    assert r.status_code == 200

    r = c.get(f"/api/image/{img_id_g2}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_image_admin_always_200(client_two_galleries):
    """admin 绕过 check_gallery_access，任意图库均可访问。"""
    c, _, _, _, _, r2, imgs = client_two_galleries
    img_id_g2, _sha1 = imgs[r2]

    r = c.get(f"/api/image/{img_id_g2}")
    assert r.status_code == 200
