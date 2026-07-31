# myPhotoGallery Phase 4 实现计划：多用户 + Viewer 角色 + LAN/远程访问 + trusted_proxies

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 权限链步骤 3（`access_scope` 判 LAN/远程）与步骤 5（图库授权 `user_galleries`）一次性上线；让家人以 viewer 角色登录浏览；引入 `[security] trusted_proxies` 配置贯通 `X-Forwarded-For` 解析；`/api/admin/users*` 全套管理 API 与 `AdminUsers` 页面交付。Admin 本人自动全图库可见，viewer 仅可见被授权的图库。

**Architecture:** 新增 `access_scope` 校验依赖（步骤 3）、`gallery_scope_guard` 依赖（步骤 5，path 注入用）、`check_gallery_access` 纯函数（媒体端手工调用用）、`get_client_ip(request, config)` 工具（基于 `trusted_proxies` 决定是否信任 `X-Forwarded-For`）。`routes_admin.py` 新增 user CRUD 段。前端 `AdminUsers` 页面 + `LoginView` 感知 `access_scope_violation` + `AppHeader` 显示当前访问域。

**Tech Stack:** 与 P1/P2/P3 完全一致：Python 3.11+ / FastAPI / SQLAlchemy 2.0 async + aiosqlite / Vue 3 + Vite + Pinia + Router + UnoCSS

---

## Global Constraints

- 所有 P1/P2/P3 的 Global Constraints 继续生效（含 P1 红线 1/3、P2 审计写失败不传播、P3 trash 红线 2/3）
- **权限判定链（spec §5.2）** —— 一次性贯通：
  1. `authenticate`：解析 JWT cookie（已有）
  2. `user active`：`enabled==1`（已有）
  3. **`access_scope`**：若 `user.access_scope == "lan_only"`，校验 client_ip 在 RFC1918 + 127/8 + IPv6 fc00::/7 + ::1；否则 403 `access_scope_violation`（**新增**）
  4. `role check`：`admin_required` / `viewer_required` 依赖
  5. **`gallery/root scope`**：admin 跳过；viewer 必须有 `user_galleries` 行；root 必须 enabled 且 `gallery_id` 匹配（**新增**）
  6. `path safety`（已有）
  7. 处理器
- **`[security] trusted_proxies`**：默认空列表；为空时只看 `request.client.host`；非空时**仅当** `request.client.host` 命中 `trusted_proxies` 才读 `X-Forwarded-For`（取最左非空非 unknown 段）。`admin_fs_lan_only` 错误码也基于同一 client_ip 判定（贯通实际强制）
- **最后一个 admin 保护**：禁止删除或将最后一个 admin 设为 `enabled=0` 或 `role≠admin`，返回 409 `last_admin_protected`
- **viewer 初始密码**：admin 创建 viewer 时可填或留空（留空时后端生成 12 字符随机密码一次性回显，**不存明文**）
- **admin 自助**：admin 不出现在 `user_galleries` 表中，admin 角色隐含全图库可见
- **viewer 自我修改**：viewer 不能改自己 `role` / `access_scope` / `enabled`，只能改自己密码（已有 P2 `POST /api/auth/change-password`）；admin 可改任何人的一切属性（含 admin 改自己）
- **审计写失败不传播**（P2 沿用）
- **错误码新增但向后兼容**：`access_scope_violation`（403，已在 spec §6.9 列出）、`last_admin_protected`（409，spec §6.9 列出）
- **新表迁移**：`user_galleries` 由 `create_all` 自动建表（spec §11 沿用）

---

## 目录结构（P4 完成时新增/修改）

```
backend/src/myphoto/
├─ models.py                # MODIFY: +UserGallery ORM
├─ config.py                # MODIFY: +[security] section (trusted_proxies, login_lockout_*, session_hours)
├─ access.py                # NEW: get_client_ip(), access_scope_guard, gallery_scope_guard
├─ deps.py                  # MODIFY: current_user 接入 access_scope_guard; require_lan_ip 改用 get_client_ip
├─ routes_auth.py           # MODIFY: /api/auth/login 错误码细化（access_scope_violation）/api/auth/me 返回 access_scope
├─ routes_admin.py          # MODIFY: +/api/admin/users* 整套路由; 自身使用 access_scope_guard（admin 不必 lan_only，依赖 require_lan_ip 仍判定 client_ip lan）
├─ routes_browse.py         # MODIFY: 所有图库相关端点应用 gallery_scope_guard
├─ routes_media.py          # MODIFY: /api/thumb 与 /api/image 应用 check_gallery_access（通过 image.root_id → gallery_id）
└─ main.py                  # MODIFY: 无需改（[security] 由 config.load_or_init 解析后挂在 app.state.config）

backend/tests/
├─ test_models.py              # MODIFY: +UserGallery ORM 测试
├─ test_config.py              # NEW: [security] 段解析 + 默认值
├─ test_access.py              # NEW: get_client_ip (trusted_proxies), access_scope_guard, gallery_scope_guard
├─ test_deps_lan.py            # MODIFY: require_lan_ip 走新 get_client_ip
├─ test_routes_auth.py         # MODIFY: 登录返回 access_scope; access_scope_violation 错误码
├─ test_routes_admin_users.py  # NEW: users 列表/新建/详情/更新/重置密码/删除/最后 admin 保护
├─ test_routes_browse.py       # MODIFY: viewer 不可见未授权图库; admin 全见
├─ test_routes_media.py        # MODIFY: viewer 不可访问未授权图库的 thumb/image

frontend/src/
├─ stores/
│  └─ auth.ts                 # MODIFY: User type +access_scope
├─ api.ts                     # MODIFY: 401/403 时细分 access_scope_violation 文案
├─ router.ts                  # MODIFY: +/admin/users 路由 + guard
├─ components/
│  └─ AppHeader.vue           # MODIFY: 显示"LAN"/"远程"角标 + 管理菜单加"用户"
├─ views/
│  ├─ LoginView.vue           # MODIFY: 感知 access_scope_violation 错误码，给出"请连接家庭 Wi-Fi"提示
│  ├─ AdminOverview.vue       # MODIFY: 用户数卡片链接到 /admin/users
│  └─ AdminUsers.vue          # NEW: 表格 + 新建/编辑/重置密码/禁用/删除
└─ tests/
   ├─ admin-users.spec.ts     # NEW
   └─ access-scope.spec.ts    # NEW（前端）
```

---

## Task 清单概览（15 个任务）

| # | 主题 | 端 |
|---|---|---|
| 1 | UserGallery ORM 模型 + 建表 | BE |
| 2 | `[security]` 配置 + 扩展 `AppConfig` | BE |
| 3 | `access.py` 工具：`get_client_ip` + `access_scope_guard` + `gallery_scope_guard` | BE |
| 4 | `deps.py` / `require_lan_ip` 接入新工具；`current_user` 串联步骤 3 | BE |
| 5 | `/api/auth/me` 返回 `access_scope`；`/api/auth/login` 错误码细化 | BE |
| 6 | 浏览端 `routes_browse.py` 应用 `gallery_scope_guard` | BE |
| 7 | 媒体端 `routes_media.py` 应用 `check_gallery_access` | BE |
| 8 | `/api/admin/users*` 全套（list/create/get/patch/reset-password/delete） + 最后一个 admin 保护 | BE |
| 9 | admin 路由所有 user 端点接 audit + `user_galleries` 写库 | BE |
| 10 | 前端 `auth` store 扩展 + `apiClient` 错误码处理 | FE |
| 11 | LoginView 感知 `access_scope_violation` + AppHeader 显示访问域 | FE |
| 12 | 前端 `/admin/users` 路由 + AdminOverview 卡片链接 | FE |
| 13 | AdminUsers 视图（表格 + 新建/编辑/重置密码/禁用/删除 + 图库授权多选） | FE |
| 14 | 前端测试 + 后端集成测试 | Full |
| 15 | 端到端验证 + 红线 grep + 提交 + tag | Full |

---

## 关键接口速查（跨任务共享）

### UserGallery ORM（spec §4.2）

```python
class UserGallery(Base):
    __tablename__ = "user_galleries"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    gallery_id: Mapped[int] = mapped_column(ForeignKey("galleries.id", ondelete="CASCADE"), primary_key=True)
    granted_at: Mapped[int] = mapped_column(Integer, nullable=False)
```

> **Admin 不入此表**：admin 角色隐含全图库可见，view/`/api/admin/users/{id}` 返回的 `gallery_ids` 字段对 admin 返回全部图库 id，对 viewer 返回 `user_galleries` 中实际授权的图库 id 列表（写入时由前端提交）。

### `AppConfig` 新增字段（spec §9）

```python
@dataclass
class AppConfig:
    # ... 既有字段
    trusted_proxies: list[str]        # CIDR / 单 IP；空 = 不信任 X-Forwarded-For
    login_lockout_threshold: int      # 默认 5
    login_lockout_minutes: int        # 默认 15
    # session_hours 已在 P1
```

`config.toml` 模板追加：
```toml
[security]
trusted_proxies = []                # e.g. ["127.0.0.1", "10.0.0.0/8", "::1"]
login_lockout_threshold = 5
login_lockout_minutes = 15
```

### `access.py` 接口

```python
# access.py —— 单向依赖 deps.py（_PRIVATE_RANGES / _is_lan_ip / current_user 留在 deps.py）

import ipaddress
from fastapi import Depends, Request
from sqlalchemy import select

from myphoto.deps import _PRIVATE_RANGES, _is_lan_ip, current_user
from myphoto.errors import AppError
from myphoto.models import User, UserGallery


def get_client_ip(request: Request, trusted_proxies: list[str]) -> str:
    """Return the effective client IP.

    - If trusted_proxies is empty: request.client.host (or "unknown")
    - Else if request.client.host is in trusted_proxies: take leftmost non-empty
      non-"unknown" segment of X-Forwarded-For; fall back to request.client.host.
    - Else: request.client.host
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


def _ip_in_trusted(host: str, trusted: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    for entry in trusted:
        try:
            net = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if addr in net:
            return True
    return False


async def access_scope_guard(
    request: Request,
    user: User = Depends(current_user),
) -> User:
    """Step 3: enforce user.access_scope against effective client IP.

    Returns the user unchanged; raises 403 access_scope_violation on mismatch.
    """
    if user.access_scope == "lan_only":
        cfg = request.app.state.config
        ip = get_client_ip(request, cfg.trusted_proxies)
        if not _is_lan_ip(ip):
            raise AppError(
                "access_scope_violation", 403,
                "this account is restricted to the local network",
            )
    return user


async def check_gallery_access(
    session,
    user: User,
    gallery_id: int,
) -> None:
    """Step 5 helper for routes that resolve gallery_id at runtime
    (media endpoints lookup image → root → gallery_id, not from path).

    - admin: pass-through
    - viewer: require a row in user_galleries; otherwise 404 not_found (anti-enum)
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
    user: User = Depends(access_scope_guard),
) -> User:
    """Step 5 dependency for routes that have `gid` in the path
    (browse endpoints: /galleries/{gid}, /galleries/{gid}/roots/{rid}/...).

    FastAPI extracts `gid` from the path and injects it here.
    - admin: pass-through
    - viewer: require a row in user_galleries; otherwise 404 not_found (anti-enum)
    """
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
```

### `require_lan_ip` 改造

```python
# deps.py（修改后）
async def require_lan_ip(request: Request) -> None:
    cfg = request.app.state.config
    host = access.get_client_ip(request, cfg.trusted_proxies)
    if not access._is_lan_ip(host):
        raise AppError("admin_fs_lan_only", 403,
                       "this endpoint is only available on the local network")
```

### 权限链组合（routes_browse.py 改法示意）

```python
# GET /api/galleries
@router.get("/galleries")
async def list_galleries(
    request: Request,
    response: Response,
    user: User = Depends(access_scope_guard),   # P4: 替换 current_user
):
    # admin 全见；viewer 仅见 user_galleries 中的
    sm = request.app.state.sessionmaker
    async with sm() as s:
        if user.role == "admin":
            gals = (await s.execute(select(Gallery))).scalars().all()
        else:
            gals = (
                await s.execute(
                    select(Gallery)
                    .join(UserGallery, UserGallery.gallery_id == Gallery.id)
                    .where(UserGallery.user_id == user.id)
                )
            ).scalars().all()
        ...
```

`/api/galleries/{gid}` / `folders` / `images` / `breadcrumbs` 全部使用 `gallery_scope_guard(gid=...)` 替代 `current_user`（FastAPI 从 path 注入 `gid`）。`/api/thumb/{sha1}` / `/api/image/{image_id}` 没有 `gid` 在 path，路由内查 image → root → gallery_id 后调 `access.check_gallery_access(session, user, gallery_id)` 做步骤 5 判定；admin 仍跳过 DB 查询。

### 管理端用户 API（spec §6.5）

```
GET    /api/admin/users                  → 列表（含 username / role / access_scope / enabled / gallery_count / last_login_at / created_at）
POST   /api/admin/users                  → {username, password?, role, access_scope, gallery_ids[]?}
                                        → 201 + {id, username, ..., initial_password?: str}（密码缺省时回显）
GET    /api/admin/users/{uid}            → 详情 + gallery_ids: list[int]（admin 返回全部图库 id）
PATCH  /api/admin/users/{uid}            → {role?, access_scope?, enabled?, gallery_ids?}（admin 改自己时受限，见下）
POST   /api/admin/users/{uid}/reset-password
                                        → {new_password} 或空 body（后端生成 12 字符并回显）
DELETE /api/admin/users/{uid}            → 204；最后一个 admin 保护 → 409 last_admin_protected
```

**最后 admin 保护位点**（4 处都校验）：
1. `DELETE /api/admin/users/{uid}`：目标若是 admin，事务内 `select count(users where role='admin' and enabled=1) - (1 if target=admin and enabled=1 else 0) < 1` → 拒绝
2. `PATCH role=viewer` 或 `PATCH enabled=0`：同上，把"目标切换后"的 admin 计数与 1 比较
3. **admin 改自己**：admin 可改自己的 password、access_scope、enabled（disabled 自己是合法的退路）；但**改自己 role** 也走最后 admin 保护（防误操作把自己降级）
4. 任何失败 409 `last_admin_protected`

**viewer 自我修改**：
- viewer 调 `PATCH /api/admin/users/{self.id}`：仅 `gallery_ids` 字段可改（且需 admin 授权——不允许）；更简单：viewer 根本无权调 `/api/admin/*`（依赖 `admin_required`），所有 viewer 自助改密走 `POST /api/auth/change-password`（P2 已有）

### 错误码表

| code | HTTP | 触发 |
|---|---|---|
| `access_scope_violation` | 403 | step 3 拒绝（已有 spec §6.9） |
| `last_admin_protected` | 409 | 最后 admin 保护（已有 spec §6.9） |

### 前端接口速查

**AdminUsers 页面**：
- 表格列：用户名 / 角色（admin/viewer 徽章）/ 访问域（LAN/远程 徽章）/ 启用（开关）/ 授权图库数 / 最近登录 / 操作
- 工具栏：[+ 新建用户]
- 行操作：[编辑] [重置密码] [禁用/启用] [删除]
- **新建/编辑 modal**：
  - 用户名（必填，3-32 字符，唯一性后端校验）
  - 角色（radio：admin / viewer）
  - 访问域（radio：lan_only / remote_allowed）
  - 启用（开关）
  - 密码（新建时可填或留空，**留空 → 提交后弹一次性显示密码 modal**；编辑时隐藏）
  - 授权图库（多选下拉；admin 角色时灰显并标注"admin 自动全图库可见"）
- **重置密码 modal**：可填或留空生成；提交后弹一次性显示密码 modal
- **删除**：二次确认（输入用户名确认）
- **最后 admin 保护**：UI 层若当前用户是唯一 admin，禁用删除按钮 + 提示文字

**AppHeader 访问域徽标**：
- 在用户头像旁显示：`LAN` 灰色 / `远程` 橙色（依 `auth.user.access_scope` 渲染，反映"该账号**被允许**的访问域"，不是当前请求的实际域）
- 若当前用户当前请求实际跨域（admin 浏览端点被 LAN guard 拒绝时由 401/403 触发，UI 不直接感知；此徽标只是"账号属性"展示）

**LoginView 错误码处理**：
- 403 `access_scope_violation` → 红色 banner "该账号仅限局域网访问，请连接家庭 Wi-Fi 后重试"
- 401 `invalid_credentials` → "账号或密码错误"
- 423 `login_locked` → 黄色 banner "尝试次数过多，请稍后再试"

---

### Task 1: UserGallery ORM 模型 + 建表

**Files:**
- Modify: `backend/src/myphoto/models.py`
- Modify: `backend/tests/test_models.py`（如不存在则新建）

**Steps:**
- [ ] **Step 1: 在 models.py 中添加 UserGallery** — 按上面接口速查的 schema 实现（联合主键 user_id+gallery_id，FK ON DELETE CASCADE，granted_at: int）
- [ ] **Step 2: 验证 create_all 自动建表** — 启动 app → 检查 `sqlite_master` 含 `user_galleries` 表与 PK
- [ ] **Step 3: 写测试** — 创建 user/gallery → 创建 user_gallery 行 → 删除 user → 行级联消失；删除 gallery → 同样级联
- [ ] **Step 4: 运行测试验证通过并提交**

---

### Task 2: `[security]` 配置 + 扩展 `AppConfig`

**Files:**
- Modify: `backend/src/myphoto/config.py`
- Modify: `config.toml`（首启动自动生成；模板追加 `[security]` 段；不破坏既有配置）
- Create: `backend/tests/test_config.py`

**Steps:**
- [ ] **Step 1: 在 AppConfig 加字段** — `trusted_proxies: list[str]`, `login_lockout_threshold: int`, `login_lockout_minutes: int`
- [ ] **Step 2: 解析 `[security]` 段** — `tomllib` 读出 `trusted_proxies` 列表（支持 CIDR 与单 IP，存为原样字符串，运行时由 `access.py` 解析为 `ip_network`）；其他两个字段给默认值
- [ ] **Step 3: 更新 `_DEFAULT_TEMPLATE`** — 追加 `[security]` 默认段（trusted_proxies=[], threshold=5, minutes=15）
- [ ] **Step 4: 写测试** — 缺省值、显式值、非法 CIDR 抛错或忽略（推荐忽略 + 警告日志）
- [ ] **Step 5: 运行测试验证通过并提交**

---

### Task 3: `access.py` 工具：`get_client_ip` + `access_scope_guard` + `gallery_scope_guard`

**Files:**
- Create: `backend/src/myphoto/access.py`
- Create: `backend/tests/test_access.py`

**Steps:**
- [ ] **Step 1: 实现 `get_client_ip`** — 按接口速查的逻辑实现；`trusted_proxies` 解析时尝试 `ip_network` 失败则跳过该项并打 warn 日志
- [ ] **Step 2: 实现 `access_scope_guard`** — 步骤 3 判定；`user.access_scope == "lan_only"` 时检查 `get_client_ip` 解析出的 IP 是否在 `_PRIVATE_RANGES`（`_PRIVATE_RANGES` 与 `_is_lan_ip` **保持**在 `deps.py`，`access.py` 单向 import 复用，不迁移以避免循环导入）
- [ ] **Step 3: 实现 `gallery_scope_guard(gid)`** — admin 放行；viewer 查 `user_galleries` 表；缺行 404 not_found
- [ ] **Step 4: 写测试** —
  - `get_client_ip`：trusted_proxies 空 → 始终用 `request.client.host`；非空且 client 在 trusted → 取 XFF 左起第一段；非空但 client 不在 trusted → 忽略 XFF 用 `request.client.host`；XFF 段为 "unknown" 跳过
  - `access_scope_guard`：`lan_only` + LAN IP 通过；`lan_only` + 公网 IP 拒；`remote_allowed` 任意 IP 通过；admin 与 viewer 行为一致（不区分角色）
  - `gallery_scope_guard`（path 注入）：admin 直接通过；viewer 有授权通过；viewer 无授权 404（不是 403，防枚举）；授权 gallery 删除后 viewer 访问 404
  - `check_gallery_access`（手工调用）：与 `gallery_scope_guard` 行为一致；不依赖 `request` 注入
- [ ] **Step 5: 运行测试验证通过并提交**

---

### Task 4: `deps.py` / `require_lan_ip` 接入新工具；`current_user` 串联步骤 3

**Files:**
- Modify: `backend/src/myphoto/deps.py`
- Modify: `backend/tests/test_deps_lan.py`
- Modify: `backend/tests/test_routes_auth.py`

**Steps:**
- [ ] **Step 1: 不迁移 helpers —— 避免循环导入** — `_PRIVATE_RANGES` / `_is_lan_ip` **保持**在 `deps.py`；`access.py` 单向 `from myphoto.deps import _PRIVATE_RANGES, _is_lan_ip, current_user`（不反向 import）。原计划"迁移到 access.py"会导致循环导入，已改为共享 helpers。
- [ ] **Step 2: `require_lan_ip` 改用 `access.get_client_ip`** — 从 `request.app.state.config` 读 `trusted_proxies`；判定逻辑与 `access_scope_guard` 共用同一 `_is_lan_ip`
- [ ] **Step 3: 把步骤 3 串入 `current_user`** — 在 `current_user` 末尾追加步骤 3 判定逻辑（直接复用 `_is_lan_ip` 与 `get_client_ip`，不通过 `Depends(access_scope_guard)` 嵌套——避免 self-referential dependency）。保证所有用 `current_user` 的端点都自动获得步骤 3 判定。代码模式：`enabled` 校验通过后 → `if user.access_scope == "lan_only" and not _is_lan_ip(get_client_ip(request, cfg.trusted_proxies)): raise AppError("access_scope_violation", 403, ...)`
- [ ] **Step 4: `admin_required` 不变** — 已通过 `current_user` 继承步骤 3；`require_lan_ip` 仍可独立叠加（重复判定不冲突，有冗余但不互相干扰）
- [ ] **Step 5: 写测试** — `current_user` 在 `lan_only` + 公网 IP 抛 403；LAN IP 通过；`remote_allowed` + 公网 IP 通过；admin_required 在 lan_only admin 从公网访问 admin 端点时也 403
- [ ] **Step 6: 运行全部 auth/access/deps 测试并提交**

---

### Task 5: `/api/auth/me` 返回 `access_scope`；`/api/auth/login` 错误码细化

**Files:**
- Modify: `backend/src/myphoto/routes_auth.py`
- Modify: `backend/tests/test_routes_auth.py`

**Steps:**
- [ ] **Step 1: `/api/auth/me` 返回 access_scope** — `{"id", "username", "role", "access_scope", "enabled", "last_login_at"}`
- [ ] **Step 2: 登录失败错误码** — 现状：失败统一 401；细化：密码错 401 `invalid_credentials`；锁定 423 `login_locked`；新加：admin 把 access_scope 设为 lan_only 但从公网登录时（步骤 3） → 403 `access_scope_violation`（沿用 P4 step 3 判定）
- [ ] **Step 3: 写测试** — me 返回字段完整；公网 IP 登录 lan_only admin 返 403；LAN IP 通过；锁定 5 次后返 423
- [ ] **Step 4: 提交**

---

### Task 6: 浏览端 `routes_browse.py` 应用 `gallery_scope_guard`

**Files:**
- Modify: `backend/src/myphoto/routes_browse.py`
- Modify: `backend/tests/test_routes_browse.py`

**Steps:**
- [ ] **Step 1: `GET /api/galleries` 按用户过滤** — 改用 `Depends(access_scope_guard)` 替代 `current_user`；admin 拉全部，viewer join `user_galleries` 拉授权
- [ ] **Step 2: `GET /api/galleries/{gid}` 引入 `gallery_scope_guard(gid=...)`** — viewer 看不到未授权图库（404）
- [ ] **Step 3: `GET /api/galleries/{gid}/roots/{rid}/folders|images|breadcrumbs`** — 同样套 `gallery_scope_guard`
- [ ] **Step 4: 写测试** — viewer 列表只含授权图库；viewer 访问未授权图库 404；admin 行为不变；viewer 取消授权后立刻 404
- [ ] **Step 5: 提交**

---

### Task 7: 媒体端 `routes_media.py` 应用 `check_gallery_access`

**Files:**
- Modify: `backend/src/myphoto/routes_media.py`
- Modify: `backend/tests/test_routes_media.py`

**Steps:**
- [ ] **Step 1: `GET /api/thumb/{sha1}` 加权限** — 改 `Depends(current_user)` 为 `Depends(access_scope_guard)`；路由内查 image → root → gallery_id；open 新 session 后调 `await access.check_gallery_access(session, user, gallery_id)`；未授权 404（不是 403）
- [ ] **Step 2: `GET /api/image/{image_id}` 同上**
- [ ] **Step 3: 写测试** — viewer 对授权图库的图片 200；对未授权图库的图片 404；admin 不受限
- [ ] **Step 4: 提交**

---

### Task 8: `/api/admin/users*` 全套（list/create/get/patch/reset-password/delete）+ 最后 admin 保护

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py`（追加 user 段路由，不影响既有 gallery/root/browse-fs/status/audit 等）
- Create: `backend/tests/test_routes_admin_users.py`

**Steps:**
- [ ] **Step 1: 实现 `GET /api/admin/users`** — 列表：username / role / access_scope / enabled / gallery_count / last_login_at / created_at；查询参数 `?role=&enabled=` 可选
- [ ] **Step 2: 实现 `POST /api/admin/users`** — body: `{username, password?, role, access_scope, gallery_ids?}`；password 缺省时后端生成 12 字符随机（`secrets.token_urlsafe(9)`）一次性回显在响应中；`gallery_ids` 对 admin 角色忽略（不入 user_galleries）
- [ ] **Step 3: 实现 `GET /api/admin/users/{uid}`** — 详情：含 `gallery_ids: list[int]`（admin 角色返全部图库 id；viewer 返 user_galleries 实际授权）；不返回 password_hash
- [ ] **Step 4: 实现 `PATCH /api/admin/users/{uid}`** — 字段：role / access_scope / enabled / gallery_ids；不允许改 username 与 password_hash（password 用 reset-password 端点）；最后 admin 保护集成
- [ ] **Step 5: 实现 `POST /api/admin/users/{uid}/reset-password`** — body: `{new_password}` 可缺省（缺省生成 12 字符并回显）；成功后写 audit `password_reset`
- [ ] **Step 6: 实现 `DELETE /api/admin/users/{uid}`** — 最后 admin 保护；写 audit `user_delete`
- [ ] **Step 7: 写测试** —
  - list：分页 / 过滤 / 不含密码哈希
  - create：成功；密码缺省回显；重复用户名 409；密码弱 422 `password_too_weak`；admin 创建 viewer 时 gallery_ids 写入 user_galleries
  - get：admin 返全图库 id；viewer 返实际授权
  - patch：部分字段；admin 把自己改 viewer 409 `last_admin_protected`；最后一个 admin enabled=0 409
  - reset-password：成功；生成密码回显；写 audit
  - delete：成功；最后一个 admin 409；写 audit
- [ ] **Step 8: 提交**

---

### Task 9: admin user 端点接 audit + `user_galleries` 写库

**Files:**
- Modify: `backend/src/myphoto/routes_admin.py`（同 Task 8）
- Modify: `backend/tests/test_routes_admin_users.py`（追加 audit 断言）

**Steps:**
- [ ] **Step 1: 写 audit 事件** — `user_create` / `user_delete` / `user_disable`（patch enabled=0）/ `user_update`（其他字段变更）/ `password_reset`（spec §4.9 已定义）
- [ ] **Step 2: 写 `user_galleries` 同步** — PATCH 时如含 `gallery_ids`，事务内 delete-all-then-insert；CREATE 时同理
- [ ] **Step 3: 测试断言 audit 行存在** — `action`, `target`（`user:<id>`）, `actor_user_id`（操作者 id）
- [ ] **Step 4: 提交**

---

### Task 10: 前端 `auth` store 扩展 + `apiClient` 错误码处理

**Files:**
- Modify: `frontend/src/stores/auth.ts`
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/tests/access-scope.spec.ts`（前端错误码测试可与 Task 14 合并）

**Steps:**
- [ ] **Step 1: User 类型扩展** — `{ id, username, role, access_scope: "lan_only" | "remote_allowed", enabled, last_login_at? }`
- [ ] **Step 2: apiClient 细分 403 错误码** — 当后端返回 `access_scope_violation` → toast "该账号仅限局域网访问"；其他 403 → 通用 "无权访问"；401 → 跳登录（保留）
- [ ] **Step 3: 提交**

---

### Task 11: LoginView 感知 `access_scope_violation` + AppHeader 显示访问域

**Files:**
- Modify: `frontend/src/views/LoginView.vue`
- Modify: `frontend/src/components/AppHeader.vue`

**Steps:**
- [ ] **Step 1: LoginView 错误码处理** — 捕获 403 `access_scope_violation` → 红色 banner "该账号仅限局域网访问，请连接家庭 Wi-Fi 后重试"；423 `login_locked` → 黄色 banner "尝试次数过多，请稍后再试"
- [ ] **Step 2: AppHeader 加访问域徽标** — 在用户名前显示小徽标：`LAN` 灰底 / `远程` 橙底（依 `auth.user.access_scope`）；与"管理"链接同行
- [ ] **Step 3: 提交**

---

### Task 12: 前端 `/admin/users` 路由 + AdminOverview 卡片链接

**Files:**
- Modify: `frontend/src/router.ts`
- Modify: `frontend/src/views/AdminOverview.vue`

**Steps:**
- [ ] **Step 1: 添加路由** — `{ path: "/admin/users", component: () => import("./views/AdminUsers.vue"), meta: { requiresAdmin: true } }`
- [ ] **Step 2: AdminOverview "用户" 卡片加链接** — `router.push("/admin/users")`；卡片数显示当前用户总数
- [ ] **Step 3: AppHeader "管理" 菜单加 "用户" 子项**（dropdown 形式或新增链接）
- [ ] **Step 4: 提交**

---

### Task 13: AdminUsers 视图（表格 + 新建/编辑/重置密码/禁用/删除 + 图库授权多选）

**Files:**
- Create: `frontend/src/views/AdminUsers.vue`

**Steps:**
- [ ] **Step 1: 表格视图** — `onMounted` 调 `GET /api/admin/users`；表格列：用户名 / 角色徽章 / 访问域徽章 / 启用开关（仅 admin 可改） / 授权图库数 / 最近登录 / 操作按钮组
- [ ] **Step 2: 新建用户 modal** — 表单：username / role (radio) / access_scope (radio) / enabled (switch) / password (可空) / gallery_ids (多选下拉，仅 viewer 角色可编辑) / [取消] [创建]；提交后若响应含 `initial_password` 弹一次性显示 modal
- [ ] **Step 3: 编辑用户 modal** — 同上但 password 字段隐藏；可改 role / access_scope / enabled / gallery_ids
- [ ] **Step 4: 重置密码 modal** — 输入框可空 / 提交后弹一次性显示 modal
- [ ] **Step 5: 禁用/启用切换** — 启用开关直接 PATCH enabled；若目标是最后 admin，前端预判后禁用按钮 + 提示（后端是权威）
- [ ] **Step 6: 删除** — 二次确认（输入 username）；最后 admin 前端预判禁用按钮
- [ ] **Step 7: 提交**

---

### Task 14: 前端测试 + 后端集成测试

**Files:**
- Create: `frontend/src/tests/admin-users.spec.ts`
- Create: `frontend/src/tests/access-scope.spec.ts`
- Create: `backend/tests/test_users_integration.py`

**Steps:**
- [ ] **Step 1: 前端 admin-users 测试** — 加载列表、新建/编辑/重置密码/删除/禁用的请求路径与状态切换
- [ ] **Step 2: 前端 access-scope 测试** — LoginView 错误码文案；AppHeader 徽标根据 access_scope 切换
- [ ] **Step 3: 后端集成测试** —
  - 端到端：admin 创建 viewer → 授权 gallery1 → viewer 登录 → 仅见 gallery1 → admin 改 viewer enabled=0 → viewer 登录 401 → admin 重新启用 → viewer 重登
  - last admin 保护：admin 试图把唯一 admin 改 viewer 409；试图删除唯一 admin 409；试图 disable 唯一 admin 409
  - trusted_proxies 链路：本地裸跑（trusted_proxies=[]）→ XFF 不影响 client_ip；nginx 反代场景（trusted_proxies=["127.0.0.1"]）→ XFF 生效
- [ ] **Step 4: 提交**

---

### Task 15: 端到端验证 + 红线 grep + 提交 + tag

**Files:** 无新文件

**Steps:**
- [ ] **Step 1: 重启后端确认 schema 升级无报错** — `user_galleries` 表由 `create_all` 自动创建；`config.toml` 模板追加 `[security]` 段
- [ ] **Step 2: curl 验证完整多用户流程** — admin 登录 → 创建 viewer + 授权 gallery1 → viewer 登录 → 列表仅 gallery1 → viewer 访问 gallery2 404 → admin 改 viewer enabled=0 → viewer 重登 401
- [ ] **Step 3: 验证最后 admin 保护** — 单 admin 时 PATCH self role=viewer / DELETE self / PATCH self enabled=0 全部 409
- [ ] **Step 4: 验证 trusted_proxies** — 本地裸跑 + curl 加 `-H "X-Forwarded-For: 8.8.8.8"` → lan_only admin 仍 200（XFF 被忽略）；手动改 config 设 `trusted_proxies=["127.0.0.1"]` 后同样命令 → 403 access_scope_violation
- [ ] **Step 5: 前端构建** — `pnpm build` 确认无构建错误
- [ ] **Step 6: 浏览器手动验证** —
  - admin 登录后顶栏显示"LAN"或"远程"徽标
  - `/admin/users` 显示表格；新建/编辑/重置密码/禁用/删除全部走通
  - 新建 viewer 时密码留空 → 弹一次性显示密码
  - viewer 用一次性密码登录 → 顶栏显示对应徽标
  - viewer 访问未授权图库 404（前端按 `not_found` 处理：toast "图库不存在"）
  - viewer 远程登录 lan_only 账号 → LoginView 红色 banner
- [ ] **Step 7: 全量 backend 测试** — `pytest backend/tests/ -v`，全绿
- [ ] **Step 8: 全量 frontend 测试** — `cd frontend && pnpm test`，全绿
- [ ] **Step 9: 红线 grep** —
  ```bash
  rg -i 'os\.remove' backend/src/myphoto/   # 只在 trash.py purge_expired
  rg -i 'shutil\.rmtree' backend/src/myphoto/  # 只在 routes_admin.py thumb-cache purge
  rg -i 'X-Forwarded-For' backend/src/myphoto/  # 只在 access.py get_client_ip
  ```
  期望：无新增越界位点
- [ ] **Step 10: 提交并打 tag `phase4-users-roles`**

---

## Design Decision Summary

1. **Task granularity**: 15 tasks — 9 backend, 5 frontend, 1 integration+tag
2. **Permission chain 一次性上线**: 把步骤 3 串入 `current_user`（覆盖所有受保护端点），把步骤 5 拆成两层：浏览端用 `gallery_scope_guard(gid)`（path 注入，FastAPI 自动传 `gid`）；媒体端用纯函数 `check_gallery_access(session, user, gallery_id)`（路由内查 image→root→gallery_id 后调用，避开 path 无 `gid` 的问题）
3. **trusted_proxies 处理**: 严格"只在 trusted 时读 XFF"——避免公网伪造 XFF 绕过 `lan_only`；默认空 list 行为兼容 P1-P3
4. **admin 隐含全图库可见**: 不写 `user_galleries` 行；UI 在 admin 角色的 modal 上把 gallery_ids 灰显并标注"admin 自动全图库可见"，避免误填
5. **最后 admin 保护**: 4 个位点（DELETE、PATCH role 改非 admin、PATCH enabled=0、admin 改自己）都查 `count(admin enabled=1)`；P2 的 `admin_required` 不变，但 PATCH / DELETE 端点内部再做一次计数
6. **密码回显**: 创建/重置时允许后端生成 12 字符 `secrets.token_urlsafe(9)`（base64 12 字符）一次性回显；不存明文；前端弹一次性 modal 并"复制"按钮
7. **viewer 自助改密**: 走已有 `POST /api/auth/change-password`，**不**经 `/api/admin/*`；viewer 角色根本进不了 admin 路由
8. **错误码**: 沿用 spec §6.9 已定义的 `access_scope_violation` / `last_admin_protected`，无新增；LoginView 401 / 403 错误码细分仅前端处理
9. **审计**: 复用 P2 `write_audit`；新事件 `user_create` / `user_delete` / `user_disable` / `user_update` / `password_reset` 全部在 spec §4.9 列表内
10. **前端最小改动**: AppHeader 仅加徽标与"管理"菜单项；LoginView 仅加错误码分支；AdminOverview 仅加卡片链接；不引入新依赖
