from __future__ import annotations

import secrets
import time

from sqlalchemy import select

from myphoto.db import create_all
from myphoto.models import User
from myphoto.security import hash_password


def _generate_password() -> str:
    # 16 chars, alphanumeric, human-typeable
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(16))


async def ensure_schema_and_admin(engine, sessionmaker) -> tuple[bool, str | None]:
    """Create tables if missing and seed initial admin if no admin exists.

    Returns (created_initial_admin, plain_password_if_created).
    The plain password is only known here; caller must print it once.
    """
    await create_all(engine)
    async with sessionmaker() as s:
        existing = (await s.execute(select(User).where(User.role == "admin"))).first()
        if existing is not None:
            return False, None
        password = _generate_password()
        s.add(User(
            username="admin",
            password_hash=hash_password(password),
            role="admin",
            # P4: 初始 admin 默认 remote_allowed，确保首次登录（不论网络位置）可用。
            # 安全模式下 admin 可在登录后通过 PATCH /api/admin/users/{self} 改回 lan_only。
            access_scope="remote_allowed",
            enabled=1,
            created_at=int(time.time()),
        ))
        await s.commit()
        return True, password
