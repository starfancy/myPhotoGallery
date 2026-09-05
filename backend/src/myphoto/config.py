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
    # P4: [security] section
    trusted_proxies: list[str]        # CIDR / 单 IP；空 = 不信任 X-Forwarded-For
    login_lockout_threshold: int      # 默认 5
    login_lockout_minutes: int        # 默认 15
    # [scanner] section
    scanner_hash_workers: int | None  # 扫描并发哈希/EXIF 线程数；None = 源码默认 min(8, CPU 核数)


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

[security]
trusted_proxies = []
login_lockout_threshold = 5
login_lockout_minutes = 15

[scanner]
# 扫描时并发计算 sha1 / 读取 EXIF 的工作线程数。
# 保持注释（默认）= 源码内置 min(8, CPU 核数)；
# 机械硬盘或网络盘（SMB/NFS）随机读抖动时可调小，如 2。
# hash_workers = 8
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
    security_section = data.get("security", {})
    scanner_section = data.get("scanner", {})

    # None / 缺失 / 非正数 → None，表示沿用源码内置默认（scanner._HASH_WORKERS）。
    hash_workers_raw = scanner_section.get("hash_workers")
    try:
        scanner_hash_workers = (
            int(hash_workers_raw) if hash_workers_raw is not None else None
        )
    except (TypeError, ValueError):
        scanner_hash_workers = None
    if scanner_hash_workers is not None and scanner_hash_workers < 1:
        scanner_hash_workers = None

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
        # P4: 解析 [security] 段；trusted_proxies 支持 CIDR 与单 IP，存为字符串列表
        #     运行时由 access._ip_in_trusted() 解析为 ip_network
        trusted_proxies=list(security_section.get("trusted_proxies", [])),
        login_lockout_threshold=int(security_section.get("login_lockout_threshold", 5)),
        login_lockout_minutes=int(security_section.get("login_lockout_minutes", 15)),
        scanner_hash_workers=scanner_hash_workers,
    )
