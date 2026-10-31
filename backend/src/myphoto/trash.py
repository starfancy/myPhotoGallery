"""回收站工具：TRASH_DIR 定位、路径护栏、purge_expired、delete_one。

**红线 3**：`os.remove` 唯一位点在本模块（[purge_expired]、[delete_one]）中，
且每次调用前都要过 [is_under_trash_dir] 前缀校验；不通过则跳过并写审计
`trash_purge` detail=`path_guard_blocked`，绝不对文件做任何写操作。
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import time
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from myphoto.audit import purge_expired as purge_audit_expired, write_audit
from myphoto.models import GalleryRoot, Trash

log = logging.getLogger("myphoto.trash")

# .trash/ 目录固定基名（同盘，供 os.rename 原子重命名）
TRASH_BASENAME = ".trash"

# 2286 年附近；retention_days=0（永不自动清理）时作为 purge_after 哨兵值。
# purge_expired 的查询是 purge_after < now，哨兵永不命中。
NEVER_PURGE_TS = 9_999_999_999


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


_DEFAULT_PURGE_HOUR = 3
_DEFAULT_PURGE_MINUTE = 30


def next_daily_run(
    now_dt: datetime.datetime, hour: int, minute: int
) -> datetime.datetime:
    """今天 hour:minute（未到）→ 今天；已到/越界配置 → 明天。

    非法 hour/minute 回退 03:30 而非抛异常（配置被手改不应拖垮启动）。
    """
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        hour, minute = _DEFAULT_PURGE_HOUR, _DEFAULT_PURGE_MINUTE
    target = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now_dt:
        target += datetime.timedelta(days=1)
    return target


async def daily_purge_loop(sessionmaker, config_getter) -> None:
    """P5: 每日按 [trash] purge_hour/purge_minute 跑一次到期清理。

    config_getter 每轮读取，设置页改了时刻下一轮即生效。CancelledError
    向外传播供 lifespan 关停；其他异常记录后继续，定时任务永不静默死亡。
    """
    while True:
        try:
            cfg = config_getter()
            now_dt = datetime.datetime.now()
            nxt = next_daily_run(
                now_dt, cfg.trash_purge_hour, cfg.trash_purge_minute
            )
            await asyncio.sleep(max(1.0, (nxt - now_dt).total_seconds()))
            # 同一 tick 内先 trash 后 audit；两段清理各自独立 try，
            # trash 失败不应跳过 audit（两者都仍在外层总 try 之内）。
            try:
                async with sessionmaker() as session:
                    result = await purge_expired(
                        session, actor_user_id=None, actor_ip="scheduled",
                    )
                    if any(result.values()):
                        await write_audit(
                            session, "trash_purge", None, "scheduled",
                            target="scheduled",
                            detail=(
                                "purged={purged} blocked={blocked} "
                                "missing={missing} errors={errors}"
                            ).format(**result),
                        )
                    await session.commit()
            except Exception:
                log.exception("scheduled trash purge failed")

            # audit 清理块在 trash try 外面：trash 失败不影响 audit。
            try:
                async with sessionmaker() as session:
                    removed = await purge_audit_expired(
                        session, config_getter().audit_retention_days
                    )
                    await session.commit()
                if removed:
                    log.info("scheduled audit purge removed=%s", removed)
            except Exception:
                log.exception("scheduled audit purge failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduled purge loop iteration failed")


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
    # 时间型清理（含手动 before 覆盖）永不触碰"永不清理"哨兵行；
    # 显式单条删除走 delete_one，不受 purge_after 约束。
    cutoff = min(cutoff, NEVER_PURGE_TS)

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


async def delete_one(
    session: AsyncSession,
    trash_id: int,
    *,
    actor_user_id: Optional[int] = None,
    actor_ip: str = "system",
) -> dict:
    """物理删除单条回收站条目——`os.remove` 的另一个受控入口。

    与 [purge_expired] 一样必须过 [is_under_trash_dir] 前缀护栏。
    - 找不到 trash 行 → ``{"status": "not_found"}``
    - 路径不在 TRASH_DIR 下 → 拒绝 + 写审计 `trash_purge:path_guard_blocked`，
      ``{"status": "blocked"}``
    - 文件缺失 → 仍清理 DB 行，``{"status": "missing"}``
    - 正常 → ``{"status": "purged"}``

    调用方（handler）负责事务提交。不在此写"成功清理"审计——单条删除
    与批量 purge 语义不同，交给上层聚合。
    """
    row = await session.get(Trash, trash_id)
    if row is None:
        return {"status": "not_found"}

    root = await session.get(GalleryRoot, row.root_id)
    if root is None:
        # root 已消失，无法定位 TRASH_DIR；只清 DB 行
        log.warning("delete_one: trash row %s references missing root %s", row.id, row.root_id)
        await session.delete(row)
        return {"status": "purged"}

    trash_file = Path(root.absolute_path) / row.trash_relative_path
    if not is_under_trash_dir(trash_file, root):
        await write_audit(
            session, "trash_purge", actor_user_id, actor_ip,
            target=f"trash:{row.id}",
            detail=f"path_guard_blocked:trash_id={row.id} path={row.trash_relative_path}",
        )
        log.error("delete_one blocked by path guard: trash_id=%s path=%s", row.id, trash_file)
        return {"status": "blocked"}

    try:
        os.remove(trash_file)
        status = "purged"
    except FileNotFoundError:
        status = "missing"
    except OSError:
        log.exception("delete_one failed to remove file: trash_id=%s path=%s", row.id, trash_file)
        return {"status": "errors"}

    await session.delete(row)
    return {"status": status}

