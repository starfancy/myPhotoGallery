"""P5: 行级更新 config.toml 中 AdminSettings 受管的少量键。

不使用 tomli_w：它会重排文件并丢失注释（config.toml 是给人看的运维文档）。
本模块按行替换 `key = value`，保留注释、空行、未知键与既有行尾；
渲染结果先过 tomllib 自校验，再用临时文件 + os.replace 原子落盘。
"""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*=")

# settings 字段 → (toml section, toml key)
_FIELD_MAP: dict[str, tuple[str, str]] = {
    "trash_retention_days": ("trash", "retention_days"),
    "login_lockout_threshold": ("security", "login_lockout_threshold"),
    "trusted_proxies": ("security", "trusted_proxies"),
    "session_hours": ("app", "session_hours"),
    "download_batch_limit": ("download", "batch_limit"),
}


@dataclass
class SettingsUpdates:
    trash_retention_days: int | None = None
    login_lockout_threshold: int | None = None
    trusted_proxies: list[str] | None = None
    session_hours: int | None = None
    download_batch_limit: int | None = None


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _render(value) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(f'"{_toml_escape(v)}"' for v in value) + "]"
    return str(int(value))


def update_settings_file(path: str | Path, updates: SettingsUpdates) -> None:
    p = Path(path)
    # newline="" disables universal-newline translation so the CRLF probe below
    # can see the file's real line endings (read_text would normalize them to \n).
    with open(p, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    newline = "\r\n" if "\r\n" in raw else "\n"
    ends_newline = raw.endswith("\n")
    lines = raw.splitlines()

    wanted: dict[tuple[str, str], str] = {}
    for field, value in vars(updates).items():
        if value is not None:
            wanted[_FIELD_MAP[field]] = _render(value)
    if not wanted:
        return

    # Map section name -> [header_line, end_line_exclusive) from the ORIGINAL
    # text; insertions are applied bottom-up so earlier indices stay valid.
    section_ranges: dict[str, tuple[int, int]] = {}
    headers: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m:
            headers.append((i, m.group(1).strip()))
    for idx, (line_i, name) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(lines)
        section_ranges[name] = (line_i, end)

    replaced: set[tuple[str, str]] = set()
    current_section = ""
    out: list[str] = []
    for line in lines:
        m_sec = _SECTION_RE.match(line)
        if m_sec:
            current_section = m_sec.group(1).strip()
            out.append(line)
            continue
        m_key = _KEY_RE.match(line)
        if m_key and (current_section, m_key.group(1)) in wanted:
            key_tuple = (current_section, m_key.group(1))
            out.append(f"{m_key.group(1)} = {wanted[key_tuple]}")
            replaced.add(key_tuple)
            continue
        out.append(line)

    # Group missing keys by section; existing sections get in-section inserts,
    # absent sections are appended at EOF as new blocks.
    missing: dict[str, list[tuple[str, str]]] = {}
    for key_tuple, rendered in wanted.items():
        if key_tuple not in replaced:
            missing.setdefault(key_tuple[0], []).append((key_tuple[1], rendered))

    insertions: list[tuple[int, list[str]]] = []  # (insert_at_index, lines)
    appends: list[str] = []
    for section, keys in missing.items():
        new_lines = [f"{key} = {rendered}" for key, rendered in keys]
        if section in section_ranges:
            _header, end = section_ranges[section]
            insertions.append((end, new_lines))
        else:
            appends.extend([f"[{section}]"] + new_lines)

    for at, new_lines in sorted(insertions, key=lambda x: x[0], reverse=True):
        out[at:at] = new_lines

    if appends:
        if out and out[-1] != "":
            out.append("")
        out.extend(appends)

    new_text = newline.join(out)
    if ends_newline:
        new_text += newline

    # Self-validate before touching disk: a broken render must never land.
    parsed = tomllib.loads(new_text)
    for (section, key) in wanted:
        assert key in parsed.get(section, {}), f"missing after render: [{section}] {key}"

    tmp = p.with_name(p.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        os.replace(tmp, p)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
