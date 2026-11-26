from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from myphoto.core.models import Lut

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    discovered: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    soft_deleted: list[str] = field(default_factory=list)


@dataclass
class PurgedLut:
    slug: str
    group: str
    file_path: str
    enabled: int


@dataclass
class PurgeResult:
    deleted: list[PurgedLut] = field(default_factory=list)


def _slug_from_path(p: Path) -> str:
    stem = p.stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "lut"


async def scan_luts(
    sessionmaker: async_sessionmaker[AsyncSession],
    luts_dir: Path,
) -> ScanResult:
    # 不创建目录：luts_dir 不存在 = 未安装 LUT 库，直接返回空。
    # 避免污染测试 fixture 的目录计数（每个 test 的 tmp_path 都会被
    # browse-fs 之类的端点枚举）。
    if not luts_dir.exists():
        return ScanResult()
    # 收集磁盘上所有 .cube 文件（一层子目录）
    disk_files: set[str] = set()
    for p in luts_dir.rglob("*.cube"):
        rel = p.relative_to(luts_dir).as_posix()
        # 只允许一层子目录：若 rel 含两个或更多 "/"，跳过
        if rel.count("/") > 1:
            log.warning("lut_scanner: skipping nested file %s (only 1 group level allowed)", rel)
            continue
        disk_files.add(rel)

    result = ScanResult()
    async with sessionmaker() as s:
        # 拿 DB 里所有行
        db_rows = (await s.execute(select(Lut))).scalars().all()
        db_by_path = {r.file_path: r for r in db_rows}
        used_slugs = {r.slug for r in db_rows}

        # 1. 磁盘上有、DB 没有 → 插入
        for rel in sorted(disk_files):
            if rel in db_by_path:
                result.skipped_existing.append(rel)
                continue
            p = luts_dir / rel
            group = p.parent.relative_to(luts_dir).as_posix() if p.parent != luts_dir else ""
            slug = _slug_from_path(p)
            # slug 冲突兜底：加序号（同时考虑本次扫描内已占用的 slug）
            base_slug = slug
            n = 2
            while slug in used_slugs:
                slug = f"{base_slug}_{n}"
                n += 1
            used_slugs.add(slug)
            s.add(Lut(
                slug=slug,
                label=slug,
                group=group,
                file_path=rel,
                enabled=0,
                sort_order=0,
                source="",
                license="",
                created_at=int(time.time()),
            ))
            result.discovered.append(rel)

        # 2. DB 里有、磁盘上没有 → 软删（enabled=0）
        for rel, row in db_by_path.items():
            if rel not in disk_files and row.enabled != 0:
                row.enabled = 0
                result.soft_deleted.append(rel)

        await s.commit()
    return result


async def purge_missing_luts(
    sessionmaker: async_sessionmaker[AsyncSession],
    luts_dir: Path,
) -> PurgeResult:
    """硬删 file_path 已不在磁盘上的 LUT 行（scan_luts 软删的出口）。

    重命名/移动 LUT 目录后，旧路径的行只被 scan_luts 置 enabled=0，
    管理页仍会显示幽灵分组；本函数把文件缺失的行物理删除。
    调用方必须先确认 luts_dir 存在——盘未挂载时绝不能清空整表。
    """
    result = PurgeResult()
    async with sessionmaker() as s:
        db_rows = (await s.execute(select(Lut))).scalars().all()
        for row in db_rows:
            if not (luts_dir / row.file_path).exists():
                # 会话关闭后行即为 detached，先快照需要的字段
                result.deleted.append(PurgedLut(
                    slug=row.slug,
                    group=row.group,
                    file_path=row.file_path,
                    enabled=row.enabled,
                ))
                await s.delete(row)
        if result.deleted:
            await s.commit()
    return result
