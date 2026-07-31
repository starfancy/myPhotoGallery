import re
import time
from contextlib import contextmanager

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from myphoto.deps import SESSION_COOKIE, admin_required
from myphoto.errors import AppError
from myphoto.main import build_app
from myphoto.models import User


@pytest.fixture
def app_factory(tmp_path_factory, capsys):
    @contextmanager
    def make_client():
        data_dir = tmp_path_factory.mktemp("auth-app")
        app = build_app(config_path=str(data_dir / "config.toml"))
        with TestClient(app) as client:
            out = capsys.readouterr().out
            match = re.search(r"password=(\S+)", out)
            assert match, out
            yield client, match.group(1), app

    return make_client


@pytest.fixture
def app_and_pw(app_factory):
    with app_factory() as app_data:
        yield app_data


async def _set_admin_enabled(app, enabled):
    async with app.state.sessionmaker() as session:
        await session.execute(
            update(User).where(User.username == "admin").values(enabled=enabled)
        )
        await session.commit()


def _login(client, password, username="admin"):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )


def _assert_invalid_credentials(response):
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_me_unauthenticated(app_and_pw):
    client, _, _ = app_and_pw
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_login_success(app_and_pw):
    client, password, _ = app_and_pw
    response = _login(client, password)
    assert response.status_code == 200
    assert SESSION_COOKIE in response.cookies
    assert response.json()["user"]["role"] == "admin"
    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200


def test_wrong_password(app_and_pw):
    client, _, _ = app_and_pw
    _assert_invalid_credentials(_login(client, "wrong"))


def test_unknown_user_still_verifies_one_password(app_and_pw, monkeypatch):
    client, _, _ = app_and_pw
    from myphoto import routes_auth

    calls = []
    real_verify = routes_auth.verify_password

    def recording_verify(plain, hashed):
        calls.append((plain, hashed))
        return real_verify(plain, hashed)

    monkeypatch.setattr(routes_auth, "verify_password", recording_verify)
    _assert_invalid_credentials(_login(client, "wrong", username="missing"))
    assert len(calls) == 1


def test_lockout_counts_first_five_as_failures(app_and_pw):
    client, _, _ = app_and_pw
    for _ in range(5):
        _assert_invalid_credentials(_login(client, "wrong"))

    response = _login(client, "wrong")
    assert response.status_code == 423
    assert response.json()["error"]["code"] == "login_locked"


def test_lockout_is_isolated_per_app(app_factory):
    with app_factory() as (client, _, _):
        for _ in range(5):
            _assert_invalid_credentials(_login(client, "wrong"))
        assert _login(client, "wrong").status_code == 423

    with app_factory() as (client, _, _):
        _assert_invalid_credentials(_login(client, "wrong"))


def test_successful_login_resets_failures(app_and_pw):
    client, password, _ = app_and_pw
    for _ in range(4):
        _assert_invalid_credentials(_login(client, "wrong"))

    assert _login(client, password).status_code == 200

    for _ in range(5):
        _assert_invalid_credentials(_login(client, "wrong"))
    assert _login(client, "wrong").status_code == 423


def test_lockout_expires_at_exact_window_boundary(app_and_pw, monkeypatch):
    client, _, _ = app_and_pw
    from myphoto import routes_auth

    now = [0.0]
    monkeypatch.setattr(routes_auth.time, "monotonic", lambda: now[0])

    for _ in range(5):
        _assert_invalid_credentials(_login(client, "wrong"))

    now[0] = 15 * 60
    _assert_invalid_credentials(_login(client, "wrong"))
    for _ in range(4):
        _assert_invalid_credentials(_login(client, "wrong"))
    assert _login(client, "wrong").status_code == 423


def test_logout_deletes_session_cookie(app_and_pw):
    client, password, _ = app_and_pw
    assert _login(client, password).status_code == 200

    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    set_cookie = response.headers["set-cookie"]
    assert f"{SESSION_COOKIE}=" in set_cookie
    assert "Max-Age=0" in set_cookie
    assert "Path=/" in set_cookie
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "subject",
    [True, 1.5, 0, -1, 2**63, float("inf")],
    ids=["bool", "float", "zero", "negative", "too-large", "infinity"],
)
def test_malformed_token_subject_is_unauthenticated(app_and_pw, subject):
    client, _, app = app_and_pw
    now = int(time.time())
    token = jwt.encode(
        {"sub": subject, "role": "admin", "iat": now, "exp": now + 3600},
        app.state.config.jwt_secret,
        algorithm="HS256",
    )
    client.cookies.set(SESSION_COOKIE, token)

    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_disabled_user_session_is_unauthenticated(app_and_pw):
    client, password, app = app_and_pw
    assert _login(client, password).status_code == 200
    client.portal.call(_set_admin_enabled, app, 0)

    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_disabled_user_login_verifies_password_then_rejects(app_and_pw, monkeypatch):
    client, password, app = app_and_pw
    client.portal.call(_set_admin_enabled, app, 0)
    from myphoto import routes_auth

    calls = []
    real_verify = routes_auth.verify_password

    def recording_verify(plain, hashed):
        calls.append((plain, hashed))
        return real_verify(plain, hashed)

    monkeypatch.setattr(routes_auth, "verify_password", recording_verify)
    _assert_invalid_credentials(_login(client, password))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_admin_required_rejects_non_admin():
    viewer = User(
        id=2,
        username="viewer",
        password_hash="unused",
        role="viewer",
        access_scope="lan_only",
        enabled=1,
        created_at=0,
    )
    with pytest.raises(AppError) as exc_info:
        await admin_required(viewer)

    assert exc_info.value.http_status == 403
    assert exc_info.value.code == "forbidden"


# ---- change-password ----


def test_change_password_success(app_and_pw):
    client, password, _ = app_and_pw
    assert _login(client, password).status_code == 200

    new_pw = "newpassword123456"
    r = client.post("/api/auth/change-password", json={
        "old_password": password,
        "new_password": new_pw,
    })
    assert r.status_code == 204

    # Old password should now fail
    _assert_invalid_credentials(_login(client, password))

    # New password should work
    assert _login(client, new_pw).status_code == 200


def test_change_password_wrong_current(app_and_pw):
    client, password, _ = app_and_pw
    assert _login(client, password).status_code == 200
    r = client.post("/api/auth/change-password", json={
        "old_password": "wrongpassword",
        "new_password": "newpassword123456",
    })
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_change_password_too_weak(app_and_pw):
    client, password, _ = app_and_pw
    assert _login(client, password).status_code == 200
    r = client.post("/api/auth/change-password", json={
        "old_password": password,
        "new_password": "short",
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "password_too_weak"


def test_change_password_unauthenticated(app_and_pw):
    client, _, _ = app_and_pw
    r = client.post("/api/auth/change-password", json={
        "old_password": "x",
        "new_password": "longenoughpassword",
    })
    assert r.status_code == 401


# ---- P4: access_scope in login / me ----

def test_login_success_returns_access_scope(app_and_pw):
    """P4: login 成功后响应含 access_scope 字段。"""
    client, password, _ = app_and_pw
    response = _login(client, password)
    assert response.status_code == 200
    assert response.json()["user"]["access_scope"] == "remote_allowed"


def test_me_returns_access_scope(app_and_pw):
    """P4: GET /api/auth/me 响应含 access_scope。"""
    client, password, _ = app_and_pw
    assert _login(client, password).status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["access_scope"] == "remote_allowed"


def test_login_lan_only_from_public_ip_blocked(app_factory):
    """P4: access_scope=lan_only 用户从公网 IP 登录 → 403。"""
    from myphoto.models import User
    from myphoto.security import hash_password

    with app_factory() as (client, _, app):
        # 创建 lan_only viewer
        async def _create_lan_viewer():
            async with app.state.sessionmaker() as s:
                s.add(User(
                    username="lanviewer",
                    password_hash=hash_password("lanviewerpw"),
                    role="viewer",
                    access_scope="lan_only",
                    enabled=1,
                    created_at=int(time.time()),
                ))
                await s.commit()
        client.portal.call(_create_lan_viewer)

        # 从公网 IP 登录 → 应被拒绝
        with TestClient(app, client=("8.8.8.8", 50000)) as wan_client:
            r = wan_client.post("/api/auth/login", json={
                "username": "lanviewer", "password": "lanviewerpw",
            })
            assert r.status_code == 403
            assert r.json()["error"]["code"] == "access_scope_violation"


def test_login_lan_only_ip_does_not_lock_account(app_factory):
    """P4: access_scope_violation 不计入登录失败锁计数器。"""
    from myphoto.models import User
    from myphoto.security import hash_password

    with app_factory() as (client, _, app):
        async def _create_lan_viewer():
            async with app.state.sessionmaker() as s:
                s.add(User(
                    username="lanviewer2",
                    password_hash=hash_password("lanviewer2pw"),
                    role="viewer",
                    access_scope="lan_only",
                    enabled=1,
                    created_at=int(time.time()),
                ))
                await s.commit()
        client.portal.call(_create_lan_viewer)

        # 从公网 IP 登录 6 次（超过锁阈值）→ 每次都应 403，不触发锁
        with TestClient(app, client=("8.8.8.8", 50000)) as wan_client:
            for _ in range(6):
                r = wan_client.post("/api/auth/login", json={
                    "username": "lanviewer2", "password": "lanviewer2pw",
                })
                assert r.status_code == 403
                assert r.json()["error"]["code"] == "access_scope_violation"
