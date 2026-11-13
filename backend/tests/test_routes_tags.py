"""tags Phase 3 人物簇 API 测试：list / images / rename。"""

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


async def _seed(app, photos):
    from myphoto.models import Gallery, GalleryRoot

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


async def _tag_cluster(app, images_spec):
    """直接写 face_clusters + face_embeddings + images 标签。

    images_spec: [(filename, taken_at), ...]
    """
    from sqlalchemy import select
    from myphoto.models import FaceCluster, FaceEmbedding, Folder, GalleryRoot, Image

    async with app.state.sessionmaker() as s:
        root = (await s.execute(select(GalleryRoot))).scalar_one()
        folder = Folder(
            root_id=root.id, relative_path="", name="", image_count=0, descendant_count=0,
        )
        s.add(folder)
        await s.flush()
        s.add(FaceCluster(
            cluster_id="P001", display_name=None, sample_face_id=None,
            created_at=int(time.time()), updated_at=int(time.time()),
        ))
        await s.flush()
        face_id = None
        for filename, taken_at in images_spec:
            img = Image(
                root_id=root.id, folder_id=folder.id,
                relative_path=filename, filename=filename, ext="jpg",
                size_bytes=100, sha1="sha_" + filename, mtime=int(time.time()),
                taken_at=taken_at, indexed_at=int(time.time()),
            )
            s.add(img)
            await s.flush()
            s.add(FaceEmbedding(
                image_id=img.id, face_index=0, bbox="[0,0,10,10]",
                embedding=b"\x00" * 20, confidence=0.9,
                cluster_id="P001", model_version="v1", created_at=int(time.time()),
            ))
        await s.commit()


@pytest.fixture
def client(tmp_path, capsys):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    _jpg(photos / "b.jpg")
    cfg = tmp_path / "config.toml"
    app = build_app(config_path=str(cfg))
    with TestClient(app) as c:
        out = capsys.readouterr().out
        pw = re.search(r"password=(\S+)", out).group(1)
        c.post("/api/auth/login", json={"username": "admin", "password": pw})
        gid, rid = c.portal.call(_seed, app, photos)
        c.portal.call(_tag_cluster, app, [
            ("a.jpg", 1704067200),  # 2024-01-01
            ("b.jpg", None),         # 无 EXIF 日期
        ])
        yield c, gid, rid


def test_list_clusters(client):
    c, _gid, _rid = client
    r = c.get("/api/tags/clusters")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["cluster_id"] == "P001"
    assert body[0]["image_count"] == 2


def test_list_clusters_hides_orphan_empty_clusters(client):
    """force 重打后无 face 指向的孤儿簇不应出现在列表。"""
    c, _gid, _rid = client
    app = c.app

    async def _add_orphan():
        from myphoto.models import FaceCluster
        async with app.state.sessionmaker() as s:
            s.add(FaceCluster(
                cluster_id="P999", display_name="孤儿", sample_face_id=None,
                created_at=int(time.time()), updated_at=int(time.time()),
            ))
            await s.commit()
    c.portal.call(_add_orphan)

    body = c.get("/api/tags/clusters").json()
    ids = [row["cluster_id"] for row in body]
    assert "P001" in ids
    assert "P999" not in ids


def test_cluster_images_groups_by_year_month(client):
    c, _gid, _rid = client
    r = c.get("/api/tags/clusters/P001/images")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    groups = body["groups"]
    # 2024-01 一组 + 未知日期一组 (0,0)
    years = {(g["year"], g["month"]) for g in groups}
    assert (2024, 1) in years
    assert (0, 0) in years  # taken_at=None 的图归未知组
    jan = next(g for g in groups if g["year"] == 2024)
    assert len(jan["images"]) == 1
    assert jan["images"][0]["filename"] == "a.jpg"


def test_rename_cluster(client):
    c, _gid, _rid = client
    r = c.put("/api/tags/clusters/P001", json={"display_name": "张三"})
    assert r.status_code == 200
    assert r.json()["display_name"] == "张三"
    # 列表里应回显新名字
    body = c.get("/api/tags/clusters").json()
    assert body[0]["display_name"] == "张三"
    # 清空命名 → None
    r = c.put("/api/tags/clusters/P001", json={"display_name": "  "})
    assert r.json()["display_name"] is None


def test_cluster_not_found(client):
    c, _gid, _rid = client
    assert c.get("/api/tags/clusters/P999/images").status_code == 404
    assert c.put("/api/tags/clusters/P999", json={"display_name": "x"}).status_code == 404
