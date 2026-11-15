from pathlib import Path

from fastapi.testclient import TestClient
from myphoto.main import build_app


def test_build_app_lifespan_creates_db_and_state(tmp_path):
    cfg_path = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg_path))
    assert cfg_path.exists()
    with TestClient(app) as client:
        # lifespan has fired: db file created by ensure_schema_and_admin
        assert (tmp_path / "app.db").exists()
        # app.state populated
        assert app.state.engine is not None
        assert app.state.sessionmaker is not None
        assert app.state.config is not None
        # health endpoint reachable
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


def test_build_app_honors_explicit_relative_data_dir(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        'data_dir="db"\n',
        encoding="utf-8",
    )
    app = build_app(config_path=cfg_path)
    with TestClient(app):
        db = tmp_path / "db" / "app.db"
        assert db.exists(), f"expected db at {db}"
        assert app.state.config.data_dir == str((tmp_path / "db").resolve())


def test_lifespan_survives_explicit_cuda_unavailable(tmp_path, monkeypatch):
    import onnxruntime as ort
    monkeypatch.setattr(ort, "get_available_providers", lambda: ["CPUExecutionProvider"])
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        '[tagging]\ndevice = "cuda"\n',
        encoding="utf-8",
    )
    app = build_app(config_path=str(cfg_path))
    with TestClient(app):  # 不抛异常即通过：打标禁用、服务照常启动
        assert (tmp_path / "app.db").exists()
