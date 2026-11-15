from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from PIL import Image as PILImage

# 导入即注册 HEIF opener，并拿到统一解码入口（普通图/RAW、EXIF 转正逻辑唯一来源）
from myphoto.imaging import ImageDecodeError, load_pil_image

log = logging.getLogger("myphoto.thumbnails")

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
        # 解码逻辑与打标完全共用 myphoto.imaging（RAW 内嵌预览/demosaic、EXIF 转正）
        image = load_pil_image(source, is_raw)
    except ImageDecodeError as exc:
        raise ThumbnailError(str(exc)) from exc
    with image:
        image.thumbnail((size, size), PILImage.Resampling.LANCZOS)
        image.save(out, "JPEG", quality=85, optimize=True)
