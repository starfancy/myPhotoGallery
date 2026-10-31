# Phase 7 实施计划：审计 UI + 主题令牌 + 移动端 + 无障碍 + 文档

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 roadmap 最后一个 phase：AdminAudit 页面与 CSV 导出、浅色/深色双主题、移动端复核、无障碍闭合、文档定稿。

**Architecture:** 唯一后端改动是审计日志留存清理（config + `audit.purge_expired` + 启动/每日调度 + settings 登记）。前端建立语义化 CSS 变量颜色令牌体系（UnoCSS 注册），全库机械迁移；新 AdminAudit 页面复用 AdminTrash 模式；CSV 在前端用既有分页接口循环拉取本地生成。

**Tech Stack:** FastAPI / SQLAlchemy async / pytest（后端）；Vue 3 `<script setup>` + Pinia + vue-router + UnoCSS 0.58 + PhotoSwipe / vitest + @vue/test-utils + jsdom（前端）。

**Spec：** `docs/superpowers/specs/2026-10-31-phase7-audit-theme-mobile-a11y-design.md`

## Global Constraints

- 测试基线：后端 **518 passed / 6 skipped**（`pytest` 在仓库根目录运行）；前端 **249 passed**（`cd frontend && pnpm test`）。每个 task 结束必须保持/扩大全绿；`pnpm build`（含 `vue-tsc --noEmit`）必须通过。
- 后端除 **Task 1** 外零改动；无新表、无新 API 路径（settings 既有 PATCH 登记新键不算新 API）。
- 分支：Task 1 第一步建 `git checkout -b phase7-audit-theme-a11y`；提交粒度跟随各 task；**不推送远程**（用户走代理手动推，最终由用户决定 merge/no-ff）。
- TDD：后端逻辑、前端 utils/组件行为先写失败测试再实现；纯机械颜色迁移（Task 4/5）以守卫测试 + grep 零命中 + 既有 249 测试不回归 + 人工目验为验收。
- 用户文案一律中文（与现有界面一致）；代码注释风格跟随相邻文件（关键约束写「为什么」中文注释）。
- 不引入任何新 npm/pip 依赖。
- 主题相关全局规则（Task 3–5 必须遵守的最终令牌表与映射表，spec §4.1 的实现定稿，新增了 soft/badge 类令牌）：

  **令牌表**（变量存 RGB 通道，消费形态 `rgb(var(--color-X) / <alpha>)`；`:root` 浅色为默认，深色在 `@media (prefers-color-scheme: dark)` 覆盖）：

  | 令牌 | 深色 RGB | 浅色 RGB | 语义 |
  | --- | --- | --- | --- |
  | `base` | 10 10 10 | 250 250 250 | 页面底色 |
  | `surface` | 23 23 23 | 255 255 255 | 卡片/头部/弹层 |
  | `surface-2` | 38 38 38 | 244 244 245 | 输入框/嵌套面板 |
  | `surface-3` | 64 64 64 | 228 228 231 | hover |
  | `surface-4` | 82 82 82 | 212 212 216 | active/禁用强调 |
  | `line` | 38 38 38 | 228 228 231 | 默认边框/分隔线 |
  | `line-strong` | 64 64 64 | 212 212 216 | 强边框 |
  | `ink` | 245 245 245 | 23 23 23 | 主文字 |
  | `ink-2` | 163 163 163 | 64 64 64 | 次要文字 |
  | `ink-muted` | 115 115 115 | 115 115 115 | 弱化/非关键文字 |
  | `primary` | 59 130 246 | 37 99 235 | 主操作底 |
  | `primary-hover` | 37 99 235 | 29 78 216 | 主操作 hover |
  | `primary-text` | 96 165 250 | 29 78 216 | 文字链接/蓝徽标文字 |
  | `primary-soft` | 30 58 138 | 219 234 254 | 蓝色浅底（admin 角色徽标） |
  | `danger` | 220 38 38 | 220 38 38 | 危险按钮底 |
  | `danger-hover` | 185 28 28 | 185 28 28 | 危险按钮 hover |
  | `danger-text` | 248 113 113 | 185 28 28 | 危险文字 |
  | `danger-soft` | 127 29 29 | 254 226 226 | 危险浅底（透明度写在类上） |
  | `danger-line` | 153 27 27 | 254 202 202 | 危险态边框 |
  | `success` | 74 222 128 | 21 128 61 | 成功文字/图标 |
  | `success-btn` | 22 101 52 | 21 128 61 | 启用类绿按钮 |
  | `success-btn-hover` | 21 128 61 | 22 101 52 | 绿按钮 hover |
  | `warning` | 250 204 21 | 180 83 9 | 警告文字/图标 |
  | `warning-soft` | 113 63 18 | 254 243 199 | 警告浅底（远程徽标/警告框） |
  | `warning-line` | 133 77 14 | 253 230 138 | 警告态边框 |
  | `warning-btn` | 133 77 14 | 217 119 6 | 禁用类琥珀按钮 |
  | `warning-btn-hover` | 113 63 18 | 180 83 9 | 琥珀按钮 hover |
  | `focus-ring` | 96 165 250 | 37 99 235 | :focus-visible 焦点环 |

  **机械映射表**（左旧 → 右新，透明度修饰符原样保留，如 `bg-neutral-900/95` → `bg-surface/95`）：

  | 旧 | 新 |
  | --- | --- |
  | `bg-neutral-950` | `bg-base` |
  | `bg-neutral-900` | `bg-surface` |
  | `bg-neutral-800` | `bg-surface-2` |
  | `bg-neutral-700` | `bg-surface-3` |
  | `bg-neutral-600` | `bg-surface-4` |
  | `border-neutral-800` / `divide-neutral-800` | `border-line` / `divide-line` |
  | `border-neutral-700` / `border-neutral-500` | `border-line-strong` |
  | `text-neutral-100` / `text-neutral-200` / `text-neutral-300` | `text-ink` |
  | `text-neutral-400` | `text-ink-2` |
  | `text-neutral-500` / `text-neutral-600` | `text-ink-muted` |
  | `bg-blue-500` / `bg-blue-600` / `bg-blue-700` | `bg-primary` / `bg-primary` / `bg-primary-hover` |
  | `hover:bg-blue-500`（配 bg-blue-600） | `hover:bg-primary-hover` |
  | `hover:bg-blue-600`（配 bg-blue-500） | `hover:bg-primary-hover` |
  | `ring-blue-500` / `accent-blue-600` | `ring-primary` / `accent-primary` |
  | `text-blue-400` / `text-blue-300` | `text-primary-text` |
  | 任意 `bg-red-600/700/800/900` 实心 | `bg-danger` |
  | 任意 red 的 `hover:bg-red-*` | `hover:bg-danger-hover` |
  | `text-red-400` / `text-red-300` | `text-danger-text` |
  | `bg-red-900/30`、`bg-red-950/40` | `bg-danger-soft/30`、`bg-danger-soft/40` |
  | `border-red-800/60` | `border-danger-line/60` |
  | `text-green-400` | `text-success` |
  | `bg-green-800` / `hover:bg-green-700` | `bg-success-btn` / `hover:bg-success-btn-hover` |
  | `text-yellow-*` / `text-amber-*`（文字） | `text-warning` |
  | `bg-yellow-900/20` / `bg-yellow-950/40` / `bg-amber-950/40` | `bg-warning-soft/20` / `bg-warning-soft/40` / `bg-warning-soft/40` |
  | `border-yellow-900/40` / `border-yellow-800/60` / `border-amber-800/60` | `border-warning-line/40` / `border-warning-line/60` / `border-warning-line/60` |
  | `bg-yellow-800` / `hover:bg-yellow-700` | `bg-warning-btn` / `hover:bg-warning-btn-hover` |
  | `bg-purple-900/60` / `text-purple-200` | `bg-primary-soft/60` / `text-primary-text` |
  | `bg-orange-900/60` / `text-orange-200` | `bg-warning-soft/60` / `text-warning` |

  **样式块裸值规则**：图片上的黑色渐变遮罩/白字（PhotoCell、SubfolderStrip）与 ImageLightbox 全部 scoped 样式保持字面量不动（灯箱常暗，见 Task 5 说明）。其余裸值：AdminTrash `.lb-trash-thumb background: rgb(23 23 23)` → `rgb(var(--color-surface))`；CellContextMenu 的 `rgba(24,24,27,.98)` → `rgb(var(--color-surface) / .98)`、`rgba(255,255,255,.08)` 边框 → `rgb(var(--color-line))`、hover 同值 → `rgb(var(--color-surface-3))`；PhotoCell scoped 里的 `rgb(37 99 235)`（选中描边/勾选底）→ `rgb(var(--color-primary-hover))`。

---

### Task 1: 审计留存后端（config + purge + 调度 + settings 登记）

**Files:**
- Modify: `backend/src/myphoto/config.py`（AppConfig 字段、模板、loader）
- Modify: `backend/src/myphoto/audit.py`（新增 `purge_expired`）
- Modify: `backend/src/myphoto/trash.py`（每日 tick 追加 audit 清理）
- Modify: `backend/src/myphoto/main.py`（启动清理钩子）
- Modify: `backend/src/myphoto/config_writer.py`（field map + SettingsUpdates）
- Modify: `backend/src/myphoto/routes_admin.py`（SettingsPatch/_settings_payload/_validate_settings/updates/changed）
- Create: `backend/tests/test_audit_retention.py`

**Interfaces:**
- Produces:
  - `AppConfig.audit_retention_days: int`（{0,30,90,180,365}，默认 180，0=永不）
  - `async def purge_expired(session: AsyncSession, retention_days: int, now: int | None = None) -> int` in `myphoto/audit.py`（删除 `AuditLog.ts < now-retention_days*86400`，返回删除条数；retention_days=0 直接返回 0；自身不写审计）
  - settings GET/PATCH 新增键 `audit_retention_days`，合法集合 `{0,30,90,180,365}`；config_writer 映射 `("audit", "retention_days")`

- [ ] **Step 1: 建分支**

```bash
git checkout -b phase7-audit-theme-a11y
```

- [ ] **Step 2: 写失败测试** `backend/tests/test_audit_retention.py`：

```python
"""P7: audit_log retention — loader clamp, purge_expired, startup/daily hooks, settings."""
from __future__ import annotations

import asyncio
import re
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from myphoto.audit import purge_expired
from myphoto.config import load_or_init
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.main import build_app
from myphoto.models import AuditLog


@pytest.mark.parametrize("value,expected", [
    ("30", 30), ("90", 90), ("180", 180), ("365", 365), ("0", 0),
])
def test_loader_accepts_allowed_values(tmp_path, value, expected):
    p = tmp_path / "config.toml"
    p.write_text(
        f'[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        f"[audit]\nretention_days = {value}\n",
        encoding="utf-8",
    )
    assert load_or_init(p).audit_retention_days == expected


def test_loader_default_180_when_section_missing(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n', encoding="utf-8")
    assert load_or_init(p).audit_retention_days == 180


def test_loader_bad_type_falls_back_180(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\njwt_secret="x"\n[audit]\nretention_days = "forever"\n',
        encoding="utf-8",
    )
    assert load_or_init(p).audit_retention_days == 180


@pytest.mark.parametrize("raw,expected", [("100", 90), ("999", 365), ("-5", 0), ("200", 180)])
def test_loader_clamps_to_nearest_choice(tmp_path, raw, expected):
    # 最近合法集合 {0,30,90,180,365}；等距时取较小值（实现需稳定）
    p = tmp_path / "config.toml"
    p.write_text(
        f'[app]\njwt_secret="x"\n[audit]\nretention_days = {raw}\n',
        encoding="utf-8",
    )
    assert load_or_init(p).audit_retention_days == expected


def test_generated_template_contains_audit_section(tmp_path):
    p = tmp_path / "config.toml"
    load_or_init(p)
    text = p.read_text(encoding="utf-8")
    assert "[audit]" in text
    assert "retention_days = 180" in text


@pytest.fixture
async def memdb():
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    yield sm
    await engine.dispose()


async def test_purge_deletes_only_expired(memdb):
    now = 1_000_000_000
    async with memdb() as s:
        s.add(AuditLog(ts=now - 181 * 86400, actor_ip="x", action="login_success"))   # 删
        s.add(AuditLog(ts=now - 180 * 86400, actor_ip="x", action="login_success"))   # 保留边界
        s.add(AuditLog(ts=now - 100, actor_ip="x", action="login_success"))           # 保留
        await s.commit()

    async with memdb() as s:
        removed = await purge_expired(s, 180, now=now)
        await s.commit()
        assert removed == 1
        rows = (await s.execute(select(AuditLog))).scalars().all()
        assert len(rows) == 2


async def test_purge_zero_retention_is_noop(memdb):
    async with memdb() as s:
        s.add(AuditLog(ts=1, actor_ip="x", action="login_success"))
        await s.commit()
        assert await purge_expired(s, 0, now=2_000_000_000) == 0
        await s.commit()
        assert len((await s.execute(select(AuditLog))).scalars().all()) == 1


async def test_purge_empty_table(memdb):
    async with memdb() as s:
        assert await purge_expired(s, 30, now=int(time.time())) == 0


@pytest.fixture
def client(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        pw = re.search(r"password=(\S+)", capsys.readouterr().out).group(1)
        r = c.post("/api/auth/login", json={"username": "admin", "password": pw})
        assert r.status_code == 200
        yield c, app, cfg


def test_settings_exposes_audit_retention(client):
    c, _, _ = client
    assert c.get("/api/admin/settings").json()["audit_retention_days"] == 180


@pytest.mark.parametrize("ok", [0, 30, 90, 180, 365])
def test_settings_patch_allowed(client, ok):
    c, _, _ = client
    r = c.patch("/api/admin/settings", json={"audit_retention_days": ok})
    assert r.status_code == 200
    assert r.json()["audit_retention_days"] == ok


@pytest.mark.parametrize("bad", [1, 7, 100, 366, -30])
def test_settings_patch_rejects(client, bad):
    c, _, _ = client
    r = c.patch("/api/admin/settings", json={"audit_retention_days": bad})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


async def test_daily_tick_purges_audit_after_trash(monkeypatch):
    """daily_purge_loop 同一 tick 内先 trash 后 audit；audit 段独立 try。"""
    from myphoto.trash import daily_purge_loop

    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    now = int(time.time())
    async with sm() as s:
        s.add(AuditLog(ts=now - 31 * 86400, actor_ip="x", action="login_fail"))
        s.add(AuditLog(ts=now - 100, actor_ip="x", action="login_success"))
        await s.commit()

    class _Cfg:
        trash_purge_hour = 3
        trash_purge_minute = 30
        audit_retention_days = 30

    sleeps = {"n": 0}

    async def fake_sleep(seconds):
        sleeps["n"] += 1
        if sleeps["n"] == 1:
            return
        raise asyncio.CancelledError

    import myphoto.trash as trash_mod
    monkeypatch.setattr(trash_mod.asyncio, "sleep", fake_sleep)
    task = asyncio.create_task(daily_purge_loop(sm, lambda: _Cfg()))
    with pytest.raises(asyncio.CancelledError):
        await task

    async with sm() as s:
        rows = (await s.execute(select(AuditLog))).scalars().all()
        assert len(rows) == 1
    await engine.dispose()


def test_startup_purges_expired_audit_rows(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[app]\njwt_secret="x"\n[audit]\nretention_days = 30\n',
        encoding="utf-8",
    )
    app = build_app(config_path=str(cfg))
    # 首次启动写默认模板（jwt 缺失会怎样？先 build 一次让它生成模板再覆盖不行——
    # 直接走 TestClient 启动后用 sessionmaker 插旧行再第二次 lifespan 不现实；
    # 改为：第一次启动后插入旧行，关闭；第二次启动验证被清）。
    with TestClient(app) as c:
        capsys.readouterr()
        old = int(time.time()) - 31 * 86400
        fresh = int(time.time()) - 10
        async def _seed():
            async with app.state.sessionmaker() as s:
                s.add(AuditLog(ts=old, actor_ip="x", action="login_fail"))
                s.add(AuditLog(ts=fresh, actor_ip="x", action="login_success"))
                await s.commit()
        c.portal.call(_seed)

    with TestClient(app) as c2:
        async def _check():
            async with app.state.sessionmaker() as s:
                return [(await s.execute(select(AuditLog))).scalars().all()]
        (rows,) = c2.portal.call(_check)
        assert all(r.ts > int(time.time()) - 30 * 86400 for r in rows)
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest backend/tests/test_audit_retention.py -v`
Expected: FAIL（`AttributeError: audit_retention_days` / `ImportError: purge_expired`）

- [ ] **Step 4: 实现 config.py**

`AppConfig` 增加字段（在 `download_batch_limit` 后）：

```python
    # [audit] section
    audit_retention_days: int  # 审计日志保留天数，合法 {0,30,90,180,365}，默认 180，0=永不清理
```

模板 `_DEFAULT_TEMPLATE` 在 `[download]` 段后追加：

```python
[audit]
# 审计日志保留天数，合法值: 0(永不清理) / 30 / 90 / 180 / 365
retention_days = 180
```

`load_or_init` 内在 download 段解析之后追加：

```python
    # [audit] retention_days：缺失/非法类型=180；越界整数钳到最近合法值。
    # 与 download.batch_limit 同理：手改 config.toml 不应导致启动失败。
    audit_section = data.get("audit", {})
    raw_retention = audit_section.get("retention_days", 180)
    try:
        audit_retention_days = int(raw_retention)
    except (TypeError, ValueError):
        log.warning(
            "invalid [audit].retention_days=%r; falling back to 180", raw_retention,
        )
        audit_retention_days = 180
    else:
        _AUDIT_CHOICES = (0, 30, 90, 180, 365)
        if audit_retention_days not in _AUDIT_CHOICES:
            clamped = min(_AUDIT_CHOICES, key=lambda c: abs(c - audit_retention_days))
            log.warning(
                "[audit].retention_days=%s not in %s; clamped to %s",
                audit_retention_days, _AUDIT_CHOICES, clamped,
            )
            audit_retention_days = clamped
```

`return AppConfig(...)` 末尾加 `audit_retention_days=audit_retention_days,`。

- [ ] **Step 5: 实现 audit.purge_expired**

在 `backend/src/myphoto/audit.py` 顶部 import 增加 `from sqlalchemy import delete` 与 `from sqlalchemy.ext.asyncio import AsyncSession`（文件已有 `from myphoto.models import AuditLog`），文件末尾追加：

```python
async def purge_expired(
    session: AsyncSession,
    retention_days: int,
    now: int | None = None,
) -> int:
    """物理删除超过保留期的审计行，返回删除条数。

    retention_days=0 为「永不清理」哨兵。审计行无 FS 副作用、无外键关联，
    直接 DELETE。清理动作自身不写审计（避免自引用噪声）。
    """
    if retention_days <= 0:
        return 0
    effective_now = int(time.time()) if now is None else int(now)
    cutoff = effective_now - retention_days * 86400
    result = await session.execute(delete(AuditLog).where(AuditLog.ts < cutoff))
    return int(result.rowcount or 0)
```

- [ ] **Step 6: 启动钩子**（`backend/src/main.py`）

import 行改为：

```python
from myphoto.audit import purge_expired as purge_audit_expired
```

在现有 startup trash 清理块（`except Exception: log.exception("startup purge_expired failed")`）之后、`app.state...` 赋值之前，插入独立 try 块：

```python
        # 启动时顺带清理一次过期审计日志；与回收站清理互不影响。
        try:
            async with sm() as session:
                removed = await purge_audit_expired(session, cfg.audit_retention_days)
                await session.commit()
            if removed:
                log.info("startup audit purge removed=%s", removed)
        except Exception:
            log.exception("startup audit purge failed")
```

- [ ] **Step 7: 每日 tick**（`backend/src/myphoto/trash.py`）

import：

```python
from myphoto.audit import purge_expired as purge_audit_expired, write_audit
```

把 `daily_purge_loop` 循环体里 trash 那段（`async with sessionmaker() as session: ... await session.commit()`）包进内层 `try/except Exception: log.exception("scheduled trash purge failed")`，其后追加独立 try 块：

```python
            # 同一 tick 内先 trash 后 audit；audit 清理独立 try，互不影响。
            try:
                async with sessionmaker() as session:
                    removed = await purge_audit_expired(
                        session, config_getter().audit_retention_days
                    )
                    await session.commit()
                if removed:
                    log.info("scheduled audit purge removed=%s", removed)
            except Exception:
                log.exception("scheduled audit purge failed")
```

注意：audit 清理块必须放在 trash try 的**外面**（trash 失败不影响 audit），但仍在外层 `while True` 的总 try 之内。

同步把 `backend/tests/test_daily_purge.py` 里既有的 `class _Cfg` 补一行 `audit_retention_days = 180`，避免既有调度测试在日志里制造预期外异常噪声。

- [ ] **Step 8: settings 登记**（四处小改，全在 `routes_admin.py`）

1. `SettingsPatch` 加 `audit_retention_days: int | None = None`
2. 模块级加 `_AUDIT_RETENTION_CHOICES = {0, 30, 90, 180, 365}`
3. `_settings_payload` 返回字典加 `"audit_retention_days": cfg.audit_retention_days,`
4. `_validate_settings` 加：

```python
    if body.audit_retention_days is not None and (
        body.audit_retention_days not in _AUDIT_RETENTION_CHOICES
    ):
        errors.append("audit_retention_days must be one of 0/30/90/180/365")
```

5. `admin_update_settings` 中 `SettingsUpdates(...)` 加 `audit_retention_days=body.audit_retention_days,`，`changed` 元组加 `("audit_retention_days", body.audit_retention_days),`。

`config_writer.py` 两处：`_FIELD_MAP` 加 `"audit_retention_days": ("audit", "retention_days"),`；`SettingsUpdates` 加 `audit_retention_days: int | None = None`。

- [ ] **Step 9: 跑新测试与全量后端**

Run: `pytest backend/tests/test_audit_retention.py -v && pytest`
Expected: 新测试全 PASS；全量基线 518 → 约 536 全绿（新增 ~18 个参数化用例），6 skipped 不变。

- [ ] **Step 10: 提交**

```bash
git add backend/src/myphoto/config.py backend/src/myphoto/audit.py backend/src/myphoto/trash.py \
  backend/src/myphoto/main.py backend/src/myphoto/config_writer.py backend/src/myphoto/routes_admin.py \
  backend/tests/test_audit_retention.py
git commit -m "feat(audit): configurable retention purge at startup and daily tick"
```

---

### Task 2: AdminSettings 审计留存项（前端）

**Files:**
- Modify: `frontend/src/views/AdminSettings.vue`
- Test: `frontend/src/tests/admin-settings.spec.ts`

**Interfaces:**
- Consumes: Task 1 的 `GET/PATCH /api/admin/settings` 字段 `audit_retention_days`
- Produces: 设置页「审计日志」section（下拉选择），写回同一 PATCH

- [ ] **Step 1: 写失败测试**（改 `frontend/src/tests/admin-settings.spec.ts`，该文件用 `DEFAULTS` 常量 + `mountView()` + 单条 `mockResolvedValueOnce(json(DEFAULTS))` 模式）：

a. 顶部 `interface Settings` 与 `const DEFAULTS` 各加 `audit_retention_days: 180`（扫一遍文件，凡内联 settings body 字面量同样补键；有断言 PATCH body 精确对象的用例同步加键）。

b. 在 describe 内追加：

```ts
  it("loads and saves audit_retention_days", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(json({ ...DEFAULTS, audit_retention_days: 180 }))  // GET
      .mockResolvedValueOnce(json({ ...DEFAULTS, audit_retention_days: 365 }))) // PATCH 回显
    const w = await mountView()

    const select = w.find("#audit-retention")
    expect(select.exists()).toBe(true)
    expect((select.element as HTMLSelectElement).value).toBe("180")
    await select.setValue("365")
    await w.findAll("button").find((b) => b.text() === "保存")!.trigger("click")
    await flushPromises()

    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls as Array<[string, RequestInit?]>
    const patch = calls.find((c) => c[0] === "/api/admin/settings" && c[1]?.method === "PATCH")!
    expect(JSON.parse(patch[1]!.body as string).audit_retention_days).toBe(365)
  })
```

（先读该文件确认 PATCH 是否也有 loading mock 需求，按既有"saves changed fields"用例的 mock 编排对齐。）

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && pnpm test -- admin-settings`
Expected: FAIL（找不到包含「180 天」的 select）

- [ ] **Step 3: 实现**（`AdminSettings.vue`）

`SettingsForm` interface、`form` 初值、`load()` 重建、`save()` 重建、`normalized()` 五处都加 `audit_retention_days: number`（初值 180）。

在「批量下载」`</section>` 之后、保存按钮之前插入（本 task 先用旧颜色类，Task 5 统一迁移）：

```vue
        <!-- 审计日志 -->
        <section class="rounded-lg bg-neutral-900 p-4">
          <h2 class="mb-3 text-sm font-medium text-neutral-400">审计日志</h2>
          <label for="audit-retention" class="block text-xs text-neutral-500">
            审计日志保留天数
          </label>
          <select id="audit-retention" v-model.number="form.audit_retention_days"
                  class="mt-1 rounded bg-neutral-800 px-2 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500">
            <option :value="30">30 天</option>
            <option :value="90">90 天</option>
            <option :value="180">180 天</option>
            <option :value="365">365 天</option>
            <option :value="0">永不清理</option>
          </select>
          <p class="mt-2 text-xs text-neutral-500">
            超期记录在服务启动时及每日定时清理；保存后立即生效。
          </p>
        </section>
```

- [ ] **Step 4: 跑前端全量 + 类型检查**

Run: `cd frontend && pnpm test && pnpm build`
Expected: 250 passed；build 通过。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/AdminSettings.vue frontend/src/tests/admin-settings.spec.ts
git commit -m "feat(settings): audit log retention control in admin settings"
```

---

### Task 3: 主题令牌基础设施（base.css + uno.config）

**Files:**
- Modify: `frontend/src/styles/base.css`
- Modify: `frontend/uno.config.ts`

**Interfaces:**
- Produces: Global Constraints 令牌表中的全部 CSS 变量与同名 UnoCSS 颜色（`bg-surface`、`text-ink`、`border-line`、`ring-primary`、`divide-line`、`accent-primary` 等）。

- [ ] **Step 1: 在 `styles/base.css` 顶部（现有注释补丁之前）写入令牌定义**

```css
/* ---- P7 语义颜色令牌：浅色为默认，深色跟随系统 prefers-color-scheme ----
 * 变量存 RGB 通道，消费形态 rgb(var(--color-X) / <alpha>)，
 * 这样 UnoCSS 的 /60 /95 透明度修饰符仍可用。
 * 深色值 = P7 之前的既有调色板，保证深色外观零变化。
 * ImageLightbox/PhotoSwipe 不消费这些变量（其样式为常暗字面量）。
 */
:root {
  --color-base: 250 250 250;
  --color-surface: 255 255 255;
  --color-surface-2: 244 244 245;
  --color-surface-3: 228 228 231;
  --color-surface-4: 212 212 216;
  --color-line: 228 228 231;
  --color-line-strong: 212 212 216;
  --color-ink: 23 23 23;
  --color-ink-2: 64 64 64;
  --color-ink-muted: 115 115 115;
  --color-primary: 37 99 235;
  --color-primary-hover: 29 78 216;
  --color-primary-text: 29 78 216;
  --color-primary-soft: 219 234 254;
  --color-danger: 220 38 38;
  --color-danger-hover: 185 28 28;
  --color-danger-text: 185 28 28;
  --color-danger-soft: 254 226 226;
  --color-danger-line: 254 202 202;
  --color-success: 21 128 61;
  --color-success-btn: 21 128 61;
  --color-success-btn-hover: 22 101 52;
  --color-warning: 180 83 9;
  --color-warning-soft: 254 243 199;
  --color-warning-line: 253 230 138;
  --color-warning-btn: 217 119 6;
  --color-warning-btn-hover: 180 83 9;
  --color-focus-ring: 37 99 235;
}

@media (prefers-color-scheme: dark) {
  :root {
    --color-base: 10 10 10;
    --color-surface: 23 23 23;
    --color-surface-2: 38 38 38;
    --color-surface-3: 64 64 64;
    --color-surface-4: 82 82 82;
    --color-line: 38 38 38;
    --color-line-strong: 64 64 64;
    --color-ink: 245 245 245;
    --color-ink-2: 163 163 163;
    --color-ink-muted: 115 115 115;
    --color-primary: 59 130 246;
    --color-primary-hover: 37 99 235;
    --color-primary-text: 96 165 250;
    --color-primary-soft: 30 58 138;
    --color-danger: 220 38 38;
    --color-danger-hover: 185 28 28;
    --color-danger-text: 248 113 113;
    --color-danger-soft: 127 29 29;
    --color-danger-line: 153 27 27;
    --color-success: 74 222 128;
    --color-success-btn: 22 101 52;
    --color-success-btn-hover: 21 128 61;
    --color-warning: 250 204 21;
    --color-warning-soft: 113 63 18;
    --color-warning-line: 133 77 14;
    --color-warning-btn: 133 77 14;
    --color-warning-btn-hover: 113 63 18;
    --color-focus-ring: 96 165 250;
  }
}
```

现有 button 背景补丁与 `.pswp--original::after` 两段保留不动。

- [ ] **Step 2: 注册 UnoCSS 颜色**（替换整个 `frontend/uno.config.ts`）

```ts
import { defineConfig, presetUno } from "unocss"

// 名称与 base.css 中的 --color-* 变量一一对应。
const tokenNames = [
  "base", "surface", "surface-2", "surface-3", "surface-4",
  "line", "line-strong",
  "ink", "ink-2", "ink-muted",
  "primary", "primary-hover", "primary-text", "primary-soft",
  "danger", "danger-hover", "danger-text", "danger-soft", "danger-line",
  "success", "success-btn", "success-btn-hover",
  "warning", "warning-soft", "warning-line", "warning-btn", "warning-btn-hover",
  "focus-ring",
] as const

const channel = (name: string) => `rgb(var(--color-${name}) / <alpha-value>)`

export default defineConfig({
  presets: [presetUno()],
  theme: {
    colors: Object.fromEntries(tokenNames.map((n) => [n, channel(n)])),
  },
})
```

- [ ] **Step 3: 冒烟验证（视觉不变）**

Run: `cd frontend && pnpm build`
Expected: 构建通过。此时尚无组件使用新类，深色外观应无任何变化；`pnpm dev` 目验首页（系统处于深色模式时与现状一致；浅色模式下页面仍为旧深色，属预期，Task 4/5 迁移）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/styles/base.css frontend/uno.config.ts
git commit -m "feat(theme): semantic color tokens with light/dark palettes"
```

---

### Task 4: 令牌迁移第一批 —— App 外壳与浏览链路

**Files（逐文件按 Global Constraints 映射表全量替换）:**
- `frontend/src/App.vue`
- `frontend/src/components/AppHeader.vue`
- `frontend/src/components/Breadcrumb.vue`
- `frontend/src/components/PhotoCell.vue`（含 scoped 裸值规则）
- `frontend/src/components/GridLayoutSwitch.vue`
- `frontend/src/components/PaginationBar.vue`
- `frontend/src/components/SearchBox.vue`
- `frontend/src/components/SearchResults.vue`（scoped 无裸色，只换类）
- `frontend/src/components/SubfolderStrip.vue`（图片遮罩裸值保留）
- `frontend/src/components/CellContextMenu.vue`（scoped 裸值按全局规则换变量）
- `frontend/src/views/BrowseView.vue`
- `frontend/src/views/GalleryListView.vue`
- `frontend/src/views/RootListView.vue`
- `frontend/src/views/LoginView.vue`
- `frontend/src/views/ChangePasswordView.vue`

**Interfaces:** 无新增；纯样式机械替换。

- [ ] **Step 1: 迁移 App.vue**

`min-h-screen bg-neutral-950 text-neutral-100` → `min-h-screen bg-base text-ink`。

- [ ] **Step 2: 迁移 AppHeader.vue**

代表性替换（其余按映射表逐条）：`border-neutral-800 bg-neutral-900/95` → `border-line bg-surface/95`；菜单项 `text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100` → `text-ink-2 hover:bg-surface-2 hover:text-ink`；打开态 `bg-neutral-800 text-neutral-100` → `bg-surface-2 text-ink`；LAN 徽标 `bg-neutral-700 text-neutral-200` → `bg-surface-3 text-ink`；远程徽标 `bg-orange-900/60 text-orange-200` → `bg-warning-soft/60 text-warning`。

- [ ] **Step 3: 逐文件替换剩余 13 个文件**

每文件完成后用该文件路径跑一次 grep 自检：

```bash
cd frontend/src
grep -nE '(bg|text|border|ring|divide|from|to|placeholder|accent)-(neutral|blue|red|green|yellow|amber|orange|purple)-[0-9]' components/Breadcrumb.vue
# 对 15 个文件逐一替换 <file>；期望全部无输出
```

语境判定要点：
- `text-neutral-300` 一律 `text-ink`（如 PaginationBar 页码按钮文字）。
- 实心彩色按钮补 `text-white`（浅色主题下页面字色为深色，彩底必须显式白字；如 LoginView 登录按钮、BrowseView 删除/下载底栏按钮、SearchBox 等）。逐文件检查：凡 `bg-primary`/`bg-danger`/`bg-warning-btn`/`bg-success-btn` 实心按钮，class 中加 `text-white`（`text-white` 不被守卫禁止）。
- LoginView 三个提示框：红框 `border-red-800/60 bg-red-950/40 text-red-300` → `border-danger-line/60 bg-danger-soft/40 text-danger-text`；琥珀/黄同理按映射表。
- PhotoCell scoped：仅 `rgb(37 99 235)` 两处换 `rgb(var(--color-primary-hover))`；黑色渐变/白字保留。
- SubfolderStrip：黑色渐变遮罩与白字保留，模板类按表换。
- CellContextMenu scoped：

```css
.lb-cell-menu {
  /* 其余属性不动 */
  background: rgb(var(--color-surface) / 0.98);
  color: rgb(var(--color-ink));
  border: 1px solid rgb(var(--color-line));
}
.lb-cell-menu-item:hover {
  background: rgb(var(--color-surface-3));
}
```

- [ ] **Step 4: 跑全量前端测试 + build**

Run: `cd frontend && pnpm test && pnpm build`
Expected: 250 passed 不回归（个别断言 class 名的测试若失败，同步改为断言令牌类），build 通过。

- [ ] **Step 5: 人工目验（深色零回归 + 浅色首检）**

`pnpm dev`，系统深色模式：登录 → 图库 → 浏览（两种网格）→ 搜索 → 灯箱 → 改密，与 P6 目视一致。系统切浅色：上述页面无白底白字、无消失边框（本批页面在浅色下应已完整可读；管理页仍为旧深色，Task 5 处理）。

- [ ] **Step 6: 提交**

```bash
git add frontend/src
git commit -m "refactor(theme): migrate shell and browse views to semantic tokens"
```

---

### Task 5: 令牌迁移第二批 —— 管理页/弹窗 + 灯箱结论 + 回潮守卫测试

**Files:**
- `frontend/src/views/AdminOverview.vue`、`AdminGalleryList.vue`、`AdminGalleryEdit.vue`、`AdminUsers.vue`、`AdminTrash.vue`、`AdminSettings.vue`
- `frontend/src/components/DirectoryChooser.vue`
- Create: `frontend/src/tests/theme-guard.spec.ts`

**Interfaces:** 无新增。

- [ ] **Step 1: 迁移 7 个文件**

按 Global Constraints 映射表逐文件替换并逐文件 grep 自检（命令同 Task 4 Step 3）。语境要点：
- 管理页所有实心蓝/红按钮补 `text-white`。
- AdminUsers：角色徽标 `bg-purple-900/60 text-purple-200` → `bg-primary-soft/60 text-primary-text`；普通徽标 `bg-neutral-700 text-neutral-200` → `bg-surface-3 text-ink`；远程徽标 → `bg-warning-soft/60 text-warning`；启用/禁用按钮黄/绿 → warning-btn / success-btn 体系（加 `text-white`）。
- AdminTrash：类按表换；scoped `.lb-trash-thumb` 的 `background: rgb(23 23 23)` → `rgb(var(--color-surface))`。
- DirectoryChooser：truncated 警告条按 warning-soft 映射；路径面包屑「/」`text-neutral-600` → `text-ink-muted`。
- AdminSettings Task 2 新增的审计段旧类一并换掉。

- [ ] **Step 2: 灯箱结论确认（不写 force-dark 死代码）**

spec §4.3 原计划给灯箱加 `.force-dark` 变量重绑。实现核查结论（执行时复核）：

```bash
cd frontend/src
grep -nE '(bg|text|border|ring|divide)-(neutral|blue|red|green|yellow|amber|orange|purple)-[0-9]' components/ImageLightbox.vue
```

期望**无输出**——ImageLightbox 的全部视觉（PhotoSwipe chrome、注入按钮/EXIF 面板/右键菜单）都由 scoped CSS 字面量深色构成，且 PhotoSwipe 挂在 `document.body`、不在 `#app` 变量继承链内。没有任何令牌消费者，因此**不需要** `.force-dark`：灯箱天然常暗。在 `styles/base.css` 的令牌注释段末尾补一行：

```css
 * 灯箱（ImageLightbox/PhotoSwipe）刻意不接入令牌：其界面常暗且挂在 body 层。
```

若 grep 意外有输出，则按 spec §4.3 给 `.pswp` 加重绑变量块并把命中类换令牌（二选一，以 grep 结果为准）。

- [ ] **Step 3: 写守卫测试** `frontend/src/tests/theme-guard.spec.ts`：

```ts
import { describe, it, expect } from "vitest"
import { readFileSync, readdirSync, statSync } from "node:fs"
import { join } from "node:path"

// 禁止回潮：应用代码不得再出现 Tailwind 色阶硬编码类。
// 豁免：测试目录（断言旧类名时可能引用）、styles/base.css（令牌定义本体）、
// ImageLightbox.vue（灯箱常暗，刻意保留字面量，详见 base.css 注释）。
const SRC = join(__dirname, "..")
const HARDCODED = /(bg|text|border|ring|divide|from|to|outline|placeholder|accent)-(neutral|blue|red|green|yellow|amber|orange|purple)-[0-9]/
const SKIP = new Set(["tests", "styles"])
const SKIP_FILES = new Set(["ImageLightbox.vue"])

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(vue|ts)$/.test(name) && !SKIP_FILES.has(name)) out.push(p)
  }
  return out
}

describe("theme token guard", () => {
  it("no hardcoded Tailwind color-scale classes outside exemptions", () => {
    const offenders: string[] = []
    for (const file of walk(SRC)) {
      const lines = readFileSync(file, "utf-8").split("\n")
      lines.forEach((line, i) => {
        if (HARDCODED.test(line)) offenders.push(`${file}:${i + 1}: ${line.trim()}`)
      })
    }
    expect(offenders).toEqual([])
  })
})
```

- [ ] **Step 4: 全量验证**

Run: `cd frontend && pnpm test && pnpm build`
Expected: 251+ passed（含新守卫），build 通过；守卫测试如果红，按输出文件行号把漏网类换完。

- [ ] **Step 5: 人工目验浅色管理页**

`pnpm dev` 浅色模式：AdminOverview/Galleries/GalleryEdit/Users/Trash/Settings/Audit 无（Audit 页 Task 7 才有）——逐页核对对比度、徽标、弹窗、禁用/启用按钮；深色模式与 P6 一致。

- [ ] **Step 6: 提交**

```bash
git add frontend/src
git commit -m "refactor(theme): migrate admin views to tokens; add hardcoded-color guard"
```

---

### Task 6: 共享审计 action 标签表 utils/audit.ts

**Files:**
- Create: `frontend/src/utils/audit.ts`
- Create: `frontend/src/tests/audit-labels.spec.ts`
- Modify: `frontend/src/views/AdminOverview.vue`（删内嵌表，改引用）
- Modify: `frontend/src/tests/admin-overview.spec.ts`（「扫描开始」断言改「开始扫描」）

**Interfaces:**
- Produces:
  - `AUDIT_ACTION_LABELS: Readonly<Record<string, string>>`（26 键，见下）
  - `auditActionLabel(action: string): string`（命中返回中文，未命中回退原值）

- [ ] **Step 1: 写失败测试** `frontend/src/tests/audit-labels.spec.ts`：

```ts
import { AUDIT_ACTION_LABELS, auditActionLabel } from "../utils/audit"

// 以后端 write_audit(...) 实际调用点为准的全集；后端新增事件时此处会逼出评审。
const BACKEND_ACTIONS = [
  "login_success", "login_fail",
  "user_create", "user_delete", "user_update", "user_disable", "user_enable",
  "user_reset_password",
  "gallery_create", "gallery_update", "gallery_delete",
  "root_add", "root_update", "root_remove",
  "exclusion_add", "exclusion_remove",
  "image_delete", "image_restore", "trash_purge",
  "thumb_cache_purge",
  "scan_start", "scan_finish", "scan_error", "rescan_exif",
  "fs_browse", "settings_update",
]

describe("audit action labels", () => {
  it("covers every backend action exactly once", () => {
    expect(Object.keys(AUDIT_ACTION_LABELS).sort()).toEqual([...BACKEND_ACTIONS].sort())
  })
  it("maps known actions to Chinese and falls back to raw value", () => {
    expect(auditActionLabel("image_delete")).toBe("删除图片")
    expect(auditActionLabel("some_future_action")).toBe("some_future_action")
  })
})
```

- [ ] **Step 2: 运行确认失败**：`cd frontend && pnpm test -- audit-labels` → FAIL（模块不存在）。

- [ ] **Step 3: 实现** `frontend/src/utils/audit.ts`：

```ts
/**
 * 审计 action 英文键 → 中文界面标签的唯一事实来源。
 * 全集以后端 write_audit(...) 调用点为准；tests/audit-labels.spec.ts 守全集。
 */
export const AUDIT_ACTION_LABELS = {
  login_success: "登录成功",
  login_fail: "登录失败",
  user_create: "创建用户",
  user_delete: "删除用户",
  user_update: "更新用户",
  user_disable: "禁用用户",
  user_enable: "启用用户",
  user_reset_password: "重置密码",
  gallery_create: "创建图库",
  gallery_update: "更新图库",
  gallery_delete: "删除图库",
  root_add: "添加根目录",
  root_update: "更新根目录",
  root_remove: "移除根目录",
  exclusion_add: "新增排除",
  exclusion_remove: "解除排除",
  image_delete: "删除图片",
  image_restore: "恢复图片",
  trash_purge: "清理回收站",
  thumb_cache_purge: "清理缩略图缓存",
  scan_start: "开始扫描",
  scan_finish: "完成扫描",
  scan_error: "扫描失败",
  rescan_exif: "重扫 EXIF",
  fs_browse: "浏览目录",
  settings_update: "更新设置",
} as const satisfies Record<string, string>

export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action as keyof typeof AUDIT_ACTION_LABELS] ?? action
}
```

- [ ] **Step 4: AdminOverview 改引用**

删除其内嵌 `ACTION_LABELS` 与 `actionLabel`（约 267–296 行），import 改为：

```ts
import { auditActionLabel } from "../utils/audit"
```

模板中 `actionLabel(a.action)` 调用改为 `auditActionLabel(a.action)`。

- [ ] **Step 5: 同步既有断言**：`tests/admin-overview.spec.ts:125` 的 `"扫描开始"` 改为 `"开始扫描"`；全文件再 grep 一次其他标签文案断言（`grep -n '扫描\|登录' tests/admin-overview.spec.ts`），有差异同步改。

- [ ] **Step 6: 全量验证**：`cd frontend && pnpm test && pnpm build` → 全绿、build 通过。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/utils/audit.ts frontend/src/tests/audit-labels.spec.ts \
  frontend/src/views/AdminOverview.vue frontend/src/tests/admin-overview.spec.ts
git commit -m "refactor(audit): shared action label map, fix label drift"
```

---

### Task 7: AdminAudit 页面（过滤 + 表格 + 分页 + 用户名映射）

**Files:**
- Modify: `frontend/src/api.ts`（类型 + fetch 封装可选；直接用 apiGet 即可，本 task 不动 api.ts）
- Modify: `frontend/src/router.ts`（注册路由）
- Modify: `frontend/src/components/AppHeader.vue`（管理菜单加项）
- Modify: `frontend/src/views/AdminOverview.vue`（「查看全部」链接）
- Create: `frontend/src/views/AdminAudit.vue`
- Create: `frontend/src/tests/admin-audit.spec.ts`

**Interfaces:**
- Consumes:
  - `GET /api/admin/audit?action=&from=&to=&limit=&cursor=` → `{ entries: AuditEntry[]; next_cursor: string | null }`，`AuditEntry = {id:number; ts:number; actor_user_id:number|null; actor_ip:string; action:string; target:string|null; detail:string|null}`
  - `GET /api/admin/users` → `UserRow[]`（只用 `id`/`username`）
  - `auditActionLabel`（Task 6）、`formatDateTime`（utils/datetime）
- Produces: `/admin/audit` 页面；导出按钮在 Task 8 接入（本 task 先放占位按钮，禁用态）。

- [ ] **Step 1: 写失败测试** `frontend/src/tests/admin-audit.spec.ts`（mount 模式仿 admin-trash.spec.ts：stubGlobal fetch、memory router、pinia）：

```ts
import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import AdminAudit from "../views/AdminAudit.vue"

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

const now = Math.floor(Date.now() / 1000)
const ENTRIES = [
  { id: 3, ts, actor_user_id: 1, actor_ip: "127.0.0.1", action: "image_delete", target: "image:9", detail: "x" },
  { id: 2, ts: now - 60, actor_user_id: null, actor_ip: "10.0.0.5", action: "login_fail", target: null, detail: null },
  { id: 1, ts: now - 120, actor_user_id: null, actor_ip: "127.0.0.1", action: "scan_start", target: "root:1", detail: null },
]

async function mountPage(auditBody: unknown = { entries: ENTRIES, next_cursor: "t_1" }, users = [
  { id: 1, username: "alice" },
]) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : (input as Request).url
    if (url.startsWith("/api/admin/users")) return response(users)
    if (url.startsWith("/api/admin/audit")) return response(auditBody)
    return response({ error: { code: "not_found", message: "x" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/admin/audit", component: AdminAudit }],
  })
  await router.push("/admin/audit")
  const w = mount(AdminAudit, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return { w, fetchFn }
}

beforeEach(() => { setActivePinia(createPinia()); vi.unstubAllGlobals() })

describe("AdminAudit", () => {
  it("renders rows with labels, mapped username, 匿名 for login_fail and 系统 for scans", async () => {
    const { w } = await mountPage()
    expect(w.text()).toContain("删除图片")
    expect(w.text()).toContain("alice")
    expect(w.text()).toContain("匿名")
    expect(w.text()).toContain("系统")
    expect(w.text()).toContain("10.0.0.5")
    expect(w.text()).toContain("image:9")
  })

  it("falls back to #id（已删除） when user missing", async () => {
    const { w } = await mountPage(undefined, [])
    expect(w.text()).toContain("#1（已删除）")
  })

  it("still lists entries and falls back to #id when users fetch fails", async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users"))
        return response({ error: { code: "internal_error", message: "x" } }, 500)
      return response({ entries: ENTRIES, next_cursor: null })
    })
    vi.stubGlobal("fetch", fetchFn)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/admin/audit", component: AdminAudit }],
    })
    await router.push("/admin/audit")
    const w = mount(AdminAudit, { global: { plugins: [createPinia(), router] } })
    await flushPromises()
    expect(w.text()).toContain("删除图片")
    expect(w.text()).toContain("#1")
    expect(w.text()).not.toContain("加载失败")
  })

  it("loads more with cursor and merges rows", async () => {
    const { w, fetchFn } = await mountPage()
    fetchFn.mockClear()
    fetchFn.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url
      if (url.startsWith("/api/admin/users")) return response([{ id: 1, username: "alice" }])
      if (url.includes("cursor=t_1"))
        return response({ entries: [{ id: 4, ts: now - 200, actor_user_id: 1, actor_ip: "127.0.0.1", action: "login_success", target: null, detail: null }], next_cursor: null })
      return response({ entries: [], next_cursor: null })
    })
    await w.findAll("button").find((b) => b.text().includes("加载更多"))!.trigger("click")
    await flushPromises()
    expect(w.text()).toContain("登录成功")
  })

  it("filters by action and date range and resets to first page", async () => {
    const { w, fetchFn } = await mountPage()
    const select = w.find("select")
    await select.setValue("image_delete")
    await w.find("#audit-from").setValue("2026-10-01")
    await w.find("#audit-to").setValue("2026-10-31")
    await flushPromises()
    const calls = fetchFn.mock.calls as Array<[string]>
    const q = calls.filter((c) => c[0].startsWith("/api/admin/audit")).map((c) => c[0]).pop()!
    expect(q).toContain("action=image_delete")
    const params = new URL(q, "http://x").searchParams
    // 2026-10-01 00:00 本地（东八区 = 1790630400）；止 = 当天 23:59:59
    expect(Number(params.get("from"))).toBe(
      Math.floor(new Date(2026, 9, 1, 0, 0, 0).getTime() / 1000),
    )
    expect(Number(params.get("to"))).toBe(
      Math.floor(new Date(2026, 9, 31, 23, 59, 59).getTime() / 1000),
    )
  })

  it("shows empty state and error state", async () => {
    const { w } = await mountPage({ entries: [], next_cursor: null })
    expect(w.text()).toContain("暂无审计记录")
  })
})
```

补「users 500 不阻塞」用例：单独 mount，users 返回 404 response，断言行内 actor 列出现 `#1`（回退）、页面无「加载失败」整体错误条。

- [ ] **Step 2: 运行确认失败**：`cd frontend && pnpm test -- admin-audit` → FAIL（组件/路由不存在）。

- [ ] **Step 3: 注册路由**（`router.ts`，在 `/admin/users` 之后）：

```ts
  {
    path: "/admin/audit",
    component: () => import("./views/AdminAudit.vue"),
    meta: { requiresAdmin: true },
  },
```

- [ ] **Step 4: AppHeader 菜单加项**（「回收站」与「用户」之间或「设置」前，放在「用户」之后）：

```vue
          <router-link to="/admin/audit" role="menuitem"
            class="block px-3 py-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
            @click="adminOpen = false">
            审计日志
          </router-link>
```

- [ ] **Step 5: AdminOverview「最近审计 (20 条)」标题行加链接**

把该 `<h2>` 包一层 flex（`mb-2 flex items-center justify-between text-sm font-medium text-ink-2`），右侧加：

```vue
<router-link to="/admin/audit" class="text-xs text-primary-text hover:underline">查看全部 →</router-link>
```

- [ ] **Step 6: 实现** `frontend/src/views/AdminAudit.vue`：

```vue
<template>
  <div>
    <AppHeader>
      <template #title><span class="text-ink-2">管理 · 审计日志</span></template>
    </AppHeader>
    <main class="space-y-4 p-4">
      <!-- 过滤工具条（Task 8 接入导出按钮） -->
      <div class="flex flex-wrap items-center gap-3">
        <label for="audit-action" class="text-sm text-ink-2">事件</label>
        <select id="audit-action" v-model="filterAction"
                class="rounded bg-surface-2 px-2 py-1 text-sm text-ink"
                @change="reload">
          <option :value="null">全部事件</option>
          <option v-for="label in actionOptions" :key="label.value" :value="label.value">
            {{ label.label }}
          </option>
        </select>

        <label for="audit-from" class="text-sm text-ink-2">起</label>
        <input id="audit-from" type="date" v-model="filterFrom"
               class="rounded bg-surface-2 px-2 py-1 text-sm text-ink" @change="reload">
        <label for="audit-to" class="text-sm text-ink-2">止</label>
        <input id="audit-to" type="date" v-model="filterTo"
               class="rounded bg-surface-2 px-2 py-1 text-sm text-ink" @change="reload">

        <button type="button" ref="exportBtn" disabled
                class="rounded bg-surface-2 px-3 py-1.5 text-sm text-ink-muted">
          导出 CSV
        </button>
      </div>

      <div v-if="loading" class="text-ink-2">加载中...</div>
      <div v-else-if="error" class="flex items-center gap-3 text-danger-text">
        <span>{{ error }}</span>
        <button type="button" class="rounded bg-surface-2 px-2 py-1 text-xs"
                @click="reload">重试</button>
      </div>
      <template v-else>
        <p v-if="entries.length === 0" class="text-sm text-ink-muted">暂无审计记录</p>
        <div v-else class="overflow-x-auto rounded-lg bg-surface">
          <table class="w-full min-w-[860px] text-left text-sm">
            <thead class="border-b border-line text-xs text-ink-muted">
              <tr>
                <th class="px-3 py-2">时间</th>
                <th class="px-3 py-2">操作人</th>
                <th class="px-3 py-2">IP</th>
                <th class="px-3 py-2">事件</th>
                <th class="px-3 py-2">目标</th>
                <th class="px-3 py-2">详情</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-line">
              <tr v-for="e in entries" :key="e.id" class="hover:bg-surface-2/60">
                <td class="whitespace-nowrap px-3 py-2 text-xs">{{ formatDateTime(e.ts) }}</td>
                <td class="px-3 py-2">{{ actorLabel(e) }}</td>
                <td class="px-3 py-2 text-xs">{{ e.actor_ip }}</td>
                <td class="px-3 py-2">{{ auditActionLabel(e.action) }}</td>
                <td class="max-w-[200px] truncate px-3 py-2 font-mono text-xs" :title="e.target ?? ''">
                  {{ e.target ?? "" }}
                </td>
                <td class="max-w-[320px] truncate px-3 py-2 font-mono text-xs text-ink-muted"
                    :title="e.detail ?? ''">
                  {{ e.detail ?? "" }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="nextCursor !== null" class="text-center">
          <button type="button"
                  class="rounded bg-surface-2 px-3 py-1.5 text-sm hover:bg-surface-3 disabled:opacity-40"
                  :disabled="loadingMore" @click="loadMore">
            {{ loadingMore ? "加载中..." : "加载更多" }}
          </button>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiGet, HttpError } from "../api"
import { formatDateTime } from "../utils/datetime"
import { AUDIT_ACTION_LABELS, auditActionLabel } from "../utils/audit"

interface AuditEntry {
  id: number
  ts: number
  actor_user_id: number | null
  actor_ip: string
  action: string
  target: string | null
  detail: string | null
}
interface UserRow { id: number; username: string }

const PAGE_SIZE = 100

const entries = ref<AuditEntry[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(true)
const loadingMore = ref(false)
const error = ref("")

const filterAction = ref<string | null>(null)
const filterFrom = ref("")  // YYYY-MM-DD
const filterTo = ref("")

const users = ref<Map<number, string>>(new Map())
const usersFailed = ref(false)

// 事件下拉：全部 + 标签表（按中文标签排序便于查找）
const actionOptions = Object.entries(AUDIT_ACTION_LABELS)
  .map(([value, label]) => ({ value, label }))
  .sort((a, b) => a.label.localeCompare(b.label, "zh"))

function actorLabel(e: AuditEntry): string {
  if (e.actor_user_id === null) {
    return e.action === "login_fail" ? "匿名" : "系统"
  }
  const name = users.value.get(e.actor_user_id)
  if (name) return name
  return usersFailed.value ? `#${e.actor_user_id}` : `#${e.actor_user_id}（已删除）`
}

function dayBounds(value: string, end: boolean): number {
  const [y, m, d] = value.split("-").map(Number)
  const dt = new Date(y, m - 1, d, end ? 23 : 0, end ? 59 : 0, end ? 59 : 0)
  return Math.floor(dt.getTime() / 1000)
}

// pageSize 可覆盖：页面浏览 100，CSV 导出 500（Task 8 使用）。
function buildQuery(cursor: string | null, pageSize: number = PAGE_SIZE): string {
  const p = new URLSearchParams()
  p.set("limit", String(pageSize))
  if (filterAction.value) p.set("action", filterAction.value)
  if (filterFrom.value) p.set("from", String(dayBounds(filterFrom.value, false)))
  if (filterTo.value) p.set("to", String(dayBounds(filterTo.value, true)))
  if (cursor) p.set("cursor", cursor)
  return `?${p.toString()}`
}

// 单调请求令牌：过滤变化/重试会使在途旧响应失效。
let seq = 0
async function reload() {
  const my = ++seq
  loading.value = true
  error.value = ""
  try {
    const r = await apiGet<{ entries: AuditEntry[]; next_cursor: string | null }>(
      `/api/admin/audit${buildQuery(null)}`,
    )
    if (my !== seq) return
    entries.value = r.entries
    nextCursor.value = r.next_cursor
  } catch (err) {
    if (my === seq) error.value = (err as HttpError).message || "加载失败"
  } finally {
    if (my === seq) loading.value = false
  }
}

async function loadMore() {
  if (nextCursor.value === null) return
  const my = seq
  loadingMore.value = true
  try {
    const r = await apiGet<{ entries: AuditEntry[]; next_cursor: string | null }>(
      `/api/admin/audit${buildQuery(nextCursor.value)}`,
    )
    if (my !== seq) return
    entries.value.push(...r.entries)
    nextCursor.value = r.next_cursor
  } catch (err) {
    if (my === seq) error.value = (err as HttpError).message || "加载失败"
  } finally {
    if (my === seq) loadingMore.value = false
  }
}

async function loadUsers() {
  try {
    const rows = await apiGet<UserRow[]>("/api/admin/users")
    users.value = new Map(rows.map((r) => [r.id, r.username]))
  } catch {
    // 用户列表失败不阻断审计列表；操作人列回退显示 #id
    usersFailed.value = true
    users.value = new Map()
  }
}

// Task 8 接入导出时替换占位按钮；先暴露给测试/后续 task 的锚点。
const exportBtn = ref<HTMLElement | null>(null)

onMounted(async () => {
  await Promise.all([loadUsers(), reload()])
})
</script>
```

- [ ] **Step 7: 跑测试 + build**：`cd frontend && pnpm test -- admin-audit && pnpm test && pnpm build`，全绿。

- [ ] **Step 8: 提交**

```bash
git add frontend/src
git commit -m "feat(audit-ui): AdminAudit page with filters, cursor paging, actor names"
```

---

### Task 8: CSV 导出（utils/csv.ts + 按钮接入）

**Files:**
- Create: `frontend/src/utils/csv.ts`
- Create: `frontend/src/tests/csv.spec.ts`
- Create: `frontend/src/components/ToastHost.vue`（顺带补上全库缺失的 toast 渲染器）
- Modify: `frontend/src/App.vue`（挂 ToastHost）
- Modify: `frontend/src/api.ts`（apiGet 透传 signal）
- Modify: `frontend/src/views/AdminAudit.vue`
- Test: `frontend/src/tests/admin-audit.spec.ts`（导出交互 2 个用例）、新增 ToastHost 渲染小测试（可并入 smoke.spec.ts 或独立 `toast-host.spec.ts`）

**Interfaces:**
- Produces:
  - `AUDIT_EXPORT_LIMIT = 10_000`
  - `class AuditExportLimitError extends Error { constructor(readonly fetched: number) }`
  - `class AuditExportAborted extends Error`
  - `toIsoLocal(unixSec: number, now?: Date): string` —— `YYYY-MM-DDTHH:mm:ss±HH:MM`（浏览器本地偏移）
  - `auditRowsToCsv(rows: AuditEntryLike[]): string` —— 含 BOM、CRLF、RFC 4180 转义、表头 `id,time,actor_user_id,actor_ip,action,target,detail`，time 走 toIsoLocal，action 输出原始英文键
  - `collectAuditCsv(fetchPage: (cursor: string | null, signal: AbortSignal) => Promise<{entries: AuditEntryLike[]; next_cursor: string | null}>, opts: {signal: AbortSignal; onProgress?: (n: number) => void}): Promise<string>` —— limit=500 循环，达 10,000 仍有下一页抛 `AuditExportLimitError`；signal abort 抛 `AuditExportAborted`

- [ ] **Step 1: 写失败测试** `frontend/src/tests/csv.spec.ts`：

```ts
import { auditRowsToCsv, collectAuditCsv, toIsoLocal,
  AuditExportLimitError, AuditExportAborted } from "../utils/csv"

const row = (over: Partial<any> = {}) => ({
  id: 1, ts: 1_700_000_000, actor_user_id: 7, actor_ip: "127.0.0.1",
  action: "image_delete", target: "image:9", detail: null, ...over,
})

describe("auditRowsToCsv", () => {
  it("writes BOM, header, CRLF and raw english action", () => {
    const csv = auditRowsToCsv([row()])
    expect(csv.startsWith("﻿")).toBe(true)
    expect(csv).toContain("id,time,actor_user_id,actor_ip,action,target,detail\r\n")
    expect(csv).toContain(",image_delete,image:9,")
    expect(csv.endsWith("\r\n")).toBe(true)
  })
  it("escapes comma, quote, newline per RFC 4180", () => {
    const csv = auditRowsToCsv([row({ target: "a,b", detail: 'he said "hi"\nx2' })])
    expect(csv).toContain('"a,b"')
    expect(csv).toContain('"he said ""hi""\nx2"')
  })
  it("renders null actor as empty cell and fixed ISO local time with offset", () => {
    const csv = auditRowsToCsv([row({ actor_user_id: null })])
    expect(csv).toMatch(/,127\.0\.0\.1,/)  // actor 空单元格：",,127.0.0.1,"
    expect(csv).toMatch(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}/)
  })
})

describe("collectAuditCsv", () => {
  const page = (entries: any[], next_cursor: string | null) =>
    vi.fn(async () => ({ entries, next_cursor }))

  it("pages until exhausted and reports progress", async () => {
    const calls: (string | null)[] = []
    const fetcher = async (cursor: string | null) => {
      calls.push(cursor)
      if (calls.length === 1) return { entries: [row({ id: 1 })], next_cursor: "c1" }
      return { entries: [row({ id: 2 })], next_cursor: null }
    }
    const progress: number[] = []
    const csv = await collectAuditCsv(fetcher, {
      signal: new AbortController().signal,
      onProgress: (n) => progress.push(n),
    })
    expect(calls).toEqual([null, "c1"])
    expect(progress).toEqual([1, 2])
    expect(csv).toContain("image:9")
  })

  it("aborts with AuditExportAborted", async () => {
    const ac = new AbortController()
    const fetcher = vi.fn(async () => {
      ac.abort()
      return { entries: [row()], next_cursor: "c" }
    })
    await expect(collectAuditCsv(fetcher, { signal: ac.signal }))
      .rejects.toBeInstanceOf(AuditExportAborted)
  })

  it("stops at 10000 with AuditExportLimitError and no truncated file", async () => {
    const many = Array.from({ length: 500 }, (_, i) => row({ id: i }))
    let pages = 0
    const fetcher = async () => {
      pages += 1
      return { entries: many, next_cursor: `c${pages}` } // 永远有下一页
    }
    await expect(collectAuditCsv(fetcher, { signal: new AbortController().signal }))
      .rejects.toBeInstanceOf(AuditExportLimitError)
    expect(pages).toBe(20) // 500 * 20 = 10000
  })
})

describe("toIsoLocal", () => {
  it("formats with explicit +08:00 style offset", () => {
    // 构造一个 UTC 时刻；只校验形状与偏移计算（用 Date 自身偏移反推）
    const d = new Date("2026-10-31T08:30:45Z")
    const s = toIsoLocal(Math.floor(d.getTime() / 1000))
    expect(s).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$/)
    const offMin = -d.getTimezoneOffset()
    const expectSign = offMin >= 0 ? "+" : "-"
    expect(s.slice(-6, -5)).toBe(expectSign)
  })
})
```

- [ ] **Step 2: 运行确认失败**：`pnpm test -- csv` → FAIL（模块不存在）。

- [ ] **Step 3: 实现** `frontend/src/utils/csv.ts`：

```ts
/** P7: 审计日志前端 CSV 导出。纯函数 + 收集器；不碰 DOM，便于测试。 */

export interface AuditCsvRow {
  id: number
  ts: number
  actor_user_id: number | null
  actor_ip: string
  action: string
  target: string | null
  detail: string | null
}

export const AUDIT_EXPORT_LIMIT = 10_000
const PAGE_SIZE = 500
const BOM = "﻿"
const HEADER = "id,time,actor_user_id,actor_ip,action,target,detail"

export class AuditExportLimitError extends Error {
  constructor(readonly fetched: number) {
    super(`audit export limit reached: ${fetched}`)
  }
}
export class AuditExportAborted extends Error {}

const pad = (n: number) => String(n).padStart(2, "0")

/** 固定格式的本地时区 ISO 时间：YYYY-MM-DDTHH:mm:ss±HH:MM（不用 toLocaleString，防 locale 漂移）。 */
export function toIsoLocal(unixSec: number): string {
  const d = new Date(unixSec * 1000)
  const offMin = -d.getTimezoneOffset()
  const sign = offMin >= 0 ? "+" : "-"
  const ah = Math.floor(Math.abs(offMin) / 60)
  const am = Math.abs(offMin) % 60
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
    `${sign}${pad(ah)}:${pad(am)}`
  )
}

function esc(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** 行 → CSV 文本（含 BOM、表头、CRLF）。action 刻意输出原始英文键。
 *  只有 target/detail 两个自由文本列做 RFC 4180 转义；数字/IP 列不含分隔符。 */
export function auditRowsToCsv(rows: AuditCsvRow[]): string {
  const lines = [HEADER]
  for (const r of rows) {
    lines.push(
      [
        String(r.id),
        toIsoLocal(r.ts),
        r.actor_user_id === null ? "" : String(r.actor_user_id),
        r.actor_ip,
        r.action,
        esc(r.target),
        esc(r.detail),
      ].join(","),
    )
  }
  return BOM + lines.join("\r\n") + "\r\n"
}

interface Page {
  entries: AuditCsvRow[]
  next_cursor: string | null
}

/**
 * 按过滤条件（封装在 fetchPage 闭包里）循环游标拉取并拼成 CSV 字符串。
 * 达 10,000 仍有下一页 → AuditExportLimitError（调用方不得落盘半截文件）；
 * signal abort → AuditExportAborted。
 */
export async function collectAuditCsv(
  fetchPage: (cursor: string | null, signal: AbortSignal) => Promise<Page>,
  opts: { signal: AbortSignal; onProgress?: (n: number) => void },
): Promise<string> {
  const all: AuditCsvRow[] = []
  let cursor: string | null = null
  do {
    if (opts.signal.aborted) throw new AuditExportAborted()
    const page = await fetchPage(cursor, opts.signal)
    if (opts.signal.aborted) throw new AuditExportAborted()
    all.push(...page.entries)
    opts.onProgress?.(all.length)
    if (all.length > AUDIT_EXPORT_LIMIT ||
        (all.length === AUDIT_EXPORT_LIMIT && page.next_cursor !== null)) {
      throw new AuditExportLimitError(all.length)
    }
    cursor = page.next_cursor
  } while (cursor !== null)
  return auditRowsToCsv(all)
}

/** audit-YYYYMMDD-HHmmss.csv（浏览器本地时间）。 */
export function auditCsvFilename(now: Date = new Date()): string {
  const p = (n: number) => pad(n)
  return `audit-${now.getFullYear()}${p(now.getMonth() + 1)}${p(now.getDate())}` +
    `-${p(now.getHours())}${p(now.getMinutes())}${p(now.getSeconds())}.csv`
}
```

- [ ] **Step 4: 跑 csv 测试**：`cd frontend && pnpm test -- csv` → PASS。

- [ ] **Step 5: 接入 AdminAudit.vue**

替换 Task 7 的占位按钮：

```vue
        <button type="button"
                class="rounded bg-primary px-3 py-1.5 text-sm text-white hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
                :disabled="loading || !!error || entries.length === 0 || exporting"
                @click="onExportClick">
          <template v-if="!exporting">导出 CSV</template>
          <template v-else>导出中…（已拉取 {{ exportCount }} 条）<span class="ml-1 underline">取消</span></template>
        </button>
```

a. `api.ts` 小改（透传 AbortSignal，既有调用方无需改，参数可选）：

```ts
async function request<T>(
  method: string, path: string, body?: unknown, signal?: AbortSignal,
): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: "include",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  }
  // ……函数其余部分不变
}

export const apiGet = <T>(p: string, signal?: AbortSignal) =>
  request<T>("GET", p, undefined, signal)
```

b. AdminAudit.vue script：删除 Task 7 的 `exportBtn` 占位 ref，加：

```ts
import {
  auditCsvFilename, collectAuditCsv, AuditExportAborted, AuditExportLimitError,
} from "../utils/csv"
import { useToastStore } from "../stores/toast"

const toast = useToastStore()
const exporting = ref(false)
const exportCount = ref(0)
let exportAbort: AbortController | null = null

async function onExportClick() {
  if (exporting.value) { exportAbort?.abort(); return }
  exportAbort = new AbortController()
  exporting.value = true
  exportCount.value = 0
  try {
    const csv = await collectAuditCsv(
      (cursor, signal) =>
        apiGet<{ entries: AuditEntry[]; next_cursor: string | null }>(
          `/api/admin/audit${buildQuery(cursor, 500)}`, signal,
        ),
      { signal: exportAbort.signal, onProgress: (n) => (exportCount.value = n) },
    )
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = auditCsvFilename()
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (err) {
    if (err instanceof AuditExportAborted) {
      // 用户主动取消，静默
    } else if (err instanceof AuditExportLimitError) {
      toast.push("error", "最多导出 10,000 条，请收窄时间范围后重试")
    } else {
      toast.push("error", "导出失败")
    }
  } finally {
    exporting.value = false
  }
}
```

toast store 的真实 API 是 `useToastStore().push(kind, text)`（kind: `"info" | "error"`）。

**现状核查结论（执行时先 grep 复核）：store 全库只有 BrowseView 写入、没有任何渲染组件**——P6 的批量上限提示实际上从未显示。本 task 顺带补上全局渲染器（约 30 行，同时让既有 P6 提示生效）：

新建 `frontend/src/components/ToastHost.vue`：

```vue
<template>
  <div aria-live="polite" aria-atomic="false"
       class="pointer-events-none fixed inset-x-0 bottom-4 z-[80] flex flex-col items-center gap-2 px-4">
    <div v-for="t in toast.items" :key="t.id"
         class="pointer-events-auto rounded-md px-4 py-2 text-sm shadow-lg"
         :class="t.kind === 'error'
           ? 'bg-danger-soft text-danger-text border border-danger-line/60'
           : 'bg-surface-2 text-ink border border-line'">
      {{ t.text }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { useToastStore } from "../stores/toast"
const toast = useToastStore()
</script>
```

在 `App.vue` 挂载（RouterView 之外）：

```vue
<template>
  <div class="min-h-screen bg-base text-ink">
    <a href="#main-content" class="skip-link">跳到主内容</a>
    <RouterView />
    <ToastHost />
  </div>
</template>
```

注意：skip link 是 Task 10 才加的——Task 8 此步只挂 `<ToastHost />`；Task 10 再补 skip link 与 `<main>`（两个 task 改同一文件，按顺序执行即可）。

- [ ] **Step 6: 补组件测试**（admin-audit.spec.ts）

两个用例的挂载要让组件与断言共享同一个 pinia（仿 `browse-selection-download.spec.ts`：`const pinia = createPinia(); setActivePinia(pinia)`，mount 时 `plugins: [pinia, router]`，断言用 `useToastStore().items`）；并 stub `URL.createObjectURL`/`revokeObjectURL` 与 `HTMLAnchorElement.prototype.click`（jsdom 中 click 导航会报错）。

- 点「导出 CSV」：mock fetch 对 audit 请求按 `limit=500` 返回两页（第二页 next_cursor=null）；断言发起两页请求、`createObjectURL` 被调用 1 次（下载发生）。
- 每页 500 且永远返回 next_cursor → 拉满 10,000 后中止：断言 `useToastStore().items` 含「最多导出 10,000 条」、`createObjectURL` **未**被调用。
- ToastHost 小测试：`push("error","x")` 后挂载组件，文本可见，容器有 `aria-live="polite"`。

- [ ] **Step 7: 全量验证**：`pnpm test && pnpm build` 全绿。

- [ ] **Step 8: 提交**

```bash
git add frontend/src
git commit -m "feat(audit-ui): client-side CSV export with cap, progress and cancel"
```

---

### Task 9: 移动端复核定点修复

**Files:**
- Modify: `frontend/src/views/AdminUsers.vue`（表格横滚容器 + 操作组）
- Modify: `frontend/src/components/AppHeader.vue`（44px 触发器）
- Modify: `frontend/src/components/PaginationBar.vue`（44px）
- Modify: `frontend/src/components/DirectoryChooser.vue`（窄屏全宽贴边 + 44px 行）
- Modify: `frontend/src/views/BrowseView.vue` / `frontend/src/components/SubfolderStrip.vue`（<640 两列紧凑，若现状已两列则只核 padding）
- Modify: `frontend/src/views/LoginView.vue`、`ChangePasswordView.vue`、`AdminSettings.vue`、`AdminGalleryEdit.vue`（窄屏边距/按钮全宽，按实际走查缺口）
- Test: 相关既有 spec 不回归；新增 1 个结构性测试（AdminUsers 横滚容器）

**Interfaces:** 无新增。断点：`<640` / `640–1024` / `>1024`（UnoCSS 默认 `sm:640px`、`md:768px`、`lg:1024px`）。

- [ ] **Step 1: 写结构测试**（加到 `frontend/src/tests/admin-users.spec.ts`，先读现有文件复用挂载方式）：

```ts
  it("wraps the users table in an overflow-x-auto container for small screens", async () => {
    const { w } = await mountUsers() // 复用既有 helper
    expect(w.find(".overflow-x-auto").exists()).toBe(true)
  })
```

- [ ] **Step 2: AdminUsers 表格**

把 `<div ... class="overflow-hidden rounded-lg bg-surface">`（约 22 行）改为 `overflow-x-auto rounded-lg bg-surface`；内层 `<table>` 加 `min-w-[720px]`。行内操作按钮容器加 `flex min-w-max gap-1`；按钮加 `px-2 py-1 min-h-11 md:min-h-0`（桌面恢复紧凑，手机 44px）。

- [ ] **Step 3: 44px 触控件**

- AppHeader 两个触发按钮 class 加 `min-h-11 min-w-11`（菜单内容「管理」保持，padding 由 min-* 撑）。
- PaginationBar 按钮加 `min-h-11 min-w-11`。
- DirectoryChooser 关闭 ✕ 与目录行按钮：行容器 class 加 `min-h-11`；✕ 按钮加 `min-h-11 min-w-11`。
- 全库扫描其他图标按钮（grep `class="[^"]*p-1[^"]*"` 等小 padding 按钮：SearchBox 清除钮、GridLayoutSwitch、灯箱外的三点按钮），逐一加 min-w/h 或 padding 使点击区 ≥44px（`@click` 挂在非 button 元素上的，改为 button 或加 class）。

- [ ] **Step 4: DirectoryChooser 窄屏**

面板容器 class 由 `w-full max-w-2xl` 改为 `w-[calc(100vw-1rem)] max-w-2xl m-2`（窄屏留 8px 边距贴边）；面包屑与路径列表 padding 保持。

- [ ] **Step 5: BrowseView 子目录条**

读 `SubfolderStrip.vue` 的 `.lb-folder-grid` 样式定义位置（grep `lb-folder-grid`，定义在 BrowseView 或本文件 style 块），确认/补充网格规则：

```css
.lb-folder-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.5rem;
}
@media (min-width: 640px) {
  .lb-folder-grid {
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  }
}
```

（若现状已等价，不动；只做确认。）

- [ ] **Step 5b: 灯箱触屏核对**

375px 视口打开 ImageLightbox：底部信息条按钮（下载/删除/信息）、顶部关闭、EXIF 面板关闭钮点击区不得小于 44×44。PhotoSwipe 自带按钮若尺寸不足，在 ImageLightbox scoped CSS 中用 `min-width/min-height:44px`（或扩大 padding）补齐；手势（左右滑/双指/下滑关闭）不动。

- [ ] **Step 6: 窄屏表单/页面走查修复**

DevTools 375px 宽度逐页打开：Login、改密、GalleryList、RootList、BrowseView（工具条是否 sticky、批量底栏按钮）、AdminSettings、AdminGalleryEdit、AdminTrash、AdminAudit。发现的具体问题就地修，典型修法：卡片容器已有 `p-4`；提交按钮在 <640 加 `w-full sm:w-auto`（登录/改密主按钮、设置保存区）。

- [ ] **Step 7: 验证**：`pnpm test && pnpm build`；DevTools 375/768/1280 三档目验 Global Constraints 冒烟清单相关项（Task 12 统一走完整清单）。

- [ ] **Step 8: 提交**

```bash
git add frontend/src
git commit -m "fix(mobile): 44px targets, table scroll, narrow-screen form layout"
```

---

### Task 10: 无障碍闭合（焦点管理 / ARIA / label / skip link / focus-visible）

**Files:**
- Create: `frontend/src/composables/useDialogFocus.ts`
- Create: `frontend/src/tests/use-dialog-focus.spec.ts`
- Modify: `frontend/src/App.vue`（skip link + `<main id="main-content">`）
- Modify: `frontend/src/styles/base.css`（skip link 样式 + 全局 :focus-visible）
- Modify: `frontend/src/components/DirectoryChooser.vue`（接入 composable）
- Modify: `frontend/src/views/AdminUsers.vue`（3 个 modal 接入 + role/aria）
- Modify: `frontend/src/components/AppHeader.vue`（菜单焦点归还）
- Modify: `frontend/src/components/CellContextMenu.vue`、`frontend/src/composables/useCellMenu.ts`（Esc 关闭 + 打开聚焦首项）
- Modify: 表单页 `LoginView.vue`、`ChangePasswordView.vue`（label 关联/aria-invalid 按需补；先读现状，缺什么补什么）
- Test: 既有相关 spec 同步

**Interfaces:**
- Produces: `useDialogFocus(open: Ref<boolean>, panelRef: Ref<HTMLElement|null>, onClose: () => void)`：open=true 时保存当前焦点→nextTick 聚焦面板内首个可聚焦元素（无则面板本身）→document capture keydown 处理 Esc（调 onClose）/Tab 循环；open=false 时归还焦点。

- [ ] **Step 1: 写失败测试** `frontend/src/tests/use-dialog-focus.spec.ts`：

```ts
import { describe, expect, it } from "vitest"
import { ref, nextTick } from "vue"
import { useDialogFocus } from "../composables/useDialogFocus"

function setupDom() {
  document.body.innerHTML = `
    <button id="trigger">open</button>
    <div id="panel" tabindex="-1">
      <input id="a" /><button id="b">x</button>
    </div>`
  const trigger = document.getElementById("trigger") as HTMLElement
  const panel = document.getElementById("panel") as HTMLElement
  return { trigger, panel }
}

describe("useDialogFocus", () => {
  it("moves focus in on open and restores on close", async () => {
    const { trigger, panel } = setupDom()
    trigger.focus()
    const open = ref(false)
    useDialogFocus(open, { value: panel } as any, () => (open.value = false))
    open.value = true
    await nextTick()
    expect(document.activeElement?.id).toBe("a")
    open.value = false
    await nextTick()
    expect(document.activeElement).toBe(trigger)
  })

  it("Esc calls onClose and Tab wraps within panel", async () => {
    const { panel } = setupDom()
    const open = ref(true)
    useDialogFocus(open, { value: panel } as any, () => (open.value = false))
    await nextTick()
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    expect(open.value).toBe(false)

    open.value = true
    await nextTick()
    const b = document.getElementById("b")!
    b.focus()
    const ev = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })
    document.dispatchEvent(ev)
    expect(ev.defaultPrevented).toBe(true)
    expect(document.activeElement?.id).toBe("a")
  })
})
```

- [ ] **Step 2: 运行确认失败**，然后实现 `composables/useDialogFocus.ts`：

```ts
import { nextTick, onBeforeUnmount, watch, type Ref } from "vue"

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", "input:not([disabled])",
  "select:not([disabled])", "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",")

/** 模态对话框焦点管理：进入聚焦、Esc 关闭、Tab 循环、退出归还触发器焦点。 */
export function useDialogFocus(
  open: Ref<boolean>,
  panelRef: Ref<HTMLElement | null>,
  onClose: () => void,
) {
  let previous: HTMLElement | null = null

  function onKeydown(e: KeyboardEvent) {
    const panel = panelRef.value
    if (!panel) return
    if (e.key === "Escape") {
      e.stopPropagation()
      onClose()
      return
    }
    if (e.key !== "Tab") return
    const items = visibleFocusable(panel)
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  watch(open, async (isOpen) => {
    if (isOpen) {
      previous = document.activeElement as HTMLElement | null
      await nextTick()
      const panel = panelRef.value
      const items = panel ? visibleFocusable(panel) : []
      ;(items[0] ?? panel)?.focus()
      document.addEventListener("keydown", onKeydown, true)
    } else {
      document.removeEventListener("keydown", onKeydown, true)
      previous?.focus?.()
      previous = null
    }
  })

  onBeforeUnmount(() => document.removeEventListener("keydown", onKeydown, true))
}

function visibleFocusable(root: ParentNode): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  )
}
```

- [ ] **Step 3: DirectoryChooser 接入**

它已有 `dialogEl` ref、`role="dialog" aria-modal="true" tabindex="-1"` 与 `@keydown.esc`：删掉 `@keydown.esc`（composable 统一处理），补 `aria-labelledby`（给标题「选择目录」加 `id="dir-chooser-title"`）。script 中加：

```ts
const modelValueBool = computed(() => props.modelValue) // 若 props 名不同按现状
useDialogFocus(
  computed({ get: () => props.modelValue, set: () => {} }),
  dialogEl,
  () => emit("update:modelValue", false),
)
```

（emit/props 名以文件现状为准；若现有关闭函数叫 `cancel`，直接传 `cancel`。）

- [ ] **Step 4: AdminUsers 三个 modal 接入**

3 个 `fixed inset-0` 弹层（新建/编辑、重置密码、密码展示）内层面板加 `role="dialog" aria-modal="true" :aria-labelledby="..."`、`ref`、`tabindex="-1"`；标题加对应 id。script 中对 `modal`/`resetModal`/`revealModal` 三个 open 状态分别 `useDialogFocus(...)`，onClose 传既有 close 函数。参考 DirectoryChooser 的写法。

- [ ] **Step 5: AppHeader 菜单焦点归还**

管理/用户两个触发按钮各加 template ref；open 翻 false 时归还：在现有 `onEsc`/`onDocClick`/`onLogout`/路由点击关闭路径上，简单做法是 watch 两个 open ref：

```ts
watch(open, (v, old) => { if (!v && old) userTrigger.value?.focus() })
watch(adminOpen, (v, old) => { if (!v && old) adminTrigger.value?.focus() })
```

（菜单不做 Tab trap；Esc/外部点击关闭已具备。）

- [ ] **Step 6: CellContextMenu Esc + 打开聚焦**

`useCellMenu.ts`：`onMounted` 增加 `window.addEventListener("keydown", onKey)`，`onKey` 中 `e.key === "Escape"` → `close()`；`onUnmounted` 对称移除。

`CellContextMenu.vue`：根 div 加 `role="menu"`，item 按钮加 `role="menuitem"`；`watch(() => props.menu, ...)`（或 `onUpdated` 简单判定）菜单首次出现时 `root.value?.querySelector<HTMLButtonElement>(".lb-cell-menu-item")?.focus()`。

- [ ] **Step 7: skip link + main 落点**

`App.vue` 替换为：

```vue
<template>
  <div class="min-h-screen bg-base text-ink">
    <a href="#main-content" class="skip-link">跳到主内容</a>
    <RouterView />
  </div>
</template>
```

各视图根已有 `<main>`（Admin 系/Trash/Settings 等）；BrowseView/GalleryList/RootList/Login/改密若顶层不是 `<main>`，把外层容器改为 `<main id="main-content">`（admin 各页给现有 `<main>` 加同一 id；确保全文档 id 唯一——RouterView 同时只挂一个视图，重复 id 不会同屏，可接受）。

`base.css` 追加：

```css
/* 键盘用户：Tab 第一跳显示「跳到主内容」 */
.skip-link {
  position: fixed;
  top: 0.5rem;
  left: 0.5rem;
  z-index: 100;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  background: rgb(var(--color-primary));
  color: #fff;
  transform: translateY(-200%);
}
.skip-link:focus {
  transform: translateY(0);
}

/* 统一焦点环：键盘可见、鼠标不显示；覆盖浏览器默认与被吞掉的 outline */
:focus-visible {
  outline: 2px solid rgb(var(--color-focus-ring));
  outline-offset: 2px;
}
```

- [ ] **Step 8: 表单 label / aria / alt / 地标 抽查修补**

按 spec §5.2 逐项 grep 核对并补缺（每发现一处补一处）：
- LoginView/ChangePasswordView：输入框是否被 `<label>` 包裹或 `id`+`for` 关联；错误文案容器加 `role="alert"`（或 aria-live），输入框 `:aria-invalid="!!error"` + `aria-describedby`。
- AdminUsers modal 表单同上；AdminSettings 数字输入补 label 关联（Task 2 的 select 已有）。
- 所有纯图标按钮（DirectoryChooser ✕、SearchBox 清除钮、GridLayoutSwitch、灯箱外的三点按钮等）补中文 `aria-label`。
- 装饰性 svg 统一 `aria-hidden="true"`（AppHeader 下拉箭头已有；其余补上）。
- 图片 alt：PhotoCell/SearchResults/SubfolderStrip/AdminTrash 已有；**灯箱已在 slide data 传 `alt: it.filename`（ImageLightbox.vue:639，已满足）**——本步只加一条断言到 `lightbox-*` 既有 spec 或人工核对，勿重复实现。
- AdminAudit/SearchResults/AdminTrash 的「加载更多」按钮区与结果计数动态文本包 `aria-live="polite"`（仅状态短句，不包整个列表）。
- 地标唯一性核对：全应用同时只存在一个 `<header>`（AppHeader）、一个 `<main id="main-content">`（Step 7）；图库/管理导航容器补 `<nav>` 或 `role="navigation"`（AppHeader 菜单区即可）。

- [ ] **Step 9: 新增/同步测试**

除 useDialogFocus 单测外：
- directory-chooser.spec.ts：补「打开后焦点进入面板、Esc 调 cancel、关闭后焦点归还触发器」。
- admin-users.spec.ts：补 modal `role="dialog"`/`aria-modal` 存在断言。
- 新 smoke 或 app 级测试：断言 skip link 存在且 `href="#main-content"`（可在 smoke.spec.ts 加）。

- [ ] **Step 10: 全量验证**：`pnpm test && pnpm build`；键盘-only 目验（Tab/Shift-Tab/Esc 全流程，焦点始终可见、不丢失、不被困）——完整走查留 Task 12 清单，本 task 至少过登录→图库→浏览→一个菜单→一个 modal。

- [ ] **Step 11: 提交**

```bash
git add frontend/src
git commit -m "feat(a11y): dialog focus management, skip link, focus-visible, aria/labels"
```

---

### Task 11: README 双语定稿 + docs/deployment.md

**Files:**
- Rewrite: `README.md`（英文扩充）
- Create: `README.zh-CN.md`（中文对等版）
- Create: `docs/deployment.md`（中文）

**Interfaces:** 无代码。

- [ ] **Step 1: 重写 `README.md`**，结构（英文，内容以代码现状为准，写完逐条核对命令/键名真实存在）：

1. 顶部语言切换行：`[English](README.md) · [简体中文](README.zh-CN.md)`
2. **What it is**：一句话 + 特性列表 bullet（multi-gallery/multi-root, admin/viewer roles, LAN-vs-remote access scope, trash with retention, EXIF panel, filename search, batch ZIP download, audit log with retention & CSV, light/dark theme, mobile-friendly）
3. **Architecture**：Vue 3 SPA built to `frontend/dist/` → served by FastAPI StaticFiles directly or Caddy; FastAPI + SQLite (`db/app.db`) + on-disk thumbnail cache; scanner walks roots, no file moves except trash.
4. **Quick start**：沿用现有 venv → `pip install -e ".[dev]"` → `pnpm install && pnpm build` → `myphoto add-gallery/add-root/rescan/serve`；首次密码提示；`http://localhost:8080`。
5. **Configuration reference**：表格列出 config.toml 全部键（从 `backend/src/myphoto/config.py` 与 `_DEFAULT_TEMPLATE` 抄全：`[app] listen_host/listen_port/jwt_secret/session_hours/data_dir`、`[trash] retention_days/purge_hour/purge_minute`、`[security] trusted_proxies/login_lockout_threshold/login_lockout_minutes`、`[thumbnails] sizes`（若代码读取则列，先 grep 确认）、`[scan] sha1_buffer_kb/hash_workers`、`[download] batch_limit`、`[audit] retention_days`），含默认值/合法值/含义。
6. **Data & backups**：`db/app.db`、`db/.cache/thumbnails`（可重建）、`config.toml`；备份只需 app.db + config.toml。
7. **Upgrading**：git pull → `pip install -e ".[dev]"` → `pnpm build` → 重启；schema 迁移由 `schema_init` 自动执行。
8. **Development**：`myphoto serve --reload`、`cd frontend && npx vite`（proxy /api）、`pytest`、`pnpm test`、`pnpm build`（vue-tsc 门禁）。
9. **Deployment**：链接 `docs/deployment.md`。
10. 末行保留 specs/plans 索引说明。

- [ ] **Step 2: 写 `README.zh-CN.md`**

与英文版逐节对等（不是机翻腔：命令/键名/路径不译，说明文字自然中文）。顶部语言切换行：`[English](README.md) · [简体中文](README.zh-CN.md)`。

- [ ] **Step 3: 写 `docs/deployment.md`（中文）**，大纲：

1. 两种形态总览：家庭局域网 HTTP；公网域名 HTTPS。
2. 前置：后端 `myphoto serve`（config 默认 0.0.0.0:8080）；`pnpm --dir frontend build`。
3. 形态一（局域网 HTTP）：在项目根启动 `caddy run`（Caddyfile 已随仓库）；Caddyfile 四段职责简述（静态托管、SPA 回退、资源缓存、/api 反代）；访问 `http://<局域网 IP>`；**常见问题**：本机 80 端口被 Watt Toolkit（Steam++）占用时，改用局域网 IP 访问或改 Caddy 监听端口；Windows 防火墙放行。
4. 形态二（域名 + 自动 HTTPS）：把 Caddyfile 的 `:80` 改成 `your.domain`；Caddy 自动证书 + HTTP→HTTPS；后端 config 设 `trusted_proxies = ["127.0.0.1", "::1"]`（否则 X-Forwarded-For 不被采纳，access_scope 判定异常）；说明 viewer 的 `lan_only`/`remote_allowed` 语义：远程连接时 lan_only 账号会被拒。
5. 进程常驻：Windows 可选 `caddy start`（后台）+ 自建计划任务/`pythonw` 跑后端的思路（不绑定第三方工具版本）；Linux 可选 systemd unit 示例（`ExecStart=.../bin/myphoto serve`，WorkingDirectory 项目根）。
6. 升级/备份链接回 README。

- [ ] **Step 4: 自检**：README 中每条命令与配置键 grep 源码核对（`grep -n 'sha1_buffer_kw\|sizes' backend/src/myphoto/config.py backend/src/myphoto/thumbnails.py` 等）；不得出现已删改的键。

- [ ] **Step 5: 提交**

```bash
git add README.md README.zh-CN.md docs/deployment.md
git commit -m "docs: bilingual README and deployment guide finalization"
```

---

### Task 12: 全量验证、人工冒烟清单、roadmap/台账更新、合并

**Files:**
- Modify: `docs/superpowers/plans/2026-07-22-roadmap-p2-p7.md`（P7 状态行）
- Modify: `.superpowers/sdd/progress.md`（P7 台账；若文件存在）

- [ ] **Step 1: 全量自动化**

```bash
pytest
cd frontend && pnpm test && pnpm build
```

Expected: 后端全绿（518 + 本 phase 新增，6 skipped 不变）；前端全绿（249 → 约 270+）；build 零 TS 错误。

- [ ] **Step 2: 人工冒烟清单（交付给用户边用边验，沿用 P5/P6 惯例）**

在最终回复中给出此清单，并由用户实际验证：

1. 浅色模式（系统切换）：图库列表/RootList/浏览（两种网格 + 长按/右键菜单）/搜索/管理 6 页/DirectoryChooser/登录/改密/设置/Toast——无白底白字、边框正常、彩底按钮文字可读；AdminAudit 表格/过滤/分页/导出。
2. 深色模式：与 P6 目视一致（灯箱始终深色）。
3. 375px 手机视口：所有可点元素无明显 <44px 难点；AdminUsers/Trash/Audit 表格横滚；DirectoryChooser 贴边；子目录卡片两列；登录/设置按钮全宽。
4. 键盘-only：Tab 走头部→工具条→内容→分页；skip link；三个 AdminUsers modal + DirectoryChooser 焦点进入/循环/Esc/归还；CellContextMenu Esc；AppHeader 菜单归还焦点。
5. CSV：真实数据导出后用 Excel 打开中文不乱码；action 为英文键；过滤条件生效；>1 万条场景（可临时候选：改小 PAGE 上限自测后还原，不提交）显示中止 toast；取消可用无下载。
6. 审计留存：config 改 30 天 + 手工插旧 ts 行，重启服务验证被清、新行保留；0 不清理；AdminSettings 改 365 保存热生效。
7. （可选）屏幕阅读器过一遍主要页面朗读顺序。

- [ ] **Step 3: roadmap 更新**

`2026-07-22-roadmap-p2-p7.md`：状态表 P7 行改为 ✅（tag 在合并后由用户/执行时打 `phase7-audit-theme-a11y`）；顶部状态日期更新为 2026-10-31，补一句实际范围摘要（审计留存为 roadmap 外补丁、灯箱经核查无需 force-dark）。

- [ ] **Step 4: 台账更新**

`.superpowers/sdd/progress.md` 存在则按 P6 格式补 P7 各 task 完成记录与终审遗留 backlog（执行中发现的 Minor 项如实登记）。

- [ ] **Step 5: 合并（由用户选择时执行；不推送）**

```bash
git checkout main
git merge --no-ff phase7-audit-theme-a11y -m "Merge phase7: audit UI, light theme, mobile and a11y polish"
git tag phase7-audit-theme-a11y
git branch -d phase7-audit-theme-a11y
```

提醒用户：本地 main 将领先 origin/main，需走代理手动 `git push`（含 tag：`git push origin main --tags`）。

- [ ] **Step 6: 更新记忆**

更新 `roadmap-and-phase-status` 记忆文件：P7 ✅、tag、未推送状态、新测试基线、遗留 backlog 索引。
