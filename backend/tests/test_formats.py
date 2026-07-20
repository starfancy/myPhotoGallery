import pytest
from myphoto.formats import (
    ALL_EXTENSIONS,
    RAW_EXTENSIONS,
    WEB_EXTENSIONS,
    classify,
    is_supported,
)


def test_web_set_contains_jpg():
    assert "jpg" in WEB_EXTENSIONS


def test_raw_set_contains_nef():
    assert "nef" in RAW_EXTENSIONS


def test_all_is_union():
    assert ALL_EXTENSIONS == WEB_EXTENSIONS | RAW_EXTENSIONS


def test_web_and_raw_disjoint():
    assert WEB_EXTENSIONS & RAW_EXTENSIONS == set()


@pytest.mark.parametrize(
    "name, expected",
    [
        ("photo.JPG", "web"),
        ("photo.jpeg", "web"),
        ("photo.HEIC", "web"),
        ("photo.avif", "web"),
        ("photo.NEF", "raw"),
        ("photo.cr3", "raw"),
        ("readme.txt", "unsupported"),
        ("noext", "unsupported"),
        (".hidden", "unsupported"),
    ],
)
def test_classify(name, expected):
    assert classify(name) == expected


def test_is_supported_true_for_web_and_raw():
    assert is_supported("a.jpg") is True
    assert is_supported("a.NEF") is True


def test_is_supported_false_for_others():
    assert is_supported("a.txt") is False
