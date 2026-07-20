import tomllib
from pathlib import Path
from myphoto.config import AppConfig, load_or_init


def test_creates_default_when_missing(tmp_path):
    p = tmp_path / "config.toml"
    cfg = load_or_init(p)
    assert p.exists()
    assert isinstance(cfg, AppConfig)
    assert cfg.listen_port == 8080
    assert cfg.session_hours == 8
    assert len(cfg.jwt_secret) >= 32
    assert cfg.data_dir == str(tmp_path)


def test_reads_existing(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\nlisten_host="127.0.0.1"\nlisten_port=9000\n'
        'jwt_secret="secret-value-of-sufficient-length-xxxxx"\nsession_hours=4\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.listen_host == "127.0.0.1"
    assert cfg.listen_port == 9000
    assert cfg.session_hours == 4
    assert cfg.jwt_secret.startswith("secret-value")


def test_generated_secret_written_to_file(tmp_path):
    p = tmp_path / "config.toml"
    cfg = load_or_init(p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["app"]["jwt_secret"] == cfg.jwt_secret
