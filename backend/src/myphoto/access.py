"""P4: 权限链步骤 3 + 步骤 5 工具。

模块结构（避免循环导入 —— 单向依赖 deps.py）：
- _PRIVATE_RANGES / _is_lan_ip  保留在 deps.py（admin_fs_lan_only 早期 P2 即用）
- access.py 单向 import；不反向 import deps.py 的 current_user 之外的内容

API：
- get_client_ip(request, trusted_proxies) -> str
- access_scope_guard(request, user) -> User           # Depends：步骤 3
- check_gallery_access(session, user, gallery_id)    # 纯函数：步骤 5（媒体端用）
- gallery_scope_guard(gid, request, user) -> User    # Depends：步骤 5（浏览端用）
"""
from __future__ import annotations

import ipaddress
import logging

from fastapi import Request
from sqlalchemy import select

from myphoto.deps import _is_lan_ip, current_user  # 单向：helpers + current_user
from myphoto.errors import AppError
from myphoto.models import User, UserGallery

_log = logging.getLogger("myphoto.access")


# ---- IP 解析 ----

def _ip_in_trusted(host: str, trusted: list[str]) -> bool:
    """检查 host 是否命中 trusted 列表中的任一 IP 或 CIDR。

    trusted 中的非法条目（不是合法 IP / CIDR）会被静默忽略并打 warn。
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    for entry in trusted:
        try:
            net = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            _log.warning("access: ignoring invalid trusted_proxies entry %r", entry)
            continue
        if addr in net:
            return True
    return False


def get_client_ip(request: Request, trusted_proxies: list[str]) -> str:
    """根据 trusted_proxies 决定有效客户端 IP。

    语义（spec §5.2 IP 获取）：
    - trusted_proxies 空 → 仅用 request.client.host（忽略 XFF，避免伪造）
    - trusted_proxies 非空 + request.client.host 命中 trusted →
      取 X-Forwarded-For 左起第一个非空非 "unknown" 段
    - trusted_proxies 非空 + request.client.host 未命中 trusted →
      忽略 XFF，用 request.client.host（防止公网直接伪造 XFF 绕过 lan_only）
    """
    raw_host = request.client.host if request.client else "unknown"
    if not trusted_proxies:
        return raw_host
    if not _ip_in_trusted(raw_host, trusted_proxies):
        return raw_host
    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return raw_host
    for seg in xff.split(","):
        seg = seg.strip()
        if seg and seg.lower() != "unknown":
            return seg
    return raw_host


# ---- 步骤 3：access_scope_guard ----

async def access_scope_guard(
    request: Request,
    user=None,  # 内部 fallback 解析（非 FastAPI 注入）；保持无类型提示避免 Pydantic 误判
) -> User:
    """权限链步骤 3：用户访问域判定（spec §5.2）。

    依赖 current_user（位于 deps.py），user 由 FastAPI 通过 Depends 注入。
    当 user.access_scope == "lan_only" 时，校验有效 client_ip 在 RFC1918 私网范围；
    否则 403 access_scope_violation。
    """
    if user is None:
        # 防御性 fallback：直接调用 current_user（它内部含步骤 1+2+3）
        user = await current_user(request=request)
    if user.access_scope == "lan_only":
        cfg = request.app.state.config
        ip = get_client_ip(request, cfg.trusted_proxies)
        if not _is_lan_ip(ip):
            raise AppError(
                "access_scope_violation", 403,
                "this account is restricted to the local network",
            )
    return user


# ---- 步骤 5 ----

async def check_gallery_access(
    session,
    user: User,
    gallery_id: int,
) -> None:
    """权限链步骤 5 纯函数版（spec §5.2）。

    用于路由内查 image → root → gallery_id 后手工调用（媒体端无 gid 在 path）。
    - admin：放行（不入 user_galleries 表）
    - viewer：要求 user_galleries 行存在；否则 404 not_found（防枚举）
    """
    if user.role == "admin":
        return
    exists = (
        await session.execute(
            select(UserGallery).where(
                UserGallery.user_id == user.id,
                UserGallery.gallery_id == gallery_id,
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        raise AppError("not_found", 404, "gallery not found")


async def gallery_scope_guard(
    gid: int,
    request: Request,
    user=None,  # 内部 fallback 解析（非 FastAPI 注入）；保持无类型提示避免 Pydantic 误判
) -> User:
    """权限链步骤 5 Depends 版（spec §5.2）。

    用于路径含 {gid} 的浏览端路由（FastAPI 从 path 注入 gid）。
    - admin：放行
    - viewer：要求 user_galleries 行存在；否则 404 not_found
    """
    if user is None:
        # 防御性 fallback（生产不会触发）
        user = await access_scope_guard(request=request)
    if user.role == "admin":
        return user
    sm = request.app.state.sessionmaker
    async with sm() as s:
        exists = (
            await s.execute(
                select(UserGallery).where(
                    UserGallery.user_id == user.id,
                    UserGallery.gallery_id == gid,
                )
            )
        ).scalar_one_or_none()
    if exists is None:
        raise AppError("not_found", 404, "gallery not found")
    return user
