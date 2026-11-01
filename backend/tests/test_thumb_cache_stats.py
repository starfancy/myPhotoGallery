from __future__ import annotations

from pathlib import Path

import pytest

from myphoto.thumb_cache_stats import ThumbCacheUsage, walk_usage


def test_walk_usage_sums_files(tmp_path: Path):
    cache = tmp_path / ".cache" / "thumbnails"
    (cache / "aa").mkdir(parents=True)
    (cache / "aa" / "200.jpg").write_bytes(b"x" * 10)
    (cache / "bb" / "cc").mkdir(parents=True)
    (cache / "bb" / "cc" / "400.jpg").write_bytes(b"y" * 20)

    assert walk_usage(cache) == (30, 2)


def test_walk_usage_missing_dir_is_zero(tmp_path: Path):
    assert walk_usage(tmp_path / "nope") == (0, 0)


async def test_usage_cached_until_invalidated(tmp_path: Path):
    cache = tmp_path / "thumbnails"
    usage = ThumbCacheUsage(cache, ttl=300)
    cache.mkdir()
    (cache / "a.jpg").write_bytes(b"x" * 10)

    assert await usage.get() == {"bytes": 10, "files": 1}

    # TTL 内新增文件不触发重新遍历（方案 B：进程内短缓存）
    (cache / "b.jpg").write_bytes(b"y" * 20)
    assert await usage.get() == {"bytes": 10, "files": 1}

    usage.invalidate()
    assert await usage.get() == {"bytes": 30, "files": 2}


async def test_reset_empty_marks_zero_without_walk(tmp_path: Path):
    cache = tmp_path / "thumbnails"
    cache.mkdir()
    (cache / "a.jpg").write_bytes(b"x" * 10)
    usage = ThumbCacheUsage(cache, ttl=300)
    assert await usage.get() == {"bytes": 10, "files": 1}

    # 清理后目录确定为空：直接记零，下一次点击不必再遍历
    usage.reset_empty()
    assert await usage.get() == {"bytes": 0, "files": 0}
