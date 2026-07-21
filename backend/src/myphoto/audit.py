from __future__ import annotations

import logging
import time

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
