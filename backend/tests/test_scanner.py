import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from sqlalchemy import select

from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import Folder, Gallery, GalleryRoot, Image
from myphoto.scanner import Scanner


def _jpg(path: Path, w: int = 40, h: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (w, h), (10, 20, 30)).save(path, "JPEG")


@pytest.fixture
async def env(tmp_path):
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    root_dir = tmp_path / "photos"
    root_dir.mkdir()
    async with sm() as session:
        gallery = Gallery(name="G", created_at=int(time.time()))
        session.add(gallery)
        await session.flush()
        root = GalleryRoot(
            gallery_id=gallery.id,
            label="R",
            absolute_path=str(root_dir.resolve()),
            enabled=1,
        )
        session.add(root)
        await session.commit()
        await session.refresh(root)
        root_id = root.id
    yield root_dir, sm, root_id
    await engine.dispose()


async def test_indexes_images(env):
    root_dir, sm, root_id = env
    _jpg(root_dir / "a.jpg")
    _jpg(root_dir / "sub" / "b.JPG")
    (root_dir / "note.txt").write_text("x", encoding="utf-8")

    await Scanner(sm).scan_root_now(root_id)

    async with sm() as session:
        paths = sorted(
            row.relative_path for row in (await session.execute(select(Image))).scalars()
        )
        assert paths == ["a.jpg", "sub/b.JPG"]
        folders = sorted(
            row.relative_path for row in (await session.execute(select(Folder))).scalars()
        )
        assert "" in folders and "sub" in folders


async def test_removes_deleted(env):
    root_dir, sm, root_id = env
    image_path = root_dir / "a.jpg"
    _jpg(image_path)
    scanner = Scanner(sm)
    await scanner.scan_root_now(root_id)

    image_path.unlink()
    await scanner.scan_root_now(root_id)

    async with sm() as session:
        assert (await session.execute(select(Image))).scalars().all() == []


async def test_skips_hidden(env):
    root_dir, sm, root_id = env
    _jpg(root_dir / ".hidden" / "a.jpg")
    _jpg(root_dir / "ok" / "b.jpg")

    await Scanner(sm).scan_root_now(root_id)

    async with sm() as session:
        paths = [
            row.relative_path for row in (await session.execute(select(Image))).scalars()
        ]
        assert paths == ["ok/b.jpg"]


async def test_folder_counts(env):
    root_dir, sm, root_id = env
    _jpg(root_dir / "a.jpg")
    _jpg(root_dir / "sub" / "b.jpg")
    _jpg(root_dir / "sub" / "c.jpg")

    await Scanner(sm).scan_root_now(root_id)

    async with sm() as session:
        root_folder = (
            await session.execute(select(Folder).where(Folder.relative_path == ""))
        ).scalar_one()
        sub_folder = (
            await session.execute(select(Folder).where(Folder.relative_path == "sub"))
        ).scalar_one()
        assert root_folder.image_count == 1
        assert root_folder.descendant_count == 3
        assert sub_folder.image_count == 2
        assert sub_folder.descendant_count == 2


async def test_status_ok(env):
    _, sm, root_id = env
    scanner = Scanner(sm)

    await scanner.scan_root_now(root_id)

    status = scanner.get_status(root_id)
    assert status["status"] == "idle"
    assert status["last_scan_at"] is not None
    assert status["last_scan_error"] is None


async def test_missing_root_marks_error(tmp_path):
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as session:
        gallery = Gallery(name="G", created_at=1)
        session.add(gallery)
        await session.flush()
        root = GalleryRoot(
            gallery_id=gallery.id,
            label="R",
            absolute_path=str(tmp_path / "nope"),
            enabled=1,
        )
        session.add(root)
        await session.commit()
        await session.refresh(root)
        root_id = root.id

    scanner = Scanner(sm)
    await scanner.scan_root_now(root_id)

    assert scanner.get_status(root_id)["last_scan_error"] is not None
    await engine.dispose()


async def test_skips_corrupted_file_continues(env):
    root_dir, sm, root_id = env
    _jpg(root_dir / "valid.jpg")
    (root_dir / "truncated.jpg").write_bytes(b"\xff\xd8\xff\xe0truncated")
    scanner = Scanner(sm)

    await scanner.scan_root_now(root_id)

    async with sm() as session:
        paths = [
            row.relative_path for row in (await session.execute(select(Image))).scalars()
        ]
        root = await session.get(GalleryRoot, root_id)
        assert paths == ["valid.jpg"]
        assert root is not None
        assert root.last_scan_status == "ok"
        assert root.last_scan_error is None
    status = scanner.get_status(root_id)
    assert status["status"] == "idle"
    assert status["last_scan_error"] is None
