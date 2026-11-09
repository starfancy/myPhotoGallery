from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from myphoto.main import build_app


def _write_cube(d: Path, rel: str):
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("LUT_3D_SIZE 2\n0 0 0\n1 0 0\n")


@pytest.fixture
def client_with_luts(tmp_path, capsys):
    # 预置 luts 目录（build_app 之前写好）。
    # cfg.data_dir 解析为 config.toml 所在目录（= tmp_path），
    # 因此 luts 目录即 tmp_path/luts（Path(cfg.data_dir)/"luts"）。
    luts_dir = tmp_path / "luts"
    _write_cube(luts_dir, "fujifilm/velvia.cube")
    _write_cube(luts_dir, "synthetic/warm.cube")
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        yield c, tmp_path


def test_list_enabled_luts_grouped(client_with_luts):
    c, _ = client_with_luts
    # 两个 LUT 默认 disabled，先空列表
    r = c.get("/api/luts")
    assert r.status_code == 200
    assert r.json() == []

    # admin 启用两支
    c.patch("/api/admin/luts/velvia", json={"enabled": 1})
    c.patch("/api/admin/luts/warm", json={"enabled": 1})

    r = c.get("/api/luts")
    data = r.json()
    groups = {g["group"]: [i["slug"] for i in g["items"]] for g in data}
    assert groups == {"fujifilm": ["velvia"], "synthetic": ["warm"]}


def test_get_cube_text_enabled_only(client_with_luts):
    c, _ = client_with_luts
    # 未启用 → 404
    r = c.get("/api/luts/velvia/cube")
    assert r.status_code == 404

    c.patch("/api/admin/luts/velvia", json={"enabled": 1})
    r = c.get("/api/luts/velvia/cube")
    assert r.status_code == 200
    assert "LUT_3D_SIZE 2" in r.text


def test_get_cube_unknown_slug_404(client_with_luts):
    c, _ = client_with_luts
    r = c.get("/api/luts/nonexistent/cube")
    assert r.status_code == 404


def test_admin_rescan_discover_new_file(client_with_luts):
    c, tmp_path = client_with_luts
    # 运行时往 luts 目录丢新文件
    _write_cube(tmp_path / "luts", "fujifilm/astia.cube")
    r = c.post("/api/admin/luts/rescan")
    assert r.status_code == 200
    data = r.json()
    assert "fujifilm/astia.cube" in data["discovered"]

    # 立即出现在 admin 列表（默认 disabled）
    r = c.get("/api/admin/luts")
    slugs = [x["slug"] for x in r.json()]
    assert "astia" in slugs
