from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from myphoto.audit import write_audit
from myphoto.deps import SESSION_COOKIE, current_user
from myphoto.errors import AppError
from myphoto.models import User
from myphoto.security import hash_password, make_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

_LOCKOUT_THRESHOLD = 5
_LOCKOUT_WINDOW_SEC = 15 * 60
_DUMMY_PASSWORD_HASH = hash_password("myphoto-login-dummy-password")


def _client_ip(request: Request) -> str:
    """原始请求 IP（锁计数器用，不走 trusted_proxies —— 锁定应基于直连 IP）。

    P4 新增的 access_scope 判定用 access.get_client_ip（走 trusted_proxies）；
    此处保留原始 IP 以确保锁计数器独立于代理配置。
    """
    return request.client.host if request.client else "unknown"


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class ChangePasswordBody(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=1)  # strength checked in handler (single authority)


def _record_fail(state: dict[str, tuple[int, float]], ip: str) -> None:
    now = time.monotonic()
    count, first = state.get(ip, (0, now))
    if now - first >= _LOCKOUT_WINDOW_SEC:
        count, first = 0, now
    state[ip] = (count + 1, first)


def _is_locked(state: dict[str, tuple[int, float]], ip: str) -> bool:
    entry = state.get(ip)
    if entry is None:
        return False
    count, first = entry
    if time.monotonic() - first >= _LOCKOUT_WINDOW_SEC:
        state.pop(ip, None)
        return False
    return count >= _LOCKOUT_THRESHOLD


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    ip = _client_ip(request)
    lockout_state = request.app.state.login_lockout
    if _is_locked(lockout_state, ip):
        raise AppError("login_locked", 423, "too many failed attempts; try again later")

    sm = request.app.state.sessionmaker
    login_failed = False
    async with sm() as session:
        user = (
            await session.execute(select(User).where(User.username == body.username))
        ).scalar_one_or_none()
        password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        password_valid = verify_password(body.password, password_hash)
        if user is None or user.enabled != 1 or not password_valid:
            _record_fail(lockout_state, ip)
            login_failed = True
        else:
            # P4: 步骤 3 判定 — lan_only 用户从公网登录直接拒绝（403），不计入锁计数。
            if user.access_scope == "lan_only":
                from myphoto import access  # lazy import 避免循环
                from myphoto.deps import _is_lan_ip
                cfg = request.app.state.config
                effective_ip = access.get_client_ip(request, cfg.trusted_proxies)
                if not _is_lan_ip(effective_ip):
                    raise AppError(
                        "access_scope_violation", 403,
                        "this account is restricted to the local network",
                    )

            user.last_login_at = int(time.time())
            await write_audit(
                session, "login_success", user.id, ip,
                target=f"user:{user.id}",
            )
            await session.commit()
            lockout_state.pop(ip, None)

            cfg = request.app.state.config
            max_age = cfg.session_hours * 3600
            token = make_token(cfg.jwt_secret, user.id, user.role, max_age)
            response.set_cookie(
                SESSION_COOKIE,
                token,
                max_age=max_age,
                httponly=True,
                samesite="lax",
                path="/",
            )
            return {
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "role": user.role,
                    "access_scope": user.access_scope,
                }
            }

    # Reach here only on failed login — main session has been released, so the
    # audit session below is not nested (avoids sqlite writer-writer contention
    # on non-WAL setups).
    if login_failed:
        async with sm() as audit_session:
            await write_audit(
                audit_session, "login_fail", None, ip,
                target=f"username={body.username}",
            )
            await audit_session.commit()
        raise AppError("invalid_credentials", 401, "wrong username or password")


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "access_scope": user.access_scope,
    }


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordBody,
    request: Request,
    user: User = Depends(current_user),
):
    if len(body.new_password) < 8:
        raise AppError("password_too_weak", 422, "password must be at least 8 characters")
    if not verify_password(body.old_password, user.password_hash):
        raise AppError("invalid_credentials", 403, "current password is incorrect")

    sm = request.app.state.sessionmaker
    async with sm() as session:
        u = await session.get(User, user.id)
        if u is None or u.enabled != 1:
            raise AppError("unauthenticated", 401, "user not found or disabled")
        u.password_hash = hash_password(body.new_password)
        await session.commit()
