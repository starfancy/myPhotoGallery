from __future__ import annotations

from typing import Literal

WEB_EXTENSIONS: frozenset[str] = frozenset({
    "jpg", "jpeg", "png", "gif", "webp",
    "heic", "heif", "avif",
})

RAW_EXTENSIONS: frozenset[str] = frozenset({
    "cr2", "cr3", "nef", "arw", "dng",
    "orf", "rw2", "raf", "pef",
})

ALL_EXTENSIONS: frozenset[str] = WEB_EXTENSIONS | RAW_EXTENSIONS


def _ext(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def classify(filename: str) -> Literal["web", "raw", "unsupported"]:
    ext = _ext(filename)
    if ext in WEB_EXTENSIONS:
        return "web"
    if ext in RAW_EXTENSIONS:
        return "raw"
    return "unsupported"


def is_supported(filename: str) -> bool:
    return _ext(filename) in ALL_EXTENSIONS
