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

    from myphoto.core.models import Gallery, GalleryRoot

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


def test_empty_query_without_filter_returns_empty(env):
    c, _, gid, rid = env
    # 无关键词且无筛选：不再 400，返回空结果（不做全量倾倒）
    body = search(c, gid, rid, q="   ").json()
    assert body["images"] == [] and body["folders"] == []


def test_search_scene_filter(env):
    c, app, gid, rid = env
    async def _tag():
        from sqlalchemy import update
        from myphoto.core.models import Image
        async with app.state.sessionmaker() as s:
            await s.execute(update(Image).where(Image.filename == "apple.JPG")
                             .values(scene_major="食物", scene_minor="甜点", tagged_at=1))
            await s.commit()
    c.portal.call(_tag)

    # 纯筛选（无关键词）：命中带标签的图
    body = search(c, gid, rid, scene_major="食物").json()
    assert [i["filename"] for i in body["images"]] == ["apple.JPG"]
    assert body["folders"] == []  # 无关键词 → 无文件夹区块
    # 二级联动
    body = search(c, gid, rid, scene_major="食物", scene_minor="甜点").json()
    assert len(body["images"]) == 1
    body = search(c, gid, rid, scene_major="城市建筑").json()
    assert body["images"] == []
    # 关键词 + 场景叠加
    body = search(c, gid, rid, q="apple", scene_major="食物").json()
    assert len(body["images"]) == 1
    body = search(c, gid, rid, q="apple", scene_major="城市建筑").json()
    assert body["images"] == []


def test_search_date_range_filter(env):
    c, app, gid, rid = env
    async def _tag():
        from sqlalchemy import update
        from myphoto.core.models import Image
        async with app.state.sessionmaker() as s:
            await s.execute(update(Image).where(Image.filename == "apple.JPG")
                             .values(taken_at=1_700_000_000))
            await s.execute(update(Image).where(Image.filename == "a_b.jpg")
                             .values(taken_at=1_600_000_000))
            await s.commit()
    c.portal.call(_tag)

    # 纯日期筛选（无关键词），含边界
    body = search(c, gid, rid, date_from=1_700_000_000, date_to=1_800_000_000).json()
    assert [i["filename"] for i in body["images"]] == ["apple.JPG"]
    # taken_at 为 NULL 的图在日期筛选下被排除
    body = search(c, gid, rid, date_from=1_500_000_000).json()
    names = {i["filename"] for i in body["images"]}
    assert "apple.JPG" in names and "a_b.jpg" in names
    # 区间反转 → 400
    r = search(c, gid, rid, date_from=2_000_000_000, date_to=1_000_000_000)
    assert r.status_code == 400


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
    from myphoto.core.models import User
    from myphoto.core.security import hash_password

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
