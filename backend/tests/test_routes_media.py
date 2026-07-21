import re
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient

from myphoto.main import build_app


def _jpg(p: Path, size=(200, 150)):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", size, (200, 100, 50)).save(p, "JPEG")


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
