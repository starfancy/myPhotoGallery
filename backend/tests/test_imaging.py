"""统一解码模块 imaging：普通图 PIL+EXIF 转正，RAW 走 rawpy（预览优先）。

真实 RAW 文件不进 CI，RAW 分支用 monkeypatch sys.modules['rawpy'] 覆盖。
"""

import io
import sys

import numpy as np
import pytest
from PIL import Image as PILImage

from myphoto.imaging.decode import ImageDecodeError, load_pil_image


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


# ---------- DCT 降分辨率解码（target_shortest_edge） ----------

def test_jpeg_dct_halves_large_image(tmp_path):
    p = tmp_path / "big.jpg"
    _jpg(p, size=(3200, 2400))
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    # 最短边 2400 > 1600 → draft DCT 1/2，偶数尺寸精确减半
    assert im.mode == "RGB"
    assert im.size == (1600, 1200)


def test_jpeg_at_or_below_floor_is_not_drafted(tmp_path):
    # 守卫是严格大于：最短边恰等于地板不降；小图也不降
    p = tmp_path / "edge.jpg"
    _jpg(p, size=(1600, 1200))
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    assert im.size == (1600, 1200)


def test_jpeg_shortest_edge_equal_to_floor_is_not_drafted(tmp_path):
    # 等号边界：(2000,1600) 最短边恰好 1600，严格 > 守卫不触发 DCT 降分辨率
    p = tmp_path / "exact_floor.jpg"
    _jpg(p, size=(2000, 1600))
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    assert im.size == (2000, 1600)


def test_png_silently_ignores_target_and_keeps_full_size(tmp_path):
    p = tmp_path / "big.png"
    PILImage.new("RGB", (3200, 2400)).save(p)
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    assert im.size == (3200, 2400)


def test_default_none_keeps_legacy_full_resolution(tmp_path):
    p = tmp_path / "big.jpg"
    _jpg(p, size=(3200, 2400))
    assert load_pil_image(p, is_raw=False).size == (3200, 2400)


def test_draft_combined_with_exif_orientation(tmp_path):
    # 3200x2400 横版 + Orientation=6：先 DCT 1/2 到 1600x1200，
    # 再顺时针 90° EXIF 转正为 1200x1600 竖版
    p = tmp_path / "big_orient.jpg"
    _jpg(p, size=(3200, 2400), orientation=6)
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    assert im.size == (1200, 1600)


# ---------- MPO（相机直出多图 JPEG 容器，Lumix 等） ----------

def _mpo(path, size=(3200, 2400), orientation=None):
    """写一个真实 MPO 文件（主图 + 一张缩略图），Pillow 重开时 format == 'MPO'。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = PILImage.new("RGB", size)
    thumb = PILImage.new("RGB", (max(1, size[0] // 10), max(1, size[1] // 10)))
    kwargs = dict(save_all=True, append_images=[thumb])
    if orientation is not None:
        exif = img.getexif()
        exif[0x0112] = orientation
        kwargs["exif"] = exif.tobytes()
    img.save(path, "MPO", **kwargs)


def test_mpo_uses_dct_half_resolution(tmp_path):
    # 回归：Lumix 直出 .JPG 实为 MPO 容器，旧守卫只认 "JPEG" 导致 draft 被
    # 整体跳过、全分辨率进打标管线。MPO 走同一 JPEG 解码管线，draft 生效。
    p = tmp_path / "p1000.JPG"
    _mpo(p, size=(3200, 2400))
    with PILImage.open(p) as meta:
        assert meta.format == "MPO"  # 守卫前提：文件确实被识别为 MPO 而非 JPEG
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    assert im.mode == "RGB"
    assert im.size == (1600, 1200)


def test_mpo_at_or_below_floor_keeps_full_size(tmp_path):
    p = tmp_path / "small.mpo"
    _mpo(p, size=(1600, 1200))
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    assert im.size == (1600, 1200)


def test_mpo_draft_combined_with_exif_orientation(tmp_path):
    # 与 JPEG 同路径：先 DCT 1/2 到 1600x1200，再 Orientation=6 转正为 1200x1600
    p = tmp_path / "orient.mpo"
    _mpo(p, size=(3200, 2400), orientation=6)
    im = load_pil_image(p, is_raw=False, target_shortest_edge=1600)
    assert im.size == (1200, 1600)
