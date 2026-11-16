"""打标图像预处理纯函数：与模型运行时无关，可直接单测。"""

from __future__ import annotations

from PIL import Image as PILImage

# CLIP ViT-B/32 处理器目标 shortest_edge=224
# （见 backend/models/clip-vit-base-patch32/preprocessor_config.json）。
CLIP_SHORTEST_EDGE = 224

# 打标解码最短边地板（px）：仅当原图最短边超过该值才启用 DCT 降分辨率解码。
TAG_DECODE_FLOOR = 1600


def resize_shortest_edge(
    img: PILImage.Image,
    size: int,
    resample=PILImage.BICUBIC,
) -> PILImage.Image:
    """等比缩放使最短边恰好为 size，保持长宽比。

    取整规则近似 CLIPProcessor：scale = size / min(w, h)，新边长
    round(w*scale) / round(h*scale)（HF 处理器对长边用 int() 截断，
    差异 ≤1px，下游中心裁剪不可感）。已是目标尺寸时原样返回，
    避免无意义的像素拷贝。
    """
    w, h = img.size
    if min(w, h) == size:
        return img
    scale = size / min(w, h)
    return img.resize(
        (max(1, round(w * scale)), max(1, round(h * scale))),
        resample,
    )
