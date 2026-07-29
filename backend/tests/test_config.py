import tomllib

from myphoto.config import AppConfig, DEFAULT_CONFIG_PATH, load_or_init, resolve_config_path


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


def test_relative_data_dir_resolves_from_config_directory(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        'data_dir="db"\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.data_dir == str((tmp_path / "db").resolve())


def test_absolute_data_dir_stays_absolute(tmp_path):
    target = (tmp_path / "external-data").resolve()
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        f'data_dir="{target.as_posix()}"\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.data_dir == str(target)


def test_omitted_data_dir_defaults_to_config_directory(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.data_dir == str(tmp_path)


def test_default_config_path_is_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_config_path() == DEFAULT_CONFIG_PATH
    assert DEFAULT_CONFIG_PATH.name == "config.toml"


def test_explicit_config_path_is_resolved_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    explicit = tmp_path / "nested" / "config.toml"
    resolved = resolve_config_path(str(explicit))
    assert resolved == explicit.resolve()


def test_trash_defaults_when_missing(tmp_path):
    """未指定 [trash] 段时使用默认值。"""
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.trash_retention_days == 30
    assert cfg.trash_purge_hour == 3
    assert cfg.trash_purge_minute == 30


def test_trash_section_is_read(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        '[trash]\nretention_days=7\npurge_hour=4\npurge_minute=15\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.trash_retention_days == 7
    assert cfg.trash_purge_hour == 4
    assert cfg.trash_purge_minute == 15


def test_default_template_contains_trash_section(tmp_path):
    p = tmp_path / "config.toml"
    load_or_init(p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert "trash" in data
    assert data["trash"]["retention_days"] == 30
