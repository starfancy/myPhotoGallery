from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from myphoto.config import load_or_init
from myphoto.config_writer import SettingsUpdates, update_settings_file


def _cfg(tmp_path: Path) -> Path:
    return tmp_path / "config.toml"


def test_updates_roundtrip_via_load_or_init(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)  # create default template

    update_settings_file(path, SettingsUpdates(
        trash_retention_days=90,
        login_lockout_threshold=3,
        trusted_proxies=["127.0.0.1", "10.0.0.0/8"],
        session_hours=24,
    ))

    cfg = load_or_init(path)
    assert cfg.trash_retention_days == 90
    assert cfg.login_lockout_threshold == 3
    assert cfg.trusted_proxies == ["127.0.0.1", "10.0.0.0/8"]
    assert cfg.session_hours == 24


def test_preserves_comments_blank_lines_and_unknown_keys(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)
    text = path.read_text(encoding="utf-8")
    assert "# myPhotoGallery config" in text
    # add an unknown managed-section key and a custom section
    path.write_text(
        text + '\n[custom]\nfoo = "bar"\nsession_hours_note = "keep me"\n',
        encoding="utf-8",
    )

    update_settings_file(path, SettingsUpdates(session_hours=12))

    after = path.read_text(encoding="utf-8")
    assert "# myPhotoGallery config" in after
    assert 'foo = "bar"' in after
    assert 'session_hours_note = "keep me"' in after
    # scanner default-template comment must survive
    assert "hash_workers" in after
    parsed = tomllib.loads(after)
    assert parsed["app"]["session_hours"] == 12
    assert parsed["custom"]["foo"] == "bar"


def test_none_fields_leave_file_unchanged(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)
    before = path.read_text(encoding="utf-8")
    update_settings_file(path, SettingsUpdates())
    assert path.read_text(encoding="utf-8") == before


def test_inserts_key_into_existing_section(tmp_path):
    path = _cfg(tmp_path)
    # [security] exists but without the lockout key (simulate hand-edited file)
    path.write_text(
        '[app]\njwt_secret = "abcdef"\nsession_hours = 8\n\n'
        '[trash]\nretention_days = 30\n\n'
        '[security]\ntrusted_proxies = []\n',
        encoding="utf-8",
    )
    update_settings_file(path, SettingsUpdates(login_lockout_threshold=7))
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["security"]["login_lockout_threshold"] == 7
    assert parsed["security"]["trusted_proxies"] == []


def test_appends_missing_section(tmp_path):
    path = _cfg(tmp_path)
    path.write_text(
        '[app]\njwt_secret = "abcdef"\nsession_hours = 8\n',
        encoding="utf-8",
    )
    update_settings_file(path, SettingsUpdates(trash_retention_days=7))
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["trash"]["retention_days"] == 7
    assert parsed["app"]["session_hours"] == 8


def test_crlf_line_endings_preserved(tmp_path):
    path = _cfg(tmp_path)
    path.write_bytes(
        b'[app]\r\njwt_secret = "abcdef"\r\nsession_hours = 8\r\n'
        b'[trash]\r\nretention_days = 30\r\n'
    )
    update_settings_file(path, SettingsUpdates(session_hours=2))
    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")


def test_empty_proxy_list_renders_inline_array(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)
    update_settings_file(path, SettingsUpdates(trusted_proxies=[]))
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["security"]["trusted_proxies"] == []


def test_idempotent_update(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)
    upd = SettingsUpdates(trash_retention_days=0, session_hours=1)
    update_settings_file(path, upd)
    once = path.read_text(encoding="utf-8")
    update_settings_file(path, upd)
    assert path.read_text(encoding="utf-8") == once


def test_quotes_in_string_value_escaped(tmp_path):
    path = _cfg(tmp_path)
    load_or_init(path)
    update_settings_file(path, SettingsUpdates(trusted_proxies=['10.0.0.1", "bad']))
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["security"]["trusted_proxies"] == ['10.0.0.1", "bad']
