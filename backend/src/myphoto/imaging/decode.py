"""统一图像解码入口：缩略图生成与智能打标共用同一套解码逻辑。

- 普通图（JPEG/PNG/HEIC/...）：Pillow 解码 + EXIF Orientation 转正 + RGB
- RAW（.orf/.cr2/.nef/.arw/...）：rawpy 优先取相机内嵌 JPEG 预览（同样
  转正），无可用预览时全量 demosaic（postprocess）兜底
- HEIF/HEIC opener 只在此处注册一次，替代此前 scanner/thumbnails 的重复注册

设计文档：docs/tags-upgrade-design.md §6（打标图像输入策略）。
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage, ImageOps, UnidentifiedImageError

log = logging.getLogger("myphoto.imaging")

# 全项目唯一的 HEIF opener 注册点（导入本模块即生效）
try:
    import pillow_heif  # type: ignore[import-not-found]

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - 可选解码器缺失时静默
    pass


class ImageDecodeError(Exception):
    """统一解码异常：缩略图层包装为 ThumbnailError，打标层落 tag_error。"""


def load_pil_image(source: str | Path, is_raw: bool) -> PILImage.Image:
    """把磁盘图片解码为已 EXIF 转正的全分辨率 RGB PIL 图像（不做缩放）。

    返回对象的文件句柄已关闭、像素驻留内存，调用方可继续模型推理或缩放；
    解码失败统一抛 ImageDecodeError。
    """
    try:
        if is_raw:
            return _load_raw(str(source))
        return _load_regular(str(source))
    except ImageDecodeError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as exc:
        raise ImageDecodeError(f"image decode failed for {source}: {exc}") from exc


def _load_regular(source: str) -> PILImage.Image:
    with PILImage.open(source) as im:
        # 相机直出图竖拍仅靠 Orientation 标记；先转正，打标与缩略图方向才一致
        im = ImageOps.exif_transpose(im)
        if im.mode != "RGB":
            im = im.convert("RGB")
        im.load()  # 在 with 关闭句柄前把像素载入内存
        return im


def _load_raw(source: str) -> PILImage.Image:
    import rawpy

    try:
        with rawpy.imread(source) as raw:
            # 优先内嵌 JPEG 预览：省 demosaic 开销，且含相机原厂 EXIF
            try:
                thumb = raw.extract_thumb()
            except Exception:
                thumb = None
            if thumb is not None and getattr(thumb.format, "name", "") == "JPEG":
                with PILImage.open(BytesIO(thumb.data)) as im:
                    im = ImageOps.exif_transpose(im)
                    if im.mode != "RGB":
                        im = im.convert("RGB")
                    im.load()
                    return im
            # 无内嵌预览（或非 JPEG）：全量解 RAW
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, output_bps=8)
    except ImageDecodeError:
        raise
    except Exception as exc:
        raise ImageDecodeError(f"RAW decode failed for {source}: {exc}") from exc
    return PILImage.fromarray(rgb).convert("RGB")
