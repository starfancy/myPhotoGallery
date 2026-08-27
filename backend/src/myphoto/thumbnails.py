from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from PIL import Image as PILImage, ImageOps, UnidentifiedImageError

log = logging.getLogger("myphoto.thumbnails")

try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:
    pass

ALLOWED_SIZES: frozenset[int] = frozenset({200, 400, 1600})


class ThumbnailError(Exception):
    pass


class ThumbnailGenerator:
    def __init__(self, cache_dir: str | Path):
        self._cache = Path(cache_dir)

    def cache_path(self, sha1: str, size: int) -> Path:
        return self._cache / sha1[:2] / sha1 / f"{size}.jpg"

    async def ensure(self, sha1: str, size: int, source_path: str, is_raw: bool) -> Path:
        if size not in ALLOWED_SIZES:
            raise ValueError(f"size {size} not allowed")
        out = self.cache_path(sha1, size)
        if out.exists():
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        # CPU-bound: offload to thread
        await asyncio.to_thread(_render_thumb, source_path, size, out, is_raw)
        return out


def _render_thumb(source: str, size: int, out: Path, is_raw: bool) -> None:
    try:
        if is_raw:
            _render_raw(source, size, out)
        else:
            _render_regular(source, size, out)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ThumbnailError(str(exc)) from exc


def _render_regular(source: str, size: int, out: Path) -> None:
    with PILImage.open(source) as im:
        # 相机直出 JPEG/HEIC 的像素按传感器方向存储（传感器通常为横版），
        # 竖拍仅靠 EXIF Orientation 标签标记；Pillow 不会自动旋转。必须先
        # 按标签转正再缩放——转出的 JPEG 不带 EXIF，浏览器也无法补救。
        # （Photoshop 等后期软件导出时已把旋转烘焙进像素、Orientation=1，
        # 不受影响。）
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.thumbnail((size, size), PILImage.Resampling.LANCZOS)
        im.save(out, "JPEG", quality=85, optimize=True)


def _render_raw(source: str, size: int, out: Path) -> None:
    import rawpy
    try:
        with rawpy.imread(source) as raw:
            try:
                thumb = raw.extract_thumb()
                if thumb.format.name == "JPEG":
                    from io import BytesIO
                    with PILImage.open(BytesIO(thumb.data)) as im:
                        # 内嵌预览 JPEG 同样带 EXIF Orientation，需先转正
                        im = ImageOps.exif_transpose(im)
                        im.thumbnail((size, size), PILImage.Resampling.LANCZOS)
                        im.save(out, "JPEG", quality=85, optimize=True)
                    return
            except Exception:
                pass
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, output_bps=8)
            im = PILImage.fromarray(rgb)
            im.thumbnail((size, size), PILImage.Resampling.LANCZOS)
            im.save(out, "JPEG", quality=85, optimize=True)
    except Exception as exc:
        raise ThumbnailError(f"RAW render failed: {exc}") from exc
