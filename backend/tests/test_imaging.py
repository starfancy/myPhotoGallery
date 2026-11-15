"""统一解码模块 imaging：普通图 PIL+EXIF 转正，RAW 走 rawpy（预览优先）。

真实 RAW 文件不进 CI，RAW 分支用 monkeypatch sys.modules['rawpy'] 覆盖。
"""

import io
import sys

import numpy as np
import pytest
from PIL import Image as PILImage

from myphoto.imaging import ImageDecodeError, load_pil_image


def _jpg(path, size=(800, 600), orientation=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.new("RGB", size)
    if orientation is not None:
        exif = img.getexif()
        exif[0x0112] = orientation
        img.save(path, "JPEG", exif=exif.tobytes())
    else:
        img.save(path, "JPEG")


# ---------- 普通图 ----------

def test_load_regular_returns_rgb(tmp_path):
    p = tmp_path / "a.jpg"
    _jpg(p)
    im = load_pil_image(p, is_raw=False)
    assert im.mode == "RGB" and im.size == (800, 600)


def test_load_regular_applies_exif_orientation(tmp_path):
    p = tmp_path / "portrait.jpg"
    _jpg(p, orientation=6)
    im = load_pil_image(p, is_raw=False)
    assert im.size == (600, 800)  # 像素横版 + Orientation=6 → 转正为竖版


def test_load_regular_orientation_1_no_rotation(tmp_path):
    p = tmp_path / "a.jpg"
    _jpg(p, orientation=1)
    im = load_pil_image(p, is_raw=False)
    assert im.size == (800, 600)


def test_png_rgba_converts_to_rgb(tmp_path):
    p = tmp_path / "a.png"
    PILImage.new("RGBA", (10, 8)).save(p)
    im = load_pil_image(p, is_raw=False)
    assert im.mode == "RGB"


def test_corrupt_file_raises_decode_error(tmp_path):
    p = tmp_path / "bad.jpg"
    p.write_bytes(b"not-an-image")
    with pytest.raises(ImageDecodeError):
        load_pil_image(p, is_raw=False)


# ---------- RAW（fake rawpy） ----------

class _FakeRaw:
    def __init__(self, post_rgb, thumb=None, thumb_raises=False):
        self._post = post_rgb
        self._thumb = thumb
        self._raises = thumb_raises
        self.sizes = type("Sizes", (), {
            "width": post_rgb.shape[1], "height": post_rgb.shape[0],
        })()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_thumb(self):
        if self._raises:
            raise RuntimeError("no embedded thumb")
        return self._thumb

    def postprocess(self, **kwargs):
        return self._post


class _FakeRawPy:
    def __init__(self, fake_raw):
        self._raw = fake_raw

    def imread(self, path):
        return self._raw


@pytest.fixture
def rawpy_patch(monkeypatch):
    import rawpy  # 测试环境真实安装；仅借用其 ThumbFormat 枚举

    def install_raw(fake_raw):
        monkeypatch.setitem(sys.modules, "rawpy", _FakeRawPy(fake_raw))

    def install_module(module):
        monkeypatch.setitem(sys.modules, "rawpy", module)

    return install_raw, install_module, rawpy.ThumbFormat


def test_raw_embedded_jpeg_path_transposes(tmp_path, rawpy_patch):
    install_raw, _, thumb_fmt = rawpy_patch
    buf = io.BytesIO()
    img = PILImage.new("RGB", (800, 600))
    exif = img.getexif()
    exif[0x0112] = 6
    img.save(buf, "JPEG", exif=exif.tobytes())
    thumb = type("Thumb", (), {"data": buf.getvalue(), "format": thumb_fmt.JPEG})()
    install_raw(_FakeRaw(np.zeros((40, 60, 3), dtype=np.uint8), thumb=thumb))

    im = load_pil_image(tmp_path / "a.orf", is_raw=True)
    assert im.mode == "RGB"
    assert im.size == (600, 800)  # 内嵌 JPEG 同样 EXIF 转正


def test_raw_postprocess_fallback(tmp_path, rawpy_patch):
    install_raw, _, _ = rawpy_patch
    install_raw(_FakeRaw(np.zeros((30, 45, 3), dtype=np.uint8), thumb_raises=True))

    im = load_pil_image(tmp_path / "a.orf", is_raw=True)
    assert im.mode == "RGB"
    assert im.size == (45, 30)


def test_raw_failure_wrapped_as_decode_error(tmp_path, rawpy_patch):
    _install_raw, install_module, _thumb_fmt = rawpy_patch

    class _BoomRawPy(_FakeRawPy):
        def imread(self, path):
            raise RuntimeError("unsupported raw")

    install_module(_BoomRawPy(_FakeRaw(np.zeros((4, 4, 3), dtype=np.uint8))))
    with pytest.raises(ImageDecodeError):
        load_pil_image(tmp_path / "a.orf", is_raw=True)
