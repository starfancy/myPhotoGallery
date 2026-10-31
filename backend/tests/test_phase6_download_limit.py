import re
import tomllib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from myphoto.config import load_or_init
from myphoto.config_writer import SettingsUpdates, update_settings_file
from myphoto.main import build_app
from myphoto.models import AuditLog


@pytest.fixture
def client(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        r = c.post("/api/auth/login", json={"username": "admin", "password": pw})
        assert r.status_code == 200
        yield c, app, cfg


def test_default_limit_is_100(client):
    c, _, _ = client
    assert c.get("/api/admin/settings").json()["download_batch_limit"] == 100
    me = c.get("/api/auth/me").json()
    assert me["download_batch_limit"] == 100


def test_patch_limit_hot_reloads_and_audits(client):
    c, app, _ = client

    r = c.patch("/api/admin/settings", json={"download_batch_limit": 50})
    assert r.status_code == 200
    assert r.json()["download_batch_limit"] == 50
    assert c.get("/api/auth/me").json()["download_batch_limit"] == 50

    async def _last_audit():
        async with app.state.sessionmaker() as s:
            row = (
                await s.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))
            ).scalar_one()
            return row.action, row.detail

    action, detail = c.portal.call(_last_audit)
    assert action == "settings_update"
    assert "download_batch_limit" in detail


@pytest.mark.parametrize("bad", [9, 201, 0, -5])
def test_patch_rejects_out_of_range(client, bad):
    c, _, _ = client
    r = c.patch("/api/admin/settings", json={"download_batch_limit": bad})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_loader_defaults_when_section_missing(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[app]\njwt_secret = "x"\n', encoding="utf-8")
    assert load_or_init(cfg).download_batch_limit == 100


def test_loader_clamps_out_of_range_and_bad_type(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[app]\njwt_secret = "x"\n[download]\nbatch_limit = 999\n',
        encoding="utf-8",
    )
    assert load_or_init(cfg).download_batch_limit == 200

    cfg.write_text(
        '[app]\njwt_secret = "x"\n[download]\nbatch_limit = 1\n',
        encoding="utf-8",
    )
    assert load_or_init(cfg).download_batch_limit == 10

    cfg.write_text(
        '[app]\njwt_secret = "x"\n[download]\nbatch_limit = "oops"\n',
        encoding="utf-8",
    )
    assert load_or_init(cfg).download_batch_limit == 100


def test_writer_appends_download_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[app]\nlisten_port = 8080\n', encoding="utf-8")
    update_settings_file(p, SettingsUpdates(download_batch_limit=42))
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["download"]["batch_limit"] == 42


def test_fresh_config_template_contains_download_section(tmp_path):
    cfg = tmp_path / "config.toml"
    load_or_init(cfg)  # 首次初始化写出模板
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data["download"]["batch_limit"] == 100
