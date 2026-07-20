from __future__ import annotations

import time

import bcrypt
import jwt


class TokenError(Exception):
    """Raised when a JWT is invalid, expired, or malformed."""


_BCRYPT_ROUNDS = 12
_ALG = "HS256"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(
        plain.encode("utf-8"),
        bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
    ).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def make_token(secret: str, user_id: int, role: str, ttl_seconds: int) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "role": role, "iat": now, "exp": now + ttl_seconds}
    return jwt.encode(payload, secret, algorithm=_ALG)


def decode_token(secret: str, token: str) -> dict:
    try:
        return jwt.decode(token, secret, algorithms=[_ALG], options={"verify_sub": False})
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
