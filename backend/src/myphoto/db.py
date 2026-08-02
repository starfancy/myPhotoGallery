from __future__ import annotations

import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from myphoto.models import Base

_log = logging.getLogger("myphoto.db")


# Lightweight column migrations for pre-existing tables.
# create_all() only creates missing tables; it will NOT add columns to a table
# that already exists in the DB. When we add a new column to an ORM model we
# must also declare it here so old databases upgrade in place.
#
# Format: table_name -> list of (column_name, column_ddl_type). All new columns
# MUST be nullable (or have a DEFAULT) — SQLite ALTER TABLE ADD COLUMN cannot
# add a NOT NULL column without a default.
_COLUMN_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "images": [
        ("exif_json", "TEXT"),  # Phase 3 — EXIF metadata JSON blob
    ],
}


async def _apply_column_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for table, columns in _COLUMN_MIGRATIONS.items():
            # PRAGMA table_info returns rows (cid, name, type, notnull, dflt_value, pk)
            rows = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).all()
            if not rows:
                # Table doesn't exist yet — create_all() will have made it with
                # every column from the model, nothing to migrate.
                continue
            existing = {r[1] for r in rows}
            for col_name, col_type in columns:
                if col_name in existing:
                    continue
                _log.info("migrate: ALTER TABLE %s ADD COLUMN %s %s", table, col_name, col_type)
                await conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"
                )


async def make_engine(db_url: str) -> AsyncEngine:
    engine = create_async_engine(db_url, future=True)
    # SQLite requires PRAGMA foreign_keys=ON per connection to honor
    # ForeignKey(ondelete="CASCADE") declared in the ORM. Without it, the
    # ondelete clause is inert (in schema but never fires on DELETE).
    # aiosqlite wraps a sync engine — listen on that for the per-connection
    # PRAGMA so cascade deletes actually fire.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL allows readers while a writer is active; busy_timeout makes a
            # writer wait for the lock instead of raising "database is locked"
            # immediately. :memory: databases do not support WAL — tolerate that.
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
            except Exception:
                pass
        finally:
            cursor.close()
    return engine


async def make_sessionmaker(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _apply_column_migrations(engine)
