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


def test_unauthenticated_blocked(tmp_path):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        r = c.get("/api/galleries")
        assert r.status_code == 401
