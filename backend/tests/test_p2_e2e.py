"""P2-12 Step 2: end-to-end admin flow verification.

Single test function exercising the full admin flow: login → create
gallery → update → add root → wait for scan → rescan → browse-fs →
status → audit → admin gallery detail → change-password → thumb-cache
purge. This mirrors the curl-based verification plan (P2-12 Step 2).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from myphoto.main import build_app


def test_e2e_admin_flow(tmp_path, capsys):
    photos = tmp_path / "photos"
    photos.mkdir()
    Image.new("RGB", (10, 10), (0, 0, 0)).save(photos / "a.jpg", "JPEG")

    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app, client=("127.0.0.1", 12345)) as c:
        out = capsys.readouterr().out
        match = re.search(r"password=(\S+)", out)
        assert match, f"password not found: {out!r}"
        pw = match.group(1)

        # 1. Login
        r = c.post("/api/auth/login", json={"username": "admin", "password": pw})
        assert r.status_code == 200

        # 2. Create gallery
        r = c.post("/api/admin/galleries", json={"name": "E2E", "description": "test"})
        assert r.status_code == 201
        gid = r.json()["id"]

        # 3. Update gallery
        r = c.patch(f"/api/admin/galleries/{gid}", json={"description": "updated"})
        assert r.status_code == 200
        assert r.json()["description"] == "updated"

        # 4. Browse-fs (default root)
        r = c.post("/api/admin/browse-fs", json={"path": ""})
        assert r.status_code == 200
        assert "entries" in r.json()

        # 5. Add root
        r = c.post(
            f"/api/admin/galleries/{gid}/roots",
            json={"label": "R", "absolute_path": str(photos)},
        )
        assert r.status_code == 201
        rid = r.json()["id"]

        # 6. Wait for auto-scan
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            sr = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status")
            if sr.json()["status"] == "idle":
                break
            time.sleep(0.2)
        assert sr.json()["status"] == "idle"

        # 7. Rescan
        r = c.post(f"/api/admin/galleries/{gid}/roots/{rid}/rescan")
        assert r.status_code == 200
        assert r.json()["status"] == "queued"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            sr = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status")
            if sr.json()["status"] == "idle":
                break
            time.sleep(0.2)

        # 8. Status
        r = c.get("/api/admin/status")
        assert r.status_code == 200
        s = r.json()
        assert s["stats"]["galleries"] >= 1
        assert s["stats"]["roots"] >= 1
        assert s["stats"]["images"] >= 1
        assert len(s["scan_statuses"]) >= 1

        # 9. Audit query — verify all expected actions are present
        r = c.get("/api/admin/audit")
        assert r.status_code == 200
        actions = [e["action"] for e in r.json()["entries"]]
        for a in [
            "login_success", "gallery_create", "gallery_update",
            "root_add", "scan_start", "scan_finish", "fs_browse",
        ]:
            assert a in actions, f"audit missing {a}: {actions}"

        # 10. Admin gallery detail (P2-11 endpoint)
        r = c.get(f"/api/admin/galleries/{gid}")
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == gid
        assert d["roots"][0]["absolute_path"] == str(photos.resolve())

        # 11. Change password
        new_pw = "new-pw-123456"
        r = c.post(
            "/api/auth/change-password",
            json={"old_password": pw, "new_password": new_pw},
        )
        assert r.status_code == 204
        # Old password rejected
        c.post("/api/auth/logout")
        r = c.post("/api/auth/login", json={"username": "admin", "password": pw})
        assert r.status_code == 401
        # New password works
        r = c.post("/api/auth/login", json={"username": "admin", "password": new_pw})
        assert r.status_code == 200

        # 12. Thumb-cache purge
        r = c.post("/api/admin/thumb-cache/purge")
        assert r.status_code == 204