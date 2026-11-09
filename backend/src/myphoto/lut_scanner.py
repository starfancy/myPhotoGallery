from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from myphoto.models import Lut

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    discovered: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    soft_deleted: list[str] = field(default_factory=list)


def _slug_from_path(p: Path) -> str:
    stem = p.stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or "lut"


async def scan_luts(
    sessionmaker: async_sessionmaker[AsyncSession],
    luts_dir: Path,
) -> ScanResult:
    luts_dir.mkdir(parents=True, exist_ok=True)
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
