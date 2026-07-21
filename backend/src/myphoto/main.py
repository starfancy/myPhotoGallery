from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from sqlalchemy import select

from myphoto.config import AppConfig, load_or_init
from myphoto.db import make_engine, make_sessionmaker
from myphoto.errors import install_error_handlers
from myphoto.models import GalleryRoot
from myphoto.scanner import Scanner
from myphoto.schema_init import ensure_schema_and_admin
from myphoto.thumbnails import ThumbnailGenerator

log = logging.getLogger("myphoto.main")


def build_app(config_path: str = "config.toml") -> FastAPI:
    cfg = load_or_init(config_path)
    db_path = Path(cfg.data_dir) / "app.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = await make_engine(db_url)
        sm = await make_sessionmaker(engine)
        created, pw = await ensure_schema_and_admin(engine, sm)
        if created and pw:
            # printed once to stdout so operator can grab it
            print(f"[myphoto] initial admin created. username=admin password={pw}", flush=True)
        scanner = Scanner(sm)
        await scanner.start()
        async with sm() as session:
            roots = (
                await session.execute(
                    select(GalleryRoot).where(GalleryRoot.enabled == 1)
                )
            ).scalars()
            for root in roots:
                await scanner.enqueue(root.id)
        app.state.engine = engine
        app.state.sessionmaker = sm
        app.state.config = cfg
        app.state.scanner = scanner
        app.state.thumbnails = ThumbnailGenerator(
            Path(cfg.data_dir) / ".cache" / "thumbnails"
        )
        try:
            yield
        finally:
            await scanner.stop()
            await engine.dispose()

    app = FastAPI(title="myPhotoGallery", lifespan=lifespan)
    app.state.login_lockout = {}
    install_error_handlers(app)

    from myphoto.routes_auth import router as auth_router

    app.include_router(auth_router)

    from myphoto.routes_browse import router as browse_router

    app.include_router(browse_router)

    from myphoto.routes_media import router as media_router

    app.include_router(media_router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


async def get_state(request: Request) -> tuple[AppConfig, object]:
    return request.app.state.config, request.app.state.sessionmaker


# uvicorn entry: `uvicorn myphoto.main:app`
app = build_app(os.environ.get("MYPHOTO_CONFIG", "config.toml"))
