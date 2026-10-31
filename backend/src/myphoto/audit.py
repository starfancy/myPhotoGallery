from __future__ import annotations

import logging
import time

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from myphoto.models import AuditLog

log = logging.getLogger("myphoto.audit")


async def write_audit(
    session,
    action: str,
    actor_user_id: int | None,
    actor_ip: str,
    target: str | None = None,
    detail: str | None = None,
) -> None:
    """Insert an audit log row.

    Audit failures are logged but NEVER propagated — the main operation
    must complete regardless of audit success.
    """
    try:
        session.add(
            AuditLog(
                ts=int(time.time()),
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                action=action,
                target=target,
                detail=detail,
            )
        )
        await session.flush()
    except Exception:
        log.exception("audit write failed for action=%s actor=%s", action, actor_user_id)


async def purge_expired(
    session: AsyncSession,
    retention_days: int,
    now: int | None = None,
) -> int:
    """物理删除超过保留期的审计行，返回删除条数。

    retention_days=0 为「永不清理」哨兵。审计行无 FS 副作用、无外键关联，
    直接 DELETE。清理动作自身不写审计（避免自引用噪声）。
    """
    if retention_days <= 0:
        return 0
    effective_now = int(time.time()) if now is None else int(now)
    cutoff = effective_now - retention_days * 86400
    result = await session.execute(delete(AuditLog).where(AuditLog.ts < cutoff))
    return int(result.rowcount or 0)
