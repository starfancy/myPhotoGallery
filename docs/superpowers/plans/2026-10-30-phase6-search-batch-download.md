# P6 搜索 + 批量下载 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 root 内文件名/文件夹名子串搜索、跨页多选批量下载 ZIP（票据两步式流式打包），并把批量下载上限做成 10–200 可配置（默认 100）。

**Architecture:** 后端新增 `GET .../search`（LIKE 子串 + keyset 分页 + 文件夹固定 50 条）与 `routes_download.py`（POST 鉴权解析后签发 5 分钟一次性内存 ticket；GET 用 `queue.Queue` + 写线程把 `zipfile` 流式输出，ZIP_STORED/force_zip64，服务端零落地）。前端新增 SearchBox/SearchResults 组件，BrowseView 增加搜索态（query 持久化到路由）、选择集跨页累积（硬上限 200）、票据锚点下载，ImageLightbox 加可选的目录标注/跳转钩子，AdminSettings 加批量下载上限。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (async) + aiosqlite + Pydantic v2 + pytest；Vue 3 `<script setup>` + Pinia + vue-router + vitest/@vue/test-utils + Tailwind/UnoCSS 工具类；PhotoSwipe v5。

## Global Constraints

- 设计唯一权威：`docs/superpowers/specs/2026-10-30-phase6-search-batch-download-design.md`。
- 错误响应必须走统一信封 `{"error":{"code","message"}}` + `AppError(code, http_status, message)`；本期新错误码只有一个：`batch_too_large`（400）。
- UI 文案一律中文；时间戳 Unix 秒；路径一律 posix 相对路径。
- 后端测试（repo 根目录）：`pytest`；单文件：`pytest backend/tests/test_xxx.py -v`。
- 前端（`frontend/`）：`pnpm test`、`pnpm build`（含 `vue-tsc --noEmit`，每个前端 task 后都要过）。
- TDD：先写失败测试 → 跑红 → 最小实现 → 跑绿 → commit。
- 在分支 `phase6-search-download` 上开发；**不要 `git push`**（本机 GitHub 直连被重置，用户走代理手动推）。
- 不改批量删除 API 的 500 上限；下载不写审计。
- 测试基线：后端 461 passed / 6 skipped；前端 203 passed。

## File Structure

新增：

- `backend/src/myphoto/routes_download.py` — TicketStore、arcname 纯函数、POST/GET 路由、ZIP 流式管道
- `backend/tests/test_routes_search.py`、`backend/tests/test_phase6_download_limit.py`、`backend/tests/test_routes_download.py`
- `frontend/src/components/SearchBox.vue`、`frontend/src/components/SearchResults.vue`
- `frontend/src/tests/search-box.spec.ts`、`lightbox-location.spec.ts`、`search-results.spec.ts`、`browse-selection-download.spec.ts`、`browse-search.spec.ts`

修改：

- backend：`config.py`、`config_writer.py`、`routes_admin.py`、`routes_auth.py`、`routes_browse.py`、`main.py`
- frontend：`api.ts`、`stores/browse.ts`、`stores/auth.ts`、`PhotoCell.vue`、`JustifiedGrid.vue`、`MasonryGrid.vue`、`ImageLightbox.vue`、`BrowseView.vue`、`AdminSettings.vue`、`tests/browse-view-delete.spec.ts`、`tests/admin-settings.spec.ts`

---

### Task 1: 下载上限配置（config / settings API / auth payload）

**Files:**
- Modify: `backend/src/myphoto/config.py`
- Modify: `backend/src/myphoto/config_writer.py`
- Modify: `backend/src/myphoto/routes_admin.py`（SettingsPatch / payload / validate / PATCH）
- Modify: `backend/src/myphoto/routes_auth.py`（login + me）
- Test: `backend/tests/test_phase6_download_limit.py`

**Interfaces:**
- Produces: `AppConfig.download_batch_limit: int`（10–200，默认 100）；`GET /api/auth/me` 与 login 响应 user 对象含 `download_batch_limit`；`GET/PATCH /api/admin/settings` 含 `download_batch_limit`；config.toml 键为 `[download] batch_limit`。

- [ ] **Step 1: 建分支**

```bash
git checkout -b phase6-search-download
```

- [ ] **Step 2: 写失败测试** `backend/tests/test_phase6_download_limit.py`：

```python
import re
import tomllib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from myphoto.config import load_or_init
from myphoto.config_writer import SettingsUpdates, update_settings_file
from myphoto.main import build_app
from myphoto.models import AuditLog


@pytest.fixture
def client(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        r = c.post("/api/auth/login", json={"username": "admin", "password": pw})
        assert r.status_code == 200
        yield c, app, cfg


def test_default_limit_is_100(client):
    c, _, _ = client
    assert c.get("/api/admin/settings").json()["download_batch_limit"] == 100
    me = c.get("/api/auth/me").json()
    assert me["download_batch_limit"] == 100


def test_patch_limit_hot_reloads_and_audits(client):
    c, app, _ = client

    r = c.patch("/api/admin/settings", json={"download_batch_limit": 50})
    assert r.status_code == 200
    assert r.json()["download_batch_limit"] == 50
    assert c.get("/api/auth/me").json()["download_batch_limit"] == 50

    async def _last_audit():
        async with app.state.sessionmaker() as s:
            row = (
                await s.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1))
            ).scalar_one()
            return row.action, row.detail

    action, detail = c.portal.call(_last_audit)
    assert action == "settings_update"
    assert "download_batch_limit" in detail


@pytest.mark.parametrize("bad", [9, 201, 0, -5])
def test_patch_rejects_out_of_range(client, bad):
    c, _, _ = client
    r = c.patch("/api/admin/settings", json={"download_batch_limit": bad})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request"


def test_loader_defaults_when_section_missing(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[app]\njwt_secret = "x"\n', encoding="utf-8")
    assert load_or_init(cfg).download_batch_limit == 100


def test_loader_clamps_out_of_range_and_bad_type(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[app]\njwt_secret = "x"\n[download]\nbatch_limit = 999\n',
        encoding="utf-8",
    )
    assert load_or_init(cfg).download_batch_limit == 200

    cfg.write_text(
        '[app]\njwt_secret = "x"\n[download]\nbatch_limit = 1\n',
        encoding="utf-8",
    )
    assert load_or_init(cfg).download_batch_limit == 10

    cfg.write_text(
        '[app]\njwt_secret = "x"\n[download]\nbatch_limit = "oops"\n',
        encoding="utf-8",
    )
    assert load_or_init(cfg).download_batch_limit == 100


def test_writer_appends_download_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[app]\nlisten_port = 8080\n', encoding="utf-8")
    update_settings_file(p, SettingsUpdates(download_batch_limit=42))
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["download"]["batch_limit"] == 42


def test_fresh_config_template_contains_download_section(tmp_path):
    cfg = tmp_path / "config.toml"
    load_or_init(cfg)  # 首次初始化写出模板
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data["download"]["batch_limit"] == 100
```

- [ ] **Step 3: 跑红**

`pytest backend/tests/test_phase6_download_limit.py -v`
Expected: FAIL（`download_batch_limit` 不存在 / KeyError）。

- [ ] **Step 4: 实现 config.py**

加 logger（文件顶部 import 区）：

```python
import logging
```

模块级（`PROJECT_ROOT` 附近）：

```python
log = logging.getLogger("myphoto.config")
```

`AppConfig` dataclass 末尾加字段：

```python
    # [download] section
    download_batch_limit: int  # 单次批量下载 ZIP 图片数上限，合法 10–200，默认 100
```

`_DEFAULT_TEMPLATE` 在 `[security]` 段之后、`[scanner]` 段之前插入：

```toml
[download]
# 单次批量下载 ZIP 的图片数量上限（10–200），对所有用户生效
batch_limit = 100

```

`load_or_init()` 中 section 读取处加：

```python
    download_section = data.get("download", {})
```

紧接着 hash_workers 解析块之后，加：

```python
    # [download] batch_limit：缺失=100；非法类型回退 100；越界钳到 [10,200]。
    # 故意钳制而非报错：手改 config.toml 不应导致启动失败，也避开
    # P5 retention 枚举值“手改后设置页保存必 400”的别扭。
    raw_limit = download_section.get("batch_limit", 100)
    try:
        download_batch_limit = int(raw_limit)
    except (TypeError, ValueError):
        log.warning("invalid [download].batch_limit=%r; falling back to 100", raw_limit)
        download_batch_limit = 100
    if not 10 <= download_batch_limit <= 200:
        clamped = min(200, max(10, download_batch_limit))
        log.warning(
            "[download].batch_limit=%s out of range 10-200; clamped to %s",
            download_batch_limit, clamped,
        )
        download_batch_limit = clamped
```

返回的 `AppConfig(...)` 末尾加参数：

```python
        download_batch_limit=download_batch_limit,
```

- [ ] **Step 5: 实现 config_writer.py**

`_FIELD_MAP` 加一行：

```python
    "download_batch_limit": ("download", "batch_limit"),
```

`SettingsUpdates` 加字段：

```python
    download_batch_limit: int | None = None
```

- [ ] **Step 6: 实现 routes_admin.py settings**

`SettingsPatch` 加：

```python
    download_batch_limit: int | None = None
```

`_settings_payload` 加：

```python
        "download_batch_limit": cfg.download_batch_limit,
```

`_validate_settings` 加：

```python
    if body.download_batch_limit is not None and not (
        10 <= body.download_batch_limit <= 200
    ):
        errors.append("download_batch_limit must be between 10 and 200")
```

PATCH handler 中 `SettingsUpdates(...)` 加参数：

```python
        download_batch_limit=body.download_batch_limit,
```

`changed` 元组加一行：

```python
            ("download_batch_limit", body.download_batch_limit),
```

- [ ] **Step 7: 实现 routes_auth.py login + me**

login 成功响应的 user dict 加一行：

```python
                    "download_batch_limit": cfg.download_batch_limit,
```

`me` 端点改为接收 request 并输出该字段：

```python
@router.get("/me")
async def me(request: Request, user: User = Depends(current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "access_scope": user.access_scope,
        "download_batch_limit": request.app.state.config.download_batch_limit,
    }
```

（`Request` 已在该文件 import。）

- [ ] **Step 8: 跑绿 + 全量回归**

```bash
pytest backend/tests/test_phase6_download_limit.py -v
pytest
```

Expected: 新测试全绿；全量后端无回归（应为 461 + 新增数 passed）。

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(download): configurable batch_limit (10-200, default 100)"
```

---

### Task 2: 搜索 API（routes_browse.py）

**Files:**
- Modify: `backend/src/myphoto/routes_browse.py`
- Test: `backend/tests/test_routes_search.py`

**Interfaces:**
- Produces: `GET /api/galleries/{gid}/roots/{rid}/search?q=&path=&limit=&cursor=` →
  `{q, path, folders: FolderHit[], folders_truncated: bool, images: (ImageRow+relative_path)[], next_cursor: str|null}`；模块级工具 `_escape_like(term)`、`_subtree_clause(column, p)`、`_image_payload(r)`。

- [ ] **Step 1: 写失败测试** `backend/tests/test_routes_search.py`：

```python
import re
import time
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient

from myphoto.main import build_app


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (50, 40), (10, 20, 30)).save(p, "JPEG")


def _build(tmp_path, capsys, files):
    photos = tmp_path / "photos"
    for f in files:
        _jpg(photos / f)
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    c_cm = TestClient(app)
    c = c_cm.__enter__()
    out = capsys.readouterr().out
    pw = re.search(r"password=(\S+)", out).group(1)
    c.post("/api/auth/login", json={"username": "admin", "password": pw})

    from myphoto.models import Gallery, GalleryRoot

    async def _seed():
        async with app.state.sessionmaker() as s:
            g = Gallery(name="G", created_at=int(time.time()))
            s.add(g)
            await s.flush()
            r = GalleryRoot(
                gallery_id=g.id, label="R",
                absolute_path=str(photos.resolve()), enabled=1,
            )
            s.add(r)
            await s.commit()
            await s.refresh(r)
            return g.id, r.id

    gid, rid = c.portal.call(_seed)
    c.portal.call(app.state.scanner.scan_root_now, rid)
    return c, app, c_cm, gid, rid


# 51 个 tripXX 文件夹（命中截断）+ 各种匹配用例
FILES = (
    [f"trip{i:02d}/p.jpg" for i in range(51)]
    + ["apple.JPG", "a_b.jpg", "axb.jpg", "a%b.jpg"]
    + ["旅行/照片.jpg"]
    + ["x/hit.jpg", "y/hit.jpg"]
    + [f"page/ma{i}.jpg" for i in range(6)]
)


@pytest.fixture
def env(tmp_path, capsys):
    c, app, c_cm, gid, rid = _build(tmp_path, capsys, FILES)
    yield c, app, gid, rid
    c_cm.__exit__(None, None, None)


def search(c, gid, rid, **params):
    return c.get(f"/api/galleries/{gid}/roots/{rid}/search", params=params)


def test_ascii_case_insensitive(env):
    c, _, gid, rid = env
    r = search(c, gid, rid, q="APPLE")
    assert r.status_code == 200
    names = [i["filename"] for i in r.json()["images"]]
    assert names == ["apple.JPG"]


def test_underscore_is_literal(env):
    c, _, gid, rid = env
    names = [i["filename"] for i in search(c, gid, rid, q="a_b").json()["images"]]
    assert names == ["a_b.jpg"]  # 不能命中 axb.jpg


def test_percent_is_literal(env):
    c, _, gid, rid = env
    names = [i["filename"] for i in search(c, gid, rid, q="a%b").json()["images"]]
    assert names == ["a%b.jpg"]


def test_chinese_hits_folder_and_photo(env):
    c, _, gid, rid = env
    body = search(c, gid, rid, q="旅行").json()
    assert [f["name"] for f in body["folders"]] == ["旅行"]
    assert body["images"] == []

    body = search(c, gid, rid, q="照片").json()
    assert body["images"][0]["relative_path"] == "旅行/照片.jpg"


def test_subtree_scoping(env):
    c, _, gid, rid = env
    body = search(c, gid, rid, q="hit", path="x").json()
    assert [i["relative_path"] for i in body["images"]] == ["x/hit.jpg"]
    # 子树根自身即使名字命中也不出现在文件夹结果里
    assert body["folders"] == []


def test_subtree_root_covers_whole_root(env):
    c, _, gid, rid = env
    body = search(c, gid, rid, q="hit").json()
    assert sorted(i["relative_path"] for i in body["images"]) == [
        "x/hit.jpg", "y/hit.jpg",
    ]


def test_folder_results_capped_at_50(env):
    c, _, gid, rid = env
    body = search(c, gid, rid, q="trip").json()
    assert len(body["folders"]) == 50
    assert body["folders_truncated"] is True


def test_image_rows_carry_relative_path_and_folder_cover(env):
    c, _, gid, rid = env
    item = search(c, gid, rid, q="照片").json()["images"][0]
    assert {"id", "filename", "width", "height", "sha1", "size_bytes",
            "taken_at", "mtime", "is_raw", "relative_path"} <= set(item)
    folder = search(c, gid, rid, q="旅行").json()["folders"][0]
    assert set(folder) == {
        "name", "relative_path", "image_count",
        "descendant_count", "cover_thumb_sha1",
    }
    assert folder["cover_thumb_sha1"]  # 旅行 自身含图 → 有封面


def test_cursor_pagination_walks_all(env):
    c, _, gid, rid = env
    seen = []
    cursor = None
    for _ in range(10):
        params = {"q": "ma", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = search(c, gid, rid, **params).json()
        seen.extend(i["filename"] for i in body["images"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == [f"ma{i}.jpg" for i in range(6)]


def test_empty_query_rejected(env):
    c, _, gid, rid = env
    assert search(c, gid, rid, q="   ").status_code == 400


def test_path_traversal_rejected(env):
    c, _, gid, rid = env
    r = search(c, gid, rid, q="a", path="../..")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "path_invalid"


def test_missing_folder_is_empty(env):
    c, _, gid, rid = env
    body = search(c, gid, rid, q="a", path="no-such-dir").json()
    assert body["images"] == [] and body["folders"] == []


def test_unauthenticated_blocked(tmp_path):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        r = c.get("/api/galleries/1/roots/1/search", params={"q": "a"})
        assert r.status_code == 401


def test_viewer_unauthorized_gallery_404(env):
    c, app, gid, rid = env
    from myphoto.models import User
    from myphoto.security import hash_password

    async def _mk_viewer():
        async with app.state.sessionmaker() as s:
            s.add(User(
                username="v", password_hash=hash_password("vpw12345"),
                role="viewer", access_scope="remote_allowed", enabled=1,
                created_at=int(time.time()),
            ))
            await s.commit()

    c.portal.call(_mk_viewer)
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login",
                  json={"username": "v", "password": "vpw12345"}).status_code == 200
    assert search(c, gid, rid, q="a").status_code == 404
```

- [ ] **Step 2: 跑红**

`pytest backend/tests/test_routes_search.py -v`
Expected: FAIL（404/405，路由不存在）。

- [ ] **Step 3: 实现** `backend/src/myphoto/routes_browse.py`

新增工具函数（放在 `_decode_cursor` 之后）：

```python
def _escape_like(term: str) -> str:
    """转义 SQLite LIKE 的通配符（% _）与转义符本身；配合 ESCAPE 反斜杠。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _subtree_clause(column, rel: str):
    """relative_path 位于 rel 子树内（含自身）；rel 为空时恒真（返回 None）。"""
    if rel == "":
        return None
    return or_(
        column == rel,
        column.like(_escape_like(rel) + "/%", escape="\\"),
    )


def _image_payload(r: Image) -> dict:
    return {
        "id": r.id,
        "filename": r.filename,
        "width": r.width,
        "height": r.height,
        "sha1": r.sha1,
        "size_bytes": r.size_bytes,
        "taken_at": r.taken_at,
        "mtime": r.mtime,
        "is_raw": bool(r.is_raw),
    }
```

把 `list_images` 里内联的 items 列表推导替换为复用 helper（行为不变）：

```python
        items = [_image_payload(r) for r in rows]
```

文件末尾新增搜索路由：

```python
@router.get("/galleries/{gid}/roots/{rid}/search")
async def search(
    gid: int,
    rid: int,
    request: Request,
    response: Response,
    q: str = Query(""),
    path: str = "",
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = None,
    _user: User = Depends(gallery_scope_guard),
):
    _no_store(response)
    term = q.strip()
    if not term:
        raise AppError("bad_request", 400, "query must not be empty")
    if len(term) > 100:
        raise AppError("bad_request", 400, "query too long")
    rel = _norm_or_400(path)
    needle = f"%{_escape_like(term.lower())}%"
    sm = request.app.state.sessionmaker
    async with sm() as s:
        await _get_root_or_404(s, gid, rid)
        anchor = (
            await s.execute(
                select(Folder.id).where(
                    Folder.root_id == rid, Folder.relative_path == rel
                )
            )
        ).scalar_one_or_none()
        empty = {
            "q": term, "path": rel, "folders": [],
            "folders_truncated": False, "images": [], "next_cursor": None,
        }
        if anchor is None:
            return empty

        # ---- 文件夹命中：严格后代，固定 50 条上限 ----
        fq = select(Folder).where(Folder.root_id == rid, Folder.name != "")
        if rel:
            fq = fq.where(
                Folder.relative_path.like(
                    _escape_like(rel) + "/%", escape="\\"
                )
            )
        fq = (
            fq.where(func.lower(Folder.name).like(needle, escape="\\"))
            .order_by(Folder.name.asc(), Folder.id.asc())
            .limit(51)
        )
        frows = (await s.execute(fq)).scalars().all()
        folders_out = []
        for f in frows[:50]:
            cover = (
                await s.execute(
                    select(Image.sha1)
                    .where(Image.folder_id == f.id)
                    .order_by(Image.filename.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            folders_out.append({
                "name": f.name,
                "relative_path": f.relative_path,
                "image_count": f.image_count,
                "descendant_count": f.descendant_count,
                "cover_thumb_sha1": cover,
            })

        # ---- 图片命中：子树内 filename LIKE，keyset 分页 ----
        iq = (
            select(Image)
            .join(Folder, Image.folder_id == Folder.id)
            .where(
                Image.root_id == rid,
                func.lower(Image.filename).like(needle, escape="\\"),
            )
        )
        subtree = _subtree_clause(Folder.relative_path, rel)
        if subtree is not None:
            iq = iq.where(subtree)
        if cursor:
            last_val, last_id = _decode_cursor(cursor)
            iq = iq.where(or_(
                Image.filename > last_val,
                and_(Image.filename == last_val, Image.id > last_id),
            ))
        iq = iq.order_by(Image.filename.asc(), Image.id.asc()).limit(limit + 1)
        irows = (await s.execute(iq)).scalars().all()
        has_more = len(irows) > limit
        irows = irows[:limit]
        images_out = []
        for r in irows:
            item = _image_payload(r)
            item["relative_path"] = r.relative_path
            images_out.append(item)
        next_cursor = None
        if has_more and irows:
            next_cursor = _encode_cursor("search", irows[-1].filename, irows[-1].id)

        return {
            "q": term,
            "path": rel,
            "folders": folders_out,
            "folders_truncated": len(frows) > 50,
            "images": images_out,
            "next_cursor": next_cursor,
        }
```


- [ ] **Step 4: 跑绿 + 回归**

```bash
pytest backend/tests/test_routes_search.py -v
pytest backend/tests/test_routes_browse.py -v
pytest
```

Expected: 新测试全绿；list_images 改 helper 后旧测试无回归。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(browse): subtree filename/folder substring search API"
```

---

### Task 3: TicketStore 与 arcname 纯函数（无路由）

**Files:**
- Create: `backend/src/myphoto/routes_download.py`（本 task 只放纯逻辑，Task 4 加路由）
- Test: `backend/tests/test_routes_download.py`（本 task 写纯逻辑用例，Task 4 追加 HTTP 用例到同文件）

**Interfaces:**
- Produces:
  - `DownloadEntry(image_id: int, disk_path: str, arcname: str)` dataclass
  - `TicketRecord(user_id, filename, entries, expires_at)` dataclass
  - `TicketStore(ttl_sec=300, max_entries=200)`：`issue(user_id, entries, filename, *, now=None, token=None) -> str`、`claim(token, user_id, *, now=None) -> TicketRecord | None`（一次性、过期/换人返回 None）
  - `build_arcnames(seq: list[tuple[int, str, str]]) -> list[str]`：元素 `(root_id, root_label, relative_path)`，已按请求顺序去重；单 root 用相对路径，跨 root 加清洗后的 label 前缀，残余撞名加 8 位 hex 后缀。

- [ ] **Step 1: 写失败测试** —— 在 `backend/tests/test_routes_download.py` 写：

```python
import time

import pytest

from myphoto.routes_download import (
    DownloadEntry,
    TicketStore,
    build_arcnames,
)


# ---------- build_arcnames ----------

def test_arcnames_single_root_keeps_tree():
    seq = [(1, "R", "2024/a.jpg"), (1, "R", "2024/sub/b.jpg")]
    assert build_arcnames(seq) == ["2024/a.jpg", "2024/sub/b.jpg"]


def test_arcnames_multi_root_adds_label_prefix():
    seq = [(1, "R1", "a.jpg"), (2, "R2", "b.jpg")]
    assert build_arcnames(seq) == ["R1/a.jpg", "R2/b.jpg"]


def test_arcnames_sanitizes_label():
    # label 来自用户输入，可能含 Windows 非法文件名字符或分隔符；
    # \\ / : * ? " < > | 逐字符替换为 _
    seq = [(1, 'D:/照片:库?', "a.jpg"), (2, "R2", "b.jpg")]
    assert build_arcnames(seq) == ["D__照片_库_/a.jpg", "R2/b.jpg"]


def test_arcnames_label_collision_gets_suffix():
    # 两个 root label 相同且相对路径相同 → 两个 arcname 必须可区分
    seq = [(1, "R", "a.jpg"), (2, "R", "a.jpg")]
    out = build_arcnames(seq)
    assert out[0] == "R/a.jpg"
    assert out[1] != "R/a.jpg"
    assert out[1].endswith(".jpg") and "-" in out[1]


# ---------- TicketStore ----------

def _entry(i: int) -> DownloadEntry:
    return DownloadEntry(image_id=i, disk_path=f"/tmp/{i}.jpg", arcname=f"{i}.jpg")


def test_issue_then_claim_returns_record_once():
    store = TicketStore()
    tok = store.issue(7, [_entry(1), _entry(2)], "p.zip", now=1000.0, token="tok")
    assert tok == "tok"
    rec = store.claim("tok", 7, now=1001.0)
    assert rec is not None and rec.filename == "p.zip" and len(rec.entries) == 2
    assert store.claim("tok", 7) is None  # 一次性


def test_claim_wrong_user_or_unknown_is_none():
    store = TicketStore()
    store.issue(7, [_entry(1)], "p.zip", now=1000.0, token="tok")
    assert store.claim("tok", 8, now=1001.0) is None
    assert store.claim("nope", 7) is None


def test_expired_ticket_is_none():
    store = TicketStore(ttl_sec=300)
    store.issue(7, [_entry(1)], "p.zip", now=1000.0, token="tok")
    assert store.claim("tok", 7, now=1299.0) is not None
    store.issue(7, [_entry(1)], "p.zip", now=1000.0, token="tok2")
    assert store.claim("tok2", 7, now=1301.0) is None


def test_max_entries_evicts_oldest():
    store = TicketStore(ttl_sec=300, max_entries=2)
    store.issue(1, [_entry(1)], "a.zip", now=1000.0, token="t1")
    store.issue(1, [_entry(1)], "b.zip", now=1001.0, token="t2")
    store.issue(1, [_entry(1)], "c.zip", now=1002.0, token="t3")
    assert store.claim("t1", 1, now=1002.0) is None
    assert store.claim("t2", 1, now=1002.0) is not None
```

- [ ] **Step 2: 跑红**

`pytest backend/tests/test_routes_download.py -v`
Expected: FAIL（模块不存在，ImportError）。

- [ ] **Step 3: 实现** `backend/src/myphoto/routes_download.py`（本 task 不含路由）：

```python
"""P6: 批量下载。

POST /api/download-batch        鉴权 + 数量校验 + 解析磁盘路径 → 一次性 ticket
GET  /api/download-batch/{tok}  凭 ticket 流式输出 ZIP（浏览器原生下载）

票据存内存（单进程部署）：TTL 300 秒、绑定 user_id、claim 即焚、总量上限淘汰最旧。
ZIP：ZIP_STORED（照片已压缩）、force_zip64（RAW 合集可能超 4GB）、
输出不可 seek，靠有界 queue 把写线程的字节交给 StreamingResponse。
"""
from __future__ import annotations

import logging
import re
import secrets
import time
from dataclasses import dataclass

log = logging.getLogger("myphoto.routes_download")

TICKET_TTL_SEC = 300
TICKET_MAX_ENTRIES = 200


@dataclass
class DownloadEntry:
    image_id: int
    disk_path: str
    arcname: str


@dataclass
class TicketRecord:
    user_id: int
    filename: str
    entries: list[DownloadEntry]
    expires_at: float


class TicketStore:
    def __init__(self, ttl_sec: float = TICKET_TTL_SEC,
                 max_entries: int = TICKET_MAX_ENTRIES) -> None:
        self._t: dict[str, TicketRecord] = {}
        self.ttl_sec = ttl_sec
        self.max_entries = max_entries

    def _purge(self, now: float) -> None:
        expired = [k for k, v in self._t.items() if v.expires_at <= now]
        for k in expired:
            del self._t[k]

    def issue(self, user_id: int, entries: list[DownloadEntry],
              filename: str, *, now: float | None = None,
              token: str | None = None) -> str:
        now = time.time() if now is None else now
        self._purge(now)
        if len(self._t) >= self.max_entries:
            oldest = min(self._t, key=lambda k: self._t[k].expires_at)
            del self._t[oldest]
        token = token or secrets.token_urlsafe(16)
        self._t[token] = TicketRecord(
            user_id=user_id, filename=filename,
            entries=entries, expires_at=now + self.ttl_sec,
        )
        return token

    def claim(self, token: str, user_id: int,
              *, now: float | None = None) -> TicketRecord | None:
        now = time.time() if now is None else now
        rec = self._t.get(token)
        if rec is None or rec.expires_at <= now or rec.user_id != user_id:
            return None
        del self._t[token]
        return rec


_LABEL_BAD = re.compile(r'[\\/:*?"<>|]')


def _safe_label(label: str) -> str:
    """清洗 root label 用作 ZIP 内目录名（Windows 解压友好）；空结果回退 root。"""
    out = _LABEL_BAD.sub("_", label).strip().lstrip(".")
    return out or "root"


def _disambiguate(name: str) -> str:
    """同 arcname 撞名时在文件名 stem 后加 8 位 hex 后缀，保留父目录与扩展名。"""
    if "." in name.rsplit("/", 1)[-1]:
        stem, _, ext = name.rpartition(".")
        suffix = "." + ext
    else:
        stem, suffix = name, ""
    tail = f"{stem.rsplit('/', 1)[-1]}-{secrets.token_hex(4)}{suffix}"
    parent = name.rsplit("/", 1)[0] if "/" in name else ""
    return f"{parent}/{tail}" if parent else tail


def build_arcnames(seq: list[tuple[int, str, str]]) -> list[str]:
    """seq 元素 (root_id, root_label, relative_path)，已去重保序。"""
    multi = len({root_id for root_id, _, _ in seq}) > 1
    out: list[str] = []
    used: set[str] = set()
    for root_id, label, rel in seq:
        name = f"{_safe_label(label)}/{rel}" if multi else rel
        if name in used:
            name = _disambiguate(name)
        used.add(name)
        out.append(name)
    return out
```

注意 `field` import 本 task 用不到，import 行写成 `from dataclasses import dataclass`（Task 4 也用不到 field）。

- [ ] **Step 4: 跑绿**

`pytest backend/tests/test_routes_download.py -v`
Expected: 8 passed。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(download): in-memory one-time ticket store and arcname rules"
```

---

### Task 4: POST/GET 下载路由 + ZIP 流 + main 装配

**Files:**
- Modify: `backend/src/myphoto/routes_download.py`（在 Task 3 纯逻辑上加路由）
- Modify: `backend/src/myphoto/main.py`（lifespan 初始化 ticket store + 注册路由）
- Test: `backend/tests/test_routes_download.py`（同文件追加 HTTP 集成用例）

**Interfaces:**
- Consumes: Task 1 的 `cfg.download_batch_limit`；Task 3 的 TicketStore/build_arcnames；`check_gallery_access`、`current_user`、`resolve_within_root`。
- Produces: `POST /api/download-batch {image_ids}` → `{ticket, filename, count}`；`GET /api/download-batch/{ticket}` → `application/zip` 流；`app.state.download_tickets: TicketStore`。

- [ ] **Step 1: 在测试文件顶部补 import**

把 `backend/tests/test_routes_download.py` 顶部 import 扩成（保留 Task 3 的三个 import）：

```python
import io
import re
import time
import zipfile
from pathlib import Path

import pytest
from PIL import Image as PILImage
from fastapi.testclient import TestClient

from myphoto.main import build_app
from myphoto.routes_download import (
    DownloadEntry,
    TicketStore,
    build_arcnames,
)
```

- [ ] **Step 2: 追加失败测试**（同文件末尾）：

```python
# ---------- HTTP 集成 ----------


def _jpg(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (20, 20), (1, 2, 3)).save(p, "JPEG")


@pytest.fixture
def env(tmp_path, capsys):
    photos = tmp_path / "photos"
    for f in ["a.jpg", "sub/b.jpg", "相册/c.jpg"]:
        _jpg(photos / f)
    photos2 = tmp_path / "photos2"
    _jpg(photos2 / "a2.jpg")

    app = build_app(config_path=str(tmp_path / "config.toml"))
    c_cm = TestClient(app)
    c = c_cm.__enter__()
    pw = re.search(r"password=(\S+)", capsys.readouterr().out).group(1)
    c.post("/api/auth/login", json={"username": "admin", "password": pw})

    from myphoto.models import Gallery, GalleryRoot

    async def _seed():
        async with app.state.sessionmaker() as s:
            g = Gallery(name="G", created_at=int(time.time()))
            s.add(g)
            await s.flush()
            r1 = GalleryRoot(gallery_id=g.id, label="R",
                             absolute_path=str(photos.resolve()), enabled=1)
            r2 = GalleryRoot(gallery_id=g.id, label="R2",
                             absolute_path=str(photos2.resolve()), enabled=1)
            s.add_all([r1, r2])
            await s.commit()
            await s.refresh(r1)
            await s.refresh(r2)
            return g.id, r1.id, r2.id

    gid, r1, r2 = c.portal.call(_seed)
    c.portal.call(app.state.scanner.scan_root_now, r1)
    c.portal.call(app.state.scanner.scan_root_now, r2)
    yield c, app, gid, r1, r2, photos
    c_cm.__exit__(None, None, None)


def _ids_at(c, gid, rid, path=""):
    r = c.get(f"/api/galleries/{gid}/roots/{rid}/images", params={"path": path, "limit": 500})
    return [i["id"] for i in r.json()["items"]]


def _post(c, ids):
    return c.post("/api/download-batch", json={"image_ids": ids})


def test_post_requires_auth(tmp_path):
    app = build_app(config_path=str(tmp_path / "config.toml"))
    with TestClient(app) as c:
        assert _post(c, [1]).status_code == 401


def test_happy_path_zip_bytes_and_headers(env):
    c, _, gid, r1, _, photos = env
    root_ids = _ids_at(c, gid, r1)
    sub_ids = _ids_at(c, gid, r1, "sub")
    r = _post(c, root_ids + sub_ids)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ticket", "filename", "count"}
    assert body["count"] == 2
    assert body["filename"].endswith(".zip")

    z = c.get(f"/api/download-batch/{body['ticket']}")
    assert z.status_code == 200
    assert z.headers["content-type"] == "application/zip"
    assert "attachment" in z.headers["content-disposition"]

    zf = zipfile.ZipFile(io.BytesIO(z.content))
    assert set(zf.namelist()) == {"a.jpg", "sub/b.jpg"}
    assert zf.read("a.jpg") == (photos / "a.jpg").read_bytes()


def test_utf8_filename_in_zip(env):
    c, _, gid, r1, _, _ = env
    cid = [i for i in _ids_at(c, gid, r1, "相册")][0]
    ticket = _post(c, [cid]).json()["ticket"]
    zf = zipfile.ZipFile(io.BytesIO(c.get(f"/api/download-batch/{ticket}").content))
    assert zf.namelist() == ["相册/c.jpg"]
    info = zf.infolist()[0]
    assert info.flag_bits & 0x800  # UTF-8 文件名标志


def test_duplicate_ids_deduped_preserve_order(env):
    c, _, gid, r1, _, _ = env
    i = _ids_at(c, gid, r1)[0]
    body = _post(c, [i, i, i]).json()
    assert body["count"] == 1


def test_ticket_is_one_time(env):
    c, _, gid, r1, _, _ = env
    i = _ids_at(c, gid, r1)[0]
    ticket = _post(c, [i]).json()["ticket"]
    assert c.get(f"/api/download-batch/{ticket}").status_code == 200
    assert c.get(f"/api/download-batch/{ticket}").status_code == 404


def test_ticket_bound_to_user(env):
    c, app, gid, r1, _, _ = env
    from myphoto.models import User, UserGallery
    from myphoto.security import hash_password

    async def _go():
        async with app.state.sessionmaker() as s:
            u = User(username="v", password_hash=hash_password("vpw12345"),
                     role="viewer", access_scope="remote_allowed", enabled=1,
                     created_at=int(time.time()))
            s.add(u)
            await s.flush()
            s.add(UserGallery(user_id=u.id, gallery_id=gid,
                              granted_at=int(time.time())))
            await s.commit()

    c.portal.call(_go)
    i = _ids_at(c, gid, r1)[0]
    ticket = _post(c, [i]).json()["ticket"]
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "v", "password": "vpw12345"})
    # viewer 已授权该图库，但票据属于 admin → 404
    assert c.get(f"/api/download-batch/{ticket}").status_code == 404


def test_viewer_without_gallery_grant_cannot_post(env):
    c, app, gid, r1, _, _ = env
    from myphoto.models import User
    from myphoto.security import hash_password

    async def _go():
        async with app.state.sessionmaker() as s:
            s.add(User(username="v2", password_hash=hash_password("vpw12345"),
                       role="viewer", access_scope="remote_allowed", enabled=1,
                       created_at=int(time.time())))
            await s.commit()

    c.portal.call(_go)
    i = _ids_at(c, gid, r1)[0]
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "v2", "password": "vpw12345"})
    r = _post(c, [i])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_unknown_image_id_404(env):
    c, _, _, _, _, _ = env
    r = _post(c, [999999])
    assert r.status_code == 404


def test_over_200_is_422(env):
    c, _, _, _, _, _ = env
    r = _post(c, list(range(201)))
    assert r.status_code == 422


def test_batch_too_large_uses_configured_limit(env):
    c, _, gid, r1, _, _ = env
    assert c.patch("/api/admin/settings",
                   json={"download_batch_limit": 10}).status_code == 200
    r = _post(c, list(range(100, 112)))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "batch_too_large"


def test_cross_root_arcnames_prefixed(env):
    c, _, gid, r1, r2, _ = env
    i1 = _ids_at(c, gid, r1)[0]
    i2 = _ids_at(c, gid, r2)[0]
    ticket = _post(c, [i1, i2]).json()["ticket"]
    zf = zipfile.ZipFile(io.BytesIO(c.get(f"/api/download-batch/{ticket}").content))
    assert set(zf.namelist()) == {"R/a.jpg", "R2/a2.jpg"}


def test_missing_file_listed_in_zip(env):
    c, app, gid, r1, _, photos = env
    cid = _ids_at(c, gid, r1, "相册")[0]
    keep = _ids_at(c, gid, r1)[0]
    ticket = _post(c, [keep, cid]).json()["ticket"]
    # POST→GET 之间文件被删/盘离线
    (photos / "相册" / "c.jpg").unlink()
    z = c.get(f"/api/download-batch/{ticket}")
    assert z.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    assert "a.jpg" in zf.namelist()
    listing = zf.read("missing-files.txt").decode("utf-8")
    assert "相册/c.jpg" in listing and str(cid) in listing
```

- [ ] **Step 3: 跑红**

`pytest backend/tests/test_routes_download.py -v`
Expected: 纯逻辑用例 8 passed；HTTP 用例全 FAIL（404）。

- [ ] **Step 4: 实现路由** —— `routes_download.py` 顶部补 import：

```python
import queue
import shutil
import threading
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from myphoto.access import check_gallery_access
from myphoto.deps import current_user
from myphoto.errors import AppError
from myphoto.models import GalleryRoot, Image, User
from myphoto.paths import PathTraversalError, resolve_within_root
```

在文件末尾追加本 Step 给出的 POST/GET 全部代码（`router`、`BatchBody`、`_QueueSink`、`_zip_stream`、两个路由），即下面两个代码块的内容。

```python
router = APIRouter(prefix="/api", tags=["download"])


class BatchBody(BaseModel):
    image_ids: list[int] = Field(..., min_length=1, max_length=200)


@router.post("/download-batch")
async def create_download_batch(
    body: BatchBody,
    request: Request,
    user: User = Depends(current_user),
):
    limit = int(request.app.state.config.download_batch_limit)
    ids = list(dict.fromkeys(body.image_ids))  # 去重保序
    if len(ids) > limit:
        raise AppError(
            "batch_too_large", 400,
            f"batch exceeds configured limit: {limit}",
        )

    sm = request.app.state.sessionmaker
    async with sm() as s:
        rows = (
            await s.execute(
                select(Image, GalleryRoot)
                .join(GalleryRoot, Image.root_id == GalleryRoot.id)
                .where(Image.id.in_(ids))
            )
        ).all()
        by_id = {img.id: (img, root) for img, root in rows}
        if any(i not in by_id for i in ids):
            raise AppError("not_found", 404, "image not found")

        checked_galleries: set[int] = set()
        seq: list[tuple[int, str, str]] = []
        disk_paths: dict[int, Path] = {}
        for i in ids:
            img, root = by_id[i]
            if root.gallery_id not in checked_galleries:
                await check_gallery_access(s, user, root.gallery_id)
                checked_galleries.add(root.gallery_id)
            try:
                disk_paths[i] = resolve_within_root(
                    root.absolute_path, img.relative_path
                )
            except PathTraversalError:
                raise AppError("path_invalid", 400, "invalid path")
            seq.append((root.id, root.label, img.relative_path))

    arcnames = build_arcnames(seq)
    entries = [
        DownloadEntry(
            image_id=i, disk_path=str(disk_paths[i]), arcname=arc,
        )
        for i, arc in zip(ids, arcnames)
    ]
    filename = f"photos-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    store: TicketStore = request.app.state.download_tickets
    ticket = store.issue(user.id, entries, filename)
    return {"ticket": ticket, "filename": filename, "count": len(entries)}
```

```python
# ---------- GET：一次性票据 → 流式 ZIP ----------

_SENTINEL = object()
_ERROR = object()
_CHUNK_MAX = 1024 * 1024
_QUEUE_DEPTH = 8


class _QueueSink:
    """zipfile 的写入端：有界 queue 背压（写满阻塞写线程）；
    seekable=False 让 zipfile 走数据描述符 + ZIP64 的流式写法。"""

    def __init__(self, q: "queue.Queue[object]") -> None:
        self._q = q
        self._pos = 0

    def write(self, b) -> int:
        data = bytes(b)
        self._q.put(data)
        self._pos += len(data)
        return len(data)

    def flush(self) -> None:
        pass

    def tell(self) -> int:
        return self._pos

    def seekable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def close(self) -> None:
        pass


def _zip_stream(record: TicketRecord):
    q: "queue.Queue[object]" = queue.Queue(maxsize=_QUEUE_DEPTH)

    def worker() -> None:
        try:
            with zipfile.ZipFile(
                _QueueSink(q), "w", compression=zipfile.ZIP_STORED
            ) as zf:
                missing: list[str] = []
                for e in record.entries:
                    p = Path(e.disk_path)
                    if not p.is_file():
                        missing.append(f"{e.image_id}  {e.arcname}")
                        continue
                    try:
                        mt = time.localtime(p.stat().st_mtime)[:6]
                    except OSError:
                        mt = (1980, 1, 1, 0, 0, 0)
                    zi = zipfile.ZipInfo(e.arcname, date_time=mt)
                    zi.compress_type = zipfile.ZIP_STORED
                    zi.external_attr = (0o644 & 0xFFFF) << 16
                    zi.flag_bits |= 0x800  # UTF-8 文件名
                    try:
                        with zf.open(zi, "w", force_zip64=True) as out, \
                                p.open("rb") as fh:
                            shutil.copyfileobj(fh, out, length=_CHUNK_MAX)
                    except OSError:
                        log.exception("zip entry read failed: %s", e.arcname)
                        missing.append(f"{e.image_id}  {e.arcname} (read error)")
                if missing:
                    mi = zipfile.ZipInfo("missing-files.txt")
                    mi.compress_type = zipfile.ZIP_STORED
                    mi.flag_bits |= 0x800
                    # 流模式必须 force_zip64，writestr 不支持，显式 open：
                    with zf.open(mi, "w", force_zip64=True) as out:
                        out.write("".join(line + "\n" for line in missing)
                                  .encode("utf-8"))
        except Exception:
            log.exception("zip streaming failed")
            q.put(_ERROR)
        finally:
            q.put(_SENTINEL)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        while True:
            chunk = q.get()
            if chunk is _SENTINEL:
                break
            if chunk is _ERROR:
                # 响应头已发出无法改状态码；提前结束流，客户端会得到损坏 ZIP
                log.error("aborting zip response after worker error")
                return
            yield chunk
    finally:
        # 客户端断连（generator 被关闭）后写线程可能正阻塞在满队列上：
        # 继续排空到 SENTINEL，让它正常写完退出，避免 daemon 线程泄漏。
        if thread.is_alive():
            while True:
                chunk = q.get()
                if chunk is _SENTINEL or chunk is _ERROR:
                    break
        thread.join(timeout=30)


@router.get("/download-batch/{ticket}")
def download_batch_zip(
    ticket: str,
    request: Request,
    user: User = Depends(current_user),
):
    store: TicketStore = request.app.state.download_tickets
    record = store.claim(ticket, user.id)
    if record is None:
        raise AppError("not_found", 404, "ticket not found")
    quoted = quote(record.filename, safe="")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{record.filename}"; '
            f"filename*=UTF-8''{quoted}"
        ),
        "Cache-Control": "no-store",
    }
    return StreamingResponse(
        _zip_stream(record),
        media_type="application/zip",
        headers=headers,
    )
```

说明：GET 用同步 `def`，FastAPI 自动把路由体与同步 generator 放线程池；`current_user` 是 async 依赖，FastAPI 支持混用，无需特殊处理。

- [ ] **Step 5: main.py 装配**

import 区（其他 routes import 旁）：

```python
    from myphoto.routes_download import router as download_router
```

注册（images router 之后）：

```python
    app.include_router(download_router)
```

lifespan 中 `app.state.thumbnails = ...` 之后加一行：

```python
        from myphoto.routes_download import TicketStore
        app.state.download_tickets = TicketStore()
```

（import 也可放到函数内与现有风格一致；TicketStore 实例化放 lifespan 内，确保 TestClient 进入上下文后属性存在。）

- [ ] **Step 6: 跑绿 + 全量回归**

```bash
pytest backend/tests/test_routes_download.py -v
pytest
```

Expected: 全部新用例绿（纯逻辑 8 + HTTP 12）；全量后端无回归。

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(download): ticket-based streaming zip batch download"
```

---

### Task 5: 前端类型与错误码基础

**Files:**
- Modify: `frontend/src/api.ts`（`batch_too_large` 中文映射）
- Modify: `frontend/src/stores/browse.ts`（ImageRow 加可选 `relative_path`）
- Modify: `frontend/src/stores/auth.ts`（AuthUser 加 `download_batch_limit`）
- Test: `frontend/src/tests/batch-too-large.spec.ts`

**Interfaces:**
- Produces: `AuthUser.download_batch_limit: number`；`ImageRow.relative_path?: string`；`errorMessage(HttpError(400,"batch_too_large"))` 返回中文。

- [ ] **Step 1: 写失败测试** `frontend/src/tests/batch-too-large.spec.ts`：

```ts
import { describe, expect, it } from "vitest"
import { HttpError, errorMessage } from "../api"

describe("batch_too_large 错误码", () => {
  it("映射为中文文案", () => {
    const msg = errorMessage(new HttpError(400, "batch_too_large", "english raw"))
    expect(msg).toBe("超出批量下载数量上限")
  })
})
```

- [ ] **Step 2: 跑红**

`cd frontend && pnpm test -- batch-too-large`
Expected: FAIL（实际拿到英文原文或兜底）。

- [ ] **Step 3: 实现**

`api.ts` 的 `ERROR_MSG_ZH` 加一行（放在 `bad_request` 附近）：

```ts
  batch_too_large: "超出批量下载数量上限",
```

`stores/browse.ts` 的 `ImageRow` interface 加可选字段：

```ts
  /** 搜索结果才有：图片相对 root 的完整 posix 路径（含目录） */
  relative_path?: string
```

`stores/auth.ts` 的 `AuthUser` 加：

```ts
  download_batch_limit: number
```

- [ ] **Step 4: 跑绿 + 类型检查**

```bash
cd frontend && pnpm test -- batch-too-large
pnpm build
```

Expected: 测试绿；`vue-tsc` 可能报现有测试桩 user 对象缺字段（如 `auth.$patch({user:{...}})`）。若报错，给报错处的桩对象补 `download_batch_limit: 100`（涉及 `browse-view-delete.spec.ts` 等），生产代码由后端新字段保证。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(web): batch_too_large copy, download limit/relative_path types"
```

---

### Task 6: SearchBox 组件

**Files:**
- Create: `frontend/src/components/SearchBox.vue`
- Test: `frontend/src/tests/search-box.spec.ts`

**Interfaces:**
- Props: `modelValue: string`（受控 query）、`scopeAll: boolean`、`isRoot: boolean`（true 时隐藏「整个 root」勾选）。
- Emits: `update:modelValue`（输入防抖 300ms / 回车立即 / 清除立即）、`update:scopeAll`。

- [ ] **Step 1: 写失败测试** `frontend/src/tests/search-box.spec.ts`：

```ts
import { afterEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import SearchBox from "../components/SearchBox.vue"

function mountBox(props: Partial<{ modelValue: string; scopeAll: boolean; isRoot: boolean }> = {}) {
  return mount(SearchBox, {
    props: { modelValue: "", scopeAll: false, isRoot: false, ...props },
    attachTo: document.body,
  })
}

describe("SearchBox", () => {
  afterEach(() => vi.useRealTimers())

  it("输入后防抖 300ms 才 emit，回车立即 emit", async () => {
    vi.useFakeTimers()
    const w = mountBox()
    const input = w.get("input[type='search']")
    await input.setValue("旅行")
    expect(w.emitted("update:modelValue")).toBeUndefined()
    vi.advanceTimersByTime(299)
    expect(w.emitted("update:modelValue")).toBeUndefined()
    vi.advanceTimersByTime(1)
    expect(w.emitted("update:modelValue")![0]).toEqual(["旅行"])
  })

  it("回车立即触发，不等防抖", async () => {
    vi.useFakeTimers()
    const w = mountBox()
    const input = w.get("input[type='search']")
    await input.setValue("img")
    await w.get("form").trigger("submit.prevent")
    expect(w.emitted("update:modelValue")![0]).toEqual(["img"])
  })

  it("清除按钮：有文本时出现，点击立即 emit 空串并聚焦", async () => {
    vi.useFakeTimers()
    const w = mountBox({ modelValue: "x" })
    expect(w.find('button[aria-label="清除搜索"]').exists()).toBe(true)
    await w.get('button[aria-label="清除搜索"]').trigger("click")
    expect(w.emitted("update:modelValue")![0]).toEqual([""])
    expect(w.get("input[type='search']").element).toBe(document.activeElement)
  })

  it("isRoot=true 时隐藏整个 root 勾选；否则切换 emit scopeAll", async () => {
    const wRoot = mountBox({ isRoot: true })
    expect(wRoot.find('input[type="checkbox"]').exists()).toBe(false)

    const w = mountBox({ isRoot: false })
    const cb = w.get('input[type="checkbox"]')
    await cb.setValue(true)
    expect(w.emitted("update:scopeAll")![0]).toEqual([true])
  })

  it("外部 modelValue 变化同步回输入框", async () => {
    const w = mountBox({ modelValue: "a" })
    expect((w.get("input[type='search']").element as HTMLInputElement).value).toBe("a")
    await w.setProps({ modelValue: "b" })
    await flushPromises()
    expect((w.get("input[type='search']").element as HTMLInputElement).value).toBe("b")
  })
})
```

- [ ] **Step 2: 跑红**

`cd frontend && pnpm test -- search-box`
Expected: FAIL（组件不存在）。

- [ ] **Step 3: 实现** `frontend/src/components/SearchBox.vue`：

```vue
<template>
  <form class="flex items-center gap-2 text-sm" @submit.prevent="flush">
    <div class="relative">
      <input
        ref="inputEl"
        type="search"
        :value="text"
        placeholder="搜索文件名或文件夹…"
        aria-label="搜索"
        class="w-44 rounded bg-neutral-800 py-1 pl-2 pr-6 text-neutral-100 placeholder:text-neutral-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        @input="onInput"
      >
      <button
        v-if="text"
        type="button"
        aria-label="清除搜索"
        class="absolute right-1 top-1/2 -translate-y-1/2 px-0.5 leading-none text-neutral-400 hover:text-neutral-200"
        @click="clear"
      >×</button>
    </div>
    <label
      v-if="!isRoot"
      class="flex shrink-0 select-none items-center gap-1 whitespace-nowrap text-neutral-400"
    >
      <input
        type="checkbox"
        class="accent-blue-600"
        :checked="scopeAll"
        @change="onScopeChange(($event.target as HTMLInputElement).checked)"
      >
      整个 root
    </label>
  </form>
</template>

<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from "vue"

const props = defineProps<{
  modelValue: string
  scopeAll: boolean
  /** 在 root 根目录时为 true：子树本就等于整个 root，隐藏勾选 */
  isRoot: boolean
}>()

const emit = defineEmits<{
  (e: "update:modelValue", v: string): void
  (e: "update:scopeAll", v: boolean): void
}>()

const text = ref(props.modelValue)
const inputEl = ref<HTMLInputElement | null>(null)
let timer: number | null = null

// 路由前进/后退带来的外部 query 变化同步回输入框；输入自身触发的同值更新不重复排防抖
watch(
  () => props.modelValue,
  (v) => {
    if (v !== text.value) text.value = v
  },
)

function schedule() {
  if (timer !== null) window.clearTimeout(timer)
  timer = window.setTimeout(() => {
    timer = null
    emit("update:modelValue", text.value)
  }, 300)
}

function flush() {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
  emit("update:modelValue", text.value)
}

function onInput(ev: Event) {
  text.value = (ev.target as HTMLInputElement).value
  schedule()
}

function onScopeChange(v: boolean) {
  emit("update:scopeAll", v)
}

function clear() {
  if (timer !== null) window.clearTimeout(timer)
  timer = null
  text.value = ""
  emit("update:modelValue", "")
  inputEl.value?.focus()
}

onBeforeUnmount(() => {
  if (timer !== null) window.clearTimeout(timer)
})
</script>
```

- [ ] **Step 4: 跑绿 + 类型检查**

```bash
cd frontend && pnpm test -- search-box
pnpm build
```

Expected: 5 passed；类型检查过。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(web): SearchBox with debounce and whole-root scope toggle"
```

---

### Task 7: ImageLightbox 目录标注 +「在所在文件夹中查看」

**Files:**
- Modify: `frontend/src/components/ImageLightbox.vue`
- Test: `frontend/src/tests/lightbox-location.spec.ts`

**Interfaces:**
- 新增可选 prop `locationResolver?: (item: ImageRow) => string | null`：传入时 PhotoSwipe 顶栏注册目录标签（order 7）和跳转按钮（`view-in-folder`，order 10）；不传时零变化（普通浏览态）。
- 新增 emit `viewInFolder(item: ImageRow)`。

- [ ] **Step 1: 写失败测试** `frontend/src/tests/lightbox-location.spec.ts`：

```ts
/**
 * PhotoSwipe 在 jsdom 里无法真实运行，整体 mock（与 lightbox-exif.spec.ts
 * 同款手法）：init() 触发 uiRegister 回调，registerElement 保存注册项并
 * 立刻调 onInit（传入一个 span 充当 DOM 元素）。
 */
import { beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createPinia, setActivePinia } from "pinia"

interface UIRegistration {
  name: string
  ariaLabel?: string
  isButton?: boolean
  onInit?: (el: HTMLElement) => void
  onClick?: () => void
}

const registered: UIRegistration[] = []

vi.mock("photoswipe", () => {
  class MockPhotoSwipe {
    currIndex = 0
    currSlide = { data: {} }
    ui = {
      registerElement: (opts: UIRegistration) => {
        registered.push(opts)
        opts.onInit?.(document.createElement("span"))
      },
    }
    handlers: Record<string, () => void> = {}
    constructor(_opts: unknown) {}
    on(evt: string, cb: () => void) {
      this.handlers[evt] = cb
    }
    addFilter() {}
    init() {
      this.handlers["uiRegister"]?.()
    }
    close() {}
    destroy() {}
  }
  return { default: MockPhotoSwipe }
})
vi.mock("photoswipe/style.css", () => ({}))

import ImageLightbox from "../components/ImageLightbox.vue"
import type { ImageRow } from "../stores/browse"

const ITEMS: ImageRow[] = [
  { id: 1, filename: "a.jpg", width: 400, height: 300, sha1: "s1",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    relative_path: "2024/旅行/a.jpg" },
]

function findEl(name: string) {
  return registered.find((r) => r.name === name)
}

async function mountBox(resolver?: (it: ImageRow) => string | null) {
  registered.length = 0
  document.body.innerHTML = ""
  setActivePinia(createPinia())
  const w = mount(ImageLightbox, {
    props: { items: ITEMS, startId: 1, ...(resolver ? { locationResolver: resolver } : {}) },
  })
  await flushPromises()
  return w
}

describe("ImageLightbox location hook", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    document.body.innerHTML = ""
  })

  it("不传 resolver 时不注册目录元素（普通浏览态零变化）", async () => {
    await mountBox()
    expect(findEl("location-label")).toBeUndefined()
    expect(findEl("view-in-folder")).toBeUndefined()
  })

  it("传入 resolver：显示目录名，按钮 emit viewInFolder", async () => {
    const resolver = (it: ImageRow) => {
      const p = it.relative_path ?? ""
      const i = p.lastIndexOf("/")
      return i >= 0 ? p.slice(0, i) : ""
    }
    const w = await mountBox(resolver)

    const label = findEl("location-label")
    expect(label).toBeDefined()
    expect(label!.isButton).toBe(false)

    const btn = findEl("view-in-folder")
    expect(btn).toBeDefined()
    expect(btn!.ariaLabel).toBe("在所在文件夹中查看")
    btn!.onClick!()
    expect(w.emitted("viewInFolder")![0][0]).toMatchObject({ id: 1, filename: "a.jpg" })
  })
})
```

- [ ] **Step 2: 跑红**

`cd frontend && pnpm test -- lightbox-location`
Expected: FAIL（注册项不存在）。

- [ ] **Step 3: 实现** `ImageLightbox.vue`

props 加可选项：

```ts
const props = defineProps<{
  items: ImageRow[]
  startId: number
  /** 搜索结果态：返回图片所在目录相对路径（root 根目录返回 ""）。
   *  传入时才注册目录标注与「在所在文件夹中查看」；普通浏览态不传。 */
  locationResolver?: (item: ImageRow) => string | null
}>()
```

emits 加：

```ts
  (e: "viewInFolder", item: ImageRow): void
```

`open()` 内，`updateFilenameLabel` 定义之后加：

```ts
  // 搜索结果态目录标注：仅在传入 locationResolver 时注册元素
  let locationEl: HTMLElement | null = null
  const updateLocationLabel = () => {
    if (!locationEl || !pswp) return
    const it = props.items[pswp.currIndex]
    locationEl.textContent =
      it && props.locationResolver ? (props.locationResolver(it) ?? "") : ""
  }
```

`pswp.on("change", ...)` 里在 `updateFilenameLabel()` 之后加一行：

```ts
    updateLocationLabel()
```

`pswp.on("uiRegister", ...)` 里，`filename-label` 注册块之后加：

```ts
    if (props.locationResolver) {
      pswp!.ui!.registerElement({
        name: "location-label",
        order: 7,
        isButton: false,
        tagName: "span",
        className: "pswp__location-label",
        onInit: (el) => {
          locationEl = el
          updateLocationLabel()
        },
      })
      pswp!.ui!.registerElement({
        name: "view-in-folder",
        ariaLabel: "在所在文件夹中查看",
        order: 10,
        isButton: true,
        html: `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`,
        onClick: () => {
          const it = pswp ? props.items[pswp.currIndex] : undefined
          if (it) emit("viewInFolder", it)
        },
      })
    }
```

`<style>` 末尾（`.pswp__filename-label` 规则旁）加：

```css
/* 搜索结果态：文件名右侧的所在目录，弱化一档 */
.pswp__location-label {
  color: rgba(255, 255, 255, 0.75);
  font-size: 13px;
  line-height: 1;
  margin-inline-start: 10px;
  align-self: center;
  max-width: 40vw;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-shadow: 0 0 3px rgba(0, 0, 0, 0.8);
}
```

（字号/颜色以相邻 `.pswp__filename-label` 实际值为准对齐，只保留更弱的透明度与省略号两个差异。）

- [ ] **Step 4: 跑绿 + 全量前端回归**

```bash
cd frontend && pnpm test -- lightbox-location lightbox-exif
pnpm test
pnpm build
```

Expected: 新测试绿；既有 lightbox 套件无回归；类型过。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(web): lightbox location label and view-in-folder hook"
```

---

### Task 8: SearchResults 组件 + 网格目录角标

**Files:**
- Create: `frontend/src/components/SearchResults.vue`
- Modify: `frontend/src/components/PhotoCell.vue`（可选 `badge`）
- Modify: `frontend/src/components/JustifiedGrid.vue`、`MasonryGrid.vue`（可选 `badgeFor`）
- Test: `frontend/src/tests/search-results.spec.ts`

**Interfaces:**
- SearchResults props：`gid, rid, q, path, grid: GridLayout, selectionMode?, selectedIds?, showFilename?`；emits `open(id)`、`toggleSelect(id)`、`menuAction(id,"delete")`、`itemsChange(ImageRow[])`；`defineExpose({ reload })`。
- 网格新增可选 prop `badgeFor?: (item: ImageRow) => string | null`；PhotoCell 新增可选 prop `badge?: string`。

- [ ] **Step 1: PhotoCell / 网格加角标（先改，组件测试要用）**

`PhotoCell.vue` props 加：

```ts
  /** 搜索结果：所在目录小字（posix 目录路径）；root 图片与普通浏览不传 */
  badge?: string
```

模板中文件名 div 之后加：

```html
    <div v-if="badge"
         class="lb-cell-badge pointer-events-none truncate text-left"
         :class="{ 'lb-cell-badge--up': showFilename }"
         :title="badge">
      {{ badge }}
    </div>
```

`<style scoped>` 加：

```css
.lb-cell-badge {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 1;
  padding: 16px 6px 3px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.72), rgba(0, 0, 0, 0));
  color: #fff;
  font-size: 10px;
  line-height: 1.2;
}
.lb-cell-badge--up {
  /* 同时显示文件名时，目录行抬到文件名行之上 */
  bottom: 15px;
}
```

`JustifiedGrid.vue` 与 `MasonryGrid.vue` 做同样三处修改：

1. props 类型加：

```ts
  /** 搜索结果用：把图片映射成角标文本（所在目录）；不传则无角标 */
  badgeFor?: (item: ImageRow) => string | null
```

2. setup 中加 id→item 映射（排版 cell 对象只保留了部分字段）：

```ts
const itemById = computed(() => new Map(props.items.map((it) => [it.id, it])))
```

3. 模板 `<PhotoCell>` 上加：

```html
                 :badge="badgeFor ? badgeFor(itemById.get(cell.id)!) ?? undefined : undefined"
```

- [ ] **Step 2: 写失败测试** `frontend/src/tests/search-results.spec.ts`：

```ts
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import SearchResults from "../components/SearchResults.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"

type ImageRowish = { id: number }

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
  })
}

const FOLDERS = [
  { name: "旅行", relative_path: "2024/旅行", image_count: 0,
    descendant_count: 9, cover_thumb_sha1: "sha-f" },
]
const IMAGES_A = [
  { id: 11, filename: "a.jpg", width: 400, height: 300, sha1: "s11",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    relative_path: "2024/旅行/a.jpg" },
  { id: 12, filename: "b.jpg", width: 400, height: 300, sha1: "s12",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    relative_path: "root.jpg" },
]
const IMAGES_B = [
  { id: 13, filename: "c.jpg", width: 400, height: 300, sha1: "s13",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    relative_path: "2024/旅行/c.jpg" },
]

function mountResults(fetchFn: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchFn)
  setActivePinia(createPinia())
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/galleries/:gid/r/:rid/:path(.*)*", component: { template: "<div/>" } }],
  })
  return mount(SearchResults, {
    props: { gid: 1, rid: 2, q: "旅行", path: "", grid: "justified" as const },
    global: { plugins: [router] },
  })
}

describe("SearchResults", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("渲染匹配文件夹与图片：链接、截断提示、目录角标", async () => {
    const fetchFn = vi.fn(async () => json({
      q: "旅行", path: "", folders: FOLDERS, folders_truncated: true,
      images: IMAGES_A, next_cursor: "cur1",
    }))
    const w = mountResults(fetchFn)
    await flushPromises()
    await flushPromises()

    expect(w.text()).toContain("匹配的文件夹")
    expect(w.text()).toContain("仅显示前 50 个")
    const link = w.get("a")
    expect(link.attributes("href")).toContain("/galleries/1/r/2/2024/%E6%97%85%E8%A1%8C")
    // 子目录图片带角标，root 图片不带
    const badges = w.findAll(".lb-cell-badge")
    expect(badges.length).toBe(1)
    expect(badges[0].text()).toBe("2024/旅行")
    // 图片角标之外，缩略图本身都在
    expect(w.findAll("img").length).toBeGreaterThanOrEqual(3)
    // itemsChange 已上抛
    expect((w.emitted("itemsChange")!.at(-1) as ImageRowish[])[0]).toHaveLength(2)
  })

  it("加载更多：带 cursor 追加图片", async () => {
    const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes("cursor=cur1")) {
        return json({ q: "旅行", path: "", folders: [], folders_truncated: false,
                      images: IMAGES_B, next_cursor: null })
      }
      return json({ q: "旅行", path: "", folders: [], folders_truncated: false,
                    images: IMAGES_A, next_cursor: "cur1" })
    })
    const w = mountResults(fetchFn)
    await flushPromises()
    await flushPromises()
    await w.get("button").trigger("click")
    await flushPromises()
    const items = w.emitted("itemsChange")!.at(-1) as unknown as ImageRowish[][]
    expect(items[0]).toHaveLength(3)
  })

  it("空结果显示空态", async () => {
    const fetchFn = vi.fn(async () => json({
      q: "zzz", path: "", folders: [], folders_truncated: false,
      images: [], next_cursor: null,
    }))
    const w = mountResults(fetchFn)
    await flushPromises()
    expect(w.text()).toContain("未找到匹配的图片或文件夹")
  })

  it("网格 open/toggleSelect 透传；defineExpose.reload 可重拉", async () => {
    const fetchFn = vi.fn(async () => json({
      q: "旅行", path: "", folders: [], folders_truncated: false,
      images: IMAGES_A, next_cursor: null,
    }))
    const w = mountResults(fetchFn)
    await flushPromises()
    await flushPromises()
    w.findComponent(JustifiedGrid).vm.$emit("open", 11)
    expect(w.emitted("open")![0]).toEqual([11])
    w.findComponent(JustifiedGrid).vm.$emit("toggleSelect", 11)
    expect(w.emitted("toggleSelect")![0]).toEqual([11])

    await (w.vm as unknown as { reload: () => Promise<void> }).reload()
    expect(fetchFn).toHaveBeenCalledTimes(2)
  })
})
```

- [ ] **Step 3: 跑红**

`cd frontend && pnpm test -- search-results`
Expected: FAIL（组件不存在）。

- [ ] **Step 4: 实现** `frontend/src/components/SearchResults.vue`：

```vue
<template>
  <div>
    <section v-if="folders.length" class="pb-3">
      <h2 class="mb-2 text-sm text-neutral-400">
        匹配的文件夹（{{ folders.length }}<template v-if="foldersTruncated">，仅显示前 50 个，请细化关键词</template>）
      </h2>
      <div class="lb-search-folder-grid">
        <router-link
          v-for="f in folders"
          :key="f.relative_path"
          :to="folderLink(f.relative_path)"
          class="flex flex-col overflow-hidden rounded bg-neutral-800 text-sm hover:ring-2 hover:ring-blue-500"
        >
          <div class="h-20 w-full overflow-hidden bg-neutral-700">
            <img
              v-if="f.cover_thumb_sha1"
              :src="`/api/thumb/${f.cover_thumb_sha1}?size=200`"
              :alt="f.name"
              loading="lazy"
              class="h-full w-full object-cover"
            >
          </div>
          <div class="truncate p-2">
            <div class="truncate font-medium">{{ f.name }}</div>
            <div class="text-xs text-neutral-400">{{ f.descendant_count }} 张</div>
          </div>
        </router-link>
      </div>
    </section>

    <div v-if="error"
         class="mb-2 rounded bg-red-900/30 px-3 py-2 text-sm text-red-300">
      {{ error }}
    </div>

    <component
      :is="gridComponent"
      v-if="items.length"
      :items="items"
      :badge-for="badgeFor"
      :selection-mode="selectionMode"
      :selected-ids="selectedIds"
      :show-filename="showFilename"
      @open="onOpen"
      @toggle-select="onToggleSelect"
      @menu-action="onMenuAction"
    />

    <div v-else-if="!loading && !folders.length"
         class="mt-8 text-center text-neutral-500">
      未找到匹配的图片或文件夹
    </div>

    <div v-if="nextCursor" class="py-4 text-center">
      <button
        type="button"
        class="rounded bg-neutral-800 px-3 py-1.5 text-sm hover:bg-neutral-700 disabled:opacity-50"
        :disabled="loadingMore"
        @click="loadMore"
      >
        {{ loadingMore ? "加载中..." : "加载更多" }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue"
import JustifiedGrid from "./JustifiedGrid.vue"
import MasonryGrid from "./MasonryGrid.vue"
import type { GridLayout } from "./GridLayoutSwitch.vue"
import { apiGet, errorMessage } from "../api"
import type { ImageRow } from "../stores/browse"

interface SearchFolder {
  name: string
  relative_path: string
  image_count: number
  descendant_count: number
  cover_thumb_sha1: string | null
}

interface SearchResponse {
  q: string
  path: string
  folders: SearchFolder[]
  folders_truncated: boolean
  images: ImageRow[]
  next_cursor: string | null
}

const props = defineProps<{
  gid: number
  rid: number
  q: string
  /** 子树根；scope=all 时父组件传 "" */
  path: string
  grid: GridLayout
  selectionMode?: boolean
  selectedIds?: Set<number>
  showFilename?: boolean
}>()

const emit = defineEmits<{
  (e: "open", id: number): void
  (e: "toggleSelect", id: number): void
  (e: "menuAction", id: number, action: "delete"): void
  (e: "itemsChange", items: ImageRow[]): void
}>()

defineExpose({ reload })

// 模板里不写内联 TS 类型，用具名包装透传网格事件
function onOpen(id: number) {
  emit("open", id)
}
function onToggleSelect(id: number) {
  emit("toggleSelect", id)
}
function onMenuAction(id: number, action: "delete") {
  emit("menuAction", id, action)
}

const gridComponent = computed(() =>
  props.grid === "masonry" ? MasonryGrid : JustifiedGrid,
)

const folders = ref<SearchFolder[]>([])
const foldersTruncated = ref(false)
const items = ref<ImageRow[]>([])
const nextCursor = ref<string | null>(null)
const loading = ref(false)
const loadingMore = ref(false)
const error = ref("")

function dirOf(it: ImageRow): string | null {
  const p = it.relative_path ?? ""
  const i = p.lastIndexOf("/")
  return i >= 0 ? p.slice(0, i) : null
}

const badgeFor = dirOf

function folderLink(rel: string) {
  return `/galleries/${props.gid}/r/${props.rid}/${rel}`
}

function searchParams(cursor?: string | null) {
  const params = new URLSearchParams({
    q: props.q,
    path: props.path,
    limit: "100",
  })
  if (cursor) params.set("cursor", cursor)
  return params
}

async function loadFirst() {
  if (!props.q.trim()) return
  loading.value = true
  error.value = ""
  try {
    const r = await apiGet<SearchResponse>(
      `/api/galleries/${props.gid}/roots/${props.rid}/search?${searchParams()}`,
    )
    folders.value = r.folders
    foldersTruncated.value = r.folders_truncated
    items.value = r.images
    nextCursor.value = r.next_cursor
    emit("itemsChange", items.value)
  } catch (e) {
    error.value = errorMessage(e, "搜索失败")
    folders.value = []
    items.value = []
    nextCursor.value = null
    emit("itemsChange", [])
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (!nextCursor.value || loadingMore.value) return
  loadingMore.value = true
  try {
    const r = await apiGet<SearchResponse>(
      `/api/galleries/${props.gid}/roots/${props.rid}/search?${searchParams(nextCursor.value)}`,
    )
    items.value = [...items.value, ...r.images]
    nextCursor.value = r.next_cursor
    emit("itemsChange", items.value)
  } catch (e) {
    error.value = errorMessage(e, "搜索失败")
  } finally {
    loadingMore.value = false
  }
}

async function reload() {
  await loadFirst()
}

watch(
  () => [props.gid, props.rid, props.q, props.path] as const,
  () => {
    void loadFirst()
  },
  { immediate: true },
)
</script>

<style scoped>
.lb-search-folder-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
  gap: 16px;
}
</style>
```

- [ ] **Step 5: 跑绿 + 回归**

```bash
cd frontend && pnpm test -- search-results justified-grid masonry-grid
pnpm test
pnpm build
```

Expected: 新测试绿；两个网格旧测试无回归（新增可选 prop）。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(web): SearchResults with folder hits, load-more, dir badges"
```

---

### Task 9: BrowseView 多选跨页累积 + 批量下载

**Files:**
- Modify: `frontend/src/views/BrowseView.vue`
- Modify: `frontend/src/tests/browse-view-delete.spec.ts`（旧断言「选择按钮仅 admin」需改）
- Test: `frontend/src/tests/browse-selection-download.spec.ts`

**Interfaces:**
- 「选择」按钮对所有登录用户可见；底部条 viewer 只有「下载 ZIP」，admin 另有「移入回收站」。
- 选择集跨翻页累积，硬上限 200（toast 拦截）；切换 gid/rid/path 仍清空（现有 watcher 保留）。

- [ ] **Step 1: 修改既有测试** `browse-view-delete.spec.ts`

把 `it("shows the '选择' button only for admin", ...)` 整个用例替换为：

```ts
  it("所有角色都显示「选择」按钮（P6 下载对 viewer 开放）", async () => {
    const { w } = await mountView("admin")
    expect(w.findAll("button").find((b) => b.text() === "选择")).toBeTruthy()

    const { w: w2 } = await mountView("viewer")
    expect(w2.findAll("button").find((b) => b.text() === "选择")).toBeTruthy()
  })
```

（`mountView` 里 auth.\$patch 的 user 对象加 `download_batch_limit: 100`，Task 5 类型已要求。）

- [ ] **Step 2: 写失败测试** `frontend/src/tests/browse-selection-download.spec.ts`：

```ts
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import BrowseView from "../views/BrowseView.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import PaginationBar from "../components/PaginationBar.vue"
import { useAuthStore } from "../stores/auth"
import { useToastStore } from "../stores/toast"

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

function pageItems(page: number) {
  if (page === 1) {
    return Array.from({ length: 200 }, (_, i) => ({
      id: i + 1, filename: `a${i + 1}.jpg`, width: 40, height: 30,
      sha1: `s${i + 1}`, size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
    }))
  }
  return [{ id: 201, filename: "a201.jpg", width: 40, height: 30,
            sha1: "s201", size_bytes: 1, taken_at: null, mtime: 0, is_raw: false }]
}

async function mountView(role: "admin" | "viewer", limit = 100, total = 2) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const json = (body: unknown) => new Response(JSON.stringify(body), {
      headers: { "content-type": "application/json" },
    })
    if (url.includes("/breadcrumbs")) return json([{ name: "R", relative_path: "" }])
    if (url.includes("/folders")) return json([])
    if (url.includes("/images")) {
      const page = url.includes("offset=0") || !url.includes("offset") ? 1 : 2
      return json({ items: total === 201 ? pageItems(page) : pageItems(1).slice(0, 2),
                    total })
    }
    if (url.includes("/api/download-batch")) {
      return json({ ticket: "TICK", filename: "photos-test.zip", count: 1 })
    }
    return json({ error: { code: "not_found", message: "not mocked" } }, 404)
  })

  vi.stubGlobal("fetch", fetchFn)
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({
    user: { id: 1, username: "u", role, access_scope: "lan_only",
            download_batch_limit: limit },
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/galleries/:gid/r/:rid/:path(.*)*", component: BrowseView },
      { path: "/galleries/:gid/r/:rid/:path(.*)*/image/:iid", component: BrowseView },
    ],
  })
  await router.push("/galleries/1/r/1")
  const w = mount(BrowseView, {
    global: { plugins: [router], stubs: { ImageLightbox: true } },
  })
  await flushPromises()
  await flushPromises()
  return { w, fetchFn, auth }
}

async function enterSelection(w: VueWrapper<any>) {
  await w.findAll("button").find((b) => b.text() === "选择")!.trigger("click")
}

describe("BrowseView 多选与下载", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("viewer 底部条只有下载；admin 有下载+删除", async () => {
    const v = await mountView("viewer", 100, 2)
    await enterSelection(v.w)
    expect(v.w.text()).toContain("下载 ZIP")
    expect(v.w.findAll("button").some((b) => b.text().includes("移入回收站"))).toBe(false)

    const a = await mountView("admin", 100, 2)
    await enterSelection(a.w)
    expect(a.w.text()).toContain("下载 ZIP")
    expect(a.w.findAll("button").some((b) => b.text().includes("移入回收站"))).toBe(true)
  })

  it("下载：POST 拿票据后用 <a> 原生下载", async () => {
    const { w, fetchFn } = await mountView("admin", 100, 2)
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    await enterSelection(w)
    const grid = w.findComponent(JustifiedGrid)
    grid.vm.$emit("toggle-select", 1)
    grid.vm.$emit("toggle-select", 2)
    await flushPromises()
    await w.findAll("button").find((b) => b.text().includes("下载 ZIP"))!.trigger("click")
    await flushPromises()

    const calls = fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>
    const post = calls.find((c) => c[0] === "/api/download-batch" && c[1]?.method === "POST")!
    expect(JSON.parse(post[1]!.body as string)).toEqual({ image_ids: [1, 2] })
    const anchor = clickSpy.mock.instances[0] as HTMLAnchorElement
    expect(anchor.href).toContain("/api/download-batch/TICK")
    expect(anchor.getAttribute("download")).toBe("photos-test.zip")
  })

  it("超过 me 下发的上限：alert 且不发请求", async () => {
    const { w, fetchFn } = await mountView("admin", 1, 2)
    vi.stubGlobal("alert", vi.fn())
    await enterSelection(w)
    w.findComponent(JustifiedGrid).vm.$emit("toggle-select", 1)
    w.findComponent(JustifiedGrid).vm.$emit("toggle-select", 2)
    await flushPromises()
    await w.findAll("button").find((b) => b.text().includes("下载 ZIP"))!.trigger("click")
    expect(window.alert).toHaveBeenCalled()
    expect((fetchFn.mock.calls as unknown as Array<[string, RequestInit?]>)
      .some((c) => c[0] === "/api/download-batch")).toBe(false)
  })

  it("选择集跨翻页保留；第 201 张被 toast 拒绝", async () => {
    const { w } = await mountView("admin", 100, 201)
    const toast = useToastStore()
    await enterSelection(w)
    w.findComponent(JustifiedGrid).vm.$emit("toggle-select", 1)
    await flushPromises()

    // 翻到第 2 页：选择模式与已选计数保留
    w.findComponent(PaginationBar).vm.$emit("change", 2)
    await flushPromises()
    await flushPromises()
    expect(w.text()).toContain("已选 1 项")

    // 在第 2 页补选第 201 张之前，先用事件把 2..200 选满
    const grid = w.findComponent(JustifiedGrid)
    for (let i = 2; i <= 200; i++) grid.vm.$emit("toggle-select", i)
    grid.vm.$emit("toggle-select", 201)
    await flushPromises()
    expect(toast.items.some((t) => t.text.includes("200"))).toBe(true)
    expect(w.text()).toContain("已选 200 项")
  })
})
```

- [ ] **Step 3: 跑红**

`cd frontend && pnpm test -- browse-selection-download browse-view-delete`
Expected: 新用例 FAIL；改后的旧用例 FAIL（viewer 现在还看不到选择按钮/下载按钮）。

- [ ] **Step 4: 实现** `BrowseView.vue`

import 行改为：

```ts
import { apiGet, apiDelete, apiPost, HttpError, errorMessage } from "../api"
import { useToastStore } from "../stores/toast"
```

setup 内加：

```ts
const toast = useToastStore()

/** 前端选择集硬上限（下载 API Pydantic 上限同为 200）。 */
const SELECT_HARD_LIMIT = 200
const downloading = ref(false)
```

模板：把工具条里整段 `<template v-if="auth.isAdmin"> ... </template>`（含「选择」按钮和全选）替换为：

```html
        <button v-if="!selectionMode"
                type="button"
                class="rounded bg-neutral-800 px-2 py-1 text-neutral-300 hover:bg-neutral-700"
                @click="enterSelectionMode">
          选择
        </button>
        <template v-else>
          <span class="text-neutral-400">已选 {{ selectedIds.size }} 项</span>
          <button type="button"
                  class="rounded bg-neutral-800 px-2 py-1 text-neutral-300 hover:bg-neutral-700"
                  @click="selectAll">
            {{ isAllSelected ? "取消全选" : "全选" }}
          </button>
        </template>
```

底部浮动工具条的按钮区改为：

```html
        <div class="flex items-center gap-2">
          <button type="button"
                  :disabled="selectedIds.size === 0 || downloading"
                  class="rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
                  @click="onBatchDownload">
            {{ downloading ? "准备中..." : `下载 ZIP（${selectedIds.size}）` }}
          </button>
          <button v-if="auth.isAdmin"
                  type="button"
                  :disabled="selectedIds.size === 0 || batchDeleting"
                  class="rounded bg-red-700 px-3 py-1.5 text-sm hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-40"
                  @click="onBatchDelete">
            {{ batchDeleting ? "移入中..." : "移入回收站" }}
          </button>
          <button type="button"
                  class="rounded bg-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-600"
                  @click="exitSelectionMode">
            取消
          </button>
        </div>
```

script 中：

`onToggleSelect` 加硬上限：

```ts
function onToggleSelect(id: number) {
  const s = new Set(selectedIds.value)
  if (s.has(id)) {
    s.delete(id)
  } else {
    if (s.size >= SELECT_HARD_LIMIT) {
      toast.push("error", `一次最多选择 ${SELECT_HARD_LIMIT} 张`)
      return
    }
    s.add(id)
  }
  selectedIds.value = s
}
```

`selectAll` 改为只操作当前批次（取消全选只摘当前批次，保留跨页已选）：

```ts
function selectAll() {
  const s = new Set(selectedIds.value)
  if (isAllSelected.value) {
    for (const it of images.value) s.delete(it.id)
  } else {
    for (const it of images.value) s.add(it.id)
  }
  selectedIds.value = s
}
```

`changePage` 删掉 `exitSelectionMode()` 调用（翻页保留选择集）。

新增下载逻辑：

```ts
function triggerAnchorDownload(href: string, filename: string) {
  const a = document.createElement("a")
  a.href = href
  a.download = filename
  a.rel = "noopener"
  document.body.appendChild(a)
  a.click()
  a.remove()
}

async function onBatchDownload() {
  const ids = Array.from(selectedIds.value)
  if (ids.length === 0) return
  const limit = auth.user?.download_batch_limit ?? 100
  if (ids.length > limit) {
    window.alert(
      `当前设置单次最多下载 ${limit} 张（已选 ${ids.length} 张），请减少选择；` +
      "管理员可在「设置」中调整，最高 200。",
    )
    return
  }
  downloading.value = true
  try {
    const r = await apiPost<{ ticket: string; filename: string; count: number }>(
      "/api/download-batch",
      { image_ids: ids },
    )
    triggerAnchorDownload(`/api/download-batch/${r.ticket}`, r.filename)
    // 浏览器原生下载已接管；无法感知完成，给 1s 防连点窗口
    await new Promise((res) => setTimeout(res, 1000))
  } catch (err) {
    window.alert(`下载失败：${errorMessage(err, "请稍后重试")}`)
  } finally {
    downloading.value = false
  }
}
```

- [ ] **Step 5: 跑绿 + 回归**

```bash
cd frontend && pnpm test -- browse-selection-download browse-view-delete
pnpm build
```

Expected: 全部绿。暂不跑全量（Task 10 还会动 BrowseView），但 `pnpm build` 必须过。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(browse): cross-page selection with 200 cap and ticket zip download"
```

---

### Task 10: BrowseView 搜索态集成

**Files:**
- Modify: `frontend/src/views/BrowseView.vue`
- Test: `frontend/src/tests/browse-search.spec.ts`

**Interfaces:**
- 路由 query：`q`（搜索词）、`scope=all`（整 root；缺省=当前 path 子树）、`image=<id>`（结果 Lightbox）。
- 搜索态隐藏 SubfolderStrip/PaginationBar/普通网格，挂载 SearchResults；普通浏览态零变化。

- [ ] **Step 1: 写失败测试** `frontend/src/tests/browse-search.spec.ts`：

```ts
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent } from "vue"
import { flushPromises, mount } from "@vue/test-utils"
import { createMemoryHistory, createRouter } from "vue-router"
import { createPinia, setActivePinia } from "pinia"
import BrowseView from "../views/BrowseView.vue"
import SearchResults from "../components/SearchResults.vue"
import JustifiedGrid from "../components/JustifiedGrid.vue"
import { useAuthStore } from "../stores/auth"

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

const IMG_A = {
  id: 11, filename: "a.jpg", width: 400, height: 300, sha1: "s11",
  size_bytes: 1, taken_at: null, mtime: 0, is_raw: false,
  relative_path: "2024/旅行/a.jpg",
}
const BROWSE_IMAGES = [
  { id: 1, filename: "x.jpg", width: 40, height: 30, sha1: "s1",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false },
  { id: 2, filename: "y.jpg", width: 40, height: 30, sha1: "s2",
    size_bytes: 1, taken_at: null, mtime: 0, is_raw: false },
]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  })
}

const LightboxStub = defineComponent({
  name: "ImageLightbox",
  props: ["items", "startId", "locationResolver"],
  emits: ["viewInFolder", "close", "change", "deleted"],
  template: `<div class="lb-stub" />`,
})

async function mountAt(url: string) {
  const fetchFn = vi.fn(async (input: RequestInfo | URL) => {
    const u = String(input)
    if (u.includes("/breadcrumbs")) return json([{ name: "R", relative_path: "" }])
    if (u.includes("/folders")) return json([])
    if (u.includes("/search")) {
      return json({
        q: "旅行", path: "", folders_truncated: false,
        folders: [{ name: "旅行", relative_path: "2024/旅行", image_count: 0,
                    descendant_count: 2, cover_thumb_sha1: "sf" }],
        images: [IMG_A], next_cursor: null,
      })
    }
    if (u.includes("/images")) return json({ items: BROWSE_IMAGES, total: 2 })
    return json({ error: { code: "not_found", message: "x" } }, 404)
  })
  vi.stubGlobal("fetch", fetchFn)
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.$patch({ user: { id: 1, username: "u", role: "admin",
                         access_scope: "lan_only", download_batch_limit: 100 } })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/galleries/:gid/r/:rid/:path(.*)*", component: BrowseView },
      { path: "/galleries/:gid/r/:rid/:path(.*)*/image/:iid", component: BrowseView },
    ],
  })
  await router.push(url)
  const w = mount(BrowseView, {
    global: { plugins: [router], stubs: { ImageLightbox: LightboxStub } },
  })
  await flushPromises()
  await flushPromises()
  return { w, router, fetchFn }
}

describe("BrowseView 搜索态", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
  })

  it("?q= 进入搜索态：请求 search、显示文件夹命中、不显示分页条", async () => {
    const { w, fetchFn } = await mountAt("/galleries/1/r/1?q=%E6%97%85%E8%A1%8C")
    const searchCall = (fetchFn.mock.calls as unknown as Array<[string]>).find(
      (c) => c[0].includes("/search"),
    )!
    expect(decodeURIComponent(searchCall[0])).toContain("q=旅行")
    expect(w.text()).toContain("匹配的文件夹")
    expect(w.findComponent(SearchResults).exists()).toBe(true)
    expect(w.text()).not.toContain("此目录暂无图片")
  })

  it("输入搜索词：防抖后写入路由 query 并进入搜索态", async () => {
    vi.useFakeTimers()
    const { w, router } = await mountAt("/galleries/1/r/1")
    const input = w.get('input[aria-label="搜索"]')
    await input.setValue("abc")
    expect(router.currentRoute.value.query.q).toBeUndefined()
    vi.advanceTimersByTime(300)
    await flushPromises()
    expect(router.currentRoute.value.query.q).toBe("abc")
    expect(w.findComponent(SearchResults).exists()).toBe(true)
  })

  it("结果网格 open：以结果集开 Lightbox，resolver 给出目录，viewInFolder 跳目录", async () => {
    const { w, router } = await mountAt("/galleries/1/r/1?q=%E6%97%85%E8%A1%8C")
    w.findComponent(JustifiedGrid).vm.$emit("open", 11)
    await flushPromises()
    expect(router.currentRoute.value.query.image).toBe("11")

    const lb = w.findComponent(LightboxStub)
    expect(lb.props("startId")).toBe(11)
    const resolver = lb.props("locationResolver") as (it: { relative_path?: string }) => string
    expect(resolver(IMG_A)).toBe("2024/旅行")
    expect(resolver({ relative_path: "a.jpg" })).toBe("")

    lb.vm.$emit("viewInFolder", IMG_A)
    await flushPromises()
    expect(router.currentRoute.value.path).toBe("/galleries/1/r/1/2024/旅行")
    expect(router.currentRoute.value.query.q).toBeUndefined()
  })

  it("scope=all 时 SearchResults 的 path 为空（整 root）", async () => {
    const ctx = await mountAt("/galleries/1/r/1/sub?q=x")
    const cb = ctx.w.find('input[type="checkbox"]')
    expect(cb.exists()).toBe(true)
    await cb.setValue(true)
    expect(ctx.router.currentRoute.value.query.scope).toBe("all")
    expect(ctx.w.findComponent(SearchResults).props("path")).toBe("")
  })

  it("改搜索词清空选择集", async () => {
    vi.useFakeTimers()
    const { w } = await mountAt("/galleries/1/r/1?q=old")
    await flushPromises()
    await w.findAll("button").find((b) => b.text() === "选择")!.trigger("click")
    w.findComponent(JustifiedGrid).vm.$emit("toggle-select", 11)
    await flushPromises()
    expect(w.text()).toContain("已选 1 项")

    const input = w.get('input[aria-label="搜索"]')
    await input.setValue("new")
    vi.advanceTimersByTime(300)
    await flushPromises()
    expect(w.text()).not.toContain("已选")
  })
})
```

- [ ] **Step 2: 跑红**

`cd frontend && pnpm test -- browse-search`
Expected: FAIL（搜索态元素不存在）。

- [ ] **Step 3: 实现** `BrowseView.vue`

import：

```ts
import SearchBox from "../components/SearchBox.vue"
import SearchResults from "../components/SearchResults.vue"
```

搜索态状态（`lightboxId` computed 附近）：

```ts
// ---------- 搜索态 ----------

const searchQ = computed(() => String(route.query.q ?? "").trim())
const scopeAll = computed(() => route.query.scope === "all")
const searchItems = ref<ImageRow[]>([])
const resultsRef = ref<InstanceType<typeof SearchResults> | null>(null)

const searchImageId = computed(() => {
  if (!searchQ.value || route.query.image === undefined) return null
  const n = Number(route.query.image)
  return Number.isInteger(n) && n > 0 ? n : null
})

function queryWithoutImage(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(route.query)) {
    if (k === "image" || v === undefined || v === null) continue
    out[k] = Array.isArray(v) ? v.join("/") : String(v)
  }
  return out
}

function onSearchQuery(q: string) {
  const query = queryWithoutImage()
  if (q) query.q = q
  else delete query.q
  router.replace({ query })
}

function onScopeAll(v: boolean) {
  const query = queryWithoutImage()
  if (v) query.scope = "all"
  else delete query.scope
  router.replace({ query })
}

function onSearchItems(items: ImageRow[]) {
  searchItems.value = items
}

function onSearchOpen(id: number) {
  router.replace({ query: { ...queryWithoutImage(), image: String(id) } })
}

function onSearchLightboxClose() {
  router.replace({ query: queryWithoutImage() })
}

function onSearchLightboxChange(id: number) {
  router.replace({ query: { ...queryWithoutImage(), image: String(id) } })
}

/** 图片 → 所在目录（root 根目录返回 ""，Lightbox 仍显示跳转按钮）。 */
function searchLocation(it: ImageRow): string {
  const p = it.relative_path ?? ""
  const i = p.lastIndexOf("/")
  return i >= 0 ? p.slice(0, i) : ""
}

function onViewInFolder(it: ImageRow) {
  const dir = searchLocation(it)
  router.push(
    `/galleries/${gid.value}/r/${rid.value}${dir ? `/${dir}` : ""}`,
  )
}

async function onSearchMenuAction(id: number, action: "delete") {
  if (action !== "delete") return
  const image = searchItems.value.find((it) => it.id === id)
  if (!image) return
  const msg = `确定将「${image.filename}」移入回收站？\n\n30 天内可从「回收站」恢复。`
  if (!window.confirm(msg)) return
  try {
    await apiDelete(`/api/images/${id}`)
  } catch (err) {
    const m = err instanceof HttpError ? err.message : "删除失败"
    window.alert(`删除失败：${m}`)
    return
  }
  await onSearchImageDeleted(id)
}

/** Lightbox 删除成功后的回调：Lightbox 内部已调过 DELETE，这里只做本地摘除 + 重拉。 */
async function onSearchImageDeleted(id: number) {
  searchItems.value = searchItems.value.filter((it) => it.id !== id)
  const s = new Set(selectedIds.value)
  s.delete(id)
  selectedIds.value = s
  await resultsRef.value?.reload()
}
```

`loadAll` 改为搜索态只拉面包屑/文件夹条：

```ts
async function loadAll() {
  loading.value = true
  try {
    const key = currentKey()
    await loadFolders()
    if (searchQ.value) return  // 搜索结果由 SearchResults 自取
    page.value = 1
    await renderPage(key, 1)
    const entry = browse.get(key)
    if (entry?.scrollY) {
      requestAnimationFrame(() => window.scrollTo({ top: entry.scrollY }))
    }
  } finally {
    loading.value = false
  }
}
```

选择集在搜索词/范围变化时清空（放在现有 `watch([gid, rid, path], ...)` 旁）：

```ts
watch([searchQ, scopeAll], () => {
  exitSelectionMode()
})
```

模板：

1. 工具条容器条件改为（让只有子文件夹的目录也能搜索）：

```html
      <div v-if="images.length || folders.length || searchQ" class="mb-2 flex items-center gap-2 text-sm">
```

右侧工具区（`<div class="ml-auto ...">` 内）最前面插入：

```html
          <SearchBox
            :model-value="searchQ"
            :scope-all="scopeAll"
            :is-root="path === ''"
            @update:model-value="onSearchQuery"
            @update:scope-all="onScopeAll"
          />
```

2. 把 `<SubfolderStrip>`、`<component :is="gridComponent">`、空态 `<div>`、`<PaginationBar>` 四个节点包进 `<template v-if="!searchQ"> ... </template>`，并在其后加：

```html
      <SearchResults
        v-else
        ref="resultsRef"
        :gid="gid"
        :rid="rid"
        :q="searchQ"
        :path="scopeAll ? '' : path"
        :grid="gridLayout"
        :selection-mode="selectionMode"
        :selected-ids="selectedIds"
        :show-filename="showFilenames"
        @open="onSearchOpen"
        @toggle-select="onToggleSelect"
        @menu-action="onSearchMenuAction"
        @items-change="onSearchItems"
      />
```

3. Lightbox 区把现有 `<ImageLightbox v-if="lightboxId !== null" ...>` 开头条件改为 `v-if="lightboxId !== null && !searchQ"`，并在其后加第二个：

```html
    <ImageLightbox
      v-else-if="searchImageId !== null && searchItems.some((it) => it.id === searchImageId)"
      :items="searchItems"
      :start-id="searchImageId"
      :location-resolver="searchLocation"
      @close="onSearchLightboxClose"
      @change="onSearchLightboxChange"
      @view-in-folder="onViewInFolder"
      @deleted="onSearchImageDeleted"
    />
```

- [ ] **Step 4: 跑绿 + 全量前端**

```bash
cd frontend && pnpm test -- browse-search
pnpm test
pnpm build
```

Expected: 新测试绿；全套 203 + 本期新增全绿，无类型错误。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(browse): integrated search view with query-synced result lightbox"
```

---

### Task 11: AdminSettings 批量下载上限

**Files:**
- Modify: `frontend/src/views/AdminSettings.vue`
- Modify: `frontend/src/tests/admin-settings.spec.ts`（类型/默认值/PATCH body 断言同步）

**Interfaces:**
- 「批量下载」section：数字输入 `form.download_batch_limit`（10–200），保存走现有 PATCH。

- [ ] **Step 1: 更新既有测试** `admin-settings.spec.ts`

`Settings` interface 与 `DEFAULTS` 加字段：

```ts
interface Settings {
  trash_retention_days: number
  login_lockout_threshold: number
  trusted_proxies: string[]
  session_hours: number
  download_batch_limit: number
}

const DEFAULTS: Settings = {
  trash_retention_days: 30,
  login_lockout_threshold: 5,
  trusted_proxies: [],
  session_hours: 8,
  download_batch_limit: 100,
}
```

`saves changed fields via PATCH` 用例的期望 body 改为（新增键）：

```ts
    expect(JSON.parse(init.body)).toEqual({
      trash_retention_days: 30,
      login_lockout_threshold: 3,
      trusted_proxies: [],
      session_hours: 8,
      download_batch_limit: 100,
    })
```

- [ ] **Step 2: 写失败测试**（同文件 describe 内追加两个用例）：

```ts
  it("加载批量下载上限并可 PATCH", async () => {
    const fetchFn = vi.fn()
    fetchFn
      .mockResolvedValueOnce(json(DEFAULTS))
      .mockResolvedValueOnce(json({ ...DEFAULTS, download_batch_limit: 80 }))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()

    const numbers = w.findAll('input[type="number"]')
    // 顺序：登录锁定阈值、会话时长、批量下载上限
    expect((numbers[2].element as HTMLInputElement).value).toBe("100")
    await numbers[2].setValue(80)
    await w.findAll("button").find((b) => b.text() === "保存")!.trigger("click")
    await flushPromises()

    const [, init] = fetchFn.mock.calls[1]
    expect(JSON.parse(init.body).download_batch_limit).toBe(80)
  })

  it("批量下载上限为空时阻止保存", async () => {
    const fetchFn = vi.fn().mockResolvedValueOnce(json(DEFAULTS))
    vi.stubGlobal("fetch", fetchFn)
    const w = await mountView()
    const numbers = w.findAll('input[type="number"]')
    await numbers[2].setValue("")
    vi.stubGlobal("alert", vi.fn())
    await w.findAll("button").find((b) => b.text() === "保存")!.trigger("click")
    await flushPromises()
    // 只有 GET，没有 PATCH
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })
```

- [ ] **Step 3: 跑红**

`cd frontend && pnpm test -- admin-settings`
Expected: 新用例 FAIL。

- [ ] **Step 4: 实现** `AdminSettings.vue`

`SettingsForm` interface、`form` 默认值、`normalized()`、`load()` 的响应重建、`save()` 的响应重建五处都加 `download_batch_limit`（默认 100），模式与 `session_hours` 完全一致。

在「可信代理」section 之后、保存按钮之前插入：

```html
        <!-- 批量下载 -->
        <section class="rounded-lg bg-neutral-900 p-4">
          <h2 class="mb-3 text-sm font-medium text-neutral-400">批量下载</h2>
          <label class="block text-xs text-neutral-500">
            单次批量下载 ZIP 的图片数量上限（10–200）
          </label>
          <input v-model.number="form.download_batch_limit"
                 type="number" min="10" max="200"
                 class="mt-1 w-28 rounded bg-neutral-800 px-3 py-1.5 text-sm text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500">
          <p class="mt-2 text-xs text-neutral-500">
            对所有用户生效；保存后立即生效。
          </p>
        </section>
```

`save()` 的本地空值校验把新字段纳入：

```ts
  if (
    !isFiniteInput(form.value.login_lockout_threshold) ||
    !isFiniteInput(form.value.session_hours) ||
    !isFiniteInput(form.value.download_batch_limit)
  ) {
    error.value = "请填写有效的数字：锁定阈值、会话时长和批量下载上限不能为空。"
    return
  }
```

- [ ] **Step 5: 跑绿 + 回归**

```bash
cd frontend && pnpm test -- admin-settings
pnpm build
```

Expected: 全绿，类型过。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(settings): batch download limit in admin settings UI"
```

---

### Task 12: 全量验证 + 路线图收尾

**Files:**
- Modify: `docs/superpowers/plans/2026-07-22-roadmap-p2-p7.md`（状态表 P6 行）

- [ ] **Step 1: 后端全量**

```bash
pytest
```

Expected: 全绿（基线 461，本 phase 新增约 45 个用例；skipped 仍为 6）。

- [ ] **Step 2: 前端全量 + 类型/构建**

```bash
cd frontend && pnpm test
pnpm build
```

Expected: 全部通过（基线 203，本期新增约 23 个用例）。

- [ ] **Step 3: 手工冒烟（由用户边用边验，记录在此）**

提示用户在真实库里验证：

1. 子目录/整 root 搜索、文件夹命中跳转、结果 Lightbox 跨目录切换与「在所在文件夹中查看」。
2. viewer 账号登录：选择 → 下载 ZIP；中文文件名解压正确。
3. admin 设置改下载上限为 10，选 11 张时前端拦截；恢复 100。
4. 选 200 张后第 201 张勾不上（toast）。

- [ ] **Step 4: 更新路线图状态表**

`docs/superpowers/plans/2026-07-22-roadmap-p2-p7.md` 状态表中 P6 行改为：

```markdown
| P6 | 搜索 + 批量下载 | ✅ 完成（tag `phase6-search-download`，spec/计划 `2026-10-30-phase6-*.md`）。下载上限可配（10–200，默认 100）；票据两步式流式 ZIP |
```

顶部「状态（2026-10-29）」标题日期改为 `2026-10-31`。

- [ ] **Step 5: 提交 + tag（不 push）**

```bash
git add docs/superpowers/plans/2026-07-22-roadmap-p2-p7.md
git commit -m "docs(roadmap): mark P6 complete"
git tag phase6-search-download
git log --oneline -14
```

不要 `git push`（用户走代理手动推）。

- [ ] **Step 6: 通知主会话更新 memory**

执行完成后，由编排者更新 `memory/roadmap-and-phase-status.md`：P6 完成、P7 下一个、本地 main/分支与 tag 的推送状态。
