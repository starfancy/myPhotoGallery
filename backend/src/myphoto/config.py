from __future__ import annotations

import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Union

# ---------- shared defaults (cwd-independent) ----------

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.toml"


def resolve_config_path(path: Union[str, Path, None] = None) -> Path:
    """Return the absolute path to the config file.

    - ``None`` → project-root ``config.toml`` (independent of cwd)
    - relative / absolute string or Path → resolved from cwd
    """
    if path is None:
        return DEFAULT_CONFIG_PATH
    return Path(path).expanduser().resolve()


# ---------- config model ----------


@dataclass
class AppConfig:
    listen_host: str
    listen_port: int
    jwt_secret: str
    session_hours: int
    data_dir: str  # directory holding  app.db  and  .cache/
    trash_retention_days: int  # 回收站保留天数，默认 30；决定 purge_after
    trash_purge_hour: int      # 定时清理小时（P4 会用到；本 phase 只在启动时清理）
    trash_purge_minute: int    # 定时清理分钟


_DEFAULT_TEMPLATE = """\
# myPhotoGallery config
[app]
listen_host = "0.0.0.0"
listen_port = 8080
jwt_secret = "{secret}"
session_hours = 8

[trash]
retention_days = 30
purge_hour = 3
purge_minute = 30
"""


def load_or_init(path: Union[str, Path]) -> AppConfig:
    p = resolve_config_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if not p.exists():
        secret = secrets.token_urlsafe(48)
        p.write_text(_DEFAULT_TEMPLATE.format(secret=secret), encoding="utf-8")

    data = tomllib.loads(p.read_text(encoding="utf-8"))
    app_section = data.get("app", {})
    trash_section = data.get("trash", {})

    # ---- data_dir resolution ----
    raw = app_section.get("data_dir")
    if raw is None:
        data_dir = p.parent.resolve()
    else:
        configured = Path(str(raw)).expanduser()
        if configured.is_absolute():
            data_dir = configured.resolve()
        else:
            data_dir = (p.parent / configured).resolve()

    return AppConfig(
        listen_host=app_section.get("listen_host", "0.0.0.0"),
        listen_port=int(app_section.get("listen_port", 8080)),
        jwt_secret=app_section["jwt_secret"],
        session_hours=int(app_section.get("session_hours", 8)),
        data_dir=str(data_dir),
        trash_retention_days=int(trash_section.get("retention_days", 30)),
        trash_purge_hour=int(trash_section.get("purge_hour", 3)),
        trash_purge_minute=int(trash_section.get("purge_minute", 30)),
    )
