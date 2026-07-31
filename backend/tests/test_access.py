"""P4 Task 3: access.py 工具测试。

覆盖：
- get_client_ip: trusted_proxies 语义 / XFF 解析 / CIDR 容错
- access_scope_guard: lan_only + LAN 通过 / lan_only + 公网 403
- check_gallery_access: 纯函数 / admin 跳过 / viewer 授权与未授权
- gallery_scope_guard: Depends 形式 / 与 check_gallery_access 一致
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.errors import AppError
from myphoto.models import Gallery, User, UserGallery


# ---- helpers ----

class _FakeState:
    """Simple namespace that accepts arbitrary attributes."""
    pass


class _FakeApp:
    def __init__(self):
        self.state = _FakeState()


class _FakeHeaders:
    def __init__(self, data: dict[str, str] | None = None):
        self._data = {k.lower(): v for k, v in (data or {}).items()}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._data.get(key.lower(), default)


class _FakeClient:
    def __init__(self, host: str):
        self.host = host


class _FakeRequest:
    """Stub Request matching access.py's interface.

    - .client.host
    - .headers.get('x-forwarded-for')
    - .app.state.config / .app.state.sessionmaker
    """
    def __init__(self, client_host: str = "127.0.0.1", xff: str | None = None):
        self.client = _FakeClient(client_host) if client_host else None
        headers_dict = {"x-forwarded-for": xff} if xff is not None else {}
        self.headers = _FakeHeaders(headers_dict)
        self.app = _FakeApp()


def _make_request(client_host: str = "127.0.0.1", xff: str | None = None):
    return _FakeRequest(client_host=client_host, xff=xff)


# ---- get_client_ip ----

def test_get_client_ip_trusted_proxies_empty_ignores_xff():
    from myphoto.access import get_client_ip
    req = _make_request(client_host="8.8.8.8", xff="1.2.3.4")
    assert get_client_ip(req, []) == "8.8.8.8"


def test_get_client_ip_trusted_proxies_empty_no_xff():
    from myphoto.access import get_client_ip
    req = _make_request(client_host="10.0.0.1", xff=None)
    assert get_client_ip(req, []) == "10.0.0.1"


def test_get_client_ip_client_in_trusted_uses_xff_leftmost():
    from myphoto.access import get_client_ip
    req = _make_request(client_host="127.0.0.1", xff="203.0.113.7, 10.0.0.5")
    assert get_client_ip(req, ["127.0.0.1"]) == "203.0.113.7"


def test_get_client_ip_client_in_trusted_no_xff_falls_back():
    from myphoto.access import get_client_ip
    req = _make_request(client_host="127.0.0.1", xff=None)
    assert get_client_ip(req, ["127.0.0.1"]) == "127.0.0.1"


def test_get_client_ip_client_not_in_trusted_ignores_xff():
    from myphoto.access import get_client_ip
    req = _make_request(client_host="8.8.8.8", xff="1.2.3.4")
    assert get_client_ip(req, ["127.0.0.1", "10.0.0.0/8"]) == "8.8.8.8"


def test_get_client_ip_skips_unknown_segments():
    from myphoto.access import get_client_ip
    req = _make_request(client_host="127.0.0.1", xff="unknown, , 203.0.113.9")
    assert get_client_ip(req, ["127.0.0.1"]) == "203.0.113.9"


def test_get_client_ip_all_xff_segments_unknown_falls_back():
    from myphoto.access import get_client_ip
    req = _make_request(client_host="127.0.0.1", xff="unknown,")
    assert get_client_ip(req, ["127.0.0.1"]) == "127.0.0.1"


def test_get_client_ip_trusted_proxies_cidr_match():
    from myphoto.access import get_client_ip
    req = _make_request(client_host="10.0.0.5", xff="203.0.113.7")
    assert get_client_ip(req, ["10.0.0.0/8"]) == "203.0.113.7"


def test_get_client_ip_invalid_cidr_entry_ignored():
    """trusted_proxies 中非法 CIDR 跳过该项，不抛异常。"""
    from myphoto.access import get_client_ip
    req = _make_request(client_host="10.0.0.5", xff="203.0.113.7")
    # 第一项无效，但 10.0.0.0/8 命中
    assert get_client_ip(req, ["not-a-cidr", "10.0.0.0/8"]) == "203.0.113.7"


# ---- access_scope_guard ----

def _run(coro):
    """Sync driver for async helpers (pytest-asyncio fixtures need this for
    plain (non-async) test bodies)."""
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_access_scope_guard_lan_only_lan_ip_passes():
    from myphoto.access import access_scope_guard
    user = User(id=1, username="u", password_hash="x", role="viewer",
                access_scope="lan_only", enabled=1, created_at=0)
    req = _make_request(client_host="192.168.1.5")
    req.app.state.config = SimpleNamespace(trusted_proxies=[])
    result = _run(access_scope_guard(request=req, user=user))
    assert result is user


def test_access_scope_guard_lan_only_public_ip_raises_403():
    from myphoto.access import access_scope_guard
    user = User(id=1, username="u", password_hash="x", role="viewer",
                access_scope="lan_only", enabled=1, created_at=0)
    req = _make_request(client_host="8.8.8.8")
    req.app.state.config = SimpleNamespace(trusted_proxies=[])
    with pytest.raises(AppError) as exc:
        _run(access_scope_guard(request=req, user=user))
    assert exc.value.code == "access_scope_violation"
    assert exc.value.http_status == 403


def test_access_scope_guard_remote_allowed_any_ip_passes():
    from myphoto.access import access_scope_guard
    user = User(id=1, username="u", password_hash="x", role="admin",
                access_scope="remote_allowed", enabled=1, created_at=0)
    req = _make_request(client_host="8.8.8.8")
    req.app.state.config = SimpleNamespace(trusted_proxies=[])
    result = _run(access_scope_guard(request=req, user=user))
    assert result is user


def test_access_scope_guard_honors_trusted_proxies():
    """trusted_proxies + lan_only admin 从 XFF 标识的 LAN IP 登录应通过。"""
    from myphoto.access import access_scope_guard
    user = User(id=1, username="u", password_hash="x", role="admin",
                access_scope="lan_only", enabled=1, created_at=0)
    # request.client.host = 8.8.8.8（公网，nginx 反代）
    # XFF 标识的真实客户端 = 192.168.1.5（LAN）
    # trusted_proxies = ["127.0.0.1"]，但 client 不在 trusted → XFF 被忽略，403
    req = _make_request(client_host="8.8.8.8", xff="192.168.1.5")
    req.app.state.config = SimpleNamespace(trusted_proxies=["127.0.0.1"])
    with pytest.raises(AppError) as exc:
        _run(access_scope_guard(request=req, user=user))
    assert exc.value.code == "access_scope_violation"

    # 把 nginx IP 8.8.8.8 加入 trusted（实际场景：nginx 在 8.8.8.8）→ XFF 生效
    req.app.state.config.trusted_proxies = ["8.8.8.8"]
    result = _run(access_scope_guard(request=req, user=user))
    assert result is user


# ---- gallery / check_gallery_access fixtures ----

@pytest.fixture
async def session_and_sm():
    """Yield (session, sessionmaker) so tests can use the same sessionmaker that
    routes would use."""
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as s:
        yield s, sm
    await engine.dispose()


@pytest.fixture
async def session(session_and_sm):
    s, _ = session_and_sm
    yield s


def asyncio_run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


# ---- check_gallery_access (pure helper) ----

async def test_check_gallery_access_admin_passes_without_row(session):
    from myphoto.access import check_gallery_access
    now = int(time.time())
    admin = User(username="admin", password_hash="x", role="admin",
                 access_scope="lan_only", enabled=1, created_at=now)
    g = Gallery(name="G", created_at=now)
    session.add_all([admin, g])
    await session.commit()
    # admin 不在 user_galleries，调用不抛
    await check_gallery_access(session, admin, g.id)


async def test_check_gallery_access_viewer_with_grant_passes(session):
    from myphoto.access import check_gallery_access
    now = int(time.time())
    v = User(username="v", password_hash="x", role="viewer",
             access_scope="lan_only", enabled=1, created_at=now)
    g = Gallery(name="G", created_at=now)
    session.add_all([v, g])
    await session.flush()
    session.add(UserGallery(user_id=v.id, gallery_id=g.id, granted_at=now))
    await session.commit()
    await check_gallery_access(session, v, g.id)


async def test_check_gallery_access_viewer_without_grant_404(session):
    from myphoto.access import check_gallery_access
    now = int(time.time())
    v = User(username="v", password_hash="x", role="viewer",
             access_scope="lan_only", enabled=1, created_at=now)
    g1 = Gallery(name="G1", created_at=now)
    g2 = Gallery(name="G2", created_at=now)
    session.add_all([v, g1, g2])
    await session.flush()
    session.add(UserGallery(user_id=v.id, gallery_id=g1.id, granted_at=now))
    await session.commit()
    with pytest.raises(AppError) as exc:
        await check_gallery_access(session, v, g2.id)
    assert exc.value.code == "not_found"
    assert exc.value.http_status == 404


async def test_check_gallery_access_after_gallery_deleted_404(session):
    """gallery 删除后 viewer 访问该 gid 应 404（行被 CASCADE 删）。"""
    from myphoto.access import check_gallery_access
    now = int(time.time())
    v = User(username="v", password_hash="x", role="viewer",
             access_scope="lan_only", enabled=1, created_at=now)
    g = Gallery(name="G", created_at=now)
    session.add_all([v, g])
    await session.flush()
    session.add(UserGallery(user_id=v.id, gallery_id=g.id, granted_at=now))
    await session.commit()

    # 删除 gallery → UserGallery 行级联消失
    await session.delete(g)
    await session.commit()

    with pytest.raises(AppError) as exc:
        await check_gallery_access(session, v, g.id)
    assert exc.value.code == "not_found"


# ---- gallery_scope_guard (Depends form) ----

async def test_gallery_scope_guard_admin_passes_without_row(session_and_sm):
    from myphoto.access import gallery_scope_guard
    session, sm = session_and_sm
    now = int(time.time())
    admin = User(username="admin", password_hash="x", role="admin",
                 access_scope="lan_only", enabled=1, created_at=now)
    g = Gallery(name="G", created_at=now)
    session.add_all([admin, g])
    await session.commit()

    req = _make_request_with_sm(client_host="192.168.1.5", sm=sm)
    result = await gallery_scope_guard(gid=g.id, request=req, user=admin)
    assert result is admin


async def test_gallery_scope_guard_viewer_with_grant_passes(session_and_sm):
    from myphoto.access import gallery_scope_guard
    session, sm = session_and_sm
    now = int(time.time())
    v = User(username="v", password_hash="x", role="viewer",
             access_scope="lan_only", enabled=1, created_at=now)
    g = Gallery(name="G", created_at=now)
    session.add_all([v, g])
    await session.flush()
    session.add(UserGallery(user_id=v.id, gallery_id=g.id, granted_at=now))
    await session.commit()

    req = _make_request_with_sm(client_host="192.168.1.5", sm=sm)
    result = await gallery_scope_guard(gid=g.id, request=req, user=v)
    assert result is v


async def test_gallery_scope_guard_viewer_without_grant_404(session_and_sm):
    from myphoto.access import gallery_scope_guard
    session, sm = session_and_sm
    now = int(time.time())
    v = User(username="v", password_hash="x", role="viewer",
             access_scope="lan_only", enabled=1, created_at=now)
    g1 = Gallery(name="G1", created_at=now)
    g2 = Gallery(name="G2", created_at=now)
    session.add_all([v, g1, g2])
    await session.flush()
    session.add(UserGallery(user_id=v.id, gallery_id=g1.id, granted_at=now))
    await session.commit()

    req = _make_request_with_sm(client_host="192.168.1.5", sm=sm)
    with pytest.raises(AppError) as exc:
        await gallery_scope_guard(gid=g2.id, request=req, user=v)
    assert exc.value.code == "not_found"
    assert exc.value.http_status == 404


def _make_request_with_sm(client_host: str, sm):
    """为 gallery_scope_guard 测试用的 request 替身，挂 sessionmaker。"""
    req = _make_request(client_host=client_host)
    req.app.state.sessionmaker = sm
    return req
