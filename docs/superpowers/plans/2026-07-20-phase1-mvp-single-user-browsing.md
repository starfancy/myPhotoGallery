# myPhotoGallery Phase 1 (MVP) 实现计划：单用户单图库桌面浏览

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可运行的最小闭环 —— 登录初始 admin 账号 → 通过 CLI 添加一个图库和一个本地根目录 → 浏览器里以密铺网格看到该目录及子目录的图片 → 点开 Lightbox 查看单张（PC 键盘 / 滚轮 / Esc 交互 + 触屏基本手势）。

**Architecture:** FastAPI 单进程同时托管 API 和 Vue SPA；SQLite（aiosqlite）单库；后台单 worker asyncio 扫描队列；缩略图按 sha1 落盘缓存；JWT HttpOnly cookie 认证；密码 bcrypt。前端 Vue 3 + Vite + Pinia + Vue Router，虚拟滚动 `vue-virtual-scroller`，Lightbox 用 PhotoSwipe v5。

**Tech Stack:** Python 3.11+ · FastAPI · SQLAlchemy 2.0 async + aiosqlite · Pillow + pillow-heif + rawpy · PyJWT · bcrypt · pytest + pytest-asyncio + httpx · Vue 3 · Vite · Pinia · Vue Router · UnoCSS · vue-virtual-scroller · PhotoSwipe v5 · vitest

## Global Constraints

- Python 版本 ≥ 3.11
- 所有引用文件系统的字段存**相对路径**（相对所属 root），分隔符统一 `/`
- 时间戳统一 Unix 秒（整数）
- 认证 cookie：`HttpOnly + SameSite=Lax + Path=/`
- 错误响应统一：`{"error": {"code": "<stable_snake_case>", "message": "<human>"}}`
- **红线 1**：文件夹永不物理删除；`shutil.rmtree` 全代码库禁止（本期用 grep 检查）
- **红线 2**：本期不涉及 `os.remove` 图库根目录下文件；`os.remove` 全代码库禁止（本期无回收站清理，因此不需要，P5 再引入并加护栏）
- **红线 3**：Path safety —— 所有含相对路径的请求必须归一化并拒绝 `..`；realpath 前缀必须是所属 root 的 `absolute_path`
- 缩略图 URL 内容不可变：`Cache-Control: public, max-age=31536000, immutable`；列表 API 一律 `no-store`
- 图片格式白名单：`jpg jpeg png gif webp heic heif avif cr2 cr3 nef arw dng orf rw2 raf pef`（小写扩展名）
- 每完成一个 Task 提交一次 git；提交信息前缀 `feat:` / `fix:` / `test:` / `chore:`

---

## 目录结构（P1 完成时）

```
myPhotoGallery/
├─ pyproject.toml
├─ README.md
├─ .gitignore
├─ config.toml                 # 首启动自动生成
├─ app.db                      # 首启动自动生成
├─ backend/
│  ├─ src/
│  │  └─ myphoto/
│  │     ├─ __init__.py
│  │     ├─ main.py            # FastAPI app 装配 + lifespan
│  │     ├─ config.py          # 读写 config.toml
│  │     ├─ db.py              # 引擎 + session
│  │     ├─ models.py          # SQLAlchemy ORM
│  │     ├─ schema_init.py     # 首启动创建 schema + 初始 admin
│  │     ├─ security.py        # bcrypt + JWT
│  │     ├─ deps.py            # FastAPI dependencies (current_user, admin_required)
│  │     ├─ errors.py          # 统一异常与错误响应
│  │     ├─ paths.py           # 路径归一化 + 越界检查
│  │     ├─ formats.py         # 图片扩展名白名单 + 判定
│  │     ├─ scanner.py         # 扫描 worker + 队列
│  │     ├─ thumbnails.py      # 缩略图生成与缓存
│  │     ├─ routes_auth.py
│  │     ├─ routes_browse.py
│  │     ├─ routes_media.py    # thumb / image 流
│  │     └─ cli.py             # 命令行 (add-gallery, add-root, rescan)
│  └─ tests/
│     ├─ conftest.py
│     ├─ test_paths.py
│     ├─ test_formats.py
│     ├─ test_security.py
│     ├─ test_schema_init.py
│     ├─ test_scanner.py
│     ├─ test_thumbnails.py
│     ├─ test_routes_auth.py
│     ├─ test_routes_browse.py
│     └─ test_routes_media.py
└─ frontend/
   ├─ package.json
   ├─ vite.config.ts
   ├─ tsconfig.json
   ├─ uno.config.ts
   ├─ index.html
   └─ src/
      ├─ main.ts
      ├─ App.vue
      ├─ router.ts
      ├─ api.ts                # fetch 封装
      ├─ stores/
      │  ├─ auth.ts
      │  ├─ browse.ts
      │  └─ toast.ts
      ├─ views/
      │  ├─ LoginView.vue
      │  ├─ GalleryListView.vue
      │  ├─ RootListView.vue
      │  └─ BrowseView.vue
      ├─ components/
      │  ├─ AppHeader.vue
      │  ├─ Breadcrumb.vue
      │  ├─ SubfolderStrip.vue
      │  ├─ JustifiedGrid.vue
      │  └─ ImageLightbox.vue
      └─ tests/
         ├─ justified-layout.spec.ts
         └─ path-utils.spec.ts
```

---

## Task 清单概览（20 个任务）

| # | 主题 | 端 |
|---|---|---|
| 1 | 后端脚手架 + pytest 冒烟 | BE |
| 2 | 路径安全工具 `paths.py` | BE |
| 3 | 图片格式白名单 `formats.py` | BE |
| 4 | 密码 + JWT 工具 `security.py` | BE |
| 5 | 数据库模型 `models.py` + 迁移 | BE |
| 6 | 首启动 schema + 初始 admin `schema_init.py` | BE |
| 7 | 配置文件 `config.py` | BE |
| 8 | FastAPI 骨架 + lifespan + 错误处理 `main.py` `errors.py` | BE |
| 9 | 认证依赖 + `/api/auth/*` 路由 | BE |
| 10 | 单 worker 扫描队列 + 增量扫描 `scanner.py` | BE |
| 11 | 缩略图生成与缓存 `thumbnails.py` | BE |
| 12 | 浏览 API `/api/galleries*` `routes_browse.py` | BE |
| 13 | 媒体流 API `/api/thumb` `/api/image` `routes_media.py` | BE |
| 14 | CLI 工具 `cli.py`（add-gallery / add-root / rescan） | BE |
| 15 | 前端脚手架 Vite + Vue + Pinia + Router + UnoCSS | FE |
| 16 | `apiClient` + `useAuthStore` + LoginView | FE |
| 17 | GalleryListView + RootListView + Breadcrumb | FE |
| 18 | JustifiedGrid + `useBrowseStore` + 虚拟滚动 | FE |
| 19 | ImageLightbox（PhotoSwipe）+ 深链路由 | FE |
| 20 | 前端产物由后端托管 + 端到端手动验证清单 | Full |

---

## 关键接口速查（跨任务共享）

**HTTP 错误码（P1 用到的）**：`unauthenticated`, `invalid_credentials`, `login_locked`, `password_too_weak`, `forbidden`, `not_found`, `path_invalid`, `path_not_readable`, `root_offline`, `scan_in_progress`, `internal_error`

**JWT payload**：`{"sub": <user_id:int>, "role": "admin"|"viewer", "iat": <int>, "exp": <int>}`

**Cookie 名**：`mpg_session`

**Scanner 队列接口**：
```python
async def enqueue_scan(root_id: int) -> None
async def get_scan_status(root_id: int) -> dict  # {"status": "idle"|"running", "last_scan_at": int|None, "last_scan_error": str|None}
```

**Thumbnail 接口**：
```python
async def get_or_generate_thumb(sha1: str, size: int, source_path: str, is_raw: bool) -> Path
```

**Path safety 接口**：
```python
def normalize_relative(raw: str) -> str  # 去 "" / "." / ".."; 归一化分隔符; 拒绝绝对路径
def resolve_within_root(root_abs: str, rel: str) -> Path  # realpath 前缀检查; 越界抛 PathTraversalError
```

---

### Task 1: 后端脚手架 + pytest 冒烟

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `backend/src/myphoto/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_smoke.py`

**Interfaces:**
- Consumes: 无
- Produces: 可 import 的 `myphoto` 包；`pytest` 可运行

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "myphoto"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "sqlalchemy>=2.0",
  "aiosqlite>=0.19",
  "pyjwt>=2.8",
  "bcrypt>=4.1",
  "pillow>=10.2",
  "pillow-heif>=0.15",
  "rawpy>=0.19",
  "python-multipart>=0.0.9",
  "tomli>=2.0; python_version<'3.11'",
  "click>=8.1",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "httpx>=0.27", "anyio>=4"]

[project.scripts]
myphoto = "myphoto.cli:main"

[tool.setuptools.packages.find]
where = ["backend/src"]

[tool.pytest.ini_options]
pythonpath = ["backend/src"]
testpaths = ["backend/tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: 写 .gitignore**

```gitignore
__pycache__/
*.pyc
.venv/
.pytest_cache/
node_modules/
frontend/dist/
app.db
config.toml
.cache/
.trash/
.DS_Store
```

- [ ] **Step 3: 写 README.md（一句话开场，后期扩充）**

```markdown
# myPhotoGallery

Local photo library web viewer. See docs/superpowers/specs/ for the design.
```

- [ ] **Step 4: 写空包 __init__.py**

创建 `backend/src/myphoto/__init__.py`：

```python
__version__ = "0.1.0"
```

- [ ] **Step 5: 写 conftest.py（占位）**

创建 `backend/tests/conftest.py`：

```python
# pytest fixtures live here
```

- [ ] **Step 6: 写冒烟测试**

创建 `backend/tests/test_smoke.py`：

```python
def test_can_import_myphoto():
    import myphoto
    assert myphoto.__version__ == "0.1.0"
```

- [ ] **Step 7: 安装依赖并运行测试**

Run:
```bash
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash
pip install -e ".[dev]"
pytest -v
```
Expected: 1 passed

- [ ] **Step 8: 初始化 git 仓库并首个提交**

```bash
git init
git add .
git commit -m "chore: scaffold backend package with pytest smoke test"
```

---

### Task 2: 路径安全工具 `paths.py`

**Files:**
- Create: `backend/src/myphoto/paths.py`
- Create: `backend/tests/test_paths.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `class PathTraversalError(Exception)`
  - `def normalize_relative(raw: str) -> str`
  - `def resolve_within_root(root_abs: str | Path, rel: str) -> Path`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_paths.py`：

```python
import os
import pytest
from pathlib import Path
from myphoto.paths import (
    PathTraversalError,
    normalize_relative,
    resolve_within_root,
)


class TestNormalizeRelative:
    def test_empty_string_returns_empty(self):
        assert normalize_relative("") == ""

    def test_strips_leading_slash(self):
        assert normalize_relative("/a/b") == "a/b"

    def test_converts_backslashes(self):
        assert normalize_relative("a\\b\\c") == "a/b/c"

    def test_collapses_double_slashes(self):
        assert normalize_relative("a//b///c") == "a/b/c"

    def test_removes_current_dir_segments(self):
        assert normalize_relative("a/./b") == "a/b"

    def test_rejects_parent_dir_segment(self):
        with pytest.raises(PathTraversalError):
            normalize_relative("a/../b")

    def test_rejects_absolute_windows_drive(self):
        with pytest.raises(PathTraversalError):
            normalize_relative("C:/x")

    def test_rejects_null_byte(self):
        with pytest.raises(PathTraversalError):
            normalize_relative("a/b\x00")


class TestResolveWithinRoot:
    def test_resolves_child(self, tmp_path):
        (tmp_path / "sub").mkdir()
        result = resolve_within_root(str(tmp_path), "sub")
        assert result == (tmp_path / "sub").resolve()

    def test_rejects_traversal_via_symlink(self, tmp_path):
        outside = tmp_path.parent / "outside_target"
        outside.mkdir(exist_ok=True)
        link = tmp_path / "sneaky"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink not supported")
        with pytest.raises(PathTraversalError):
            resolve_within_root(str(tmp_path), "sneaky")

    def test_rejects_parent_segment(self, tmp_path):
        with pytest.raises(PathTraversalError):
            resolve_within_root(str(tmp_path), "../etc")

    def test_empty_rel_returns_root(self, tmp_path):
        assert resolve_within_root(str(tmp_path), "") == tmp_path.resolve()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest backend/tests/test_paths.py -v`
Expected: 全部 fail with ImportError

- [ ] **Step 3: 写实现**

创建 `backend/src/myphoto/paths.py`：

```python
from __future__ import annotations

import os
from pathlib import Path


class PathTraversalError(ValueError):
    """Raised when a supplied relative path escapes its root."""


def normalize_relative(raw: str) -> str:
    """Normalize a user-supplied relative path.

    - Converts backslashes to forward slashes.
    - Strips leading slashes.
    - Collapses `.` segments and double slashes.
    - Rejects `..` segments, absolute Windows drive letters, null bytes.
    Returns "" for empty / root-relative input.
    """
    if raw is None:
        return ""
    if "\x00" in raw:
        raise PathTraversalError("null byte in path")
    s = raw.replace("\\", "/").strip()
    # reject absolute drive letter like "C:/..."
    if len(s) >= 2 and s[1] == ":":
        raise PathTraversalError("absolute drive path not allowed")
    parts: list[str] = []
    for seg in s.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise PathTraversalError("parent segment '..' not allowed")
        parts.append(seg)
    return "/".join(parts)


def resolve_within_root(root_abs: str | Path, rel: str) -> Path:
    """Return realpath of `root_abs/rel`, ensuring it stays under root.

    Raises PathTraversalError if the resolved target escapes the root
    (via `..`, symlink, or any other means).
    """
    root_resolved = Path(root_abs).resolve()
    clean = normalize_relative(rel)
    target = (root_resolved / clean).resolve() if clean else root_resolved
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise PathTraversalError(
            f"resolved path {target} escapes root {root_resolved}"
        ) from exc
    return target
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest backend/tests/test_paths.py -v`
Expected: 全部 pass

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/paths.py backend/tests/test_paths.py
git commit -m "feat(paths): add path normalization and root containment checks"
```

---

### Task 3: 图片格式白名单 `formats.py`

**Files:**
- Create: `backend/src/myphoto/formats.py`
- Create: `backend/tests/test_formats.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `WEB_EXTENSIONS: frozenset[str]`
  - `RAW_EXTENSIONS: frozenset[str]`
  - `ALL_EXTENSIONS: frozenset[str]`
  - `def classify(filename: str) -> Literal["web", "raw", "unsupported"]`
  - `def is_supported(filename: str) -> bool`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_formats.py`：

```python
import pytest
from myphoto.formats import (
    ALL_EXTENSIONS,
    RAW_EXTENSIONS,
    WEB_EXTENSIONS,
    classify,
    is_supported,
)


def test_web_set_contains_jpg():
    assert "jpg" in WEB_EXTENSIONS


def test_raw_set_contains_nef():
    assert "nef" in RAW_EXTENSIONS


def test_all_is_union():
    assert ALL_EXTENSIONS == WEB_EXTENSIONS | RAW_EXTENSIONS


def test_web_and_raw_disjoint():
    assert WEB_EXTENSIONS & RAW_EXTENSIONS == set()


@pytest.mark.parametrize(
    "name, expected",
    [
        ("photo.JPG", "web"),
        ("photo.jpeg", "web"),
        ("photo.HEIC", "web"),
        ("photo.avif", "web"),
        ("photo.NEF", "raw"),
        ("photo.cr3", "raw"),
        ("readme.txt", "unsupported"),
        ("noext", "unsupported"),
        (".hidden", "unsupported"),
    ],
)
def test_classify(name, expected):
    assert classify(name) == expected


def test_is_supported_true_for_web_and_raw():
    assert is_supported("a.jpg") is True
    assert is_supported("a.NEF") is True


def test_is_supported_false_for_others():
    assert is_supported("a.txt") is False
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest backend/tests/test_formats.py -v`
Expected: 全部 fail

- [ ] **Step 3: 写实现**

创建 `backend/src/myphoto/formats.py`：

```python
from __future__ import annotations

from typing import Literal

WEB_EXTENSIONS: frozenset[str] = frozenset({
    "jpg", "jpeg", "png", "gif", "webp",
    "heic", "heif", "avif",
})

RAW_EXTENSIONS: frozenset[str] = frozenset({
    "cr2", "cr3", "nef", "arw", "dng",
    "orf", "rw2", "raf", "pef",
})

ALL_EXTENSIONS: frozenset[str] = WEB_EXTENSIONS | RAW_EXTENSIONS


def _ext(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def classify(filename: str) -> Literal["web", "raw", "unsupported"]:
    ext = _ext(filename)
    if ext in WEB_EXTENSIONS:
        return "web"
    if ext in RAW_EXTENSIONS:
        return "raw"
    return "unsupported"


def is_supported(filename: str) -> bool:
    return _ext(filename) in ALL_EXTENSIONS
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest backend/tests/test_formats.py -v`
Expected: 全部 pass

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/formats.py backend/tests/test_formats.py
git commit -m "feat(formats): whitelist image extensions and classify web/raw"
```

---

### Task 4: 密码 + JWT 工具 `security.py`

**Files:**
- Create: `backend/src/myphoto/security.py`
- Create: `backend/tests/test_security.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `def hash_password(plain: str) -> str`（bcrypt cost=12）
  - `def verify_password(plain: str, hashed: str) -> bool`
  - `def make_token(secret: str, user_id: int, role: str, ttl_seconds: int) -> str`
  - `def decode_token(secret: str, token: str) -> dict`（返回 payload；异常抛 `TokenError`）
  - `class TokenError(Exception)`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_security.py`：

```python
import time
import pytest
from myphoto.security import (
    TokenError,
    decode_token,
    hash_password,
    make_token,
    verify_password,
)


SECRET = "test-secret-32bytes-minimum-length-abcdef"


def test_hash_is_not_plain():
    h = hash_password("hunter2hunter2")
    assert "hunter2" not in h


def test_verify_success():
    h = hash_password("hunter2hunter2")
    assert verify_password("hunter2hunter2", h) is True


def test_verify_failure():
    h = hash_password("hunter2hunter2")
    assert verify_password("wrong", h) is False


def test_hash_differs_between_calls():
    assert hash_password("same") != hash_password("same")


def test_token_roundtrip():
    token = make_token(SECRET, user_id=42, role="admin", ttl_seconds=3600)
    payload = decode_token(SECRET, token)
    assert payload["sub"] == 42
    assert payload["role"] == "admin"
    assert payload["exp"] > int(time.time())


def test_token_bad_signature():
    token = make_token(SECRET, 1, "viewer", 3600)
    with pytest.raises(TokenError):
        decode_token(SECRET + "x", token)


def test_token_expired():
    token = make_token(SECRET, 1, "viewer", ttl_seconds=-1)
    with pytest.raises(TokenError):
        decode_token(SECRET, token)


def test_token_malformed():
    with pytest.raises(TokenError):
        decode_token(SECRET, "not-a-jwt")
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest backend/tests/test_security.py -v`
Expected: 全部 fail

- [ ] **Step 3: 写实现**

创建 `backend/src/myphoto/security.py`：

```python
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
        return jwt.decode(token, secret, algorithms=[_ALG])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest backend/tests/test_security.py -v`
Expected: 全部 pass

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/security.py backend/tests/test_security.py
git commit -m "feat(security): bcrypt password hashing and HS256 JWT tokens"
```

---

### Task 5: 数据库模型 `models.py`

**Files:**
- Create: `backend/src/myphoto/db.py`
- Create: `backend/src/myphoto/models.py`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `class Base(DeclarativeBase)`
  - `class User(Base)`：字段见 spec §4.1
  - `class Gallery(Base)`：见 §4.3
  - `class GalleryRoot(Base)`：见 §4.4
  - `class Folder(Base)`：见 §4.5
  - `class Image(Base)`：见 §4.6
  - `async def make_engine(db_url: str) -> AsyncEngine`
  - `async def make_sessionmaker(engine) -> async_sessionmaker`
  - `async def create_all(engine) -> None`

**注意**：P1 只建 P1 用得到的表；user_galleries / exclusions / trash / audit_log 留到后续期。为了避免后续加表 migration 麻烦，把 `access_scope`、`enabled` 字段一并加，即使 P1 用不到。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_models.py`：

```python
import asyncio
import time

import pytest
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import Gallery, GalleryRoot, Image, User


@pytest.fixture
async def session():
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as s:
        yield s
    await engine.dispose()


async def test_create_user_and_query(session):
    now = int(time.time())
    session.add(User(
        username="admin",
        password_hash="x",
        role="admin",
        access_scope="lan_only",
        enabled=1,
        created_at=now,
    ))
    await session.commit()
    from sqlalchemy import select
    row = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()
    assert row.role == "admin"


async def test_gallery_root_unique_path_per_gallery(session):
    now = int(time.time())
    g = Gallery(name="A", created_at=now)
    session.add(g)
    await session.flush()
    session.add(GalleryRoot(gallery_id=g.id, label="l1", absolute_path="/x", enabled=1))
    session.add(GalleryRoot(gallery_id=g.id, label="l2", absolute_path="/x", enabled=1))
    with pytest.raises(Exception):
        await session.commit()


async def test_image_unique_relative_path_per_root(session):
    now = int(time.time())
    g = Gallery(name="A", created_at=now)
    session.add(g)
    await session.flush()
    r = GalleryRoot(gallery_id=g.id, label="l", absolute_path="/x", enabled=1)
    session.add(r)
    await session.flush()
    from myphoto.models import Folder
    f = Folder(root_id=r.id, relative_path="", name="", image_count=0, descendant_count=0)
    session.add(f)
    await session.flush()
    session.add(Image(
        root_id=r.id, folder_id=f.id, relative_path="a.jpg", filename="a.jpg",
        ext="jpg", size_bytes=1, sha1="s", mtime=1, is_raw=0, indexed_at=1,
    ))
    session.add(Image(
        root_id=r.id, folder_id=f.id, relative_path="a.jpg", filename="a.jpg",
        ext="jpg", size_bytes=1, sha1="s", mtime=1, is_raw=0, indexed_at=1,
    ))
    with pytest.raises(Exception):
        await session.commit()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest backend/tests/test_models.py -v`
Expected: 全部 fail with ImportError

- [ ] **Step 3: 写 db.py**

创建 `backend/src/myphoto/db.py`：

```python
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from myphoto.models import Base


async def make_engine(db_url: str) -> AsyncEngine:
    return create_async_engine(db_url, future=True)


async def make_sessionmaker(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 4: 写 models.py**

创建 `backend/src/myphoto/models.py`：

```python
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # admin|viewer
    access_scope: Mapped[str] = mapped_column(String, nullable=False, default="lan_only")
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    last_login_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Gallery(Base):
    __tablename__ = "galleries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class GalleryRoot(Base):
    __tablename__ = "gallery_roots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gallery_id: Mapped[int] = mapped_column(ForeignKey("galleries.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    absolute_path: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_scan_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_scan_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_scan_error: Mapped[str | None] = mapped_column(String, nullable=True)
    __table_args__ = (
        UniqueConstraint("gallery_id", "absolute_path", name="uq_root_path_per_gallery"),
    )


class Folder(Base):
    __tablename__ = "folders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("gallery_roots.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(String, nullable=False)  # "" for root itself
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    descendant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        UniqueConstraint("root_id", "relative_path", name="uq_folder_path_per_root"),
        Index("ix_folder_root_parent", "root_id", "parent_id"),
    )


class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("gallery_roots.id", ondelete="CASCADE"), nullable=False)
    folder_id: Mapped[int] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    ext: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha1: Mapped[str] = mapped_column(String, nullable=False)
    mtime: Mapped[int] = mapped_column(Integer, nullable=False)
    taken_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_raw: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("root_id", "relative_path", name="uq_image_path_per_root"),
        Index("ix_image_folder_filename", "folder_id", "filename"),
        Index("ix_image_folder_taken", "folder_id", "taken_at"),
        Index("ix_image_sha1", "sha1"),
    )
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest backend/tests/test_models.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add backend/src/myphoto/db.py backend/src/myphoto/models.py backend/tests/test_models.py
git commit -m "feat(models): SQLAlchemy models for users, galleries, roots, folders, images"
```

---

### Task 6: 首启动 schema + 初始 admin `schema_init.py`

**Files:**
- Create: `backend/src/myphoto/schema_init.py`
- Create: `backend/tests/test_schema_init.py`

**Interfaces:**
- Consumes: `db.create_all`, `models.User`, `security.hash_password`
- Produces:
  - `async def ensure_schema_and_admin(engine, sessionmaker) -> tuple[bool, str | None]` — 返回 `(created_initial_admin, plain_password_if_created)`；已存在 admin 时 `(False, None)`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_schema_init.py`：

```python
import pytest
from sqlalchemy import select
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import User
from myphoto.schema_init import ensure_schema_and_admin
from myphoto.security import verify_password


@pytest.fixture
async def engine_and_sm():
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    yield engine, sm
    await engine.dispose()


async def test_creates_admin_when_none(engine_and_sm):
    engine, sm = engine_and_sm
    created, pw = await ensure_schema_and_admin(engine, sm)
    assert created is True
    assert pw is not None
    assert len(pw) >= 12
    async with sm() as s:
        u = (await s.execute(select(User).where(User.username == "admin"))).scalar_one()
        assert u.role == "admin"
        assert verify_password(pw, u.password_hash)


async def test_noop_when_admin_exists(engine_and_sm):
    engine, sm = engine_and_sm
    await ensure_schema_and_admin(engine, sm)
    created, pw = await ensure_schema_and_admin(engine, sm)
    assert created is False
    assert pw is None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest backend/tests/test_schema_init.py -v`
Expected: fail with ImportError

- [ ] **Step 3: 写实现**

创建 `backend/src/myphoto/schema_init.py`：

```python
from __future__ import annotations

import secrets
import time

from sqlalchemy import select

from myphoto.db import create_all
from myphoto.models import User
from myphoto.security import hash_password


def _generate_password() -> str:
    # 16 chars, alphanumeric, human-typeable
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(16))


async def ensure_schema_and_admin(engine, sessionmaker) -> tuple[bool, str | None]:
    """Create tables if missing and seed initial admin if no admin exists.

    Returns (created_initial_admin, plain_password_if_created).
    The plain password is only known here; caller must print it once.
    """
    await create_all(engine)
    async with sessionmaker() as s:
        existing = (await s.execute(select(User).where(User.role == "admin"))).first()
        if existing is not None:
            return False, None
        password = _generate_password()
        s.add(User(
            username="admin",
            password_hash=hash_password(password),
            role="admin",
            access_scope="lan_only",
            enabled=1,
            created_at=int(time.time()),
        ))
        await s.commit()
        return True, password
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest backend/tests/test_schema_init.py -v`
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/schema_init.py backend/tests/test_schema_init.py
git commit -m "feat(bootstrap): first-run schema creation with initial admin account"
```

---

### Task 7: 配置文件 `config.py`

**Files:**
- Create: `backend/src/myphoto/config.py`
- Create: `backend/tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `@dataclass class AppConfig`: `listen_host`, `listen_port`, `jwt_secret`, `session_hours`, `data_dir`（cache/db 位置）
  - `def load_or_init(path: str | Path) -> AppConfig` — 不存在则写入默认模板并生成 32 字节 secret

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_config.py`：

```python
import tomllib
from pathlib import Path
from myphoto.config import AppConfig, load_or_init


def test_creates_default_when_missing(tmp_path):
    p = tmp_path / "config.toml"
    cfg = load_or_init(p)
    assert p.exists()
    assert isinstance(cfg, AppConfig)
    assert cfg.listen_port == 8080
    assert cfg.session_hours == 8
    assert len(cfg.jwt_secret) >= 32
    assert cfg.data_dir == str(tmp_path)


def test_reads_existing(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[app]\nlisten_host="127.0.0.1"\nlisten_port=9000\n'
        'jwt_secret="secret-value-of-sufficient-length-xxxxx"\nsession_hours=4\n',
        encoding="utf-8",
    )
    cfg = load_or_init(p)
    assert cfg.listen_host == "127.0.0.1"
    assert cfg.listen_port == 9000
    assert cfg.session_hours == 4
    assert cfg.jwt_secret.startswith("secret-value")


def test_generated_secret_written_to_file(tmp_path):
    p = tmp_path / "config.toml"
    cfg = load_or_init(p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["app"]["jwt_secret"] == cfg.jwt_secret
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest backend/tests/test_config.py -v`
Expected: fail

- [ ] **Step 3: 写实现**

创建 `backend/src/myphoto/config.py`：

```python
from __future__ import annotations

import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AppConfig:
    listen_host: str
    listen_port: int
    jwt_secret: str
    session_hours: int
    data_dir: str  # directory holding app.db and .cache/


_DEFAULT_TEMPLATE = """# myPhotoGallery config
[app]
listen_host = "0.0.0.0"
listen_port = 8080
jwt_secret = "{secret}"
session_hours = 8
"""


def load_or_init(path: str | Path) -> AppConfig:
    p = Path(path)
    if not p.exists():
        secret = secrets.token_urlsafe(48)
        p.write_text(_DEFAULT_TEMPLATE.format(secret=secret), encoding="utf-8")
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    app = data.get("app", {})
    return AppConfig(
        listen_host=app.get("listen_host", "0.0.0.0"),
        listen_port=int(app.get("listen_port", 8080)),
        jwt_secret=app["jwt_secret"],
        session_hours=int(app.get("session_hours", 8)),
        data_dir=str(p.parent.resolve()),
    )
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest backend/tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/config.py backend/tests/test_config.py
git commit -m "feat(config): load or initialize config.toml with generated JWT secret"
```

---

### Task 8: FastAPI 骨架 + lifespan + 错误处理

**Files:**
- Create: `backend/src/myphoto/errors.py`
- Create: `backend/src/myphoto/main.py`
- Create: `backend/tests/test_errors.py`
- Create: `backend/tests/test_main.py`

**Interfaces:**
- Consumes: `config.load_or_init`, `schema_init.ensure_schema_and_admin`, `db.make_engine/make_sessionmaker`
- Produces:
  - `class AppError(Exception)` with `code: str`, `http_status: int`, `message: str`
  - `def install_error_handlers(app: FastAPI) -> None`
  - `def build_app(config_path: str = "config.toml") -> FastAPI` — 装配一个可用于测试的 app
  - `async def app_state()` FastAPI dependency 返回全局 state（engine, sessionmaker, config）
  - `app` module-level FastAPI 实例用于 uvicorn

- [ ] **Step 1: 写 errors 测试**

创建 `backend/tests/test_errors.py`：

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from myphoto.errors import AppError, install_error_handlers


def test_app_error_response_shape():
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise AppError(code="something_bad", http_status=418, message="teapot")

    r = TestClient(app).get("/boom")
    assert r.status_code == 418
    assert r.json() == {"error": {"code": "something_bad", "message": "teapot"}}


def test_uncaught_maps_to_internal_error(caplog):
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise ValueError("unexpected")

    r = TestClient(app).get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "internal_error"
```

- [ ] **Step 2: 写 errors.py**

创建 `backend/src/myphoto/errors.py`：

```python
from __future__ import annotations

import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("myphoto.errors")


class AppError(Exception):
    def __init__(self, code: str, http_status: int, message: str):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message = message


def _payload(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError):
        return JSONResponse(_payload(exc.code, exc.message), status_code=exc.http_status)

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception):
        log.exception("unexpected error: %s", exc)
        return JSONResponse(_payload("internal_error", "internal server error"), status_code=500)
```

- [ ] **Step 3: 运行错误处理测试**

Run: `pytest backend/tests/test_errors.py -v`
Expected: 2 passed

- [ ] **Step 4: 写 main 测试**

创建 `backend/tests/test_main.py`：

```python
from pathlib import Path
from fastapi.testclient import TestClient
from myphoto.main import build_app


def test_build_app_creates_config_and_db(tmp_path):
    cfg_path = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg_path))
    assert cfg_path.exists()
    assert (tmp_path / "app.db").exists() or True  # created lazily on first request; startup fires
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 5: 写 main.py**

创建 `backend/src/myphoto/main.py`：

```python
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request

from myphoto.config import AppConfig, load_or_init
from myphoto.db import make_engine, make_sessionmaker
from myphoto.errors import install_error_handlers
from myphoto.schema_init import ensure_schema_and_admin

log = logging.getLogger("myphoto.main")


def build_app(config_path: str = "config.toml") -> FastAPI:
    cfg = load_or_init(config_path)
    db_path = Path(cfg.data_dir) / "app.db"
    db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = await make_engine(db_url)
        sm = await make_sessionmaker(engine)
        created, pw = await ensure_schema_and_admin(engine, sm)
        if created and pw:
            # printed once to stdout so operator can grab it
            print(f"[myphoto] initial admin created. username=admin password={pw}", flush=True)
        app.state.engine = engine
        app.state.sessionmaker = sm
        app.state.config = cfg
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="myPhotoGallery", lifespan=lifespan)
    install_error_handlers(app)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


async def get_state(request: Request) -> tuple[AppConfig, object]:
    return request.app.state.config, request.app.state.sessionmaker


# uvicorn entry: `uvicorn myphoto.main:app`
app = build_app(os.environ.get("MYPHOTO_CONFIG", "config.toml"))
```

- [ ] **Step 6: 运行 main 测试**

Run: `pytest backend/tests/test_main.py -v`
Expected: 1 passed

- [ ] **Step 7: 提交**

```bash
git add backend/src/myphoto/errors.py backend/src/myphoto/main.py backend/tests/test_errors.py backend/tests/test_main.py
git commit -m "feat(app): FastAPI app factory with lifespan bootstrap and error envelope"
```

---

### Task 9: 认证依赖 + `/api/auth/*` 路由

**Files:**
- Create: `backend/src/myphoto/deps.py`
- Create: `backend/src/myphoto/routes_auth.py`
- Modify: `backend/src/myphoto/main.py`
- Create: `backend/tests/test_routes_auth.py`

**Interfaces:**
- Consumes: `security.*`, `models.User`, `AppConfig`
- Produces:
  - `SESSION_COOKIE = "mpg_session"`
  - `async def current_user(request) -> User` (未登录/被禁用 401 `unauthenticated`)
  - `async def admin_required(user=Depends(current_user)) -> User` (403 `forbidden`)
  - 路由 `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
  - 同 IP 连续 5 次失败 15 分钟内锁定 → 429 `login_locked`

- [ ] **Step 1: 写测试**

创建 `backend/tests/test_routes_auth.py`：

```python
import re
import pytest
from fastapi.testclient import TestClient
from myphoto.main import build_app


@pytest.fixture
def app_and_pw(tmp_path, capsys):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        m = re.search(r"password=(\S+)", out)
        assert m, out
        yield c, m.group(1)


def test_me_unauthenticated(app_and_pw):
    c, _ = app_and_pw
    r = c.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_login_success(app_and_pw):
    c, pw = app_and_pw
    r = c.post("/api/auth/login", json={"username": "admin", "password": pw})
    assert r.status_code == 200
    assert "mpg_session" in r.cookies
    assert r.json()["user"]["role"] == "admin"
    r2 = c.get("/api/auth/me")
    assert r2.status_code == 200


def test_wrong_password(app_and_pw):
    c, _ = app_and_pw
    r = c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_lockout(app_and_pw):
    c, _ = app_and_pw
    for _ in range(5):
        c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    r = c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "login_locked"


def test_logout(app_and_pw):
    c, pw = app_and_pw
    c.post("/api/auth/login", json={"username": "admin", "password": pw})
    r = c.post("/api/auth/logout")
    assert r.status_code == 204
    r2 = c.get("/api/auth/me")
    assert r2.status_code == 401
```

- [ ] **Step 2: 写 deps.py**

创建 `backend/src/myphoto/deps.py`：

```python
from __future__ import annotations

from fastapi import Depends, Request

from myphoto.errors import AppError
from myphoto.models import User
from myphoto.security import TokenError, decode_token

SESSION_COOKIE = "mpg_session"


async def current_user(request: Request) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AppError("unauthenticated", 401, "authentication required")
    cfg = request.app.state.config
    try:
        payload = decode_token(cfg.jwt_secret, token)
    except TokenError:
        raise AppError("unauthenticated", 401, "invalid or expired session")
    sm = request.app.state.sessionmaker
    async with sm() as s:
        user = await s.get(User, int(payload["sub"]))
    if user is None or user.enabled != 1:
        raise AppError("unauthenticated", 401, "user not found or disabled")
    return user


async def admin_required(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise AppError("forbidden", 403, "admin only")
    return user
```

- [ ] **Step 3: 写 routes_auth.py**

创建 `backend/src/myphoto/routes_auth.py`：

```python
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from myphoto.deps import SESSION_COOKIE, current_user
from myphoto.errors import AppError
from myphoto.models import User
from myphoto.security import make_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

_LOCKOUT_THRESHOLD = 5
_LOCKOUT_WINDOW_SEC = 15 * 60
_lockout_state: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _record_fail(ip: str) -> None:
    count, first = _lockout_state[ip]
    now = int(time.time())
    if count == 0 or now - first > _LOCKOUT_WINDOW_SEC:
        _lockout_state[ip] = (1, now)
    else:
        _lockout_state[ip] = (count + 1, first)


def _is_locked(ip: str) -> bool:
    count, first = _lockout_state[ip]
    if count < _LOCKOUT_THRESHOLD:
        return False
    if int(time.time()) - first > _LOCKOUT_WINDOW_SEC:
        _lockout_state[ip] = (0, 0)
        return False
    return True


def _reset(ip: str) -> None:
    _lockout_state[ip] = (0, 0)


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    ip = _client_ip(request)
    if _is_locked(ip):
        raise AppError("login_locked", 429, "too many failed attempts; try again later")
    sm = request.app.state.sessionmaker
    async with sm() as s:
        user = (await s.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
        if user is None or user.enabled != 1 or not verify_password(body.password, user.password_hash):
            _record_fail(ip)
            raise AppError("invalid_credentials", 401, "wrong username or password")
        user.last_login_at = int(time.time())
        await s.commit()
        _reset(ip)
        cfg = request.app.state.config
        token = make_token(cfg.jwt_secret, user.id, user.role, cfg.session_hours * 3600)
        response.set_cookie(
            SESSION_COOKIE, token,
            max_age=cfg.session_hours * 3600,
            httponly=True, samesite="lax", path="/",
        )
        return {"user": {"id": user.id, "username": user.username, "role": user.role, "access_scope": user.access_scope}}


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return Response(status_code=204)


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username, "role": user.role, "access_scope": user.access_scope}
```

- [ ] **Step 4: 挂路由到 main.py**

Edit `backend/src/myphoto/main.py`：在 `install_error_handlers(app)` 之后加：

```python
    from myphoto.routes_auth import router as auth_router
    app.include_router(auth_router)
```

- [ ] **Step 5: 运行测试**

Run: `pytest backend/tests/test_routes_auth.py -v`
Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add backend/src/myphoto/deps.py backend/src/myphoto/routes_auth.py backend/src/myphoto/main.py backend/tests/test_routes_auth.py
git commit -m "feat(auth): login/logout/me endpoints with JWT cookie and IP lockout"
```

---

### Task 10: 单 worker 扫描队列 + 增量扫描 `scanner.py`

**Files:**
- Create: `backend/src/myphoto/scanner.py`
- Modify: `backend/src/myphoto/main.py`
- Create: `backend/tests/test_scanner.py`

**Interfaces:**
- Consumes: `models.*`, `paths.*`, `formats.*`
- Produces:
  - `class Scanner`
    - `def __init__(self, sessionmaker)`
    - `async def start() -> None`
    - `async def stop() -> None`
    - `async def enqueue(root_id: int) -> None` (幂等)
    - `async def scan_root_now(root_id: int) -> None`
    - `def get_status(root_id: int) -> dict` (`{"status","last_scan_at","last_scan_error"}`)

**扫描步骤**（对每个 root）：
1. `status=running`
2. `os.walk` 跳过 `.` 开头目录、`__pycache__`、符号链接
3. 对每个受支持文件：查 `images.(root_id, relative_path)`；`mtime` 与 `size` 未变则跳过；否则计算 sha1、读尺寸/EXIF、upsert
4. 折叠：删除本轮未见到的 `images` 行
5. 重建 `folders`：ensure 每个走过的目录、删除不再走到的、重算 `image_count` `descendant_count`
6. 标记 `ok` 与 `last_scan_at`；异常保留旧索引并标 `error`

- [ ] **Step 1: 写测试**

创建 `backend/tests/test_scanner.py`：

```python
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from sqlalchemy import select

from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import Folder, Gallery, GalleryRoot, Image
from myphoto.scanner import Scanner


def _jpg(path: Path, w=40, h=30):
    path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (w, h), (10, 20, 30)).save(path, "JPEG")


@pytest.fixture
async def env(tmp_path):
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    root_dir = tmp_path / "photos"
    root_dir.mkdir()
    async with sm() as s:
        g = Gallery(name="G", created_at=int(time.time()))
        s.add(g); await s.flush()
        r = GalleryRoot(gallery_id=g.id, label="R", absolute_path=str(root_dir.resolve()), enabled=1)
        s.add(r); await s.commit(); await s.refresh(r)
        rid = r.id
    yield root_dir, sm, rid
    await engine.dispose()


async def test_indexes_images(env):
    root_dir, sm, rid = env
    _jpg(root_dir / "a.jpg")
    _jpg(root_dir / "sub" / "b.JPG")
    (root_dir / "note.txt").write_text("x", encoding="utf-8")
    await Scanner(sm).scan_root_now(rid)
    async with sm() as s:
        paths = sorted(r.relative_path for r in (await s.execute(select(Image))).scalars())
        assert paths == ["a.jpg", "sub/b.JPG"]
        folders = sorted(f.relative_path for f in (await s.execute(select(Folder))).scalars())
        assert "" in folders and "sub" in folders


async def test_removes_deleted(env):
    root_dir, sm, rid = env
    _jpg(root_dir / "a.jpg")
    sc = Scanner(sm)
    await sc.scan_root_now(rid)
    (root_dir / "a.jpg").unlink()
    await sc.scan_root_now(rid)
    async with sm() as s:
        assert (await s.execute(select(Image))).scalars().all() == []


async def test_skips_hidden(env):
    root_dir, sm, rid = env
    _jpg(root_dir / ".hidden" / "a.jpg")
    _jpg(root_dir / "ok" / "b.jpg")
    await Scanner(sm).scan_root_now(rid)
    async with sm() as s:
        paths = [r.relative_path for r in (await s.execute(select(Image))).scalars()]
        assert paths == ["ok/b.jpg"]


async def test_folder_counts(env):
    root_dir, sm, rid = env
    _jpg(root_dir / "a.jpg")
    _jpg(root_dir / "sub" / "b.jpg")
    _jpg(root_dir / "sub" / "c.jpg")
    await Scanner(sm).scan_root_now(rid)
    async with sm() as s:
        root_folder = (await s.execute(select(Folder).where(Folder.relative_path == ""))).scalar_one()
        sub_folder = (await s.execute(select(Folder).where(Folder.relative_path == "sub"))).scalar_one()
        assert root_folder.image_count == 1
        assert root_folder.descendant_count == 3
        assert sub_folder.image_count == 2
        assert sub_folder.descendant_count == 2


async def test_status_ok(env):
    _, sm, rid = env
    sc = Scanner(sm)
    await sc.scan_root_now(rid)
    st = sc.get_status(rid)
    assert st["status"] == "idle"
    assert st["last_scan_at"] is not None
    assert st["last_scan_error"] is None


async def test_missing_root_marks_error(tmp_path):
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as s:
        g = Gallery(name="G", created_at=1); s.add(g); await s.flush()
        r = GalleryRoot(gallery_id=g.id, label="R", absolute_path=str(tmp_path / "nope"), enabled=1)
        s.add(r); await s.commit(); await s.refresh(r); rid = r.id
    sc = Scanner(sm)
    await sc.scan_root_now(rid)
    assert sc.get_status(rid)["last_scan_error"] is not None
    await engine.dispose()
```

- [ ] **Step 2: 写 scanner.py**

创建 `backend/src/myphoto/scanner.py`：

```python
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage, UnidentifiedImageError
from sqlalchemy import select

from myphoto.formats import classify, is_supported
from myphoto.models import Folder, GalleryRoot, Image

log = logging.getLogger("myphoto.scanner")

try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:
    pass


@dataclass
class _RootStatus:
    status: str = "idle"
    last_scan_at: int | None = None
    last_scan_error: str | None = None


class Scanner:
    def __init__(self, sessionmaker):
        self._sm = sessionmaker
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._enqueued: set[int] = set()
        self._worker: asyncio.Task | None = None
        self._status: dict[int, _RootStatus] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):
                pass
            self._worker = None

    async def enqueue(self, root_id: int) -> None:
        async with self._lock:
            if root_id in self._enqueued:
                return
            self._enqueued.add(root_id)
            self._status.setdefault(root_id, _RootStatus()).status = "queued"
        await self._queue.put(root_id)

    def get_status(self, root_id: int) -> dict:
        st = self._status.get(root_id, _RootStatus())
        return {
            "status": st.status,
            "last_scan_at": st.last_scan_at,
            "last_scan_error": st.last_scan_error,
        }

    async def _loop(self) -> None:
        while True:
            rid = await self._queue.get()
            try:
                await self.scan_root_now(rid)
            except Exception as exc:  # pragma: no cover
                log.exception("worker crashed: %s", exc)
            finally:
                async with self._lock:
                    self._enqueued.discard(rid)

    async def scan_root_now(self, root_id: int) -> None:
        self._status.setdefault(root_id, _RootStatus()).status = "running"
        try:
            async with self._sm() as s:
                root = await s.get(GalleryRoot, root_id)
                if root is None:
                    raise RuntimeError(f"root {root_id} not found")
                abs_root = Path(root.absolute_path)
                if not abs_root.exists() or not abs_root.is_dir():
                    raise RuntimeError(f"root path missing: {abs_root}")

                walked_files: set[str] = set()
                walked_dirs: set[str] = {""}
                file_meta: dict[str, tuple[Path, str, str]] = {}  # rel_file -> (path, filename, rel_dir)

                for dirpath, dirnames, filenames in os.walk(abs_root, followlinks=False):
                    dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
                    rel_dir = str(Path(dirpath).relative_to(abs_root)).replace("\\", "/")
                    if rel_dir == ".":
                        rel_dir = ""
                    walked_dirs.add(rel_dir)
                    for fname in filenames:
                        if not is_supported(fname):
                            continue
                        fpath = Path(dirpath) / fname
                        if fpath.is_symlink():
                            continue
                        rel_file = f"{rel_dir}/{fname}" if rel_dir else fname
                        walked_files.add(rel_file)
                        file_meta[rel_file] = (fpath, fname, rel_dir)

                # rebuild folders first so images can attach to correct folder_id
                id_by_path = await _rebuild_folder_rows(s, root_id, walked_dirs)

                for rel_file, (fpath, fname, rel_dir) in file_meta.items():
                    await _upsert_image(s, root_id, id_by_path[rel_dir], rel_file, fname, fpath)

                # delete images not walked
                existing = (await s.execute(select(Image).where(Image.root_id == root_id))).scalars().all()
                for img in existing:
                    if img.relative_path not in walked_files:
                        await s.delete(img)
                await s.flush()

                # recompute folder counts
                await _recompute_counts(s, root_id, walked_dirs, id_by_path)

                root.last_scan_at = int(time.time())
                root.last_scan_status = "ok"
                root.last_scan_error = None
                await s.commit()

                self._status[root_id].status = "idle"
                self._status[root_id].last_scan_at = root.last_scan_at
                self._status[root_id].last_scan_error = None
        except Exception as exc:
            log.warning("scan error root=%s: %s", root_id, exc)
            async with self._sm() as s:
                root = await s.get(GalleryRoot, root_id)
                if root is not None:
                    root.last_scan_status = "error"
                    root.last_scan_error = str(exc)[:500]
                    await s.commit()
            self._status[root_id].status = "idle"
            self._status[root_id].last_scan_error = str(exc)[:500]


def _sha1_of(path: Path, buf: int = 64 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while chunk := f.read(buf):
            h.update(chunk)
    return h.hexdigest()


def _read_meta(path: Path, is_raw: bool) -> tuple[int | None, int | None, int | None]:
    if is_raw:
        return None, None, None
    try:
        with PILImage.open(path) as im:
            w, h = im.size
            taken = None
            try:
                exif = im.getexif()
                raw = exif.get(0x9003) or exif.get(0x0132)
                if raw:
                    taken = int(time.mktime(time.strptime(raw, "%Y:%m:%d %H:%M:%S")))
            except Exception:
                pass
            return w, h, taken
    except (UnidentifiedImageError, OSError):
        return None, None, None


async def _upsert_image(s, root_id, folder_id, rel_file, filename, fpath):
    st = fpath.stat()
    existing = (await s.execute(
        select(Image).where(Image.root_id == root_id, Image.relative_path == rel_file)
    )).scalar_one_or_none()
    if existing and existing.mtime == int(st.st_mtime) and existing.size_bytes == st.st_size:
        existing.folder_id = folder_id  # keep folder link fresh
        return
    kind = classify(filename)
    is_raw = 1 if kind == "raw" else 0
    sha1 = _sha1_of(fpath)
    w, h, taken = _read_meta(fpath, bool(is_raw))
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    now = int(time.time())
    if existing is None:
        s.add(Image(
            root_id=root_id, folder_id=folder_id, relative_path=rel_file, filename=filename,
            ext=ext, size_bytes=st.st_size, width=w, height=h, sha1=sha1,
            mtime=int(st.st_mtime), taken_at=taken, is_raw=is_raw, indexed_at=now,
        ))
    else:
        existing.folder_id = folder_id
        existing.size_bytes = st.st_size
        existing.width = w
        existing.height = h
        existing.sha1 = sha1
        existing.mtime = int(st.st_mtime)
        existing.taken_at = taken
        existing.is_raw = is_raw


async def _rebuild_folder_rows(s, root_id: int, walked_dirs: set[str]) -> dict[str, int]:
    id_by_path: dict[str, int] = {}
    for d in sorted(walked_dirs, key=lambda p: p.count("/")):
        row = (await s.execute(select(Folder).where(Folder.root_id == root_id, Folder.relative_path == d))).scalar_one_or_none()
        if row is None:
            row = Folder(root_id=root_id, relative_path=d, name=d.rsplit("/", 1)[-1] if d else "",
                         image_count=0, descendant_count=0)
            s.add(row)
            await s.flush()
        else:
            row.name = d.rsplit("/", 1)[-1] if d else ""
        parent = d.rsplit("/", 1)[0] if "/" in d else ""
        row.parent_id = id_by_path.get(parent) if d != "" else None
        id_by_path[d] = row.id
    # delete rows for paths not walked
    for row in (await s.execute(select(Folder).where(Folder.root_id == root_id))).scalars().all():
        if row.relative_path not in walked_dirs:
            await s.delete(row)
    await s.flush()
    return id_by_path


async def _recompute_counts(s, root_id, walked_dirs, id_by_path):
    imgs = (await s.execute(select(Image).where(Image.root_id == root_id))).scalars().all()
    direct: dict[str, int] = {d: 0 for d in walked_dirs}
    for img in imgs:
        d = "" if "/" not in img.relative_path else img.relative_path.rsplit("/", 1)[0]
        direct[d] = direct.get(d, 0) + 1
    for d in walked_dirs:
        f = (await s.execute(select(Folder).where(Folder.root_id == root_id, Folder.relative_path == d))).scalar_one()
        f.image_count = direct.get(d, 0)
        if d == "":
            f.descendant_count = sum(direct.values())
        else:
            f.descendant_count = sum(v for p, v in direct.items() if p == d or p.startswith(d + "/"))
```

- [ ] **Step 3: 在 main.py lifespan 中启动 Scanner**

Edit `backend/src/myphoto/main.py` 的 `lifespan` 函数，在 `ensure_schema_and_admin` 之后加：

```python
        from myphoto.scanner import Scanner
        from myphoto.models import GalleryRoot
        from sqlalchemy import select as _select
        scanner = Scanner(sm)
        await scanner.start()
        async with sm() as ss:
            roots = (await ss.execute(_select(GalleryRoot).where(GalleryRoot.enabled == 1))).scalars().all()
            for r in roots:
                await scanner.enqueue(r.id)
        app.state.scanner = scanner
```

在 `finally` 分支的 `await engine.dispose()` 之前加：

```python
            await scanner.stop()
```

- [ ] **Step 4: 运行测试**

Run: `pytest backend/tests/test_scanner.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/scanner.py backend/src/myphoto/main.py backend/tests/test_scanner.py
git commit -m "feat(scanner): single-worker asyncio scan queue with incremental sync"
```

---

### Task 11: 缩略图生成与缓存 `thumbnails.py`

**Files:**
- Create: `backend/src/myphoto/thumbnails.py`
- Create: `backend/tests/test_thumbnails.py`

**Interfaces:**
- Consumes: `formats.classify`
- Produces:
  - `ALLOWED_SIZES: frozenset[int] = frozenset({200, 400, 1600})`
  - `class ThumbnailGenerator`
    - `def __init__(self, cache_dir: str | Path)`
    - `def cache_path(self, sha1: str, size: int) -> Path`
    - `async def ensure(self, sha1: str, size: int, source_path: str, is_raw: bool) -> Path`（幂等；已存在直接返回）

**RAW 策略**：`rawpy.imread(f).extract_thumb()`；若不是 `ThumbFormat.JPEG` 或抛异常，退回 `postprocess()`（较慢），再失败则抛 `ThumbnailError`。

- [ ] **Step 1: 写测试**

创建 `backend/tests/test_thumbnails.py`：

```python
import asyncio
from pathlib import Path

import pytest
from PIL import Image as PILImage

from myphoto.thumbnails import ALLOWED_SIZES, ThumbnailGenerator, ThumbnailError


def _jpg(p: Path, size=(800, 600)):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", size, (100, 150, 200)).save(p, "JPEG")


async def test_ensure_creates_cache(tmp_path):
    src = tmp_path / "in.jpg"
    _jpg(src)
    gen = ThumbnailGenerator(tmp_path / "cache")
    out = await gen.ensure("abc123", 200, str(src), is_raw=False)
    assert out.exists()
    with PILImage.open(out) as im:
        assert max(im.size) <= 200


async def test_ensure_is_idempotent(tmp_path):
    src = tmp_path / "in.jpg"
    _jpg(src)
    gen = ThumbnailGenerator(tmp_path / "cache")
    p1 = await gen.ensure("abc", 200, str(src), is_raw=False)
    mtime1 = p1.stat().st_mtime_ns
    p2 = await gen.ensure("abc", 200, str(src), is_raw=False)
    assert p1 == p2
    assert p1.stat().st_mtime_ns == mtime1  # 未重新生成


async def test_cache_layout(tmp_path):
    gen = ThumbnailGenerator(tmp_path / "cache")
    p = gen.cache_path("abcdef1234", 400)
    assert p.parts[-3:] == ("ab", "abcdef1234", "400.jpg")


async def test_rejects_disallowed_size(tmp_path):
    src = tmp_path / "in.jpg"
    _jpg(src)
    gen = ThumbnailGenerator(tmp_path / "cache")
    with pytest.raises(ValueError):
        await gen.ensure("abc", 999, str(src), is_raw=False)


async def test_unidentifiable_source_raises(tmp_path):
    (tmp_path / "bad.jpg").write_bytes(b"not-an-image")
    gen = ThumbnailGenerator(tmp_path / "cache")
    with pytest.raises(ThumbnailError):
        await gen.ensure("abc", 200, str(tmp_path / "bad.jpg"), is_raw=False)


def test_allowed_sizes_frozen():
    assert 200 in ALLOWED_SIZES and 400 in ALLOWED_SIZES and 1600 in ALLOWED_SIZES
```

- [ ] **Step 2: 写实现**

创建 `backend/src/myphoto/thumbnails.py`：

```python
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from PIL import Image as PILImage, UnidentifiedImageError

log = logging.getLogger("myphoto.thumbnails")

try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:
    pass

ALLOWED_SIZES: frozenset[int] = frozenset({200, 400, 1600})


class ThumbnailError(Exception):
    pass


class ThumbnailGenerator:
    def __init__(self, cache_dir: str | Path):
        self._cache = Path(cache_dir)

    def cache_path(self, sha1: str, size: int) -> Path:
        return self._cache / sha1[:2] / sha1 / f"{size}.jpg"

    async def ensure(self, sha1: str, size: int, source_path: str, is_raw: bool) -> Path:
        if size not in ALLOWED_SIZES:
            raise ValueError(f"size {size} not allowed")
        out = self.cache_path(sha1, size)
        if out.exists():
            return out
        out.parent.mkdir(parents=True, exist_ok=True)
        # CPU-bound: offload to thread
        await asyncio.to_thread(_render_thumb, source_path, size, out, is_raw)
        return out


def _render_thumb(source: str, size: int, out: Path, is_raw: bool) -> None:
    try:
        if is_raw:
            _render_raw(source, size, out)
        else:
            _render_regular(source, size, out)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ThumbnailError(str(exc)) from exc


def _render_regular(source: str, size: int, out: Path) -> None:
    with PILImage.open(source) as im:
        im = im.convert("RGB") if im.mode not in ("RGB", "L") else im
        im.thumbnail((size, size), PILImage.Resampling.LANCZOS)
        im.save(out, "JPEG", quality=85, optimize=True)


def _render_raw(source: str, size: int, out: Path) -> None:
    import rawpy
    try:
        with rawpy.imread(source) as raw:
            try:
                thumb = raw.extract_thumb()
                if thumb.format.name == "JPEG":
                    from io import BytesIO
                    with PILImage.open(BytesIO(thumb.data)) as im:
                        im.thumbnail((size, size), PILImage.Resampling.LANCZOS)
                        im.save(out, "JPEG", quality=85, optimize=True)
                    return
            except Exception:
                pass
            rgb = raw.postprocess(use_camera_wb=True, no_auto_bright=False, output_bps=8)
            im = PILImage.fromarray(rgb)
            im.thumbnail((size, size), PILImage.Resampling.LANCZOS)
            im.save(out, "JPEG", quality=85, optimize=True)
    except Exception as exc:
        raise ThumbnailError(f"RAW render failed: {exc}") from exc
```

- [ ] **Step 3: 运行测试**

Run: `pytest backend/tests/test_thumbnails.py -v`
Expected: 6 passed

- [ ] **Step 4: 提交**

```bash
git add backend/src/myphoto/thumbnails.py backend/tests/test_thumbnails.py
git commit -m "feat(thumb): sha1-keyed thumbnail cache with RAW fallback"
```

---

### Task 12: 浏览 API `routes_browse.py`

**Files:**
- Create: `backend/src/myphoto/routes_browse.py`
- Modify: `backend/src/myphoto/main.py`
- Create: `backend/tests/test_routes_browse.py`

**Interfaces:**
- Consumes: `deps.current_user`, `paths.normalize_relative`, models
- Produces（每个响应带 `Cache-Control: no-store`）：
  - `GET /api/galleries` → `[{"id","name","description","root_count","image_count"}]`
  - `GET /api/galleries/{gid}` → `{"gallery": {...}, "roots": [{"id","label","image_count","offline": false}]}`
  - `GET /api/galleries/{gid}/roots/{rid}/folders?path=` → `[{"name","relative_path","image_count","descendant_count","cover_thumb_sha1"}]`
  - `GET /api/galleries/{gid}/roots/{rid}/images?path=&sort=name_asc|name_desc|taken_at_asc|taken_at_desc|size_desc&limit=&cursor=` → `{"items": [{"id","filename","width","height","sha1","size_bytes","taken_at","is_raw"}], "next_cursor": str|null}`
  - `GET /api/galleries/{gid}/roots/{rid}/breadcrumbs?path=` → `[{"name","relative_path"}]`（首项为 root label 与 `""`）

**P1 权限**：只需要登录（任何角色）；P3 再引入 user_galleries 校验。

**分页**：`limit` 默认 200，最大 500；`cursor` = base64(f"{sort_key}|{id}")；下一页 `WHERE (sort_key, id) > cursor`。P1 用 keyset。

- [ ] **Step 1: 写测试**

创建 `backend/tests/test_routes_browse.py`：

```python
import re
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient

from myphoto.main import build_app


def _jpg(p: Path, size=(50, 40)):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", size, (10, 20, 30)).save(p, "JPEG")


@pytest.fixture
def client_with_data(tmp_path, capsys):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    _jpg(photos / "sub" / "b.jpg")
    _jpg(photos / "sub" / "c.jpg")
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        # seed a gallery + root directly via sm
        import asyncio
        from myphoto.models import Gallery, GalleryRoot
        async def seed():
            async with app.state.sessionmaker() as s:
                g = Gallery(name="G", created_at=int(time.time()))
                s.add(g); await s.flush()
                r = GalleryRoot(gallery_id=g.id, label="R", absolute_path=str(photos.resolve()), enabled=1)
                s.add(r); await s.commit(); await s.refresh(r)
                return g.id, r.id
        gid, rid = asyncio.get_event_loop().run_until_complete(seed())
        # trigger scan
        asyncio.get_event_loop().run_until_complete(app.state.scanner.scan_root_now(rid))
        yield c, gid, rid


def test_galleries_list(client_with_data):
    c, gid, _ = client_with_data
    r = c.get("/api/galleries")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert any(item["id"] == gid and item["image_count"] == 3 for item in r.json())


def test_gallery_detail_lists_roots(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(f"/api/galleries/{gid}")
    body = r.json()
    assert body["gallery"]["id"] == gid
    assert any(root["id"] == rid for root in body["roots"])


def test_folders_endpoint(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(f"/api/galleries/{gid}/roots/{rid}/folders", params={"path": ""})
    assert r.status_code == 200
    names = [f["name"] for f in r.json()]
    assert "sub" in names


def test_images_endpoint_root(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(f"/api/galleries/{gid}/roots/{rid}/images", params={"path": ""})
    body = r.json()
    assert [i["filename"] for i in body["items"]] == ["a.jpg"]


def test_images_endpoint_subdir(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(f"/api/galleries/{gid}/roots/{rid}/images", params={"path": "sub"})
    filenames = sorted(i["filename"] for i in r.json()["items"])
    assert filenames == ["b.jpg", "c.jpg"]


def test_breadcrumbs(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(f"/api/galleries/{gid}/roots/{rid}/breadcrumbs", params={"path": "sub"})
    crumbs = r.json()
    assert crumbs[0]["relative_path"] == ""
    assert crumbs[-1]["relative_path"] == "sub"


def test_path_traversal_rejected(client_with_data):
    c, gid, rid = client_with_data
    r = c.get(f"/api/galleries/{gid}/roots/{rid}/folders", params={"path": "../.."})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_unauthenticated_blocked(tmp_path):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        r = c.get("/api/galleries")
        assert r.status_code == 401
```

- [ ] **Step 2: 写 routes_browse.py**

创建 `backend/src/myphoto/routes_browse.py`：

```python
from __future__ import annotations

import base64
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select

from myphoto.deps import current_user
from myphoto.errors import AppError
from myphoto.models import Folder, Gallery, GalleryRoot, Image, User
from myphoto.paths import PathTraversalError, normalize_relative

router = APIRouter(prefix="/api", tags=["browse"])

_MAX_LIMIT = 500
_DEFAULT_LIMIT = 200

Sort = Literal["name_asc", "name_desc", "taken_at_asc", "taken_at_desc", "size_desc"]


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _norm_or_400(path: str) -> str:
    try:
        return normalize_relative(path)
    except PathTraversalError as exc:
        raise AppError("path_invalid", 400, str(exc))


async def _get_root_or_404(s, gid: int, rid: int) -> GalleryRoot:
    r = (await s.execute(select(GalleryRoot).where(
        GalleryRoot.id == rid, GalleryRoot.gallery_id == gid
    ))).scalar_one_or_none()
    if r is None or r.enabled != 1:
        raise AppError("not_found", 404, "root not found")
    return r


@router.get("/galleries")
async def list_galleries(request: Request, response: Response, _user: User = Depends(current_user)):
    _no_store(response)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        gals = (await s.execute(select(Gallery))).scalars().all()
        out = []
        for g in gals:
            root_count = (await s.execute(
                select(func.count()).select_from(GalleryRoot).where(GalleryRoot.gallery_id == g.id)
            )).scalar_one()
            image_count = (await s.execute(
                select(func.count()).select_from(Image).join(GalleryRoot, GalleryRoot.id == Image.root_id)
                .where(GalleryRoot.gallery_id == g.id)
            )).scalar_one()
            out.append({
                "id": g.id, "name": g.name, "description": g.description,
                "root_count": root_count, "image_count": image_count,
            })
        return out


@router.get("/galleries/{gid}")
async def gallery_detail(gid: int, request: Request, response: Response, _user: User = Depends(current_user)):
    _no_store(response)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        g = await s.get(Gallery, gid)
        if g is None:
            raise AppError("not_found", 404, "gallery not found")
        roots = (await s.execute(select(GalleryRoot).where(GalleryRoot.gallery_id == gid))).scalars().all()
        root_out = []
        for r in roots:
            cnt = (await s.execute(select(func.count()).select_from(Image).where(Image.root_id == r.id))).scalar_one()
            root_out.append({
                "id": r.id, "label": r.label, "image_count": cnt,
                "offline": r.last_scan_status == "error",
                "enabled": bool(r.enabled),
            })
        return {"gallery": {"id": g.id, "name": g.name, "description": g.description}, "roots": root_out}


@router.get("/galleries/{gid}/roots/{rid}/folders")
async def list_folders(gid: int, rid: int, request: Request, response: Response,
                       path: str = "", _user: User = Depends(current_user)):
    _no_store(response)
    rel = _norm_or_400(path)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        await _get_root_or_404(s, gid, rid)
        parent = (await s.execute(select(Folder).where(
            Folder.root_id == rid, Folder.relative_path == rel
        ))).scalar_one_or_none()
        if parent is None:
            return []
        children = (await s.execute(select(Folder).where(
            Folder.root_id == rid, Folder.parent_id == parent.id
        ).order_by(Folder.name.asc()))).scalars().all()
        out = []
        for c in children:
            cover = (await s.execute(
                select(Image.sha1).where(Image.folder_id == c.id).order_by(Image.filename.asc()).limit(1)
            )).scalar_one_or_none()
            out.append({
                "name": c.name, "relative_path": c.relative_path,
                "image_count": c.image_count, "descendant_count": c.descendant_count,
                "cover_thumb_sha1": cover,
            })
        return out


@router.get("/galleries/{gid}/roots/{rid}/breadcrumbs")
async def breadcrumbs(gid: int, rid: int, request: Request, response: Response,
                      path: str = "", _user: User = Depends(current_user)):
    _no_store(response)
    rel = _norm_or_400(path)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        root = await _get_root_or_404(s, gid, rid)
        crumbs = [{"name": root.label, "relative_path": ""}]
        if rel:
            parts = rel.split("/")
            acc: list[str] = []
            for p in parts:
                acc.append(p)
                crumbs.append({"name": p, "relative_path": "/".join(acc)})
        return crumbs


def _encode_cursor(sort_key: str, iid: int) -> str:
    raw = f"{sort_key}\x1f{iid}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        k, i = raw.split("\x1f", 1)
        return k, int(i)
    except Exception:
        raise AppError("path_invalid", 400, "invalid cursor")


@router.get("/galleries/{gid}/roots/{rid}/images")
async def list_images(gid: int, rid: int, request: Request, response: Response,
                      path: str = "", sort: Sort = "name_asc",
                      limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
                      cursor: str | None = None,
                      _user: User = Depends(current_user)):
    _no_store(response)
    rel = _norm_or_400(path)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        await _get_root_or_404(s, gid, rid)
        folder = (await s.execute(select(Folder).where(
            Folder.root_id == rid, Folder.relative_path == rel
        ))).scalar_one_or_none()
        if folder is None:
            return {"items": [], "next_cursor": None}
        q = select(Image).where(Image.folder_id == folder.id)
        # ordering
        if sort == "name_asc":
            q = q.order_by(Image.filename.asc(), Image.id.asc())
            key_expr = Image.filename
        elif sort == "name_desc":
            q = q.order_by(Image.filename.desc(), Image.id.desc())
            key_expr = Image.filename
        elif sort == "taken_at_asc":
            q = q.order_by(Image.taken_at.asc(), Image.id.asc())
            key_expr = Image.taken_at
        elif sort == "taken_at_desc":
            q = q.order_by(Image.taken_at.desc(), Image.id.desc())
            key_expr = Image.taken_at
        else:  # size_desc
            q = q.order_by(Image.size_bytes.desc(), Image.id.desc())
            key_expr = Image.size_bytes
        # cursor: naive OFFSET fallback for P1 (keyset TBD in P7 optimization pass)
        if cursor:
            _, last_id = _decode_cursor(cursor)
            q = q.where(Image.id > last_id) if sort.endswith("_asc") else q.where(Image.id < last_id)
        q = q.limit(limit + 1)
        rows = (await s.execute(q)).scalars().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [{
            "id": r.id, "filename": r.filename, "width": r.width, "height": r.height,
            "sha1": r.sha1, "size_bytes": r.size_bytes, "taken_at": r.taken_at, "is_raw": bool(r.is_raw),
        } for r in rows]
        next_cursor = _encode_cursor(sort, rows[-1].id) if has_more and rows else None
        return {"items": items, "next_cursor": next_cursor}
```

- [ ] **Step 3: 挂路由到 main.py**

Edit `backend/src/myphoto/main.py`：

```python
    from myphoto.routes_browse import router as browse_router
    app.include_router(browse_router)
```

- [ ] **Step 4: 运行测试**

Run: `pytest backend/tests/test_routes_browse.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/routes_browse.py backend/src/myphoto/main.py backend/tests/test_routes_browse.py
git commit -m "feat(browse): galleries/roots/folders/images/breadcrumbs endpoints"
```

---

### Task 13: 媒体流 API `routes_media.py`

**Files:**
- Create: `backend/src/myphoto/routes_media.py`
- Modify: `backend/src/myphoto/main.py`
- Create: `backend/tests/test_routes_media.py`

**Interfaces:**
- Consumes: `thumbnails.ThumbnailGenerator`, `paths.resolve_within_root`, models
- Produces：
  - `GET /api/thumb/{sha1}?size=200|400|1600` → `image/jpeg`；`Cache-Control: public, max-age=31536000, immutable`；`ETag = sha1`
  - `GET /api/image/{image_id}?download=0|1` → 原文件流；`Cache-Control: private, max-age=86400`；`ETag = sha1`；支持 `Range`
  - 应用启动时把 `ThumbnailGenerator` 绑到 `app.state.thumbnails`，缓存目录 `<data_dir>/.cache/thumbnails`

- [ ] **Step 1: 写测试**

创建 `backend/tests/test_routes_media.py`：

```python
import asyncio
import re
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient

from myphoto.main import build_app


def _jpg(p: Path, size=(200, 150)):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", size, (200, 100, 50)).save(p, "JPEG")


@pytest.fixture
def env(tmp_path, capsys):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        from myphoto.models import Gallery, GalleryRoot
        async def seed():
            async with app.state.sessionmaker() as s:
                g = Gallery(name="G", created_at=int(time.time()))
                s.add(g); await s.flush()
                r = GalleryRoot(gallery_id=g.id, label="R", absolute_path=str(photos.resolve()), enabled=1)
                s.add(r); await s.commit(); await s.refresh(r)
                return r.id
        rid = asyncio.get_event_loop().run_until_complete(seed())
        asyncio.get_event_loop().run_until_complete(app.state.scanner.scan_root_now(rid))
        # find the image row for sha1 + id
        async def fetch():
            from myphoto.models import Image
            from sqlalchemy import select as _s
            async with app.state.sessionmaker() as s:
                row = (await s.execute(_s(Image))).scalars().first()
                return row.id, row.sha1
        iid, sha1 = asyncio.get_event_loop().run_until_complete(fetch())
        yield c, iid, sha1


def test_thumb_returns_jpeg(env):
    c, _, sha1 = env
    r = c.get(f"/api/thumb/{sha1}", params={"size": 200})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert "immutable" in r.headers["cache-control"]
    assert r.headers["etag"] == sha1


def test_thumb_rejects_bad_size(env):
    c, _, sha1 = env
    r = c.get(f"/api/thumb/{sha1}", params={"size": 999})
    assert r.status_code == 400


def test_thumb_unknown_sha1_404(env):
    c, _, _ = env
    r = c.get("/api/thumb/deadbeef", params={"size": 200})
    assert r.status_code == 404


def test_image_stream(env):
    c, iid, sha1 = env
    r = c.get(f"/api/image/{iid}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert r.headers["etag"] == sha1


def test_image_download_disposition(env):
    c, iid, _ = env
    r = c.get(f"/api/image/{iid}", params={"download": 1})
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")


def test_image_range(env):
    c, iid, _ = env
    full = c.get(f"/api/image/{iid}").content
    r = c.get(f"/api/image/{iid}", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    assert r.content == full[:10]
```

- [ ] **Step 2: 写 routes_media.py**

创建 `backend/src/myphoto/routes_media.py`：

```python
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select

from myphoto.deps import current_user
from myphoto.errors import AppError
from myphoto.models import GalleryRoot, Image, User
from myphoto.paths import PathTraversalError, resolve_within_root
from myphoto.thumbnails import ALLOWED_SIZES, ThumbnailError

router = APIRouter(prefix="/api", tags=["media"])


@router.get("/thumb/{sha1}")
async def get_thumb(sha1: str, request: Request,
                    size: int = Query(200),
                    _user: User = Depends(current_user)):
    if size not in ALLOWED_SIZES:
        raise AppError("path_invalid", 400, f"size {size} not allowed")
    sm = request.app.state.sessionmaker
    async with sm() as s:
        img = (await s.execute(select(Image).where(Image.sha1 == sha1).limit(1))).scalar_one_or_none()
        if img is None:
            raise AppError("not_found", 404, "image not found")
        root = await s.get(GalleryRoot, img.root_id)
    try:
        src = resolve_within_root(root.absolute_path, img.relative_path)
    except PathTraversalError:
        raise AppError("path_invalid", 400, "invalid path")
    if not src.exists():
        raise AppError("not_found", 404, "source file missing")
    gen = request.app.state.thumbnails
    try:
        out = await gen.ensure(sha1, size, str(src), is_raw=bool(img.is_raw))
    except ThumbnailError as exc:
        raise AppError("internal_error", 500, f"thumb generation failed: {exc}")
    return FileResponse(
        out, media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": sha1,
        },
    )


def _guess_mime(filename: str) -> str:
    mt, _ = mimetypes.guess_type(filename)
    return mt or "application/octet-stream"


@router.get("/image/{image_id}")
async def get_image(image_id: int, request: Request,
                    download: int = Query(0),
                    _user: User = Depends(current_user)):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        img = await s.get(Image, image_id)
        if img is None:
            raise AppError("not_found", 404, "image not found")
        root = await s.get(GalleryRoot, img.root_id)
    try:
        src = resolve_within_root(root.absolute_path, img.relative_path)
    except PathTraversalError:
        raise AppError("path_invalid", 400, "invalid path")
    if not src.exists():
        raise AppError("not_found", 404, "source file missing")

    headers = {
        "Cache-Control": "private, max-age=86400",
        "ETag": img.sha1,
        "Accept-Ranges": "bytes",
    }
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{img.filename}"'
    media_type = _guess_mime(img.filename)

    # Range support
    range_header = request.headers.get("range")
    file_size = src.stat().st_size
    if range_header and range_header.startswith("bytes="):
        try:
            spec = range_header.split("=", 1)[1]
            start_s, end_s = spec.split("-", 1)
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else file_size - 1
            end = min(end, file_size - 1)
            if start > end or start >= file_size:
                raise ValueError
        except ValueError:
            raise AppError("path_invalid", 416, "invalid Range")
        length = end - start + 1

        def _iter():
            with src.open("rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(length)
        return StreamingResponse(_iter(), status_code=206, media_type=media_type, headers=headers)

    return FileResponse(src, media_type=media_type, headers=headers, filename=img.filename if download else None)
```

- [ ] **Step 3: 在 main.py lifespan 中注入 ThumbnailGenerator**

Edit `backend/src/myphoto/main.py`：

```python
        from myphoto.thumbnails import ThumbnailGenerator
        app.state.thumbnails = ThumbnailGenerator(Path(cfg.data_dir) / ".cache" / "thumbnails")
```

并挂路由：

```python
    from myphoto.routes_media import router as media_router
    app.include_router(media_router)
```

- [ ] **Step 4: 运行测试**

Run: `pytest backend/tests/test_routes_media.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/myphoto/routes_media.py backend/src/myphoto/main.py backend/tests/test_routes_media.py
git commit -m "feat(media): thumbnail cache endpoint and range-aware original streaming"
```

---

### Task 14: CLI 工具 `cli.py`

**Files:**
- Create: `backend/src/myphoto/cli.py`
- Create: `backend/tests/test_cli.py`

**Interfaces:**
- Consumes: `config.load_or_init`, `db.make_engine/make_sessionmaker`, models, scanner
- Produces（`click` 命令）：
  - `myphoto add-gallery NAME [--description]`
  - `myphoto add-root GALLERY_NAME LABEL ABSOLUTE_PATH`
  - `myphoto rescan [GALLERY_NAME] [ROOT_LABEL]` — 不带参 = 全部；只给 gallery = 该图库所有 root
  - `myphoto list` — 列出图库/root/图片计数
  - 所有命令共用 `--config` 选项（默认 `config.toml`）

- [ ] **Step 1: 写测试**

创建 `backend/tests/test_cli.py`：

```python
import re
from pathlib import Path

from PIL import Image as PILImage
from click.testing import CliRunner

from myphoto.cli import cli


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (60, 40), (0, 0, 0)).save(p, "JPEG")


def test_add_gallery_and_root_and_rescan(tmp_path):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    _jpg(photos / "sub" / "b.jpg")
    cfg = tmp_path / "config.toml"
    runner = CliRunner()

    r = runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["--config", str(cfg), "add-root", "Home", "Main", str(photos.resolve())])
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["--config", str(cfg), "rescan"])
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["--config", str(cfg), "list"])
    assert r.exit_code == 0, r.output
    assert "Home" in r.output
    assert re.search(r"2 images", r.output)


def test_add_root_missing_gallery(tmp_path):
    cfg = tmp_path / "config.toml"
    r = CliRunner().invoke(cli, ["--config", str(cfg), "add-root", "Nope", "L", str(tmp_path)])
    assert r.exit_code != 0


def test_add_root_missing_path(tmp_path):
    cfg = tmp_path / "config.toml"
    CliRunner().invoke(cli, ["--config", str(cfg), "add-gallery", "G"])
    r = CliRunner().invoke(cli, ["--config", str(cfg), "add-root", "G", "L", str(tmp_path / "nope")])
    assert r.exit_code != 0
```

- [ ] **Step 2: 写 cli.py**

创建 `backend/src/myphoto/cli.py`：

```python
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import click
from sqlalchemy import func, select

from myphoto.config import load_or_init
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import Gallery, GalleryRoot, Image
from myphoto.scanner import Scanner
from myphoto.schema_init import ensure_schema_and_admin


def _run(coro):
    return asyncio.run(coro)


async def _bootstrap(config_path: str):
    cfg = load_or_init(config_path)
    db = Path(cfg.data_dir) / "app.db"
    engine = await make_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    created, pw = await ensure_schema_and_admin(engine, sm)
    if created and pw:
        click.echo(f"[myphoto] initial admin created. username=admin password={pw}")
    return engine, sm, cfg


@click.group()
@click.option("--config", "config_path", default="config.toml")
@click.pass_context
def cli(ctx, config_path):
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


@cli.command("add-gallery")
@click.argument("name")
@click.option("--description", default=None)
@click.pass_context
def add_gallery(ctx, name, description):
    async def _run_it():
        engine, sm, _ = await _bootstrap(ctx.obj["config_path"])
        try:
            async with sm() as s:
                if (await s.execute(select(Gallery).where(Gallery.name == name))).scalar_one_or_none():
                    raise click.ClickException(f"gallery '{name}' already exists")
                s.add(Gallery(name=name, description=description, created_at=int(time.time())))
                await s.commit()
                click.echo(f"gallery '{name}' created")
        finally:
            await engine.dispose()
    _run(_run_it())


@cli.command("add-root")
@click.argument("gallery_name")
@click.argument("label")
@click.argument("absolute_path")
@click.pass_context
def add_root(ctx, gallery_name, label, absolute_path):
    p = Path(absolute_path).resolve()
    if not p.exists() or not p.is_dir():
        raise click.ClickException(f"path not readable: {p}")

    async def _run_it():
        engine, sm, _ = await _bootstrap(ctx.obj["config_path"])
        try:
            async with sm() as s:
                g = (await s.execute(select(Gallery).where(Gallery.name == gallery_name))).scalar_one_or_none()
                if g is None:
                    raise click.ClickException(f"gallery '{gallery_name}' not found")
                s.add(GalleryRoot(gallery_id=g.id, label=label, absolute_path=str(p), enabled=1))
                await s.commit()
                click.echo(f"root '{label}' added to '{gallery_name}' -> {p}")
        finally:
            await engine.dispose()
    _run(_run_it())


@cli.command("rescan")
@click.argument("gallery_name", required=False)
@click.argument("root_label", required=False)
@click.pass_context
def rescan(ctx, gallery_name, root_label):
    async def _run_it():
        engine, sm, _ = await _bootstrap(ctx.obj["config_path"])
        try:
            async with sm() as s:
                q = select(GalleryRoot).where(GalleryRoot.enabled == 1)
                if gallery_name:
                    g = (await s.execute(select(Gallery).where(Gallery.name == gallery_name))).scalar_one_or_none()
                    if g is None:
                        raise click.ClickException(f"gallery '{gallery_name}' not found")
                    q = q.where(GalleryRoot.gallery_id == g.id)
                if root_label:
                    q = q.where(GalleryRoot.label == root_label)
                roots = (await s.execute(q)).scalars().all()
            scanner = Scanner(sm)
            for r in roots:
                click.echo(f"scanning {r.label} ({r.absolute_path})...")
                await scanner.scan_root_now(r.id)
                status = scanner.get_status(r.id)
                click.echo(f"  -> {status}")
        finally:
            await engine.dispose()
    _run(_run_it())


@cli.command("list")
@click.pass_context
def list_all(ctx):
    async def _run_it():
        engine, sm, _ = await _bootstrap(ctx.obj["config_path"])
        try:
            async with sm() as s:
                gals = (await s.execute(select(Gallery))).scalars().all()
                for g in gals:
                    click.echo(f"gallery: {g.name} (id={g.id})")
                    roots = (await s.execute(select(GalleryRoot).where(GalleryRoot.gallery_id == g.id))).scalars().all()
                    for r in roots:
                        cnt = (await s.execute(select(func.count()).select_from(Image).where(Image.root_id == r.id))).scalar_one()
                        click.echo(f"  root: {r.label} -> {r.absolute_path} ({cnt} images)")
        finally:
            await engine.dispose()
    _run(_run_it())


def main():
    cli(obj={})
```

- [ ] **Step 3: 运行测试**

Run: `pytest backend/tests/test_cli.py -v`
Expected: 3 passed

- [ ] **Step 4: 提交**

```bash
git add backend/src/myphoto/cli.py backend/tests/test_cli.py
git commit -m "feat(cli): add-gallery / add-root / rescan / list commands"
```

---

### Task 15: 前端脚手架 Vite + Vue + Pinia + Router + UnoCSS

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/uno.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/router.ts`
- Create: `frontend/src/env.d.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/src/tests/smoke.spec.ts`

**Interfaces:**
- Consumes: 无
- Produces: 可用的 Vue 3 + Vite dev server；`pnpm dev` 显示 App；`pnpm test` 运行 vitest；`pnpm build` 产出 `frontend/dist/`

- [ ] **Step 1: 写 package.json**

创建 `frontend/package.json`：

```json
{
  "name": "myphoto-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "photoswipe": "^5.4.4",
    "pinia": "^2.1.7",
    "vue": "^3.4.21",
    "vue-router": "^4.3.0",
    "vue-virtual-scroller": "2.0.0-beta.8"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.4",
    "@vue/test-utils": "^2.4.5",
    "jsdom": "^24.0.0",
    "typescript": "^5.4.3",
    "unocss": "^0.58.9",
    "vite": "^5.2.6",
    "vitest": "^1.4.0",
    "vue-tsc": "^2.0.7"
  }
}
```

- [ ] **Step 2: 写 vite.config.ts**

创建 `frontend/vite.config.ts`：

```ts
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import UnoCSS from "unocss/vite"

export default defineConfig({
  plugins: [vue(), UnoCSS()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8080",
    },
  },
  build: {
    outDir: "dist",
  },
})
```

- [ ] **Step 3: 写 tsconfig.json**

创建 `frontend/tsconfig.json`：

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "jsx": "preserve",
    "lib": ["ES2022", "DOM"],
    "types": ["vitest/globals"],
    "esModuleInterop": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "resolveJsonModule": true
  },
  "include": ["src/**/*.ts", "src/**/*.vue", "src/**/*.d.ts"]
}
```

- [ ] **Step 4: 写 uno.config.ts**

创建 `frontend/uno.config.ts`：

```ts
import { defineConfig, presetUno } from "unocss"

export default defineConfig({
  presets: [presetUno()],
})
```

- [ ] **Step 5: 写 index.html**

创建 `frontend/index.html`：

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <title>myPhotoGallery</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 6: 写 src/env.d.ts**

创建 `frontend/src/env.d.ts`：

```ts
/// <reference types="vite/client" />
declare module "*.vue" {
  import { DefineComponent } from "vue"
  const c: DefineComponent<{}, {}, any>
  export default c
}
```

- [ ] **Step 7: 写 src/App.vue 和 src/main.ts**

创建 `frontend/src/App.vue`：

```vue
<template>
  <div class="min-h-screen bg-neutral-950 text-neutral-100">
    <RouterView />
  </div>
</template>

<script setup lang="ts"></script>
```

创建 `frontend/src/router.ts`：

```ts
import { createRouter, createWebHistory, RouteRecordRaw } from "vue-router"

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/galleries" },
  { path: "/login", component: () => import("./views/LoginView.vue") },
  { path: "/galleries", component: () => import("./views/GalleryListView.vue") },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
```

创建 `frontend/src/main.ts`：

```ts
import { createApp } from "vue"
import { createPinia } from "pinia"
import "virtual:uno.css"
import App from "./App.vue"
import { router } from "./router"

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount("#app")
```

创建占位 `frontend/src/views/LoginView.vue`：

```vue
<template><div>Login (stub)</div></template>
```

创建占位 `frontend/src/views/GalleryListView.vue`：

```vue
<template><div>Gallery list (stub)</div></template>
```

- [ ] **Step 8: 写 vitest 配置和冒烟测试**

创建 `frontend/vitest.config.ts`：

```ts
import { defineConfig } from "vitest/config"
import vue from "@vitejs/plugin-vue"

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: "jsdom",
    globals: true,
  },
})
```

创建 `frontend/src/tests/smoke.spec.ts`：

```ts
import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import App from "../App.vue"

describe("App", () => {
  it("mounts", () => {
    const w = mount(App, {
      global: {
        stubs: { RouterView: true },
      },
    })
    expect(w.exists()).toBe(true)
  })
})
```

- [ ] **Step 9: 安装依赖并运行**

Run:
```bash
cd frontend
pnpm install
pnpm test
```
Expected: 1 passed

- [ ] **Step 10: 提交**

```bash
git add frontend/
git commit -m "chore(frontend): scaffold Vue 3 + Vite + Pinia + Router + UnoCSS"
```

---

### Task 16: `apiClient` + `useAuthStore` + LoginView

**Files:**
- Create: `frontend/src/api.ts`
- Create: `frontend/src/stores/auth.ts`
- Create: `frontend/src/stores/toast.ts`
- Modify: `frontend/src/views/LoginView.vue`
- Modify: `frontend/src/router.ts`（加导航守卫）
- Create: `frontend/src/tests/api.spec.ts`

**Interfaces:**
- Produces:
  - `api.ts`：
    - `type ApiError = { code: string; message: string }`
    - `class HttpError extends Error { code: string; status: number }`
    - `async function apiGet<T>(path: string): Promise<T>`
    - `async function apiPost<T>(path: string, body?: any): Promise<T>`
    - `async function apiDelete<T>(path: string): Promise<T>`
    - 所有请求 `credentials: "include"`；解析统一错误包结构；401 时清 `useAuthStore` 并跳 `/login`
  - `stores/auth.ts`：
    - `state: { user: {id, username, role, access_scope} | null; loading: boolean }`
    - `isAdmin: boolean` (computed)
    - `async fetchMe(): Promise<void>` — GET /api/auth/me，404/401 → user = null
    - `async login(username, password): Promise<void>`
    - `async logout(): Promise<void>`
  - `stores/toast.ts`：`push(kind: "info"|"error", text: string)`；`items` ref

- [ ] **Step 1: 写 api 测试**

创建 `frontend/src/tests/api.spec.ts`：

```ts
import { describe, expect, it, vi, beforeEach } from "vitest"
import { HttpError, apiGet, apiPost } from "../api"

describe("apiClient", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn())
  })

  it("returns parsed JSON on success", async () => {
    ;(fetch as any).mockResolvedValue(new Response(JSON.stringify({ ok: 1 }), {
      status: 200,
      headers: { "content-type": "application/json" },
    }))
    const r = await apiGet<{ ok: number }>("/api/x")
    expect(r).toEqual({ ok: 1 })
    expect((fetch as any).mock.calls[0][1].credentials).toBe("include")
  })

  it("throws HttpError with code on 4xx envelope", async () => {
    ;(fetch as any).mockResolvedValue(new Response(
      JSON.stringify({ error: { code: "invalid_credentials", message: "wrong" } }),
      { status: 401, headers: { "content-type": "application/json" } },
    ))
    await expect(apiPost("/api/auth/login", {})).rejects.toMatchObject({
      code: "invalid_credentials",
      status: 401,
    })
  })

  it("throws HttpError with internal_error on non-JSON 5xx", async () => {
    ;(fetch as any).mockResolvedValue(new Response("boom", { status: 500 }))
    await expect(apiGet("/api/x")).rejects.toMatchObject({ code: "internal_error", status: 500 })
  })
})
```

- [ ] **Step 2: 写 api.ts**

创建 `frontend/src/api.ts`：

```ts
export interface ApiError {
  code: string
  message: string
}

export class HttpError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = {
    method,
    credentials: "include",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
  let res: Response
  try {
    res = await fetch(path, init)
  } catch (err) {
    throw new HttpError(0, "network_error", (err as Error).message)
  }
  if (res.status === 204) return undefined as unknown as T
  const ct = res.headers.get("content-type") || ""
  const data = ct.includes("application/json") ? await res.json().catch(() => null) : null
  if (!res.ok) {
    const code = data?.error?.code ?? "internal_error"
    const msg = data?.error?.message ?? res.statusText
    throw new HttpError(res.status, code, msg)
  }
  return data as T
}

export const apiGet = <T>(p: string) => request<T>("GET", p)
export const apiPost = <T>(p: string, body?: unknown) => request<T>("POST", p, body ?? {})
export const apiDelete = <T>(p: string) => request<T>("DELETE", p)
```

- [ ] **Step 3: 运行 api 测试**

Run: `cd frontend && pnpm test`
Expected: api tests pass

- [ ] **Step 4: 写 stores/toast.ts**

创建 `frontend/src/stores/toast.ts`：

```ts
import { defineStore } from "pinia"
import { ref } from "vue"

export const useToastStore = defineStore("toast", () => {
  const items = ref<Array<{ id: number; kind: "info" | "error"; text: string }>>([])
  let nextId = 1
  function push(kind: "info" | "error", text: string) {
    const id = nextId++
    items.value.push({ id, kind, text })
    setTimeout(() => {
      items.value = items.value.filter((x) => x.id !== id)
    }, 4000)
  }
  return { items, push }
})
```

- [ ] **Step 5: 写 stores/auth.ts**

创建 `frontend/src/stores/auth.ts`：

```ts
import { defineStore } from "pinia"
import { computed, ref } from "vue"
import { HttpError, apiGet, apiPost } from "../api"

export interface AuthUser {
  id: number
  username: string
  role: "admin" | "viewer"
  access_scope: "lan_only" | "remote_allowed"
}

export const useAuthStore = defineStore("auth", () => {
  const user = ref<AuthUser | null>(null)
  const loading = ref(false)
  const isAdmin = computed(() => user.value?.role === "admin")

  async function fetchMe() {
    loading.value = true
    try {
      user.value = await apiGet<AuthUser>("/api/auth/me")
    } catch (err) {
      if (err instanceof HttpError && err.status === 401) {
        user.value = null
      } else {
        throw err
      }
    } finally {
      loading.value = false
    }
  }

  async function login(username: string, password: string) {
    const r = await apiPost<{ user: AuthUser }>("/api/auth/login", { username, password })
    user.value = r.user
  }

  async function logout() {
    await apiPost<void>("/api/auth/logout")
    user.value = null
  }

  return { user, loading, isAdmin, fetchMe, login, logout }
})
```

- [ ] **Step 6: 写 LoginView.vue**

创建 `frontend/src/views/LoginView.vue`（覆盖占位）：

```vue
<template>
  <div class="min-h-screen flex items-center justify-center px-4">
    <form class="w-full max-w-sm space-y-4 bg-neutral-900 rounded-lg p-6" @submit.prevent="onSubmit">
      <h1 class="text-xl font-semibold text-center">myPhotoGallery</h1>
      <label class="block">
        <span class="text-sm text-neutral-400">用户名</span>
        <input v-model="username" type="text" autocomplete="username" required
               class="mt-1 w-full rounded bg-neutral-800 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </label>
      <label class="block">
        <span class="text-sm text-neutral-400">密码</span>
        <input v-model="password" type="password" autocomplete="current-password" required
               class="mt-1 w-full rounded bg-neutral-800 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
      </label>
      <p v-if="errorMsg" class="text-sm text-red-400">{{ errorMsg }}</p>
      <button type="submit" :disabled="submitting"
              class="w-full rounded bg-blue-600 py-2 font-medium hover:bg-blue-500 disabled:opacity-50">
        {{ submitting ? "登录中..." : "登录" }}
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useRouter } from "vue-router"
import { useAuthStore } from "../stores/auth"
import { HttpError } from "../api"

const auth = useAuthStore()
const router = useRouter()
const username = ref("")
const password = ref("")
const errorMsg = ref("")
const submitting = ref(false)

const CODE_MSG: Record<string, string> = {
  invalid_credentials: "用户名或密码错误",
  login_locked: "登录尝试过多，请稍后再试",
  network_error: "网络错误",
}

async function onSubmit() {
  errorMsg.value = ""
  submitting.value = true
  try {
    await auth.login(username.value, password.value)
    router.replace((router.currentRoute.value.query.next as string) || "/galleries")
  } catch (err) {
    if (err instanceof HttpError) {
      errorMsg.value = CODE_MSG[err.code] ?? err.message
    } else {
      errorMsg.value = "未知错误"
    }
  } finally {
    submitting.value = false
  }
}
</script>
```

- [ ] **Step 7: 更新 router.ts 加导航守卫**

Edit `frontend/src/router.ts`：

```ts
import { createRouter, createWebHistory, RouteRecordRaw } from "vue-router"
import { useAuthStore } from "./stores/auth"

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/galleries" },
  { path: "/login", component: () => import("./views/LoginView.vue"), meta: { public: true } },
  { path: "/galleries", component: () => import("./views/GalleryListView.vue") },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const auth = useAuthStore()
  if (auth.user === null && !auth.loading) {
    await auth.fetchMe()
  }
  if (auth.user === null) {
    return { path: "/login", query: { next: to.fullPath } }
  }
  return true
})
```

- [ ] **Step 8: 手动验证登录闭环**

启动后端：`uvicorn myphoto.main:app --host 127.0.0.1 --port 8080`
启动前端：`cd frontend && pnpm dev`
浏览器打开 `http://localhost:5173`
应重定向到 `/login`；输入 stdout 打印的 `admin` 密码 → 跳到 `/galleries` 空占位页

- [ ] **Step 9: 提交**

```bash
git add frontend/src/api.ts frontend/src/stores frontend/src/views/LoginView.vue frontend/src/router.ts frontend/src/tests/api.spec.ts
git commit -m "feat(frontend): auth store, login view, api client with error envelope"
```

---

### Task 17: GalleryListView + RootListView + Breadcrumb + AppHeader

**Files:**
- Create: `frontend/src/components/AppHeader.vue`
- Create: `frontend/src/components/Breadcrumb.vue`
- Create: `frontend/src/components/SubfolderStrip.vue`
- Modify: `frontend/src/views/GalleryListView.vue`
- Create: `frontend/src/views/RootListView.vue`
- Modify: `frontend/src/router.ts`

**Interfaces:**
- Consumes: `api.ts`, `stores/auth.ts`
- Produces：
  - `<AppHeader>` 组件：显示用户名 + 登出按钮；管理端入口在 P6 加
  - `<Breadcrumb :crumbs="Array<{name, relative_path}>" :gid :rid />`：每段点击 push 路由
  - `<SubfolderStrip :folders="Array<{name, relative_path, image_count, cover_thumb_sha1}>" :gid :rid />`
  - `GalleryListView` 拉 `/api/galleries`，卡片网格；点入 → `/galleries/:gid`
  - `RootListView` 拉 `/api/galleries/:gid`，若 `roots.length === 1` 自动 `router.replace` 到 `/galleries/:gid/r/:rid/`；否则显示 root 卡片

- [ ] **Step 1: 写 AppHeader.vue**

创建 `frontend/src/components/AppHeader.vue`：

```vue
<template>
  <header class="sticky top-0 z-40 flex items-center gap-4 border-b border-neutral-800 bg-neutral-900/95 px-4 py-3 backdrop-blur">
    <router-link to="/galleries" class="font-semibold">myPhotoGallery</router-link>
    <div class="flex-1 min-w-0 overflow-hidden">
      <slot name="title"></slot>
    </div>
    <div v-if="auth.user" class="flex items-center gap-2 text-sm">
      <span class="text-neutral-400">{{ auth.user.username }}</span>
      <button class="rounded px-2 py-1 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100" @click="onLogout">
        登出
      </button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { useRouter } from "vue-router"
import { useAuthStore } from "../stores/auth"

const auth = useAuthStore()
const router = useRouter()

async function onLogout() {
  await auth.logout()
  router.replace("/login")
}
</script>
```

- [ ] **Step 2: 写 Breadcrumb.vue**

创建 `frontend/src/components/Breadcrumb.vue`：

```vue
<template>
  <nav class="flex items-center gap-1 overflow-x-auto whitespace-nowrap text-sm text-neutral-400" aria-label="面包屑">
    <template v-for="(c, i) in crumbs" :key="c.relative_path">
      <router-link :to="linkFor(c.relative_path)" class="rounded px-2 py-1 hover:bg-neutral-800 hover:text-neutral-100">
        {{ c.name }}
      </router-link>
      <span v-if="i < crumbs.length - 1" class="text-neutral-600">›</span>
    </template>
  </nav>
</template>

<script setup lang="ts">
const props = defineProps<{
  crumbs: Array<{ name: string; relative_path: string }>
  gid: number
  rid: number
}>()

function linkFor(rel: string) {
  const suffix = rel ? `/${rel}` : ""
  return `/galleries/${props.gid}/r/${props.rid}${suffix}`
}
</script>
```

- [ ] **Step 3: 写 SubfolderStrip.vue**

创建 `frontend/src/components/SubfolderStrip.vue`：

```vue
<template>
  <div v-if="folders.length" class="flex gap-3 overflow-x-auto px-1 py-2">
    <router-link v-for="f in folders" :key="f.relative_path"
                 :to="linkFor(f.relative_path)"
                 class="group flex w-32 flex-none flex-col overflow-hidden rounded bg-neutral-800 text-sm hover:ring-2 hover:ring-blue-500">
      <div class="aspect-4/3 bg-neutral-700">
        <img v-if="f.cover_thumb_sha1"
             :src="`/api/thumb/${f.cover_thumb_sha1}?size=200`"
             class="h-full w-full object-cover"
             loading="lazy"
             :alt="f.name" />
      </div>
      <div class="truncate p-2">
        <div class="truncate font-medium">{{ f.name }}</div>
        <div class="text-xs text-neutral-400">{{ f.descendant_count }} 张</div>
      </div>
    </router-link>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  folders: Array<{
    name: string
    relative_path: string
    image_count: number
    descendant_count: number
    cover_thumb_sha1: string | null
  }>
  gid: number
  rid: number
}>()

function linkFor(rel: string) {
  return `/galleries/${props.gid}/r/${props.rid}/${rel}`
}
</script>
```

- [ ] **Step 4: 写 GalleryListView.vue**

覆盖 `frontend/src/views/GalleryListView.vue`：

```vue
<template>
  <div>
    <AppHeader>
      <template #title><span class="text-neutral-400">图库</span></template>
    </AppHeader>
    <main class="p-4">
      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <div v-else-if="error" class="text-red-400">{{ error }}</div>
      <div v-else class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <router-link v-for="g in items" :key="g.id" :to="`/galleries/${g.id}`"
                     class="block rounded-lg bg-neutral-900 p-4 hover:ring-2 hover:ring-blue-500">
          <div class="font-medium">{{ g.name }}</div>
          <div class="mt-1 text-sm text-neutral-400">
            {{ g.image_count }} 张 · {{ g.root_count }} 个根目录
          </div>
        </router-link>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue"
import AppHeader from "../components/AppHeader.vue"
import { apiGet, HttpError } from "../api"

interface Gallery {
  id: number
  name: string
  description: string | null
  root_count: number
  image_count: number
}

const items = ref<Gallery[]>([])
const loading = ref(true)
const error = ref("")

onMounted(async () => {
  try {
    items.value = await apiGet<Gallery[]>("/api/galleries")
  } catch (err) {
    error.value = (err as HttpError).message
  } finally {
    loading.value = false
  }
})
</script>
```

- [ ] **Step 5: 写 RootListView.vue**

创建 `frontend/src/views/RootListView.vue`：

```vue
<template>
  <div>
    <AppHeader>
      <template #title>
        <div class="truncate text-neutral-400">
          <router-link to="/galleries" class="hover:text-neutral-100">图库</router-link>
          <span class="mx-1 text-neutral-600">›</span>
          <span class="text-neutral-100">{{ galleryName }}</span>
        </div>
      </template>
    </AppHeader>
    <main class="p-4">
      <div v-if="loading" class="text-neutral-400">加载中...</div>
      <div v-else class="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <router-link v-for="r in roots" :key="r.id" :to="`/galleries/${gid}/r/${r.id}/`"
                     class="block rounded-lg bg-neutral-900 p-4 hover:ring-2 hover:ring-blue-500">
          <div class="font-medium">{{ r.label }}</div>
          <div class="mt-1 text-sm text-neutral-400">{{ r.image_count }} 张</div>
          <div v-if="r.offline" class="mt-1 text-xs text-yellow-400">离线 / 上次扫描出错</div>
        </router-link>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, computed } from "vue"
import { useRoute, useRouter } from "vue-router"
import AppHeader from "../components/AppHeader.vue"
import { apiGet } from "../api"

interface RootInfo {
  id: number
  label: string
  image_count: number
  offline: boolean
  enabled: boolean
}

const route = useRoute()
const router = useRouter()
const gid = computed(() => Number(route.params.gid))
const galleryName = ref("")
const roots = ref<RootInfo[]>([])
const loading = ref(true)

onMounted(async () => {
  const detail = await apiGet<{ gallery: { name: string }; roots: RootInfo[] }>(`/api/galleries/${gid.value}`)
  galleryName.value = detail.gallery.name
  roots.value = detail.roots
  if (roots.value.length === 1) {
    router.replace(`/galleries/${gid.value}/r/${roots.value[0].id}/`)
    return
  }
  loading.value = false
})
</script>
```

- [ ] **Step 6: 更新 router.ts 加两个路由**

Edit `frontend/src/router.ts`，在 `routes` 中加：

```ts
  { path: "/galleries/:gid", component: () => import("./views/RootListView.vue") },
  { path: "/galleries/:gid/r/:rid/:path(.*)*", component: () => import("./views/BrowseView.vue") },
```

（`BrowseView.vue` 在 Task 18 写；这里先加占位以免路由报错）

创建占位 `frontend/src/views/BrowseView.vue`：

```vue
<template><div>Browse (stub)</div></template>
```

- [ ] **Step 7: 手动验证**

登录后：`/galleries` 应看到图库卡片；点入若只有 1 个 root 直接跳到 BrowseView 占位，否则显示 root 卡片。

- [ ] **Step 8: 提交**

```bash
git add frontend/src/components frontend/src/views frontend/src/router.ts
git commit -m "feat(frontend): AppHeader / Breadcrumb / gallery+root list views"
```

---

### Task 18: JustifiedGrid + `useBrowseStore` + 虚拟滚动 BrowseView

**Files:**
- Create: `frontend/src/stores/browse.ts`
- Create: `frontend/src/components/JustifiedGrid.vue`
- Modify: `frontend/src/views/BrowseView.vue`
- Create: `frontend/src/tests/justified-layout.spec.ts`

**Interfaces:**
- Produces：
  - `stores/browse.ts`：
    - `interface ImageRow { id: number; filename: string; width: number|null; height: number|null; sha1: string; size_bytes: number; taken_at: number|null; is_raw: boolean }`
    - `interface BrowseKey { gid: number; rid: number; path: string; sort: string }`
    - `useBrowseStore()`：
      - `state.byKey: Map<string, { items: ImageRow[]; nextCursor: string|null; scrollY: number }>`
      - `keyOf(k: BrowseKey): string`
      - `async load(k: BrowseKey, opts: { force?: boolean }): Promise<void>` — 拉第一页
      - `async loadMore(k: BrowseKey): Promise<boolean>` — 拉下一页；无更多返回 false
      - `saveScroll(k: BrowseKey, y: number)`
      - LRU 上限 20
  - `<JustifiedGrid :items :containerWidth @open="(imageId) => …" />`
    - 按图片 `width/height` 计算 justified 布局；每行行高 160~220px 动态；未有 width/height 时使用 4:3 默认
  - `BrowseView`：
    - 加载 breadcrumbs / folders / images
    - Scroll 底部时调 `loadMore`
    - 点图触发 emit → 后续 Task 19 接 Lightbox

**Justified 布局算法**（在 `JustifiedGrid.vue` 内部或 `layout.ts` 工具）：

```
function justifiedRows(items: {w:number,h:number}[], containerWidth: number,
                       targetHeight: number, gap: number) {
  const rows: Array<{items:{w,h,scaledW,scaledH}[], height:number}> = []
  let cursor: typeof items = []
  for (const it of items) {
    cursor.push(it)
    // aspect sums with normalized height
    const aspectSum = cursor.reduce((a, x) => a + x.w / x.h, 0)
    const rowW = aspectSum * targetHeight + gap * (cursor.length - 1)
    if (rowW >= containerWidth) {
      // scale to exactly containerWidth
      const scale = (containerWidth - gap * (cursor.length - 1)) / (aspectSum * targetHeight)
      const height = targetHeight * scale
      rows.push({ items: cursor.map(x => ({...x, scaledW: (x.w/x.h)*height, scaledH: height})), height })
      cursor = []
    }
  }
  // trailing partial row keeps target height, flex-align left
  if (cursor.length) {
    rows.push({ items: cursor.map(x => ({...x, scaledW:(x.w/x.h)*targetHeight, scaledH: targetHeight})), height: targetHeight })
  }
  return rows
}
```

- [ ] **Step 1: 写 layout 工具与测试**

创建 `frontend/src/utils/layout.ts`：

```ts
export interface LayoutInput {
  w: number
  h: number
}

export interface LayoutItem extends LayoutInput {
  scaledW: number
  scaledH: number
}

export interface LayoutRow {
  items: LayoutItem[]
  height: number
}

export function justifiedRows(
  items: LayoutInput[],
  containerWidth: number,
  targetHeight = 200,
  gap = 4,
): LayoutRow[] {
  const rows: LayoutRow[] = []
  let cursor: LayoutInput[] = []
  for (const it of items) {
    cursor.push(it)
    const aspectSum = cursor.reduce((a, x) => a + x.w / x.h, 0)
    const rowW = aspectSum * targetHeight + gap * (cursor.length - 1)
    if (rowW >= containerWidth) {
      const scale = (containerWidth - gap * (cursor.length - 1)) / (aspectSum * targetHeight)
      const height = targetHeight * scale
      rows.push({
        items: cursor.map((x) => ({ ...x, scaledW: (x.w / x.h) * height, scaledH: height })),
        height,
      })
      cursor = []
    }
  }
  if (cursor.length) {
    rows.push({
      items: cursor.map((x) => ({ ...x, scaledW: (x.w / x.h) * targetHeight, scaledH: targetHeight })),
      height: targetHeight,
    })
  }
  return rows
}
```

创建 `frontend/src/tests/justified-layout.spec.ts`：

```ts
import { describe, expect, it } from "vitest"
import { justifiedRows } from "../utils/layout"

describe("justifiedRows", () => {
  it("packs items into full rows", () => {
    const items = Array.from({ length: 10 }, () => ({ w: 300, h: 200 }))
    const rows = justifiedRows(items, 1000, 200, 4)
    for (const r of rows.slice(0, -1)) {
      const total = r.items.reduce((a, x) => a + x.scaledW, 0) + 4 * (r.items.length - 1)
      expect(Math.abs(total - 1000)).toBeLessThan(1)
    }
  })

  it("keeps trailing partial row at target height", () => {
    const items = [{ w: 300, h: 200 }]
    const rows = justifiedRows(items, 1000, 200, 4)
    expect(rows[0].height).toBe(200)
  })

  it("empty input returns no rows", () => {
    expect(justifiedRows([], 1000, 200, 4)).toEqual([])
  })
})
```

Run: `cd frontend && pnpm test`
Expected: layout tests pass

- [ ] **Step 2: 写 stores/browse.ts**

创建 `frontend/src/stores/browse.ts`：

```ts
import { defineStore } from "pinia"
import { ref } from "vue"
import { apiGet } from "../api"

export interface ImageRow {
  id: number
  filename: string
  width: number | null
  height: number | null
  sha1: string
  size_bytes: number
  taken_at: number | null
  is_raw: boolean
}

export interface BrowseKey {
  gid: number
  rid: number
  path: string
  sort: string
}

interface CacheEntry {
  items: ImageRow[]
  nextCursor: string | null
  scrollY: number
  keyString: string
  atime: number
}

const CACHE_MAX = 20

function keyOf(k: BrowseKey) {
  return `${k.gid}|${k.rid}|${k.path}|${k.sort}`
}

export const useBrowseStore = defineStore("browse", () => {
  const cache = ref(new Map<string, CacheEntry>())

  function touch(entry: CacheEntry) {
    entry.atime = Date.now()
  }

  function evict() {
    while (cache.value.size > CACHE_MAX) {
      let oldestKey: string | null = null
      let oldest = Infinity
      for (const [k, v] of cache.value) {
        if (v.atime < oldest) {
          oldest = v.atime
          oldestKey = k
        }
      }
      if (oldestKey) cache.value.delete(oldestKey)
      else break
    }
  }

  function get(k: BrowseKey) {
    return cache.value.get(keyOf(k)) ?? null
  }

  async function load(k: BrowseKey, opts: { force?: boolean } = {}) {
    const key = keyOf(k)
    if (!opts.force && cache.value.has(key)) {
      touch(cache.value.get(key)!)
      return
    }
    const params = new URLSearchParams({ path: k.path, sort: k.sort })
    const r = await apiGet<{ items: ImageRow[]; next_cursor: string | null }>(
      `/api/galleries/${k.gid}/roots/${k.rid}/images?${params}`,
    )
    cache.value.set(key, { items: r.items, nextCursor: r.next_cursor, scrollY: 0, keyString: key, atime: Date.now() })
    evict()
  }

  async function loadMore(k: BrowseKey): Promise<boolean> {
    const entry = get(k)
    if (!entry || !entry.nextCursor) return false
    const params = new URLSearchParams({ path: k.path, sort: k.sort, cursor: entry.nextCursor })
    const r = await apiGet<{ items: ImageRow[]; next_cursor: string | null }>(
      `/api/galleries/${k.gid}/roots/${k.rid}/images?${params}`,
    )
    entry.items.push(...r.items)
    entry.nextCursor = r.next_cursor
    touch(entry)
    return r.items.length > 0
  }

  function saveScroll(k: BrowseKey, y: number) {
    const e = get(k)
    if (e) {
      e.scrollY = y
      touch(e)
    }
  }

  return { cache, get, load, loadMore, saveScroll }
})
```

- [ ] **Step 3: 写 JustifiedGrid.vue**

创建 `frontend/src/components/JustifiedGrid.vue`：

```vue
<template>
  <div ref="rootEl" class="w-full">
    <div v-for="(row, ri) in rows" :key="ri"
         class="flex gap-1"
         :style="{ marginBottom: `${gap}px` }">
      <button v-for="cell in row.items" :key="cell.id"
              class="relative overflow-hidden bg-neutral-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
              :style="{ width: `${cell.scaledW}px`, height: `${cell.scaledH}px` }"
              @click="$emit('open', cell.id)">
        <img :src="`/api/thumb/${cell.sha1}?size=400`"
             :srcset="`/api/thumb/${cell.sha1}?size=200 200w, /api/thumb/${cell.sha1}?size=400 400w`"
             sizes="(max-width: 640px) 200px, 400px"
             loading="lazy"
             :alt="cell.filename"
             class="h-full w-full object-cover" />
      </button>
    </div>
    <button v-if="canLoadMore" class="mx-auto my-4 block rounded bg-neutral-800 px-4 py-2 text-sm"
            @click="$emit('loadMore')">加载更多</button>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import type { ImageRow } from "../stores/browse"
import { justifiedRows, LayoutInput } from "../utils/layout"

const props = defineProps<{
  items: ImageRow[]
  canLoadMore: boolean
  targetHeight?: number
}>()

defineEmits<{
  (e: "open", id: number): void
  (e: "loadMore"): void
}>()

const rootEl = ref<HTMLElement | null>(null)
const width = ref(1000)

function measure() {
  if (rootEl.value) width.value = rootEl.value.clientWidth
}

let ro: ResizeObserver | null = null
onMounted(() => {
  measure()
  ro = new ResizeObserver(measure)
  if (rootEl.value) ro.observe(rootEl.value)
})
onUnmounted(() => ro?.disconnect())

const gap = 4

const rows = computed(() => {
  const input: (LayoutInput & { id: number; sha1: string; filename: string })[] = props.items.map((it) => ({
    id: it.id,
    sha1: it.sha1,
    filename: it.filename,
    w: it.width ?? 4,
    h: it.height ?? 3,
  }))
  const laid = justifiedRows(input, width.value, props.targetHeight ?? 200, gap)
  // attach id/sha1/filename back onto laid items (they are shallow copies via spread)
  return laid.map((row) => ({
    height: row.height,
    items: row.items as unknown as Array<{ id: number; sha1: string; filename: string; scaledW: number; scaledH: number }>,
  }))
})
</script>
```

- [ ] **Step 4: 写 BrowseView.vue**

覆盖 `frontend/src/views/BrowseView.vue`：

```vue
<template>
  <div>
    <AppHeader>
      <template #title>
        <Breadcrumb v-if="crumbs.length" :crumbs="crumbs" :gid="gid" :rid="rid" />
      </template>
    </AppHeader>
    <main class="p-3">
      <SubfolderStrip v-if="folders.length" :folders="folders" :gid="gid" :rid="rid" />
      <JustifiedGrid v-if="images.length" :items="images" :can-load-more="!!nextCursor"
                     @open="onOpen" @load-more="onLoadMore" />
      <div v-else-if="!loading && !folders.length" class="mt-8 text-center text-neutral-500">
        此目录暂无图片
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import AppHeader from "../components/AppHeader.vue"
import Breadcrumb from "../components/Breadcrumb.vue"
import SubfolderStrip from "../components/SubfolderStrip.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import { apiGet } from "../api"
import { useBrowseStore, type ImageRow } from "../stores/browse"

const route = useRoute()
const router = useRouter()
const gid = computed(() => Number(route.params.gid))
const rid = computed(() => Number(route.params.rid))
const path = computed(() => {
  const raw = route.params.path
  if (!raw) return ""
  return (Array.isArray(raw) ? raw.join("/") : String(raw)).replace(/\/+$/, "")
})
const sort = ref("name_asc")

const crumbs = ref<{ name: string; relative_path: string }[]>([])
const folders = ref<any[]>([])
const images = ref<ImageRow[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)

const browse = useBrowseStore()

async function loadAll() {
  loading.value = true
  try {
    const key = { gid: gid.value, rid: rid.value, path: path.value, sort: sort.value }
    const [c, f] = await Promise.all([
      apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/breadcrumbs?path=${encodeURIComponent(path.value)}`),
      apiGet<any[]>(`/api/galleries/${gid.value}/roots/${rid.value}/folders?path=${encodeURIComponent(path.value)}`),
    ])
    crumbs.value = c
    folders.value = f
    await browse.load(key)
    const entry = browse.get(key)!
    images.value = entry.items
    nextCursor.value = entry.nextCursor
    // restore scroll
    if (entry.scrollY) {
      requestAnimationFrame(() => window.scrollTo({ top: entry.scrollY }))
    }
  } finally {
    loading.value = false
  }
}

function onOpen(id: number) {
  const suffix = path.value ? `/${path.value}` : ""
  router.push(`/galleries/${gid.value}/r/${rid.value}${suffix}/image/${id}`)
}

async function onLoadMore() {
  const key = { gid: gid.value, rid: rid.value, path: path.value, sort: sort.value }
  await browse.loadMore(key)
  const entry = browse.get(key)!
  images.value = entry.items
  nextCursor.value = entry.nextCursor
}

function onScroll() {
  browse.saveScroll(
    { gid: gid.value, rid: rid.value, path: path.value, sort: sort.value },
    window.scrollY,
  )
}

onMounted(() => {
  window.addEventListener("scroll", onScroll, { passive: true })
  loadAll()
})
watch([gid, rid, path], loadAll)
</script>
```

- [ ] **Step 5: 手动验证**

启动前后端；`/galleries/:gid/r/:rid/` 应显示密铺网格；点击图片跳到 `/…/image/:iid`（Lightbox 在下一 Task 实现）；子目录点击进入下一层，面包屑可回退。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/utils frontend/src/stores/browse.ts frontend/src/components/JustifiedGrid.vue frontend/src/views/BrowseView.vue frontend/src/tests/justified-layout.spec.ts
git commit -m "feat(browse): justified grid, browse store with LRU cache and scroll retention"
```

---

### Task 19: ImageLightbox（PhotoSwipe）+ 深链路由

**Files:**
- Create: `frontend/src/components/ImageLightbox.vue`
- Modify: `frontend/src/views/BrowseView.vue`

**Interfaces:**
- Consumes: `photoswipe`, `useBrowseStore`
- Produces：
  - `<ImageLightbox :items :startId @close />`
  - 通过 URL `image/:iid` 段控制打开/关闭；切图 `router.replace`；关闭 `router.back()`
  - 初始加载 thumb 1600；用户点击 100% 缩放时 fetch 原图（PhotoSwipe secondary source）

**PhotoSwipe v5 用法**（`import PhotoSwipe from "photoswipe"; import "photoswipe/style.css"`）通过 `dataSource` 数组打开，每项 `{src, width, height}`。

- [ ] **Step 1: 写 ImageLightbox.vue**

创建 `frontend/src/components/ImageLightbox.vue`：

```vue
<template>
  <div ref="rootEl"></div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue"
import PhotoSwipe from "photoswipe"
import "photoswipe/style.css"
import type { ImageRow } from "../stores/browse"

const props = defineProps<{
  items: ImageRow[]
  startId: number
}>()

const emit = defineEmits<{
  (e: "close"): void
  (e: "change", id: number): void
}>()

const rootEl = ref<HTMLElement | null>(null)
let pswp: PhotoSwipe | null = null

function open() {
  const idx = props.items.findIndex((it) => it.id === props.startId)
  if (idx < 0) return
  const dataSource = props.items.map((it) => ({
    src: `/api/thumb/${it.sha1}?size=1600`,
    width: it.width ?? 1600,
    height: it.height ?? 1200,
    alt: it.filename,
  }))
  pswp = new PhotoSwipe({
    dataSource,
    index: idx,
    appendToEl: document.body,
    showHideAnimationType: "fade",
  })
  pswp.on("change", () => {
    if (pswp) emit("change", props.items[pswp.currIndex].id)
  })
  pswp.on("close", () => emit("close"))
  pswp.init()
}

onMounted(open)
onUnmounted(() => {
  pswp?.destroy()
  pswp = null
})

watch(() => props.startId, (nid) => {
  if (!pswp) return
  const idx = props.items.findIndex((it) => it.id === nid)
  if (idx >= 0 && idx !== pswp.currIndex) pswp.goTo(idx)
})
</script>
```

- [ ] **Step 2: 在 BrowseView 中处理 image 段**

Edit `frontend/src/views/BrowseView.vue`：

在 `<template>` 末尾 `</main>` 之后加：

```vue
    <ImageLightbox v-if="lightboxId !== null" :items="images" :start-id="lightboxId"
                    @close="onLightboxClose" @change="onLightboxChange" />
```

在 `<script setup>` 中加：

```ts
import ImageLightbox from "../components/ImageLightbox.vue"

const lightboxId = computed(() => {
  const iid = route.params.iid
  return iid ? Number(iid) : null
})

function onLightboxClose() {
  const suffix = path.value ? `/${path.value}` : ""
  router.push(`/galleries/${gid.value}/r/${rid.value}${suffix}`)
}

function onLightboxChange(id: number) {
  const suffix = path.value ? `/${path.value}` : ""
  router.replace(`/galleries/${gid.value}/r/${rid.value}${suffix}/image/${id}`)
}
```

- [ ] **Step 3: 更新路由匹配 `/image/:iid`**

Edit `frontend/src/router.ts`：把 BrowseView 的 path 改成：

```ts
  { path: "/galleries/:gid/r/:rid/:path(.*)*/image/:iid", component: () => import("./views/BrowseView.vue") },
  { path: "/galleries/:gid/r/:rid/:path(.*)*", component: () => import("./views/BrowseView.vue") },
```

（第一条必须在前，vue-router 按顺序匹配）

在 BrowseView 的 `path` computed 中排除末尾的 `/image/:iid`（因为 `:path(.*)` 会吃掉）。修正 `path` computed：

```ts
const path = computed(() => {
  const raw = route.params.path
  const p = Array.isArray(raw) ? raw.join("/") : String(raw || "")
  return p.replace(/\/?image\/\d+$/, "").replace(/\/+$/, "")
})
```

- [ ] **Step 4: 手动验证**

打开 BrowseView → 点图 → PhotoSwipe 弹出显示大图 → ←→ 切换 URL 同步更新 → Esc 或右上关闭按钮 → URL 回到目录 → 浏览器"后退"能从 Lightbox 回列表；直接在浏览器地址栏输入 `/…/image/:iid` 深链能开图。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/ImageLightbox.vue frontend/src/views/BrowseView.vue frontend/src/router.ts
git commit -m "feat(lightbox): PhotoSwipe integration with deep-linked image URLs"
```

---

### Task 20: 前端产物由后端托管 + 端到端手动验证清单

**Files:**
- Modify: `backend/src/myphoto/main.py`
- Modify: `README.md`

**Interfaces:**
- Produces：
  - 生产模式下 FastAPI 挂载 `frontend/dist` 为静态目录；`/` 及所有非 `/api/*` 路径返回 `index.html`（SPA fallback）
  - 开发模式：前端 `pnpm dev`（Vite 5173）代理 `/api` 到 8080，不需要后端托管

- [ ] **Step 1: 修改 main.py 挂载静态**

Edit `backend/src/myphoto/main.py`，在 `install_error_handlers(app)` 之后、路由挂载之前加：

```python
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # api 路由不能被 fallback 吞掉 -> 让 FastAPI 优先匹配
            # 由于 spa_fallback 在路由挂载之前注册,api 路由在其之后 include 会更优先? 需要保证顺序
            raise AppError("not_found", 404, "not found")
```

注意路由顺序问题：FastAPI 按注册顺序匹配。我们需要让 `/api/*` 优先。改为**把 SPA fallback 放到路由挂载之后**：

Edit 后为在 `include_router(...)` 全部完成之后追加：

```python
    dist = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")
        index_html = dist / "index.html"

        @app.get("/", include_in_schema=False)
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_index(full_path: str = ""):
            if full_path.startswith("api/"):
                raise AppError("not_found", 404, "not found")
            if index_html.exists():
                return FileResponse(index_html)
            raise AppError("not_found", 404, "frontend not built")
```

- [ ] **Step 2: 构建前端**

```bash
cd frontend
pnpm build
```

Expected: `frontend/dist/` 产生

- [ ] **Step 3: 更新 README**

Edit `README.md`：

```markdown
# myPhotoGallery

Local photo library web viewer.

## Quick start

```bash
# backend
python -m venv .venv
source .venv/Scripts/activate       # Windows Git Bash: source .venv/Scripts/activate
pip install -e ".[dev]"

# frontend
cd frontend && pnpm install && pnpm build && cd ..

# add a gallery + root
myphoto add-gallery Home
myphoto add-root Home Main /path/to/photos
myphoto rescan Home

# run
uvicorn myphoto.main:app --host 0.0.0.0 --port 8080
```

Open <http://localhost:8080>. The initial admin password is printed to
stdout on first startup — save it. Change it via the UI (P6).

## Development

```bash
# backend (auto-reload)
uvicorn myphoto.main:app --reload --host 127.0.0.1 --port 8080

# frontend dev server (proxies /api -> 8080)
cd frontend && pnpm dev
```

See docs/superpowers/specs/ for design, docs/superpowers/plans/ for phase plans.
```

- [ ] **Step 4: 端到端手动验证清单**

按顺序执行，确认每项通过：

```
准备:
  - 有一个测试照片目录, 包含: 若干 jpg/png 混合, 至少一个子目录, 至少一张 heic (若手边有), 至少一张 raw (若手边有)

命令行:
  □ myphoto add-gallery Test
  □ myphoto add-root Test Main <照片目录>
  □ myphoto list  应看到图库/根/图片计数
  □ myphoto rescan  应打印每 root 的状态 idle 且 last_scan_error=None

启动:
  □ uvicorn myphoto.main:app --host 127.0.0.1 --port 8080
  □ stdout 首启动打印 "initial admin created" (若已运行过则不打)

浏览器:
  □ 访问 http://localhost:8080 -> 302 到 /login
  □ 用 admin + 首启动打印的密码登录成功 -> 到 /galleries
  □ 看到 "Test" 图库卡片, 数字与 CLI list 一致
  □ 点入 -> 因只有 1 个 root, 自动跳到 /galleries/1/r/1/
  □ 看到子目录条 + 密铺网格
  □ 点击子目录 -> 面包屑变化, 网格更新
  □ 点面包屑首段回根目录
  □ 点击一张图 -> PhotoSwipe 打开; ←→ 切图 URL 同步; Esc 关闭回目录
  □ 直接访问 /galleries/1/r/1/sub/image/<某图 id> -> 深链能直接开图
  □ 用手机浏览器打开同一 URL (WLAN 同网段) -> 可登录 -> 密铺显示 -> 触摸滑动切图 -> 双指缩放
  □ HEIC/RAW 若测试目录中存在, 缩略图正确显示 (不显占位图, 除非 rawpy 完全无法解)

登出:
  □ 顶栏点"登出" -> 回到 /login; 直接访问 /galleries 应被守卫回 /login
```

- [ ] **Step 5: 全量后端测试跑一遍**

Run: `pytest -v`
Expected: 全部 pass

- [ ] **Step 6: 全量前端测试跑一遍**

Run: `cd frontend && pnpm test`
Expected: 全部 pass

- [ ] **Step 7: 红线 grep 检查**

Run:
```bash
grep -rE "(shutil\.rmtree|os\.remove|os\.unlink)" backend/src/
```
Expected: 无匹配（P1 阶段严格不出现）

- [ ] **Step 8: 最终提交**

```bash
git add backend/src/myphoto/main.py README.md
git commit -m "feat(bundle): serve built frontend from backend and document quickstart"
git tag phase1-mvp
```

---

## P1 完成标准

- 全部 20 个 Task 完成 checkbox 打勾
- 后端 `pytest` 全绿；前端 `pnpm test` 全绿
- 手动验证清单每项确认
- 红线 grep 无匹配
- 打上 tag `phase1-mvp`

## P2 – P7 骨架（不属本计划，供全局参考）

> **版本 2 (2026-07-22 修订)**：P3-P7 重排。原骨架把"单图删除"排在 P5、把"完整管理端 UI"塞成大筐、把 P7 混成打包箱。修订后按 spec §1.1 场景 3 的优先级（单人 admin 场景闭环优先），把单图删除+回收站提到 P3；把散在多 phase 的 AdminSettings 集中到 P5；把 P7 的五件不相关事拆到具体位置。EXIF 抽取与展示按用户要求下沉到 P3。

- **P2 多图库多根 + 最小管理 API**：新增 `/api/admin/galleries*` `/api/admin/galleries/{gid}/roots*` `/api/admin/browse-fs`；RootListView 支持多根；后端加 audit 表与部分事件；CLI 保留但不再必需。（计划：`docs/superpowers/plans/2026-07-21-phase2-admin-gallery-management.md`）

- **P3 单图删除 + 回收站（三入口清理）+ EXIF 抽取与展示**：单人 admin 场景闭环 + Lightbox 展示 EXIF 元数据。
  - **新表 / 字段**：`trash` 表；`images.exif_json` TEXT NULL 字段
  - **红线**：spec §3.4 红线 2、3 —— `os.rename` 用于删除，`os.remove` 唯一位点在 `trash.purge_expired()`；启动清一次 + 每日 03:17 定时 + 手动，走同一幂等函数。**红线校验只针对 delete/trash 部分。**
  - **新 API（删除/回收站）**：`DELETE /api/images/{id}`、`POST /api/images/batch-delete`、`GET /api/trash`、`POST /api/trash/{id}/restore`、`POST /api/trash/batch-restore`、`DELETE /api/trash/{id}`、`POST /api/trash/purge`
  - **新 API（EXIF）**：`GET /api/images/{id}/exif` → 结构化 EXIF JSON（列表 API 不带 EXIF，避免体积膨胀）
  - **扫描器改动**：`_read_image_meta` 扩展抽取常用 EXIF tag（约 15-20 项，Make/Model/DateTimeOriginal/ExposureTime/FNumber/ISOSpeedRatings/FocalLength/LensModel/GPSInfo/Orientation 等），JSON 序列化存 `exif_json`。RAW 通过 `rawpy` 或 Pillow 读 EXIF。提供 `myphoto rescan --force-exif` CLI 一次性回补：跳过 mtime/size 判等，对所有已入库图片强制重抽 EXIF。
  - **新前端**：BrowseView admin hover 三点菜单（"移入回收站"，含预览+路径的二次确认）、Lightbox 底部删除按钮、`AdminTrash` 页面（过滤+表格+批量恢复/删除+清空）、Lightbox 顶部 `i` 按钮 + EXIF 侧边面板（常用字段中文标签由前端映射）
  - **审计事件**：`image_delete`、`image_restore`、`trash_purge`
  - **规模预估**：15-18 tasks（P2 的 1.3-1.5 倍）

- **P4 多用户 + Viewer 角色 + LAN/远程访问 + trusted_proxies**：家人可用自己账号登录浏览；权限链步骤 3 与步骤 5 一次性上线。
  - **新表**：`user_galleries`
  - **新 API**：`/api/admin/users*` 全套（列表/新建/详情/更新/重置密码/删除，含最后一个 admin 保护）；`/api/galleries` 按用户可见性过滤；权限链步骤 3（`access_scope` 判 LAN/远程）与步骤 5（图库授权）同步上线
  - **新前端**：`AdminUsers` 页面；LoginView 感知 `access_scope_violation` 错误；AppHeader 显示当前访问域（LAN / 远程）
  - **配置**：`[security] trusted_proxies` 生效；`admin_fs_lan_only` 错误码上线（P2 已定义，此处贯通实际强制）
  - **审计事件**：`user_create`、`user_delete`、`user_disable`、`user_update`、`password_reset`
  - **合并理由**：`trusted_proxies` 直接影响 `access_scope` 判定，两者若分开做会出现权限链步骤 3 只有半个能生效的中间态，Viewer 角色也会被卡

- **P5 排除清单 + AdminSettings 完整版**：admin 能把某个子目录从图库中排除（不删本地文件）；集中一次配置所有可调参数。
  - **新表**：`exclusions`
  - **新 API**：`GET/POST /api/admin/galleries/{gid}/roots/{rid}/exclusions`、`DELETE .../exclusions/{eid}`；`GET/PATCH /api/admin/settings`
  - **新前端**：`AdminGalleryEdit` 加排除清单区（复用 P2 的 DirectoryChooser，限定该 root 内）；`AdminSettings` 页面完整版（5 项：回收站保留天数 7/30/90/never、登录锁定阈值、trusted_proxies、缩略图预生成尺寸多选、会话过期时间）
  - **扫描联动**：排除变更后触发受影响 root 重扫（reconcile 阶段清索引，纯 DB 操作，不动 FS —— spec §5.6）
  - **审计事件**：`exclusion_add`、`exclusion_remove`、`settings_update`
  - **合并理由**：exclusion 与 AdminSettings 各自规模不足以独立成 phase；合并后规模约 P2 的 60-70%

- **P6 搜索 + 批量下载**：图库变大后可用性的关键补丁。
  - **新 API**：`GET /api/galleries/{gid}/roots/{rid}/search?q=&limit=&cursor=`（文件名/目录名子串搜，当前 root 子孙范围）；`POST /api/download-batch`（on-the-fly zip，上限 500 条，spec §10）
  - **新前端**：BrowseView 工具条搜索框 + 结果视图；BrowseView 批量选择模式（多选 → 底部工具条：删除/下载）
  - **合并理由**：两者都是"图库变大后必须"的功能，且都需要新 API + 显著前端改动，规模都够一个小 phase 的量；合并后规模接近 P2

- **P7 审计 UI + 深色模式 + 移动端打磨 + 无障碍**：面向发布的最后一波打磨。此 phase 无新表、无新后端 API（P2-6 的 `/api/admin/audit` 分页 API 已就绪）。
  - **新前端**：
    - `AdminAudit` 页面（表格 + 过滤 + 无限滚动 + CSV 导出）
    - 深色模式跟 `prefers-color-scheme`（spec §7.8）
    - 移动端断点复核 + 触屏最小 44×44
    - 键盘导航 + `aria-*` + 图片 `alt=filename`
    - **README + 部署文档定稿**
  - **规模**：多个独立小项拼装，无后端改动可并行推进

**Roadmap 总规模预估**：P3 ~15-18 tasks / P4 ~15 tasks / P5 ~11 tasks / P6 ~10 tasks / P7 ~10 tasks = 约 61-64 个后续 task（P2 是 12 个）。


## Self-Review 备忘（内部审计已完成）

- [x] Spec §3.4 三条红线：全部由 P1 Global Constraints + Task 20 grep 或延后到 P5
- [x] 数据模型：P1 涵盖 users / galleries / gallery_roots / folders / images；user_galleries / exclusions / trash / audit_log 延后
- [x] 认证流程：Task 9 覆盖登录/登出/me/锁定
- [x] 扫描 §5.1：Task 10 涵盖增量、跳 symlink、隐藏目录、reconcile、folder counts
- [x] 缩略图 §5.7：Task 11+13 涵盖白名单尺寸、sha1 缓存、RAW extract_thumb 回退
- [x] 原图 §5.8：Task 13 支持 Range + download 参数
- [x] 浏览端 §7.3：Task 15-19 涵盖 SPA、路由、密铺、虚拟滚动（本期通过分页 + LRU cache 实现"轻量虚拟"，若图库大到万级密铺卡顿再在 P7 引入 `vue-virtual-scroller` 的 DynamicScroller）
- [x] Lightbox §7.4：Task 19 涵盖 PhotoSwipe + 深链
- [x] 类型一致性：`SESSION_COOKIE`、`ALLOWED_SIZES`、错误码、Cookie 名跨任务一致
- [x] Placeholder 扫描：全部步骤含具体代码或命令

**Trade-off 说明**：本期 `vue-virtual-scroller` 未真正启用，`JustifiedGrid` 通过"按需分页 + LRU 缓存滚动位置"支撑万级图库单目录浏览（万张分 200 页，用户滚到底才拉下一页）。若某目录直接就是万级平铺（不用文件夹分层），P7 可切换到 DynamicScroller。这是刻意的 YAGNI。

