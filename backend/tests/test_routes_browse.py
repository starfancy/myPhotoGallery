import re
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient

from myphoto.main import build_app


def _jpg(p: Path, size=(50, 40)):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", size, (10, 20, 30)).save(p, "JPEG")


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


@pytest.fixture
def client_with_data(tmp_path, capsys):
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
        # Seed via the TestClient portal so we share its event loop.
        # (Deviation from brief: asyncio.get_event_loop().run_until_complete is
        # deprecated on Python 3.12 and cannot re-enter the loop TestClient is
        # running in; TestClient.portal is the established pattern already used
        # in test_routes_auth.py.)
        gid, rid = c.portal.call(_seed, app, photos)
        c.portal.call(_scan, app, rid)
        yield c, gid, rid


def test_galleries_list(client_with_data):
    c, gid, _ = client_with_data
    r = c.get("/api/galleries")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert any(item["id"] == gid and item["image_count"] == 3 for item in r.json())


def test_gallery_detail_lists_roots(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(f"/api/galleries/{gid}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["gallery"]["id"] == gid
    assert any(root["id"] == rid for root in body["roots"])


def test_folders_endpoint(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(f"/api/galleries/{gid}/roots/{rid}/folders", params={"path": ""})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    names = [f["name"] for f in r.json()]
    assert "sub" in names


def test_images_endpoint_root(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(f"/api/galleries/{gid}/roots/{rid}/images", params={"path": ""})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert [i["filename"] for i in body["items"]] == ["a.jpg"]


def test_images_endpoint_subdir(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(f"/api/galleries/{gid}/roots/{rid}/images", params={"path": "sub"})
    assert r.status_code == 200
    filenames = sorted(i["filename"] for i in r.json()["items"])
    assert filenames == ["b.jpg", "c.jpg"]


def test_breadcrumbs(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(
        f"/api/galleries/{gid}/roots/{rid}/breadcrumbs", params={"path": "sub"}
    )
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    crumbs = r.json()
    assert crumbs[0]["relative_path"] == ""
    assert crumbs[-1]["relative_path"] == "sub"


def test_path_traversal_rejected(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(
        f"/api/galleries/{gid}/roots/{rid}/folders", params={"path": "../.."}
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


@pytest.fixture
def client_with_many_images(tmp_path, capsys):
    photos = tmp_path / "photos"
    batch = photos / "batch"
    for i in range(12):
        _jpg(batch / f"img{i:02d}.jpg")
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        gid, rid = c.portal.call(_seed, app, photos)
        c.portal.call(_scan, app, rid)
        yield c, gid, rid


def test_images_cursor_pagination_no_duplicates(client_with_many_images):
    c, gid, rid = client_with_many_images

    # Page 1
    r1 = c.get(
        f"/api/galleries/{gid}/roots/{rid}/images",
        params={"path": "batch", "sort": "name_asc", "limit": 3},
    )
    assert r1.status_code == 200
    body1 = r1.json()
    page1_names = [i["filename"] for i in body1["items"]]
    assert len(page1_names) == 3
    assert body1["next_cursor"] is not None

    # Page 2
    r2 = c.get(
        f"/api/galleries/{gid}/roots/{rid}/images",
        params={
            "path": "batch",
            "sort": "name_asc",
            "limit": 3,
            "cursor": body1["next_cursor"],
        },
    )
    assert r2.status_code == 200
    body2 = r2.json()
    page2_names = [i["filename"] for i in body2["items"]]
    assert len(page2_names) == 3

    # No duplicates between pages
    assert set(page1_names) & set(page2_names) == set()

    # Correct ordering: names are alphabetically sorted
    assert page1_names == ["img00.jpg", "img01.jpg", "img02.jpg"]
    assert page2_names == ["img03.jpg", "img04.jpg", "img05.jpg"]


def test_unauthenticated_blocked(tmp_path):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        r = c.get("/api/galleries")
        assert r.status_code == 401


# ---- P4: viewer gallery access (gallery_scope_guard + list filtering) ----


async def _seed_two_galleries(app, photos1, photos2):
    """创建两个图库，各含一个根目录；返回 ((g1, r1), (g2, r2))。"""
    from myphoto.models import Gallery, GalleryRoot

    async with app.state.sessionmaker() as s:
        g1 = Gallery(name="Gallery1", created_at=int(time.time()))
        g2 = Gallery(name="Gallery2", created_at=int(time.time()))
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


@pytest.fixture
def client_two_galleries(tmp_path, capsys):
    """两个图库各含一张图片，admin 已登录。"""
    photos1 = tmp_path / "photos1"
    photos2 = tmp_path / "photos2"
    _jpg(photos1 / "a1.jpg")
    _jpg(photos2 / "a2.jpg")
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
        yield c, app, g1, g2


# ---- 图库列表过滤 ----

def test_viewer_sees_only_authorized_galleries(client_two_galleries):
    """viewer 只能看到 user_galleries 中授权的图库。"""
    c, app, g1, g2 = client_two_galleries
    c.portal.call(_add_viewer_with_galleries, app, "v", "vpw", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v", "password": "vpw"})
    assert r.status_code == 200

    r = c.get("/api/galleries")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()]
    assert g1 in ids
    assert g2 not in ids


def test_viewer_empty_gallery_list_when_no_auth(client_two_galleries):
    """viewer 未授权任何图库时返回空列表。"""
    c, app, _, _ = client_two_galleries
    c.portal.call(_add_viewer_with_galleries, app, "v2", "vpw2", [])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v2", "password": "vpw2"})
    assert r.status_code == 200

    r = c.get("/api/galleries")
    assert r.status_code == 200
    assert r.json() == []


def test_admin_sees_all_galleries(client_two_galleries):
    """admin 不受 user_galleries 限制，看到所有图库。"""
    c, _, g1, g2 = client_two_galleries
    r = c.get("/api/galleries")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()]
    assert g1 in ids
    assert g2 in ids


# ---- 图库详情访问控制 (404 反枚举) ----

def test_viewer_200_for_authorized_gallery_detail(client_two_galleries):
    """viewer 可以访问已授权图库的详情。"""
    c, app, g1, _ = client_two_galleries
    c.portal.call(_add_viewer_with_galleries, app, "v3", "vpw3", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v3", "password": "vpw3"})
    assert r.status_code == 200

    r = c.get(f"/api/galleries/{g1}")
    assert r.status_code == 200
    assert r.json()["gallery"]["id"] == g1


def test_viewer_404_for_unauthorized_gallery_detail(client_two_galleries):
    """viewer 访问未授权图库返回 404（防枚举，非 403）。"""
    c, app, g1, g2 = client_two_galleries
    c.portal.call(_add_viewer_with_galleries, app, "v4", "vpw4", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v4", "password": "vpw4"})
    assert r.status_code == 200

    r = c.get(f"/api/galleries/{g2}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


# ---- 文件夹/图片/面包屑访问控制 ----

def test_viewer_200_for_authorized_folders(client_two_galleries):
    """viewer 可以访问已授权图库的文件夹列表。"""
    c, app, g1, _ = client_two_galleries
    c.portal.call(_add_viewer_with_galleries, app, "v5", "vpw5", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v5", "password": "vpw5"})
    assert r.status_code == 200

    r = c.get(f"/api/galleries/{g1}")
    assert r.status_code == 200
    rid = r.json()["roots"][0]["id"]

    r = c.get(f"/api/galleries/{g1}/roots/{rid}/folders", params={"path": ""})
    assert r.status_code == 200


def test_viewer_404_for_unauthorized_folders(client_two_galleries):
    """viewer 访问未授权图库的文件夹返回 404。"""
    c, app, g1, g2 = client_two_galleries
    c.portal.call(_add_viewer_with_galleries, app, "v6", "vpw6", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v6", "password": "vpw6"})
    assert r.status_code == 200

    r = c.get(f"/api/galleries/{g2}/roots/99999/folders")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_viewer_200_for_authorized_images(client_two_galleries):
    """viewer 可以访问已授权图库的图片列表。"""
    c, app, g1, _ = client_two_galleries
    c.portal.call(_add_viewer_with_galleries, app, "v7", "vpw7", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v7", "password": "vpw7"})
    assert r.status_code == 200

    r = c.get(f"/api/galleries/{g1}")
    assert r.status_code == 200
    rid = r.json()["roots"][0]["id"]

    r = c.get(f"/api/galleries/{g1}/roots/{rid}/images", params={"path": ""})
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 1


def test_viewer_404_for_unauthorized_images(client_two_galleries):
    """viewer 访问未授权图库的图片返回 404。"""
    c, app, g1, g2 = client_two_galleries
    c.portal.call(_add_viewer_with_galleries, app, "v8", "vpw8", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v8", "password": "vpw8"})
    assert r.status_code == 200

    r = c.get(f"/api/galleries/{g2}/roots/99999/images")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_viewer_404_for_unauthorized_breadcrumbs(client_two_galleries):
    """viewer 访问未授权图库的面包屑返回 404。"""
    c, app, g1, g2 = client_two_galleries
    c.portal.call(_add_viewer_with_galleries, app, "v9", "vpw9", [g1])
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"username": "v9", "password": "vpw9"})
    assert r.status_code == 200

    r = c.get(f"/api/galleries/{g2}/roots/99999/breadcrumbs")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
