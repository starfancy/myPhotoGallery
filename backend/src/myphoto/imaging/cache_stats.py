"""缩略图缓存占用统计（按需触发 + 进程内短缓存）。

概览页点击「统计缓存占用空间」时才遍历磁盘，结果按 TTL 缓存；
清理缓存后直接记零（目录确定为空，无需再遍历）。
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

DEFAULT_TTL_SECONDS = 300.0


def walk_usage(cache_dir: Path) -> tuple[int, int]:
    """统计缓存目录：(总字节, 文件数)。目录缺失 → (0, 0)。

    os.walk 不跟随 symlink，与清理接口的安全口径一致；
    单文件 stat 失败逐文件容错，不影响整体统计。
    """
    total_bytes = 0
    files = 0
    for dirpath, _dirnames, filenames in os.walk(cache_dir, followlinks=False):
        for filename in filenames:
            try:
                total_bytes += (Path(dirpath) / filename).stat().st_size
                files += 1
            except OSError:
                continue
    return total_bytes, files


class ThumbCacheUsage:
    """(bytes, files) 的短 TTL 缓存；Lock 合并并发请求，防惊群。"""

    def __init__(self, cache_dir: Path, ttl: float = DEFAULT_TTL_SECONDS) -> None:
        self._dir = Path(cache_dir)
        self._ttl = ttl
        self._lock = asyncio.Lock()
        self._payload = {"bytes": 0, "files": 0}
        self._built_at: float | None = None  # None = 从未统计 / 已失效

    async def get(self) -> dict[str, int]:
        if self._built_at is not None and time.time() - self._built_at < self._ttl:
            return dict(self._payload)
        async with self._lock:
            # 等锁期间可能已有其他请求完成统计
            if self._built_at is not None and time.time() - self._built_at < self._ttl:
                return dict(self._payload)
            total, files = await asyncio.to_thread(walk_usage, self._dir)
            self._payload = {"bytes": total, "files": files}
            self._built_at = time.time()
            return dict(self._payload)

    def invalidate(self) -> None:
        """下次 get 重新遍历。"""
        self._built_at = None

    def reset_empty(self) -> None:
        """清理缓存后调用：目录确定为空，直接记零并刷新 TTL。"""
        self._payload = {"bytes": 0, "files": 0}
        self._built_at = time.time()
