from __future__ import annotations

import ipaddress

from fastapi import Depends, Request

from myphoto.errors import AppError
from myphoto.models import User
from myphoto.security import TokenError, decode_token

SESSION_COOKIE = "mpg_session"


async def current_user(request: Request) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AppError("unauthenticated", 401, "authentication required")

    cfg = request.app.state.config
    try:
        payload = decode_token(cfg.jwt_secret, token)
    except TokenError:
        raise AppError("unauthenticated", 401, "invalid or expired session")

    user_id = payload.get("sub")
    if type(user_id) is not int or not 1 <= user_id <= 2**63 - 1:
        raise AppError("unauthenticated", 401, "invalid or expired session")

    sm = request.app.state.sessionmaker
    async with sm() as session:
        user = await session.get(User, user_id)
    if user is None or user.enabled != 1:
        raise AppError("unauthenticated", 401, "user not found or disabled")
    return user


async def admin_required(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise AppError("forbidden", 403, "admin only")
    return user


_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("::1/128"),
]


def _is_lan_ip(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_RANGES)


async def require_lan_ip(request: Request) -> None:
    host = request.client.host if request.client else "unknown"
    if not _is_lan_ip(host):
        raise AppError(
            "admin_fs_lan_only", 403,
            "this endpoint is only available on the local network",
        )
