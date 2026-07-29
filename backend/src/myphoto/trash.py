"""回收站工具：TRASH_DIR 定位、路径护栏、purge_expired。

**红线 3**：`os.remove` 唯一位点在 [purge_expired] 中，且执行前必须通过
[is_under_trash_dir] 前缀校验；不通过则跳过 + 写审计 `trash_purge`
detail=`path_guard_blocked`，绝不对文件做任何写操作。
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myphoto.audit import write_audit
from myphoto.models import GalleryRoot, Trash

log = logging.getLogger("myphoto.trash")

# .trash/ 目录固定基名（同盘，供 os.rename 原子重命名）
TRASH_BASENAME = ".trash"


def trash_dir_for(root: GalleryRoot) -> Path:
    """返回 `<root.absolute_path>/.trash/{gallery_id}/{root_id}/`。

    每个 root 独立子目录，避免不同 root 的 trash 路径混淆。
    """
    return Path(root.absolute_path) / TRASH_BASENAME / str(root.gallery_id) / str(root.id)


def is_under_trash_dir(candidate: Path, root: GalleryRoot) -> bool:
    """校验 `candidate` 是否位于 `trash_dir_for(root)` 下。

    使用 `Path.resolve(strict=False)` 后按段前缀比对，防止符号链接、
    `..` 等花招突破护栏。文件已被删除也不影响判断（strict=False）。
    """
    base = trash_dir_for(root).resolve(strict=False)
    try:
        target = Path(candidate).resolve(strict=False)
    except OSError:
        return False
    try:
        target.relative_to(base)
    except ValueError:
        return False
    return True


async def purge_expired(
    session: AsyncSession,
    *,
    gallery_id: Optional[int] = None,
    root_id: Optional[int] = None,
    before: Optional[int] = None,
    actor_user_id: Optional[int] = None,
    actor_ip: str = "system",
    now: Optional[int] = None,
) -> dict:
    """物理清理已到期的回收站条目。

    - 默认 `purge_after < now()` 的行；`before` 覆盖时钟（用于测试与手动清理）
    - 可选 `gallery_id`/`root_id` 过滤
    - 每一行：查 root → 计算 TRASH_DIR → 校验 trash 文件路径在 TRASH_DIR 下
      - 通过：`os.remove` + `delete from trash`（幂等：文件不存在也算成功）
      - 不通过：跳过 + 写审计 `trash_purge` detail=`path_guard_blocked:...`
    - 返回 `{purged, blocked, missing, errors}` 计数供上层写总审计

    不在此处写"成功清理"总审计——留给上层聚合（启动 lifespan 或 route
    handler），因为它们更清楚触发方式（startup / manual / scheduled）。
    """
    effective_now = int(time.time()) if now is None else int(now)
    cutoff = effective_now if before is None else int(before)

    stmt = select(Trash).where(Trash.purge_after < cutoff)
    if gallery_id is not None:
        stmt = stmt.where(Trash.gallery_id == gallery_id)
    if root_id is not None:
        stmt = stmt.where(Trash.root_id == root_id)

    rows = (await session.execute(stmt)).scalars().all()

    purged = 0
    blocked = 0
    missing = 0
    errors = 0

    # 缓存 root 查询，避免 N+1
    root_cache: dict[int, GalleryRoot | None] = {}

    for row in rows:
        root = root_cache.get(row.root_id)
        if root is None and row.root_id not in root_cache:
            root = await session.get(GalleryRoot, row.root_id)
            root_cache[row.root_id] = root

        if root is None:
            # root 已被删除（GalleryRoot 走 cascade 也会 cascade trash？trash 表未加 FK）
            # 出于安全考虑：不删除文件（无法定位 TRASH_DIR），但可清理数据库孤儿行
            log.warning("trash row %s references missing root %s; removing db row only", row.id, row.root_id)
            await session.delete(row)
            purged += 1
            continue

        trash_file = Path(root.absolute_path) / row.trash_relative_path

        if not is_under_trash_dir(trash_file, root):
            # 红线 3：拒绝并审计
            blocked += 1
            detail = f"path_guard_blocked:trash_id={row.id} path={row.trash_relative_path}"
            await write_audit(
                session,
                "trash_purge",
                actor_user_id,
                actor_ip,
                target=f"trash:{row.id}",
                detail=detail,
            )
            log.error("purge_expired blocked by path guard: trash_id=%s path=%s", row.id, trash_file)
            continue

        try:
            os.remove(trash_file)
        except FileNotFoundError:
            # 文件已不在（可能被手动清理）——仍视为成功，清理数据库行
            missing += 1
            await session.delete(row)
            continue
        except OSError:
            log.exception("purge_expired failed to remove file: trash_id=%s path=%s", row.id, trash_file)
            errors += 1
            continue

        await session.delete(row)
        purged += 1

    return {
        "purged": purged,
        "blocked": blocked,
        "missing": missing,
        "errors": errors,
    }
