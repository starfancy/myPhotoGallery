"""Tests for GET /api/images/{id}/exif."""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from PIL.TiffImagePlugin import IFDRational
from fastapi.testclient import TestClient
from sqlalchemy import select

from myphoto.main import build_app
from myphoto.models import Image


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (40, 30), (0, 0, 0)).save(p, "JPEG")


def _jpg_with_exif(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.new("RGB", (60, 40), (0, 0, 0))
    exif = img.getexif()
    exif[0x010F] = "Nikon"
    exif[0x0110] = "Z6"
    sub = exif.get_ifd(0x8769)
    sub[0x829A] = IFDRational(1, 250)
    sub[0x829D] = IFDRational(40, 10)
    sub[0x8827] = 200
    img.save(p, "JPEG", exif=exif.tobytes())


async def _seed(app, photos):
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


async def _image_id(app, filename):
    async with app.state.sessionmaker() as s:
        row = (await s.execute(
            select(Image).where(Image.filename == filename)
        )).scalar_one_or_none()
        return row.id if row else None


@pytest.fixture
def client(tmp_path, capsys):
    photos = tmp_path / "photos"
    _jpg_with_exif(photos / "with.jpg")
    _jpg(photos / "without.jpg")
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        c.portal.call(_seed, app, photos)

        async def _first_rid():
            from myphoto.models import GalleryRoot

            async with app.state.sessionmaker() as s:
                return (await s.execute(select(GalleryRoot))).scalar_one().id

        rid = c.portal.call(_first_rid)
        c.portal.call(_scan, app, rid)
        yield c, app


def test_exif_returned_for_image_with_exif(client):
    c, app = client
    image_id = c.portal.call(_image_id, app, "with.jpg")
    r = c.get(f"/api/images/{image_id}/exif")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["image_id"] == image_id
    assert body["filename"] == "with.jpg"
    assert body["exif"]["Make"] == "Nikon"
    assert body["exif"]["Model"] == "Z6"
    assert body["exif"]["ExposureTime"] == "1/250"
    assert body["exif"]["FNumber"] == 4.0
    assert body["exif"]["ISOSpeedRatings"] == 200


def test_exif_returns_empty_object_when_no_exif(client):
    c, app = client
    image_id = c.portal.call(_image_id, app, "without.jpg")
    r = c.get(f"/api/images/{image_id}/exif")
    assert r.status_code == 200
    body = r.json()
    assert body["image_id"] == image_id
    assert body["filename"] == "without.jpg"
    assert body["exif"] == {}


def test_exif_returns_empty_when_json_malformed(client):
    c, app = client
    image_id = c.portal.call(_image_id, app, "without.jpg")

    async def _corrupt():
        async with app.state.sessionmaker() as s:
            img = await s.get(Image, image_id)
            img.exif_json = "{not valid json"
            await s.commit()

    c.portal.call(_corrupt)
    r = c.get(f"/api/images/{image_id}/exif")
    assert r.status_code == 200
    assert r.json()["exif"] == {}


def test_exif_404_for_unknown_image(client):
    c, _ = client
    r = c.get("/api/images/99999/exif")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_exif_viewer_can_read(client):
    """任何登录用户（含 viewer）都能读 EXIF。"""
    c, app = client
    image_id = c.portal.call(_image_id, app, "with.jpg")
    c.portal.call(_add_viewer, app)
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "viewer", "password": "viewerpw"})
    r = c.get(f"/api/images/{image_id}/exif")
    assert r.status_code == 200
    assert r.json()["exif"]["Make"] == "Nikon"


def test_exif_requires_auth(tmp_path):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        r = c.get("/api/images/1/exif")
        assert r.status_code == 401
