# myPhotoGallery Phase 2 实现计划：多图库多根 + 最小管理 API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 P1 MVP 基础上新增管理端 API (`/api/admin/*`)、审计日志系统 (`audit_log` 表 + 事件埋点)、修改密码接口、前端管理面板（AdminOverview + AdminGalleryEdit + DirectoryChooser）。

**Architecture:** 不改变现有模块布局。新增 `audit.py` 和 `routes_admin.py`。前端新增 admin 路由和 2 个视图 + 1 个组件。

**Tech Stack:** 与 P1 完全一致：Python 3.11+ / FastAPI / SQLAlchemy 2.0 async + aiosqlite / Vue 3 + Vite + Pinia + Router + UnoCSS

---

## Global Constraints

- 所有 P1 的 Global Constraints 继续生效
- 红线 1（不物理删除文件夹）和红线 3（路径安全）在管理 API 中严格执行
- 审计写入失败 **绝不** 影响主操作 —— `write_audit()` 内部 catch 并 log
- 管理端所有路由由 `admin_required` 保护；`browse-fs` 额外加 `require_lan_ip`
- 密码强度：后端 ≥8 字符（唯一权威）
- 错误码新增但保持向后兼容

---

## 目录结构（P2 完成时新增）

```
backend/src/myphoto/
├─ audit.py              # NEW
├─ routes_admin.py       # NEW
├─ models.py             # MODIFY: +AuditLog
├─ deps.py               # MODIFY: +require_lan_ip
├─ routes_auth.py        # MODIFY: +change-password + audit wiring
├─ scanner.py            # MODIFY: +audit wiring
├─ cli.py                # MODIFY: +audit wiring
└─ main.py               # MODIFY: +admin router mount

backend/tests/
├─ test_audit.py                   # NEW
├─ test_deps_lan.py                # NEW
├─ test_routes_admin_galleries.py  # NEW
├─ test_routes_admin_roots.py      # NEW
├─ test_routes_admin_browse_fs.py  # NEW
├─ test_routes_admin_system.py     # NEW
├─ test_audit_integration.py       # NEW

frontend/src/
├─ router.ts                   # MODIFY: +admin routes + guard
├─ components/
│  ├─ AppHeader.vue            # MODIFY: +admin link
│  └─ DirectoryChooser.vue     # NEW
├─ views/
│  ├─ AdminOverview.vue        # NEW
│  └─ AdminGalleryEdit.vue     # NEW
└─ tests/
   └─ admin-routes.spec.ts     # NEW
```

---

## Task 清单概览（12 个任务）

| # | 主题 | 端 |
|---|---|---|
| 1 | AuditLog 模型 + write_audit 工具 `audit.py` | BE |
| 2 | require_lan_ip 依赖 + 修改密码端点 | BE |
| 3 | Gallery CRUD 管理路由 + admin router 挂载 | BE |
| 4 | Root CRUD + 扫描控制管理路由 | BE |
| 5 | browse-fs 目录选择器端点 | BE |
| 6 | 系统状态 + 缩略图缓存清理 + 审计查询 | BE |
| 7 | 审计事件埋点（auth + scanner + CLI） | BE |
| 8 | 前端 admin 路由 + 导航守卫 + AppHeader 修改 | FE |
| 9 | AdminOverview 视图 | FE |
| 10 | DirectoryChooser 组件 | FE |
| 11 | AdminGalleryEdit 视图 | FE |
| 12 | 端到端验证 + 审计全链路检查 | Full |

---

## 关键接口速查（跨任务共享）

**审计写入工具**：
```python
# audit.py
async def write_audit(session, action: str, actor_user_id: int | None, actor_ip: str,
                      target: str | None = None, detail: str | None = None) -> None:
    """Insert audit_log row. Catches and logs all errors; never propagates."""
```

**新 FastAPI 依赖**：
```python
# deps.py
async def require_lan_ip(request: Request) -> None:
    """403 admin_fs_lan_only if client IP not in private network ranges."""
```

**browse-fs 请求/响应形状**：
```python
# POST /api/admin/browse-fs
# Request:  {"path": "C:/" | "/home" | ""}
# Response: {"path": "...", "entries": [{"name": "...", "path": "...", "is_root": false}],
#            "truncated": false}
```

**密码强度校验**：
```python
# 后端唯一权威，≥8 字符
if len(password) < 8:
    raise AppError("password_too_weak", 422, "password must be at least 8 characters")
```

---

### Task P2-1: AuditLog 模型 + write_audit 工具

**Files:**
- Modify: `backend/src/myphoto/models.py`
- Create: `backend/src/myphoto/audit.py`
- Create: `backend/tests/test_audit.py`

**Interfaces:**
- Produces: `class AuditLog(Base)`, `async def write_audit(session, ...) -> None`

**Steps:**

- [x] **Step 1: 在 models.py 中添加 AuditLog ORM**

```python
class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_ip: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
    __table_args__ = (
        Index("ix_audit_ts", "ts"),
        Index("ix_audit_action_ts", "action", "ts"),
    )
```

- [x] **Step 2: 创建 audit.py**

```python
from __future__ import annotations

import logging
import time

from myphoto.models import AuditLog

log = logging.getLogger("myphoto.audit")


async def write_audit(
    session,
    action: str,
    actor_user_id: int | None,
    actor_ip: str,
    target: str | None = None,
    detail: str | None = None,
) -> None:
    """Insert an audit log row. Audit failures never propagate."""
    try:
        session.add(
            AuditLog(
                ts=int(time.time()),
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                action=action,
                target=target,
                detail=detail,
            )
        )
        await session.flush()
    except Exception:
        log.exception("audit write failed for action=%s actor=%s", action, actor_user_id)
```

- [x] **Step 3: 写测试** — `test_audit.py`（insert + query, NULL 字段, 故障隔离）

- [x] **Step 4: 运行测试** — 3 passed, 全量 98 passed

- [x] **Step 5: 提交** — `3b68b26`

---

### Task P2-2: require_lan_ip 依赖 + 修改密码端点

**Files:**
- Modify: `backend/src/myphoto/deps.py`
- Modify: `backend/src/myphoto/routes_auth.py`
- Modify: `backend/tests/test_routes_auth.py`
- Create: `backend/tests/test_deps_lan.py`

**Interfaces:**
- Produces: `async def require_lan_ip(request: Request) -> None`, `POST /api/auth/change-password`

**Steps:**

- [ ] **Step 1: 在 deps.py 中添加 require_lan_ip**

```python
import ipaddress
from fastapi import Request

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
        raise AppError("admin_fs_lan_only", 403,
                       "this endpoint is only available on the local network")
```

- [ ] **Step 2: 在 routes_auth.py 中添加 change-password**

Add pydantic model and route:

```python
class ChangePasswordBody(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


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
```

- [ ] **Step 3: 写 deps_lan 测试** — parametrized: 私有 IP 通过、公网 IP 拒绝

- [ ] **Step 4: 在 test_routes_auth.py 中添加 change-password 测试** — 成功、旧密码错误、新密码太短、未认证

- [ ] **Step 5: 运行测试验证通过** — `pytest backend/tests/test_deps_lan.py backend/tests/test_routes_auth.py -v`

- [ ] **Step 6: 提交**

---

### Task P2-3: Gallery CRUD 管理路由 + admin router 挂载

**Files:**
- Create: `backend/src/myphoto/routes_admin.py`（gallery 部分 + router 骨架）
- Modify: `backend/src/myphoto/main.py`
- Create: `backend/tests/test_routes_admin_galleries.py`

**Interfaces:**
- `GET /api/admin/galleries` → 全部图库（含 root_count, image_count）
- `POST /api/admin/galleries` → `{name, description?}` → 201
- `PATCH /api/admin/galleries/{gid}` → `{name?, description?}`
- `DELETE /api/admin/galleries/{gid}` → 204（纯 DB 删除，无 FS 操作）

**Steps:**

- [ ] **Step 1: 创建 routes_admin.py**

```python
from __future__ import annotations

import time
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from myphoto.audit import write_audit
from myphoto.deps import admin_required
from myphoto.errors import AppError
from myphoto.models import Gallery, GalleryRoot, Image, User

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class GalleryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class GalleryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None


@router.get("/galleries")
async def admin_list_galleries(
    request: Request,
    response: Response,
    _admin: User = Depends(admin_required),
):
    response.headers["Cache-Control"] = "no-store"
    sm = request.app.state.sessionmaker
    async with sm() as s:
        gals = (await s.execute(select(Gallery))).scalars().all()
        out = []
        for g in gals:
            root_count = (
                await s.execute(
                    select(func.count()).select_from(GalleryRoot).where(
                        GalleryRoot.gallery_id == g.id
                    )
                )
            ).scalar_one()
            image_count = (
                await s.execute(
                    select(func.count()).select_from(Image).join(
                        GalleryRoot, GalleryRoot.id == Image.root_id
                    ).where(GalleryRoot.gallery_id == g.id)
                )
            ).scalar_one()
            out.append({
                "id": g.id, "name": g.name, "description": g.description,
                "root_count": root_count, "image_count": image_count,
            })
        return out


@router.post("/galleries", status_code=201)
async def admin_create_gallery(
    body: GalleryCreate,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        existing = (
            await s.execute(select(Gallery).where(Gallery.name == body.name))
        ).scalar_one_or_none()
        if existing:
            raise AppError("conflict", 409, f"gallery '{body.name}' already exists")
        g = Gallery(
            name=body.name, description=body.description,
            created_at=int(time.time()),
        )
        s.add(g)
        await s.flush()
        await write_audit(
            s, "gallery_create", admin.id, _client_ip(request),
            target=f"gallery:{g.id}", detail=f"name={body.name}",
        )
        await s.commit()
        return {"id": g.id, "name": g.name, "description": g.description}


@router.patch("/galleries/{gid}")
async def admin_update_gallery(
    gid: int, body: GalleryUpdate,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        g = await s.get(Gallery, gid)
        if g is None:
            raise AppError("not_found", 404, "gallery not found")
        if body.name is not None:
            conflict = (
                await s.execute(
                    select(Gallery).where(Gallery.name == body.name, Gallery.id != gid)
                )
            ).scalar_one_or_none()
            if conflict:
                raise AppError("conflict", 409, f"gallery name '{body.name}' already taken")
            g.name = body.name
        if body.description is not None:
            g.description = body.description
        await write_audit(
            s, "gallery_update", admin.id, _client_ip(request),
            target=f"gallery:{gid}",
        )
        await s.commit()
        return {"id": g.id, "name": g.name, "description": g.description}


@router.delete("/galleries/{gid}", status_code=204)
async def admin_delete_gallery(
    gid: int, request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        g = await s.get(Gallery, gid)
        if g is None:
            raise AppError("not_found", 404, "gallery not found")
        await write_audit(
            s, "gallery_delete", admin.id, _client_ip(request),
            target=f"gallery:{gid}", detail=f"name={g.name}",
        )
        await s.delete(g)
        await s.commit()
```

- [ ] **Step 2: 在 main.py 中挂载 admin router**

```python
from myphoto.routes_admin import router as admin_router
app.include_router(admin_router)
```

- [ ] **Step 3: 写 gallery CRUD 测试** — list empty, create, duplicate 409, update, update nonexistent 404, delete, non-admin 401, audit wiring

- [ ] **Step 4: 运行测试验证通过**

- [ ] **Step 5: 提交**

---

### Task P2-4: Root CRUD + 扫描控制管理路由

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py`
- Create: `backend/tests/test_routes_admin_roots.py`

**Interfaces:**
- `POST /api/admin/galleries/{gid}/roots` → `{label, absolute_path}` → 验证路径存在 + 触发扫描
- `PATCH /api/admin/galleries/{gid}/roots/{rid}` → `{label?, enabled?}`
- `DELETE /api/admin/galleries/{gid}/roots/{rid}` → DB only
- `POST /api/admin/galleries/{gid}/roots/{rid}/rescan` → trigger scan
- `GET /api/admin/galleries/{gid}/roots/{rid}/scan-status` → query state

**Steps:**

- [ ] **Step 1: 添加 pydantic schemas 和路由**

```python
class RootCreate(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    absolute_path: str = Field(min_length=1)

class RootUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=128)
    enabled: int | None = Field(None, ge=0, le=1)
```

Root add: `Path.resolve()`, `is_dir()` 检查, unique constraint 检查, `write_audit`, `scanner.enqueue()`.
Root update: label/enabled 修改, audit.
Root delete: 查询 + 删除, audit — **零 FS 操作**（红线 1）。
Rescan: 检查 status 防重复, `scanner.enqueue()`.
Scan-status: 返回 `scanner.get_status()` 结果 + root 验证。

- [ ] **Step 2: 写 root CRUD 测试** — add, bad path 400, duplicate 409, update label, update enabled toggle, delete, rescan, scan-status, cross-gallery 404

- [ ] **Step 3: 运行测试验证通过**

- [ ] **Step 4: 提交**

---

### Task P2-5: browse-fs 目录选择器端点

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py`
- Create: `backend/tests/test_routes_admin_browse_fs.py`

**7 Safety Rules (spec §6.8):**
1. role=admin AND LAN IP
2. 只列目录不列文件
3. Windows 返回盘符；Linux/macOS 默认 `/`
4. 不解析 symlink
5. 拒绝 `..` 段
6. 最多 5000 条
7. 每次写 `fs_browse` 审计

**Steps:**

- [ ] **Step 1: 添加 browse-fs 端点**

```python
class BrowseFsRequest(BaseModel):
    path: str = ""

@router.post("/browse-fs")
async def admin_browse_fs(
    body: BrowseFsRequest,
    request: Request,
    admin: User = Depends(admin_required),
    _lan: None = Depends(require_lan_ip),
):
```

Helper functions: `_list_directories(parent)` — 过滤 `is_dir()`, skip symlink, skip hidden; `_list_drive_letters()` — Windows 盘符。

- [ ] **Step 2: 写测试** — lists dirs, excludes files, rejects `..`, nonexistent 400, default root, skips hidden, unauthenticated 401

- [ ] **Step 3: 运行测试验证通过**

- [ ] **Step 4: 提交**

---

### Task P2-6: 系统状态 + 缩略图缓存清理 + 审计查询

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py`
- Create: `backend/tests/test_routes_admin_system.py`

**Interfaces:**
- `GET /api/admin/status` → stats + scan_statuses + recent_audit
- `POST /api/admin/thumb-cache/purge` → 204
- `GET /api/admin/audit?action=&actor=&from=&to=&limit=&cursor=` → 分页审计

**Steps:**

- [ ] **Step 1: 添加系统端点**

Status: count images/galleries/roots/users, collect scan statuses, fetch recent 20 audit.
Thumb-cache-purge: `shutil.rmtree` on cache subdirs（红线注意：这是 cache 目录不是图库目录），写 audit。
Audit query: filter by action/actor/from_ts/to_ts, cursor pagination by ts DESC, limit default 50.

- [ ] **Step 2: 写测试** — status shape, audit with filters, audit pagination no duplicates, thumb-cache-purge 204, non-admin 401

- [ ] **Step 3: 运行测试验证通过**

- [ ] **Step 4: 提交**

---

### Task P2-7: 审计事件埋点（auth + scanner + CLI）

**Files:**
- Modify: `backend/src/myphoto/routes_auth.py`
- Modify: `backend/src/myphoto/scanner.py`
- Modify: `backend/src/myphoto/cli.py`
- Create: `backend/tests/test_audit_integration.py`

**Events to wire:**

| Location | Event | actor_user_id | actor_ip |
|---|---|---|---|
| POST /api/auth/login success | login_success | user.id | client IP |
| POST /api/auth/login fail | login_fail | None | client IP |
| scanner scan_start | scan_start | None | 127.0.0.1 |
| scanner scan_finish | scan_finish | None | 127.0.0.1 |
| scanner scan_error | scan_error | None | 127.0.0.1 |
| cli add-gallery | gallery_create | None | cli |
| cli add-root | root_add | None | cli |

**Steps:**

- [ ] **Step 1: routes_auth.py login 埋点** — success path: `write_audit(session, "login_success", ...)` before `session.commit()`; failure path: separate session for `login_fail` audit (主 session 不会 commit)

- [ ] **Step 2: scanner.py 埋点** — helper `_audit_scan(sm, action, root_id)`; scan_start 在 `scan_root_now` set running 后; scan_finish 在 `_scan_transaction` commit 后; scan_error 在 `_record_scan_error` commit 后

- [ ] **Step 3: cli.py 埋点** — `add_gallery`: `write_audit(s, "gallery_create", None, "cli", ...)` before `s.commit()`; `add_root`: `write_audit(s, "root_add", None, "cli", ...)` before `s.commit()`

- [ ] **Step 4: 写集成测试** — login_success audit, login_fail audit, gallery CRUD audit actions visible

- [ ] **Step 5: 运行全量测试验证无回归**

- [ ] **Step 6: 提交**

---

### Task P2-8: 前端 admin 路由 + 导航守卫 + AppHeader 修改

**Files:**
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/components/AppHeader.vue`
- Create: `frontend/src/tests/admin-routes.spec.ts`

**Steps:**

- [ ] **Step 1: 修改 router.ts**

```typescript
{
  path: "/admin",
  component: () => import("./views/AdminOverview.vue"),
  meta: { requiresAdmin: true },
},
{
  path: "/admin/galleries/:gid",
  component: () => import("./views/AdminGalleryEdit.vue"),
  meta: { requiresAdmin: true },
},
```

beforeEach guard 加 `if (to.meta.requiresAdmin && auth.user?.role !== "admin") return { path: "/galleries" }`

- [ ] **Step 2: AppHeader 加 "管理" 链接**

```html
<router-link v-if="auth.isAdmin" to="/admin"
  class="rounded px-2 py-1 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100">
  管理
</router-link>
```

- [ ] **Step 3: 写测试并提交**

---

### Task P2-9: AdminOverview 视图

**Files:**
- Create: `frontend/src/views/AdminOverview.vue`

**Template:** stats 四卡片 (图片/图库/根目录/用户) → 扫描状态列表 → 最近 20 条审计 → "管理图库" 链接

**Script:** `onMounted` 调 `GET /api/admin/status`，填充数据

- [ ] **Step 1: 创建 AdminOverview.vue** — 使用 AppHeader, 四个 stat 卡片, scan status 列表 (状态颜色映射), 最近审计条目 (action 中文映射)

- [ ] **Step 2: 提交**

---

### Task P2-10: DirectoryChooser 组件

**Files:**
- Create: `frontend/src/components/DirectoryChooser.vue`

**Props:** `modelValue: boolean`, `startPath?: string`
**Emits:** `update:modelValue`, `confirm(path: string)`

**Template:** 固定定位 modal → 面包屑导航 → 当前路径输入框 → 目录列表 (可滚动) → 截断警告 → 取消/确认按钮

**Script:** `browse(path)` → `POST /api/admin/browse-fs`; `buildBreadcrumbs(p)`; `navigateTo(p)`; `onConfirm()`

- [ ] **Step 1: 创建 DirectoryChooser.vue**

- [ ] **Step 2: 提交**

---

### Task P2-11: AdminGalleryEdit 视图

**Files:**
- Create: `frontend/src/views/AdminGalleryEdit.vue`

**Template:** AppHeader（面包屑: 管理 › 图库名）→ 图库编辑区（名称/描述 + 保存）→ 根目录卡片网格（label + path + scan status + [重扫][移除]）→ 虚线加号卡 → DirectoryChooser modal

**Script:** `loadGallery()` → `GET /api/galleries/:gid`; `saveGallery()` → `PATCH /api/admin/galleries/:gid`; `rescanRoot(rid)` → `POST .../rescan`; `confirmRemoveRoot()` → confirm("不删除本地文件") → `DELETE`; `onPathChosen()` → prompt label → `POST .../roots`

- [ ] **Step 1: 创建 AdminGalleryEdit.vue**

- [ ] **Step 2: 提交**

---

### Task P2-12: 端到端集成验证 + 审计全链路检查

**Files:** 无新文件

**Steps:**

- [ ] **Step 1: 重启后端确认 schema 升级无报错** — `audit_log` 表被 `create_all` 自动创建

- [ ] **Step 2: curl 验证完整管理流程** — login → create gallery → update → add root → rescan → scan-status → browse-fs → status → audit → change-password → login with new password

- [ ] **Step 3: 前端构建与手动验证** — `pnpm build` → 浏览器验证登录 → 管理面板 → 创建图库 → 添加根目录 → 触发扫描 → 浏览验证 → 非 admin 看不到管理链接

- [ ] **Step 4: 运行全部 backend 测试确认无回归** — `pytest backend/tests/ -v`

- [ ] **Step 5: 运行全部 frontend 测试确认无回归** — `cd frontend && pnpm test`

- [ ] **Step 6: 红线 grep** — `rg -i 'shutil.rmtree|os\.remove' backend/src/myphoto/` 排除 `audit.py`/`thumbnails.py` cache 清理和 `.trash/` 引用

- [ ] **Step 7: 提交并打 tag `phase2-admin`**

---

## Design Decision Summary

1. **Task granularity**: 12 tasks — 7 backend, 4 frontend, 1 integration
2. **Audit writing pattern**: Standalone `audit.py` with `write_audit(session, ...)` — fault-isolated, never propagates
3. **Change-password**: Bundled with deps/errors work in Task P2-2
4. **browse-fs LAN enforcement**: Independent `require_lan_ip` dependency — not tied to user `access_scope` (P4)
5. **Scanner audit**: Helper `_audit_scan()` wraps session + error suppression; system events use `actor_ip="127.0.0.1"`
6. **CLI audit**: Inline import, write within existing session before commit; `actor_ip="cli"`
7. **Frontend**: 4 tasks (routes+header, overview, dir-chooser, gallery-edit); reuse existing UnoCSS dark patterns
