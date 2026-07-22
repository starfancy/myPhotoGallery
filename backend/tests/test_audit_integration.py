from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import select

from myphoto.cli import cli
from myphoto.main import build_app
from myphoto.models import AuditLog


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (60, 40), (0, 0, 0)).save(p, "JPEG")


@pytest.fixture
def app_with_client(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        yield c, tmp_path, pw


def _audit(client, action: str) -> list[AuditLog]:
    app = client.app

    async def _fetch():
        sm = app.state.sessionmaker
        async with sm() as s:
            rows = (
                await s.execute(
                    select(AuditLog)
                    .where(AuditLog.action == action)
                    .order_by(AuditLog.id.desc())
                )
            ).scalars().all()
            return rows

    return client.portal.call(_fetch)


# ---- login ----


def test_login_success_writes_audit(app_with_client):
    c, _, pw = app_with_client
    r = c.post("/api/auth/login", json={"username": "admin", "password": pw})
    assert r.status_code == 200

    rows = _audit(c, "login_success")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_user_id == 1  # bootstrap admin
    assert row.actor_ip == "testclient"  # httpx TestClient default
    assert row.target == "user:1"


def test_login_fail_writes_audit(app_with_client):
    c, _, _ = app_with_client
    r = c.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert r.status_code == 401

    rows = _audit(c, "login_fail")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_user_id is None
    assert row.actor_ip == "testclient"
    assert row.target == "username=admin"


def test_login_fail_unknown_user_also_audits(app_with_client):
    c, _, _ = app_with_client
    r = c.post("/api/auth/login", json={"username": "ghost", "password": "whatever"})
    assert r.status_code == 401

    rows = _audit(c, "login_fail")
    assert len(rows) == 1
    assert rows[0].target == "username=ghost"


# ---- scanner ----


def test_scan_lifecycle_writes_start_and_finish(app_with_client):
    """Add a root; wait for scan to complete; verify scan_start + scan_finish."""
    c, tmp_path, pw = app_with_client
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")

    c.post("/api/auth/login", json={"username": "admin", "password": pw})
    gid = c.post("/api/admin/galleries", json={"name": "G"}).json()["id"]
    rid = c.post(
        f"/api/admin/galleries/{gid}/roots",
        json={"label": "R", "absolute_path": str(photos)},
    ).json()["id"]

    # Wait for the automatic scan (triggered by root creation) to finish.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        sr = c.get(f"/api/admin/galleries/{gid}/roots/{rid}/scan-status")
        if sr.json()["status"] == "idle":
            break
        time.sleep(0.2)

    starts = _audit(c, "scan_start")
    finishes = _audit(c, "scan_finish")
    assert len(starts) >= 1
    assert len(finishes) >= 1
    assert starts[-1].actor_user_id is None
    assert starts[-1].actor_ip == "127.0.0.1"
    assert starts[-1].target == f"root:{rid}"
    assert finishes[-1].target == f"root:{rid}"
    assert "last_scan_at=" in (finishes[-1].detail or "")


def test_scan_error_writes_audit(app_with_client):
    """Manually run the scanner against a non-existent root; expect scan_error audit."""
    c, _, _ = app_with_client
    app = c.app

    async def _run_bad_scan():
        # Insert a root pointing to a missing path directly via ORM,
        # then invoke scanner.scan_root_now. The scan_transaction will raise.
        sm = app.state.sessionmaker
        from myphoto.models import Gallery, GalleryRoot
        async with sm() as s:
            g = Gallery(name="Broken", description=None, created_at=int(time.time()))
            s.add(g)
            await s.flush()
            r = GalleryRoot(
                gallery_id=g.id, label="X",
                absolute_path=str(Path("/definitely/not/a/real/path")),
                enabled=1,
            )
            s.add(r)
            await s.commit()
            rid = r.id
        await app.state.scanner.scan_root_now(rid)
        return rid

    rid = c.portal.call(_run_bad_scan)

    errors = _audit(c, "scan_error")
    assert len(errors) >= 1
    assert errors[-1].target == f"root:{rid}"
    assert errors[-1].actor_ip == "127.0.0.1"


# ---- CLI ----


def test_cli_add_gallery_writes_audit(tmp_path):
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    r = runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    assert r.exit_code == 0, r.output

    # Open the DB directly to inspect audit rows.
    from myphoto.config import load_or_init
    from myphoto.db import make_engine, make_sessionmaker

    async def _fetch():
        loaded = load_or_init(str(cfg))
        db = Path(loaded.data_dir) / "app.db"
        engine = await make_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
        sm = await make_sessionmaker(engine)
        try:
            async with sm() as s:
                rows = (
                    await s.execute(
                        select(AuditLog).where(AuditLog.action == "gallery_create")
                    )
                ).scalars().all()
                return [(r.actor_user_id, r.actor_ip, r.target, r.detail) for r in rows]
        finally:
            await engine.dispose()

    rows = asyncio.run(_fetch())
    assert len(rows) == 1
    actor_user_id, actor_ip, target, detail = rows[0]
    assert actor_user_id is None
    assert actor_ip == "cli"
    assert target and target.startswith("gallery:")
    assert "name=Home" in (detail or "")


def test_cli_add_root_writes_audit(tmp_path):
    cfg = tmp_path / "config.toml"
    photos = tmp_path / "photos"
    photos.mkdir()

    runner = CliRunner()
    r = runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(
        cli, ["--config", str(cfg), "add-root", "Home", "Main", str(photos.resolve())]
    )
    assert r.exit_code == 0, r.output

    from myphoto.config import load_or_init
    from myphoto.db import make_engine, make_sessionmaker

    async def _fetch():
        loaded = load_or_init(str(cfg))
        db = Path(loaded.data_dir) / "app.db"
        engine = await make_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
        sm = await make_sessionmaker(engine)
        try:
            async with sm() as s:
                rows = (
                    await s.execute(
                        select(AuditLog).where(AuditLog.action == "root_add")
                    )
                ).scalars().all()
                return [(r.actor_user_id, r.actor_ip, r.target, r.detail) for r in rows]
        finally:
            await engine.dispose()

    rows = asyncio.run(_fetch())
    assert len(rows) == 1
    actor_user_id, actor_ip, target, detail = rows[0]
    assert actor_user_id is None
    assert actor_ip == "cli"
    assert target and target.startswith("root:")
    assert "gallery=Home" in (detail or "")
    assert "label=Main" in (detail or "")


# ---- gallery CRUD audit visibility via /api/admin/audit ----


def test_gallery_crud_audit_visible_via_audit_endpoint(app_with_client):
    """End-to-end: gallery create/update/delete audits show up in the query endpoint."""
    c, _, pw = app_with_client
    c.post("/api/auth/login", json={"username": "admin", "password": pw})

    gid = c.post("/api/admin/galleries", json={"name": "Alpha"}).json()["id"]
    c.patch(f"/api/admin/galleries/{gid}", json={"description": "updated"})
    c.delete(f"/api/admin/galleries/{gid}")

    r = c.get("/api/admin/audit", params={"limit": 500})
    assert r.status_code == 200
    actions = [e["action"] for e in r.json()["entries"]]
    assert "gallery_create" in actions
    assert "gallery_update" in actions
    assert "gallery_delete" in actions
    # login_success from earlier is also there
    assert "login_success" in actions
