from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from myphoto.lut_scanner import scan_luts
from myphoto.models import Base, Lut


@pytest.fixture
async def sm(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _write_cube(d: Path, rel: str):
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("LUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n")


def test_scan_discovers_new_files(tmp_path, sm):
    luts_dir = tmp_path / "luts"
    _write_cube(luts_dir, "fujifilm/velvia.cube")
    _write_cube(luts_dir, "synthetic/warm.cube")

    result = asyncio.run(scan_luts(sm, luts_dir))
    assert sorted(result.discovered) == ["fujifilm/velvia.cube", "synthetic/warm.cube"]

    async def check():
        async with sm() as s:
            from sqlalchemy import select
            rows = (await s.execute(select(Lut))).scalars().all()
            by_path = {r.file_path: r for r in rows}
            assert by_path["fujifilm/velvia.cube"].group == "fujifilm"
            assert by_path["fujifilm/velvia.cube"].slug == "velvia"
            assert by_path["fujifilm/velvia.cube"].enabled == 0  # 默认 disabled
            assert by_path["synthetic/warm.cube"].group == "synthetic"
    asyncio.run(check())


def test_scan_skips_existing_keeps_admin_changes(tmp_path, sm):
    luts_dir = tmp_path / "luts"
    _write_cube(luts_dir, "velvia.cube")
    async def seed():
        async with sm() as s:
            s.add(Lut(
                slug="velvia", label="自定义名", group="",
                file_path="velvia.cube", enabled=1, sort_order=5,
                source="", license="", created_at=int(time.time()),
            ))
            await s.commit()
    asyncio.run(seed())

    result = asyncio.run(scan_luts(sm, luts_dir))
    assert result.discovered == []
    assert "velvia.cube" in result.skipped_existing

    async def check():
        async with sm() as s:
            from sqlalchemy import select
            row = (await s.execute(select(Lut).where(Lut.slug == "velvia"))).scalar_one()
            assert row.label == "自定义名"  # 不覆盖
            assert row.enabled == 1
            assert row.sort_order == 5
    asyncio.run(check())


def test_scan_soft_deletes_missing_files(tmp_path, sm):
    luts_dir = tmp_path / "luts"
    _write_cube(luts_dir, "keep.cube")
    async def seed():
        async with sm() as s:
            s.add(Lut(
                slug="keep", label="keep", group="", file_path="keep.cube",
                enabled=1, sort_order=0, source="", license="", created_at=int(time.time()),
            ))
            s.add(Lut(
                slug="gone", label="gone", group="", file_path="gone.cube",
                enabled=1, sort_order=0, source="", license="", created_at=int(time.time()),
            ))
            await s.commit()
    asyncio.run(seed())

    result = asyncio.run(scan_luts(sm, luts_dir))
    assert "gone.cube" in result.soft_deleted

    async def check():
        async with sm() as s:
            from sqlalchemy import select
            gone = (await s.execute(select(Lut).where(Lut.slug == "gone"))).scalar_one()
            assert gone.enabled == 0  # 软删
            keep = (await s.execute(select(Lut).where(Lut.slug == "keep"))).scalar_one()
            assert keep.enabled == 1
    asyncio.run(check())


def test_scan_creates_dir_if_missing(tmp_path, sm):
    luts_dir = tmp_path / "nonexistent"
    result = asyncio.run(scan_luts(sm, luts_dir))
    assert result.discovered == []
    assert luts_dir.exists()
