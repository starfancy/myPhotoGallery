import asyncio
from pathlib import Path

import pytest
from PIL import Image as PILImage

from myphoto.thumbnails import ALLOWED_SIZES, ThumbnailGenerator, ThumbnailError


def _jpg(p: Path, size=(800, 600)):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", size, (100, 150, 200)).save(p, "JPEG")


def _jpg_with_orientation(p: Path, size=(800, 600), orientation=6):
    """写一个像素为横版、但带 EXIF Orientation 的 JPEG（模拟相机竖拍）。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.new("RGB", size, (100, 150, 200))
    exif = img.getexif()
    exif[0x0112] = orientation  # 6 = 顺时针 90°
    img.save(p, "JPEG", exif=exif.tobytes())


async def test_ensure_creates_cache(tmp_path):
    src = tmp_path / "in.jpg"
    _jpg(src)
    gen = ThumbnailGenerator(tmp_path / "cache")
    out = await gen.ensure("abc123", 200, str(src), is_raw=False)
    assert out.exists()
    with PILImage.open(out) as im:
        assert max(im.size) <= 200


async def test_ensure_is_idempotent(tmp_path):
    src = tmp_path / "in.jpg"
    _jpg(src)
    gen = ThumbnailGenerator(tmp_path / "cache")
    p1 = await gen.ensure("abc", 200, str(src), is_raw=False)
    mtime1 = p1.stat().st_mtime_ns
    p2 = await gen.ensure("abc", 200, str(src), is_raw=False)
    assert p1 == p2
    assert p1.stat().st_mtime_ns == mtime1  # 未重新生成


async def test_cache_layout(tmp_path):
    gen = ThumbnailGenerator(tmp_path / "cache")
    p = gen.cache_path("abcdef1234", 400)
    assert p.parts[-3:] == ("ab", "abcdef1234", "400.jpg")


async def test_rejects_disallowed_size(tmp_path):
    src = tmp_path / "in.jpg"
    _jpg(src)
    gen = ThumbnailGenerator(tmp_path / "cache")
    with pytest.raises(ValueError):
        await gen.ensure("abc", 999, str(src), is_raw=False)


async def test_unidentifiable_source_raises(tmp_path):
    (tmp_path / "bad.jpg").write_bytes(b"not-an-image")
    gen = ThumbnailGenerator(tmp_path / "cache")
    with pytest.raises(ThumbnailError):
        await gen.ensure("abc", 200, str(tmp_path / "bad.jpg"), is_raw=False)


def test_allowed_sizes_frozen():
    assert 200 in ALLOWED_SIZES and 400 in ALLOWED_SIZES and 1600 in ALLOWED_SIZES


async def test_thumbnail_applies_exif_orientation(tmp_path):
    # 相机竖拍：像素按传感器横版存储 (800x600)，Orientation=6 标记旋转 90°。
    # 缩略图必须按标签转正为竖版，否则竖版照片预览显示为横版。
    src = tmp_path / "portrait.jpg"
    _jpg_with_orientation(src, orientation=6)
    gen = ThumbnailGenerator(tmp_path / "cache")
    out = await gen.ensure("abc", 200, str(src), is_raw=False)
    with PILImage.open(out) as im:
        assert max(im.size) <= 200
        assert im.size[1] > im.size[0]  # 高 > 宽（竖版）


async def test_thumbnail_orientation_1_keeps_landscape(tmp_path):
    # Orientation=1（正常）时不旋转：横版像素仍出横版缩略图
    src = tmp_path / "landscape.jpg"
    _jpg_with_orientation(src, orientation=1)
    gen = ThumbnailGenerator(tmp_path / "cache")
    out = await gen.ensure("abc", 200, str(src), is_raw=False)
    with PILImage.open(out) as im:
        assert im.size[0] > im.size[1]  # 宽 > 高（横版）
