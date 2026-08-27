import asyncio
import json
import threading
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from PIL.TiffImagePlugin import IFDRational
from sqlalchemy import select

from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import Folder, Gallery, GalleryRoot, Image
from myphoto.scanner import (
    Scanner,
    _extract_exif_json,
    _process_file,
    _read_image_meta,
)


def _jpg(path: Path, w: int = 40, h: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (w, h), (10, 20, 30)).save(path, "JPEG")


def _jpg_with_exif(path: Path) -> None:
    """写一个含常见 EXIF 字段的 JPEG，覆盖顶层 IFD + EXIF sub-IFD + GPS。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.new("RGB", (60, 40), (0, 0, 0))
    exif = img.getexif()
    # 顶层 IFD
    exif[0x010F] = "Nikon"
    exif[0x0110] = "Z6"
    exif[0x0112] = 1
    exif[0x0131] = "Test/1.0"
    exif[0x0132] = "2026:01:15 14:32:00"
    # EXIF sub-IFD
    sub = exif.get_ifd(0x8769)
    sub[0x9003] = "2026:01:15 14:32:00"
    sub[0x829A] = IFDRational(1, 250)  # 快门 1/250
    sub[0x829D] = IFDRational(40, 10)  # 光圈 f/4.0
    sub[0x8827] = 400  # ISO
    sub[0x920A] = IFDRational(50, 1)  # 焦距 50mm
    sub[0xA434] = "NIKKOR 50mm f/1.8"
    sub[0x9209] = 16
    sub[0xA403] = 0
    sub[0xA001] = 1
    sub[0x8822] = 3
    sub[0x9207] = 5
    sub[0x9204] = IFDRational(0, 1)
    sub[0xA406] = 0
    sub[0xA300] = 3
    # GPS sub-IFD
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (IFDRational(31, 1), IFDRational(14, 1), IFDRational(0, 1))
    gps[3] = "E"
    gps[4] = (IFDRational(121, 1), IFDRational(29, 1), IFDRational(0, 1))
    img.save(path, "JPEG", exif=exif.tobytes())


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


# ---------- EXIF extraction ----------


def test_process_file_returns_exif_for_jpg_with_exif(tmp_path):
    p = tmp_path / "a.jpg"
    _jpg_with_exif(p)
    sha1, w, h, taken_at, exif_json = _process_file(p, is_raw=False)
    assert sha1 and w == 60 and h == 40
    # DateTimeOriginal 2026-01-15 14:32:00 应转为 epoch（局部时区，不校验具体值，只校验 not None）
    assert taken_at is not None
    assert exif_json is not None
    data = json.loads(exif_json)
    assert data["Make"] == "Nikon"
    assert data["Model"] == "Z6"
    assert data["ExposureTime"] == "1/250"
    # FNumber f/4.0 ≥1 → float 4.0
    assert data["FNumber"] == 4.0
    assert data["ISOSpeedRatings"] == 400
    assert data["FocalLength"] == 50
    assert data["LensModel"] == "NIKKOR 50mm f/1.8"
    assert data["Orientation"] == 1
    assert data["Software"] == "Test/1.0"
    assert "GPSInfo" in data
    assert data["GPSInfo"].get("GPSLatitudeRef") == "N"
    assert data["GPSInfo"].get("GPSLongitudeRef") == "E"


def test_process_file_returns_none_exif_for_plain_jpg(tmp_path):
    p = tmp_path / "plain.jpg"
    _jpg(p)
    sha1, w, h, taken_at, exif_json = _process_file(p, is_raw=False)
    assert sha1 and w == 40 and h == 30
    assert taken_at is None
    assert exif_json is None


def _jpg_oriented(path: Path, orientation: int, size=(60, 40)) -> Path:
    """像素为横版 size、带指定 EXIF Orientation 的 JPEG（模拟相机竖拍）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.new("RGB", size, (0, 0, 0))
    exif = img.getexif()
    exif[0x0112] = orientation
    img.save(path, "JPEG", exif=exif.tobytes())
    return path


def test_read_image_meta_swaps_dims_for_rotated_orientation(tmp_path):
    # Orientation 5–8（90°/270° 旋转）：入库宽高必须交换为竖版
    for orientation in (5, 6, 7, 8):
        w, h, _taken, exif_json = _read_image_meta(
            _jpg_oriented(tmp_path / f"o{orientation}.jpg", orientation)
        )
        assert (w, h) == (40, 60), f"orientation={orientation}"
        assert json.loads(exif_json)["Orientation"] == orientation


def test_read_image_meta_keeps_dims_for_upright_orientation(tmp_path):
    # Orientation 1/3（0°/180°）：宽高不交换
    for orientation in (1, 3):
        w, h, _taken, _exif = _read_image_meta(
            _jpg_oriented(tmp_path / f"o{orientation}.jpg", orientation)
        )
        assert (w, h) == (60, 40), f"orientation={orientation}"


def test_extract_exif_json_serializes_only_whitelist(tmp_path):
    """确保未纳入白名单的 tag 不会被序列化。"""
    p = tmp_path / "extra.jpg"
    _jpg_with_exif(p)
    _, _, _, exif_json = _read_image_meta(p)
    data = json.loads(exif_json)
    # 只允许在白名单里的 key + GPSInfo
    allowed = {
        "Make", "Model", "DateTimeOriginal", "ModifyDate", "ExposureTime",
        "FNumber", "ISOSpeedRatings", "FocalLength", "LensModel", "GPSInfo",
        "Orientation", "Software", "Flash", "WhiteBalance", "ColorSpace",
        "ExposureProgram", "MeteringMode", "ExposureBiasValue",
        "SceneCaptureType", "FileSource",
    }
    assert set(data.keys()).issubset(allowed)


def test_extract_exif_json_returns_none_for_empty_exif():
    """空 exif 对象抽出为 None，不写空 dict。"""
    class _Fake:
        def items(self):
            return []

        def get_ifd(self, _):
            return {}

    assert _extract_exif_json(_Fake()) is None
    assert _extract_exif_json(None) is None


def test_extract_exif_json_survives_bad_values():
    """抽取遇到无法序列化的值应跳过而非抛异常。"""

    class _Fake:
        _items = {
            0x010F: "Sony",              # Make
            0x0110: b"\x00\x00broken",   # Model as bytes with NULs
            0x8827: 1600,                 # ISO
            0x9999: object(),            # 未知 tag（不会命中白名单，忽略）
        }

        def items(self):
            return list(self._items.items())

        def get(self, k):
            return self._items.get(k)

        def get_ifd(self, tag):
            return {}

    out = _extract_exif_json(_Fake())
    assert out is not None
    data = json.loads(out)
    assert data["Make"] == "Sony"
    assert data["Model"] == "broken"
    assert data["ISOSpeedRatings"] == 1600


async def test_status_exposes_progress_fields(env):
    _, sm, root_id = env
    scanner = Scanner(sm)

    status = scanner.get_status(root_id)
    # Idle baseline: keys present and zeroed/neutral.
    assert status["phase"] == "idle"
    assert status["total_files"] == 0
    assert status["processed_files"] == 0
    assert status["current_path"] is None
    assert "started_at" in status


async def test_progress_reset_on_audit_crash(env, monkeypatch):
    _, sm, root_id = env

    async def boom(*_args, **_kwargs):
        raise RuntimeError("audit down")

    scanner = Scanner(sm)
    monkeypatch.setattr(scanner, "_audit", boom)

    with pytest.raises(RuntimeError, match="audit down"):
        await scanner.scan_root_now(root_id)

    status = scanner.get_status(root_id)
    assert status["status"] == "idle"
    assert status["phase"] == "idle"
    assert status["started_at"] is None


async def test_scanner_writes_exif_json(env):
    root_dir, sm, root_id = env
    _jpg_with_exif(root_dir / "a.jpg")
    _jpg(root_dir / "b.jpg")

    await Scanner(sm).scan_root_now(root_id)

    async with sm() as session:
        rows = {r.filename: r for r in (
            await session.execute(select(Image))
        ).scalars().all()}
        assert rows["a.jpg"].exif_json is not None
        data = json.loads(rows["a.jpg"].exif_json)
        assert data["Make"] == "Nikon"
        assert data["ExposureTime"] == "1/250"
        assert rows["b.jpg"].exif_json is None


async def test_progress_advances_through_phases(env, monkeypatch):
    root_dir, sm, root_id = env
    for n in range(3):
        _jpg(root_dir / f"{n}.jpg")

    import myphoto.scanner as sc
    gate = threading.Event()
    calls = {"n": 0}
    real_process = sc._process_file

    def slow_process(path, is_raw):
        calls["n"] += 1
        if calls["n"] == 1:
            gate.wait(timeout=5)
        return real_process(path, is_raw)

    monkeypatch.setattr(sc, "_process_file", slow_process)

    scanner = Scanner(sm)
    scan_task = asyncio.create_task(scanner.scan_root_now(root_id))

    # Wait until the scan reaches the hashing phase on the first file.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        st = scanner.get_status(root_id)
        if st["status"] == "running" and st["phase"] == "hashing":
            break
        await asyncio.sleep(0.01)

    running = scanner.get_status(root_id)
    assert running["phase"] == "hashing"
    assert running["total_files"] == 3
    assert running["processed_files"] == 0
    assert running["current_path"] is not None
    assert running["started_at"] is not None

    gate.set()
    await asyncio.wait_for(scan_task, timeout=5)

    done = scanner.get_status(root_id)
    assert done["status"] == "idle"
    assert done["phase"] == "idle"
    assert done["processed_files"] == 3
    assert done["current_path"] is None


async def test_concurrent_write_succeeds_during_hashing(tmp_path, monkeypatch):
    """A2 guarantee: no write transaction is held while hashing files, so an
    unrelated write completes without 'database is locked'.

    Uses a file-backed DB (not :memory:) so the two sessions use distinct
    DBAPI connections and real SQLite write-lock contention applies. A
    regression that holds the write txn across hashing blocks the concurrent
    writer past busy_timeout and fails the wait_for.
    """
    import myphoto.scanner as sc
    from myphoto.models import Gallery, GalleryRoot

    db_path = tmp_path / "test.db"
    engine = await make_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    await create_all(engine)
    sm = await make_sessionmaker(engine)

    root_dir = tmp_path / "photos"
    root_dir.mkdir()
    for n in range(3):
        _jpg(root_dir / f"{n}.jpg")

    async with sm() as session:
        gallery = Gallery(name="G", created_at=int(time.time()))
        session.add(gallery)
        await session.flush()
        root = GalleryRoot(
            gallery_id=gallery.id, label="R",
            absolute_path=str(root_dir.resolve()), enabled=1,
        )
        session.add(root)
        await session.commit()
        await session.refresh(root)
        root_id = root.id

    gate = threading.Event()
    real_process = sc._process_file

    def slow_process(path, is_raw):
        gate.wait(timeout=5)
        return real_process(path, is_raw)

    monkeypatch.setattr(sc, "_process_file", slow_process)

    scanner = Scanner(sm)
    scan_task = asyncio.create_task(scanner.scan_root_now(root_id))

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        st = scanner.get_status(root_id)
        if st["phase"] == "hashing":
            break
        await asyncio.sleep(0.01)
    assert scanner.get_status(root_id)["phase"] == "hashing"

    # A second session/connection writes while hashing is blocked. The scan
    # holds no write txn, so this commits immediately; a long-txn regression
    # would block here until busy_timeout and trip the wait_for.
    async def _concurrent_write():
        async with sm() as session:
            session.add(Gallery(name="Concurrent", created_at=int(time.time())))
            await session.commit()

    await asyncio.wait_for(_concurrent_write(), timeout=3)

    gate.set()
    try:
        await asyncio.wait_for(scan_task, timeout=10)
    finally:
        await engine.dispose()
