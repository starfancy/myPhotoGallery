"""Phase 4 integration tests: end-to-end viewer lifecycle + last-admin + trusted_proxies.

覆盖 plan Task 14 Step 3：
1. 端到端：admin 创建 viewer → 授权 gallery1 → viewer 登录 → 仅见 gallery1 →
   admin 改 viewer enabled=0 → viewer 登录 401 → admin 重新启用 → viewer 重登
2. last admin 保护：admin 试图把唯一 admin 改 viewer 409；删除唯一 admin 409；
   disable 唯一 admin 409
3. trusted_proxies 链路：本地裸跑（trusted_proxies=[]）→ XFF 不影响 client_ip；
   nginx 反代（trusted_proxies=["127.0.0.1"]）→ XFF 生效
"""
from __future__ import annotations

import re
import time
import builtins
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from myphoto.main import build_app


# ---- helpers ----

@contextmanager
def fresh_app(tmp_path: Path, *, trusted_proxies: list[str] | None = None):
    """启动一个新 app，schema 重建；捕获 build_app 打印的 admin 初始密码。

    如需定制 trusted_proxies：先走默认 build_app 引导生成 config.toml，
    然后修改文件中的 [security] 段再重新 build_app。
    """
    captured_pw: list[str] = []
    orig_print = builtins.print
    def _capture(*args, **kwargs):
        s = " ".join(str(a) for a in args)
        m = re.search(r"password=(\S+)", s)
        if m:
            captured_pw.append(m.group(1))
        return orig_print(*args, **kwargs)
    builtins.print = _capture
    try:
        cfg_path = tmp_path / "config.toml"
        if trusted_proxies is not None:
            # 先 build_app 一次让 config.toml 自动生成（包含 jwt_secret 等）
            bootstrap_app = build_app(config_path=str(cfg_path))
            with TestClient(bootstrap_app):
                pass
            # 再在文件里追加/修改 [security] 段
            text = cfg_path.read_text(encoding="utf-8")
            # 简单覆盖：把 trusted_proxies = [] 替换为指定值
            tp_repr = "[" + ", ".join(f'"{p}"' for p in trusted_proxies) + "]"
            import re as _re
            text = _re.sub(
                r"trusted_proxies\s*=\s*\[[^\]]*\]",
                f"trusted_proxies = {tp_repr}",
                text,
            )
            cfg_path.write_text(text, encoding="utf-8")
        app = build_app(config_path=str(cfg_path))
        with TestClient(app) as c:
            yield c, app, (captured_pw[0] if captured_pw else None)
    finally:
        builtins.print = orig_print


async def _seed_galleries(app, names: list[str]) -> list[int]:
    from myphoto.models import Gallery

    async with app.state.sessionmaker() as s:
        ids = []
        for name in names:
            g = Gallery(name=name, created_at=int(time.time()))
            s.add(g)
            await s.flush()
            ids.append(g.id)
        await s.commit()
        return ids


def _login_admin(c: TestClient, pw: str) -> None:
    r = c.post("/api/auth/login", json={"username": "admin", "password": pw})
    assert r.status_code == 200, r.text


# ============================================================
# 1. End-to-end viewer lifecycle
# ============================================================

def test_viewer_lifecycle_create_authorize_login_disable(tmp_path, capsys):
    """admin → 建 viewer + 授权 gallery1 → viewer 登录 → 仅见 gallery1
       → admin 禁用 → viewer 登录 401 → admin 重新启用 → viewer 重登成功"""
    captured_pw: list[str] = []
    orig_print = builtins.print
    def _capture(*args, **kwargs):
        s = " ".join(str(a) for a in args)
        m = re.search(r"password=(\S+)", s)
        if m:
            captured_pw.append(m.group(1))
        return orig_print(*args, **kwargs)
    builtins.print = _capture
    try:
        app = build_app(config_path=str(tmp_path / "config.toml"))
        with TestClient(app) as c:
            admin_pw = captured_pw[0]
            _login_admin(c, admin_pw)

            # admin 创建 gallery1 + gallery2
            ids = c.portal.call(_seed_galleries, app, ["Gallery1", "Gallery2"])
            g1, g2 = ids

            # 创建 viewer 并授权 gallery1
            r = c.post("/api/admin/users", json={
                "username": "family_viewer",
                "role": "viewer",
                "access_scope": "remote_allowed",
                "gallery_ids": [g1],
            })
            assert r.status_code == 201
            viewer_uid = r.json()["id"]

            c.post("/api/auth/logout")

            # viewer 登录
            initial_pw = r.json().get("initial_password")
            r = c.post("/api/auth/login", json={
                "username": "family_viewer", "password": initial_pw,
            })
            assert r.status_code == 200, r.text

            # viewer 列表：仅 gallery1
            r = c.get("/api/galleries")
            assert r.status_code == 200
            gids = [g["id"] for g in r.json()]
            assert g1 in gids
            assert g2 not in gids

            # viewer 访问 gallery2 详情 → 404
            r = c.get(f"/api/galleries/{g2}")
            assert r.status_code == 404

            # viewer 改密以验证后续登录
            r = c.post("/api/auth/change-password", json={
                "old_password": initial_pw,
                "new_password": "viewer_pw_1",
            })
            assert r.status_code == 204

            c.post("/api/auth/logout")

            # 切回 admin 并禁用 viewer
            _login_admin(c, admin_pw)
            r = c.patch(f"/api/admin/users/{viewer_uid}", json={"enabled": 0})
            assert r.status_code == 200

            c.post("/api/auth/logout")

            # viewer 登录 → 401（disabled；与 wrong password 同码以避免账号枚举）
            r = c.post("/api/auth/login", json={
                "username": "family_viewer", "password": "viewer_pw_1",
            })
            assert r.status_code == 401
            assert r.json()["error"]["code"] == "invalid_credentials"

            # 重新启用
            _login_admin(c, admin_pw)
            r = c.patch(f"/api/admin/users/{viewer_uid}", json={"enabled": 1})
            assert r.status_code == 200

            c.post("/api/auth/logout")

            # viewer 重新登录成功
            r = c.post("/api/auth/login", json={
                "username": "family_viewer", "password": "viewer_pw_1",
            })
            assert r.status_code == 200
    finally:
        builtins.print = orig_print


# ============================================================
# 2. Last admin protection
# ============================================================

def test_last_admin_protect_delete(tmp_path, capsys):
    """唯一 admin 不能删除自己。"""
    with fresh_app(tmp_path) as (c, app, admin_pw):
        _login_admin(c, admin_pw)
        r = c.delete("/api/admin/users/1")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "last_admin_protected"


def test_last_admin_protect_disable_self(tmp_path, capsys):
    """唯一 admin 不能 disable 自己。"""
    with fresh_app(tmp_path) as (c, app, admin_pw):
        _login_admin(c, admin_pw)
        r = c.patch("/api/admin/users/1", json={"enabled": 0})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "last_admin_protected"


def test_last_admin_protect_demote_self(tmp_path, capsys):
    """唯一 admin 不能把自己降级为 viewer。"""
    with fresh_app(tmp_path) as (c, app, admin_pw):
        _login_admin(c, admin_pw)
        r = c.patch("/api/admin/users/1", json={"role": "viewer"})
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "last_admin_protected"


def test_admin_can_delete_when_two_admins(tmp_path, capsys):
    """有两个 admin 时可以删除一个。"""
    with fresh_app(tmp_path) as (c, app, admin_pw):
        _login_admin(c, admin_pw)
        # 创建 admin2
        r = c.post("/api/admin/users", json={
            "username": "admin2", "password": "admin2_pw_1",
            "role": "admin", "access_scope": "remote_allowed",
        })
        assert r.status_code == 201
        admin2_id = r.json()["id"]

        # 现在有两个 admin，删除 admin2 → 成功
        r = c.delete(f"/api/admin/users/{admin2_id}")
        assert r.status_code == 204


# ============================================================
# 3. trusted_proxies 链路
# ============================================================

def test_xff_ignored_when_trusted_proxies_empty(tmp_path, capsys):
    """trusted_proxies=[]（默认）→ 任何 XFF 被忽略。

    lan_only admin 故意从公网（TestClient client=）登录：被 lan_only 拒绝。
    这验证 "trusted_proxies=[] → 用 request.client.host 而非 XFF" 的语义。
    """
    with fresh_app(tmp_path) as (c, app, admin_pw):
        # 默认 admin 是 remote_allowed；改为 lan_only 来触发访问域判定
        c.post("/api/auth/login", json={"username": "admin", "password": admin_pw})
        r = c.patch("/api/admin/users/1", json={"access_scope": "lan_only"})
        assert r.status_code == 200
        c.post("/api/auth/logout")

        # 从公网 + 假 XFF 头登录：
        # - 走 trusted_proxies=[] 路径：忽略 XFF，用 "8.8.8.8" → 非 LAN → 403
        with TestClient(app, client=("8.8.8.8", 50000)) as wan:
            r = wan.post(
                "/api/auth/login",
                json={"username": "admin", "password": admin_pw},
                headers={"X-Forwarded-For": "192.168.1.1"},
            )
            assert r.status_code == 403
            assert r.json()["error"]["code"] == "access_scope_violation"


def test_xff_ignored_when_client_not_in_trusted_proxies(tmp_path, capsys):
    """trusted_proxies 非空但请求来自公网 → 仍忽略 XFF（防伪）。

    即使配了 trusted_proxies=["192.168.0.0/24"]，公网 8.8.8.8 仍被识别为公网。
    """
    with fresh_app(tmp_path, trusted_proxies=["192.168.0.0/24"]) as (c, app, admin_pw):
        c.post("/api/auth/login", json={"username": "admin", "password": admin_pw})
        r = c.patch("/api/admin/users/1", json={"access_scope": "lan_only"})
        assert r.status_code == 200
        c.post("/api/auth/logout")

        # 公网直连（client host = 8.8.8.8，未命中 trusted 192.168.0.0/24）
        # XFF 即使写成 192.168.1.1 也被忽略
        with TestClient(app, client=("8.8.8.8", 50000)) as wan:
            r = wan.post(
                "/api/auth/login",
                json={"username": "admin", "password": admin_pw},
                headers={"X-Forwarded-For": "192.168.1.1"},
            )
            assert r.status_code == 403
            assert r.json()["error"]["code"] == "access_scope_violation"


def test_xff_honored_when_client_in_trusted_proxies(tmp_path, capsys):
    """trusted_proxies=["127.0.0.1"] + 直连来自 127.0.0.1 → XFF 生效。

    模拟 nginx 反代：nginx 接受真实客户端的 XFF，传给后端；
    后端识别 nginx 来自 trusted 段，于是用 XFF 的最左段作为 effective client_ip。
    """
    with fresh_app(tmp_path, trusted_proxies=["127.0.0.1"]) as (c, app, admin_pw):
        c.post("/api/auth/login", json={"username": "admin", "password": admin_pw})
        r = c.patch("/api/admin/users/1", json={"access_scope": "lan_only"})
        assert r.status_code == 200
        c.post("/api/auth/logout")

        # 直连来自 127.0.0.1（命中 trusted），XFF 头表明真实客户端是 192.168.1.1
        # → effective client_ip = 192.168.1.1 → 是 LAN → 通过
        with TestClient(app, client=("127.0.0.1", 50000)) as lan:
            r = lan.post(
                "/api/auth/login",
                json={"username": "admin", "password": admin_pw},
                headers={"X-Forwarded-For": "192.168.1.1"},
            )
            assert r.status_code == 200, r.text

        # 对照：直连来自 127.0.0.1，但 XFF 头表明真实客户端是 8.8.8.8（公网）
        # → effective client_ip = 8.8.8.8 → 非 LAN → 403
        c.post("/api/auth/logout")
        with TestClient(app, client=("127.0.0.1", 50000)) as lan:
            r = lan.post(
                "/api/auth/login",
                json={"username": "admin", "password": admin_pw},
                headers={"X-Forwarded-For": "8.8.8.8"},
            )
            assert r.status_code == 403
            assert r.json()["error"]["code"] == "access_scope_violation"
