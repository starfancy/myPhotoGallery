from __future__ import annotations

import ipaddress

from fastapi import Depends, Request

from myphoto.errors import AppError
from myphoto.models import User
from myphoto.security import TokenError, decode_token

SESSION_COOKIE = "mpg_session"


async def current_user(request: Request) -> User:
    """权限链步骤 1+2+3 串联。

    1. authenticate：解析 JWT cookie
    2. user active：enabled==1
    3. access_scope：lan_only 时校验 client_ip 在 RFC1918（get_client_ip 应用 trusted_proxies）

    access 模块在函数体内 lazy import —— 避免 deps ↔ access 模块级循环（access.py
    也 import 自本模块的 _is_lan_ip / current_user）。
    """
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

    # 步骤 3：访问域判定（spec §5.2）。逻辑与 access.access_scope_guard 一致，
    # 但这里直接复用本模块的 _is_lan_ip，避免 Depends 嵌套循环。
    if user.access_scope == "lan_only":
        from myphoto import access  # lazy：避免模块级循环
        ip = access.get_client_ip(request, cfg.trusted_proxies)
        if not _is_lan_ip(ip):
            raise AppError(
                "access_scope_violation", 403,
                "this account is restricted to the local network",
            )
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
    """P4: 改用 access.get_client_ip 解析 client_ip（应用 trusted_proxies）。

    与 current_user 步骤 3 判定共用同一 client_ip 解析逻辑：
    - trusted_proxies=[]：直接用 request.client.host
    - trusted_proxies 非空：仅当 request.client.host 命中 trusted 时才读 XFF
    """
    from myphoto import access  # lazy：避免模块级循环
    cfg = request.app.state.config
    host = access.get_client_ip(request, cfg.trusted_proxies)
    if not _is_lan_ip(host):
        raise AppError(
            "admin_fs_lan_only", 403,
            "this endpoint is only available on the local network",
        )
