from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from myphoto.models import Base


async def make_engine(db_url: str) -> AsyncEngine:
    return create_async_engine(db_url, future=True)


async def make_sessionmaker(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
