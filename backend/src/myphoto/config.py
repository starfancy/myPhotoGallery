from __future__ import annotations

import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    listen_host: str
    listen_port: int
    jwt_secret: str
    session_hours: int
    data_dir: str  # directory holding app.db and .cache/


_DEFAULT_TEMPLATE = """# myPhotoGallery config
[app]
listen_host = "0.0.0.0"
listen_port = 8080
jwt_secret = "{secret}"
session_hours = 8
"""


def load_or_init(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.exists():
        secret = secrets.token_urlsafe(48)
        p.write_text(_DEFAULT_TEMPLATE.format(secret=secret), encoding="utf-8")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    app = data.get("app", {})
    return AppConfig(
        listen_host=app.get("listen_host", "0.0.0.0"),
        listen_port=int(app.get("listen_port", 8080)),
        jwt_secret=app["jwt_secret"],
        session_hours=int(app.get("session_hours", 8)),
        data_dir=str(p.parent.resolve()),
    )
