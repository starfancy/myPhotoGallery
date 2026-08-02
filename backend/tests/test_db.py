from pathlib import Path

from myphoto.db import make_engine


async def test_pragmas_applied_to_file_connection(tmp_path):
    db_path = tmp_path / "test.db"
    engine = await make_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    try:
        async with engine.connect() as conn:
            journal = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
            timeout = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
        assert str(journal).lower() == "wal"
        assert timeout >= 5000
    finally:
        await engine.dispose()


async def test_in_memory_engine_does_not_fail(tmp_path):
    # :memory: does not support WAL; engine construction + connect must still work.
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
    finally:
        await engine.dispose()
