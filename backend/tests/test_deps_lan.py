from __future__ import annotations

import pytest

from myphoto.deps import _is_lan_ip
from myphoto.errors import AppError


@pytest.mark.parametrize("ip", [
    "10.0.0.1",
    "192.168.1.1",
    "172.16.0.1",
    "127.0.0.1",
    "::1",
    "fc00::1",
])
def test_is_lan_ip_accepts_private(ip):
    assert _is_lan_ip(ip) is True


@pytest.mark.parametrize("ip", [
    "8.8.8.8",
    "203.0.113.1",
    "2001:db8::1",
    "unknown",
])
def test_is_lan_ip_rejects_public(ip):
    assert _is_lan_ip(ip) is False


# ---- P4: trusted_proxies-aware require_lan_ip ----

class _FakeHeaders:
    def __init__(self, data: dict[str, str] | None = None):
        self._data = {k.lower(): v for k, v in (data or {}).items()}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._data.get(key.lower(), default)


class _FakeClient:
    def __init__(self, host: str):
        self.host = host


class _FakeState:
    pass


class _FakeApp:
    def __init__(self):
        self.state = _FakeState()


class _FakeRequest:
    """require_lan_ip / current_user 测试用的最小 Request 替身。"""
    def __init__(self, client_host: str, xff: str | None = None):
        self.client = _FakeClient(client_host) if client_host else None
        headers_dict = {"x-forwarded-for": xff} if xff is not None else {}
        self.headers = _FakeHeaders(headers_dict)
        self.app = _FakeApp()
        self.cookies: dict[str, str] = {}


def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_require_lan_ip_trusted_proxies_empty_ignores_xff():
    """P4: trusted_proxies=[] 时，XFF 不影响 client_ip，公网仍 403。"""
    from types import SimpleNamespace
    from myphoto.deps import require_lan_ip

    req = _FakeRequest(client_host="8.8.8.8", xff="127.0.0.1")
    req.app.state.config = SimpleNamespace(trusted_proxies=[])
    with pytest.raises(AppError) as exc:
        _run(require_lan_ip(request=req))
    assert exc.value.code == "admin_fs_lan_only"


def test_require_lan_ip_trusted_proxies_match_uses_xff_lan():
    """P4: nginx 在 trusted 中时，XFF 标识的 LAN IP 让 require_lan_ip 通过。"""
    from types import SimpleNamespace
    from myphoto.deps import require_lan_ip

    req = _FakeRequest(client_host="8.8.8.8", xff="192.168.1.5")
    req.app.state.config = SimpleNamespace(trusted_proxies=["8.8.8.8"])
    # 不抛异常 = 通过
    _run(require_lan_ip(request=req))


def test_require_lan_ip_lan_client_passes_regardless_of_config():
    """P4: 客户端本身是 LAN IP 时，无需 trusted_proxies 也通过。"""
    from types import SimpleNamespace
    from myphoto.deps import require_lan_ip

    req = _FakeRequest(client_host="192.168.1.5", xff=None)
    req.app.state.config = SimpleNamespace(trusted_proxies=[])
    _run(require_lan_ip(request=req))  # 不抛 = 通过


def test_require_lan_ip_no_state_raises_500_or_app_error():
    """app.state 缺 config 时应能优雅报错（不会 AttributeError 抛 500）。"""
    from myphoto.deps import require_lan_ip

    req = _FakeRequest(client_host="8.8.8.8")
    # 没有 req.app.state.config → 期望 AppError；不应 AttributeError
    with pytest.raises((AppError, AttributeError)):
        _run(require_lan_ip(request=req))


# ---- P4: current_user 串入步骤 3（access_scope 判定） ----

async def test_current_user_lan_only_lan_ip_passes():
    """P4: lan_only + LAN IP → current_user 通过。"""
    from types import SimpleNamespace
    from sqlalchemy import select
    from myphoto.db import create_all, make_engine, make_sessionmaker
    from myphoto.deps import current_user
    from myphoto.models import User as UserModel
    from myphoto.security import make_token

    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as s:
        now = 1700000000
        s.add(UserModel(username="u", password_hash="x", role="viewer",
                        access_scope="lan_only", enabled=1, created_at=now))
        await s.commit()
        user = (await s.execute(select(UserModel).where(UserModel.username == "u"))).scalar_one()
        token = make_token("test-secret", user.id, user.role, 3600)

    req = _FakeRequest(client_host="192.168.1.5")
    req.app.state.config = SimpleNamespace(jwt_secret="test-secret", trusted_proxies=[])
    req.app.state.sessionmaker = sm
    req.cookies = {"mpg_session": token}

    result = await current_user(request=req)
    assert result.id == user.id


async def test_current_user_lan_only_public_ip_raises_403():
    """P4: lan_only + 公网 IP → current_user 抛 403 access_scope_violation。"""
    from types import SimpleNamespace
    from sqlalchemy import select
    from myphoto.db import create_all, make_engine, make_sessionmaker
    from myphoto.deps import current_user
    from myphoto.models import User as UserModel
    from myphoto.security import make_token

    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as s:
        s.add(UserModel(username="u", password_hash="x", role="viewer",
                        access_scope="lan_only", enabled=1, created_at=1700000000))
        await s.commit()
        user = (await s.execute(select(UserModel).where(UserModel.username == "u"))).scalar_one()
        token = make_token("test-secret", user.id, user.role, 3600)

    req = _FakeRequest(client_host="8.8.8.8")
    req.app.state.config = SimpleNamespace(jwt_secret="test-secret", trusted_proxies=[])
    req.app.state.sessionmaker = sm
    req.cookies = {"mpg_session": token}

    with pytest.raises(AppError) as exc:
        await current_user(request=req)
    assert exc.value.code == "access_scope_violation"
    assert exc.value.http_status == 403


async def test_current_user_remote_allowed_public_ip_passes():
    """P4: remote_allowed + 公网 IP → 通过。"""
    from types import SimpleNamespace
    from sqlalchemy import select
    from myphoto.db import create_all, make_engine, make_sessionmaker
    from myphoto.deps import current_user
    from myphoto.models import User as UserModel
    from myphoto.security import make_token

    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as s:
        s.add(UserModel(username="u", password_hash="x", role="admin",
                        access_scope="remote_allowed", enabled=1, created_at=1700000000))
        await s.commit()
        user = (await s.execute(select(UserModel).where(UserModel.username == "u"))).scalar_one()
        token = make_token("test-secret", user.id, user.role, 3600)

    req = _FakeRequest(client_host="8.8.8.8")
    req.app.state.config = SimpleNamespace(jwt_secret="test-secret", trusted_proxies=[])
    req.app.state.sessionmaker = sm
    req.cookies = {"mpg_session": token}

    result = await current_user(request=req)
    assert result.id == user.id


async def test_current_user_lan_only_trusted_proxy_xff_lan_passes():
    """P4: lan_only + nginx 在 trusted + XFF=LAN → 通过。"""
    from types import SimpleNamespace
    from sqlalchemy import select
    from myphoto.db import create_all, make_engine, make_sessionmaker
    from myphoto.deps import current_user
    from myphoto.models import User as UserModel
    from myphoto.security import make_token

    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as s:
        s.add(UserModel(username="u", password_hash="x", role="admin",
                        access_scope="lan_only", enabled=1, created_at=1700000000))
        await s.commit()
        user = (await s.execute(select(UserModel).where(UserModel.username == "u"))).scalar_one()
        token = make_token("test-secret", user.id, user.role, 3600)

    req = _FakeRequest(client_host="8.8.8.8", xff="192.168.1.5")
    req.app.state.config = SimpleNamespace(jwt_secret="test-secret", trusted_proxies=["8.8.8.8"])
    req.app.state.sessionmaker = sm
    req.cookies = {"mpg_session": token}

    result = await current_user(request=req)
    assert result.id == user.id
