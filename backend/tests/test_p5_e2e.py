"""P5 end-to-end: exclusions prune/restore via scans + settings hot reload."""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import select

from myphoto.main import build_app
from myphoto.models import Image, Trash


def _jpg(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (20, 20), (0, 0, 0)).save(p, "JPEG")


def _wait_idle(c, gid, rid, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status").json()
        if st["status"] == "idle":
            return
        time.sleep(0.05)
    raise AssertionError("scan did not finish")


def test_p5_exclusion_and_settings_flow(tmp_path, capsys):
    photos = tmp_path / "photos"
    photos.mkdir()
    _jpg(photos / "a" / "b" / "x.jpg")
    _jpg(photos / "a" / "bc" / "y.jpg")
    _jpg(photos / "keep.jpg")

    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app, client=("127.0.0.1", 12345)) as c:
        pw = re.search(r"password=(\S+)", capsys.readouterr().out).group(1)
        assert c.post("/api/auth/login",
                      json={"username": "admin", "password": pw}).status_code == 200

        gid = c.post("/api/admin/galleries", json={"name": "G"}).json()["id"]
        rid = c.post(
            f"/api/admin/galleries/{gid}/roots",
            json={"label": "R", "absolute_path": str(photos)},
        ).json()["id"]
        _wait_idle(c, gid, rid)

        ex_url = f"/api/admin/galleries/{gid}/roots/{rid}/exclusions"

        async def _images():
            async with app.state.sessionmaker() as s:
                return sorted(
                    row.relative_path
                    for row in (await s.execute(select(Image))).scalars()
                )
        assert c.portal.call(_images) == ["a/b/x.jpg", "a/bc/y.jpg", "keep.jpg"]

        # 1. Exclude a/b -> prune that subtree, keep a/bc.
        r = c.post(ex_url, json={"absolute_path": str(photos / "a" / "b")})
        assert r.status_code == 201
        _wait_idle(c, gid, rid)
        assert c.portal.call(_images) == ["a/bc/y.jpg", "keep.jpg"]

        # 2. Unexclude -> rescan restores the subtree.
        eid = r.json()["id"]
        assert c.delete(f"{ex_url}/{eid}").status_code == 204
        _wait_idle(c, gid, rid)
        assert c.portal.call(_images) == ["a/b/x.jpg", "a/bc/y.jpg", "keep.jpg"]

        # 3. Settings: retention=0 hot-reloads; deleted image gets the sentinel.
        assert c.patch("/api/admin/settings",
                       json={"trash_retention_days": 0}).status_code == 200
        assert app.state.config.trash_retention_days == 0

        async def _one_image_id():
            async with app.state.sessionmaker() as s:
                row = (await s.execute(
                    select(Image).where(Image.relative_path == "keep.jpg")
                )).scalar_one()
                return row.id
        image_id = c.portal.call(_one_image_id)
        assert c.delete(f"/api/images/{image_id}").status_code == 204

        async def _trash_row():
            async with app.state.sessionmaker() as s:
                return (await s.execute(select(Trash))).scalar_one()
        t = c.portal.call(_trash_row)
        assert t.purge_after == 9_999_999_999

        # Purge-expired must not touch it.
        pr = c.post("/api/trash/purge", json={"confirm": True})
        assert pr.status_code == 200
        assert c.portal.call(_trash_row).purge_after == 9_999_999_999
