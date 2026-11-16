"""imaging.preprocess 纯函数：无模型依赖，直接单测。"""

from PIL import Image as PILImage

from myphoto.imaging.preprocess import (
    CLIP_SHORTEST_EDGE,
    TAG_DECODE_FLOOR,
    resize_shortest_edge,
)


def test_constants():
    assert CLIP_SHORTEST_EDGE == 224
    assert TAG_DECODE_FLOOR == 1600


def test_landscape_shortest_edge_becomes_target():
    img = PILImage.new("RGB", (2000, 1000))
    out = resize_shortest_edge(img, 224)
    assert out.size == (448, 224)  # 等比：2000/1000 * 224 = 448


def test_portrait_shortest_edge_becomes_target():
    img = PILImage.new("RGB", (1000, 2000))
    out = resize_shortest_edge(img, 224)
    assert out.size == (224, 448)


def test_already_at_target_returns_same_object():
    img = PILImage.new("RGB", (300, 224))
    assert resize_shortest_edge(img, 224) is img


def test_resample_is_forwarded(monkeypatch):
    img = PILImage.new("RGB", (400, 200))
    seen = {}
    orig = PILImage.Image.resize

    def spy(self, xy, resample=PILImage.BICUBIC):
        seen["resample"] = resample
        return orig(self, xy, resample)

    monkeypatch.setattr(PILImage.Image, "resize", spy)
    resize_shortest_edge(img, 224, resample=PILImage.NEAREST)
    assert seen["resample"] == PILImage.NEAREST


def test_default_resample_is_bicubic(monkeypatch):
    img = PILImage.new("RGB", (400, 200))
    seen = {}
    orig = PILImage.Image.resize

    def spy(self, xy, resample=PILImage.BICUBIC):
        seen["resample"] = resample
        return orig(self, xy, resample)

    monkeypatch.setattr(PILImage.Image, "resize", spy)
    resize_shortest_edge(img, 224)
    assert seen["resample"] == PILImage.BICUBIC
