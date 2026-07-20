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
