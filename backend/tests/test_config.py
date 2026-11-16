import tomllib

from myphoto.core.config import (
    AppConfig,
    DEFAULT_CONFIG_PATH,
    PROJECT_ROOT,
    load_or_init,
    resolve_config_path,
)


def test_project_root_points_at_repo_root():
    # 回归：包重组把 config.py 下移到 core/ 后，__file__ 的 parents 层级
    # 一度错位，默认 config.toml 被建到 backend/ 下而非项目根。
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert DEFAULT_CONFIG_PATH == PROJECT_ROOT / "config.toml"


def test_default_config_path_is_cwd_independent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_config_path(None) == DEFAULT_CONFIG_PATH


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


# ---- P4: [security] section (spec §9) ----

def test_security_defaults_when_missing(tmp_path):
    """未指定 [security] 段时使用默认值。"""
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.trusted_proxies == []
    assert cfg.login_lockout_threshold == 5
    assert cfg.login_lockout_minutes == 15


def test_security_section_is_read(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        '[security]\n'
        'trusted_proxies = ["127.0.0.1", "10.0.0.0/8", "::1"]\n'
        'login_lockout_threshold = 10\n'
        'login_lockout_minutes = 30\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.trusted_proxies == ["127.0.0.1", "10.0.0.0/8", "::1"]
    assert cfg.login_lockout_threshold == 10
    assert cfg.login_lockout_minutes == 30


def test_default_template_contains_security_section(tmp_path):
    """首启动自动生成的 config.toml 应包含 [security] 段。"""
    p = tmp_path / "config.toml"
    load_or_init(p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert "security" in data
    assert data["security"]["trusted_proxies"] == []
    assert data["security"]["login_lockout_threshold"] == 5
    assert data["security"]["login_lockout_minutes"] == 15


# ---- [scanner] section ----

def test_scanner_defaults_when_missing(tmp_path):
    """未指定 [scanner] 段时 hash_workers 为 None（沿用源码内置默认）。"""
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.scanner_hash_workers is None


def test_scanner_section_is_read(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        '[scanner]\nhash_workers = 4\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.scanner_hash_workers == 4


def test_scanner_non_positive_workers_falls_back_to_none(tmp_path):
    """0 或负数视为未配置，回退源码默认。"""
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        '[scanner]\nhash_workers = 0\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.scanner_hash_workers is None


def test_default_template_contains_scanner_section(tmp_path):
    """首启动自动生成的 config.toml 应包含 [scanner] 段；key 默认注释掉，
    由源码默认值生效。"""
    p = tmp_path / "config.toml"
    load_or_init(p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert "scanner" in data
    assert data["scanner"].get("hash_workers") is None
    assert load_or_init(p).scanner_hash_workers is None


# ---------- [tagging].device ----------

_SECRET = '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'


def test_tagging_device_defaults_to_auto(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(_SECRET, encoding="utf-8")
    assert load_or_init(p).tagging_device == "auto"


def test_tagging_device_reads_three_valid_values(tmp_path):
    for value in ("auto", "cpu", "cuda"):
        p = tmp_path / "config.toml"
        p.write_text(_SECRET + f"[tagging]\ndevice = {value!r}\n", encoding="utf-8")
        assert load_or_init(p).tagging_device == value


def test_tagging_device_unknown_value_falls_back_to_auto(tmp_path, caplog):
    p = tmp_path / "config.toml"
    p.write_text(_SECRET + '[tagging]\ndevice = "tpu"\n', encoding="utf-8")
    with caplog.at_level("WARNING"):
        cfg = load_or_init(p)
    assert cfg.tagging_device == "auto"
    assert "device" in caplog.text.lower()


def test_default_template_contains_tagging_device_hint(tmp_path):
    p = tmp_path / "config.toml"
    load_or_init(p)
    text = p.read_text(encoding="utf-8")
    assert "[tagging]" in text
    assert "device" in text
