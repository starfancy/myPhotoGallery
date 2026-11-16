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
    from myphoto.core.models import Gallery, GalleryRoot

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
    from myphoto.core.models import FaceCluster, FaceEmbedding, Folder, GalleryRoot, Image

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
        from myphoto.core.models import FaceCluster
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


def test_cluster_images_include_lightbox_and_location_fields(client):
    """图片项包含灯箱所需 ImageRow 字段与图库/位置字段；夹具图片都在 root 根。"""
    c, gid, rid = client
    body = c.get("/api/tags/clusters/P001/images").json()
    # 分组按 (年,月) 倒序，第一个分组是 2024-01 的 a.jpg
    img = body["groups"][0]["images"][0]
    assert img["filename"] == "a.jpg"
    # 与浏览接口 _image_payload 对齐的灯箱字段
    assert img["size_bytes"] == 100
    assert isinstance(img["mtime"], int)
    assert img["is_raw"] is False
    assert img["scene_major"] is None
    assert img["scene_minor"] is None
    # 位置字段
    assert img["gallery_id"] == gid
    assert img["root_id"] == rid
    assert img["gallery_name"] == "G"
    assert img["folder_path"] == ""


def test_cluster_images_folder_path_uses_directory_part(client):
    """子目录图片的 folder_path 是 relative_path 的目录部分；根目录图片为空串。"""
    c, _gid, _rid = client
    app = c.app

    async def _add_subfolder_face():
        from sqlalchemy import select
        from myphoto.core.models import FaceEmbedding, Folder, GalleryRoot, Image

        async with app.state.sessionmaker() as s:
            root = (await s.execute(select(GalleryRoot))).scalar_one()
            sub = Folder(
                root_id=root.id, relative_path="sub", name="sub",
                image_count=1, descendant_count=1,
            )
            s.add(sub)
            await s.flush()
            img = Image(
                root_id=root.id, folder_id=sub.id,
                relative_path="sub/x.jpg", filename="x.jpg", ext="jpg",
                size_bytes=100, sha1="sha_x", mtime=int(time.time()),
                taken_at=1704067200, indexed_at=int(time.time()),
            )
            s.add(img)
            await s.flush()
            s.add(FaceEmbedding(
                image_id=img.id, face_index=0, bbox="[0,0,10,10]",
                embedding=b"\x00" * 20, confidence=0.9,
                cluster_id="P001", model_version="v1", created_at=int(time.time()),
            ))
            await s.commit()

    c.portal.call(_add_subfolder_face)
    body = c.get("/api/tags/clusters/P001/images").json()
    by_name = {im["filename"]: im for g in body["groups"] for im in g["images"]}
    assert by_name["x.jpg"]["folder_path"] == "sub"
    assert by_name["a.jpg"]["folder_path"] == ""


def test_cluster_cover_interprets_legacy_and_normalized_bbox(client, monkeypatch):
    """同一像素区域：legacy 行存像素框、v3 行存归一化分数，cover 裁剪坐标必须一致；
    20% 外扩在图像边缘仍 clamp 到图像边界。"""
    c, _gid, _rid = client
    app = c.app

    async def _seed_covers():
        from sqlalchemy import select
        from myphoto.core.models import FaceCluster, FaceEmbedding, Folder, GalleryRoot, Image
        from myphoto.services.tagger import TAG_MODEL_VERSION

        async with app.state.sessionmaker() as s:
            root = (await s.execute(select(GalleryRoot))).scalar_one()
            folder = (await s.execute(
                select(Folder).where(Folder.root_id == root.id, Folder.relative_path == "")
            )).scalar_one()
            photos = Path(root.absolute_path)
            now = int(time.time())
            # 200x100 图。中部框 (10,10)-(50,50)；贴边框 (0,0)-(20,10)
            cases = [
                # (文件, 簇, 图片 tag 戳, bbox JSON)
                ("legacy_mid.jpg", "P002", "clip-v2-yolo11n-insightface", "[10,10,50,50]"),
                ("norm_mid.jpg", "P003", TAG_MODEL_VERSION, "[0.05,0.1,0.25,0.5]"),
                ("legacy_edge.jpg", "P004", "clip-v2-yolo11n-insightface", "[0,0,20,10]"),
                ("norm_edge.jpg", "P005", TAG_MODEL_VERSION, "[0.0,0.0,0.1,0.1]"),
            ]
            for filename, cluster_id, stamp, bbox in cases:
                _jpg(photos / filename, size=(200, 100))
                img = Image(
                    root_id=root.id, folder_id=folder.id,
                    relative_path=filename, filename=filename, ext="jpg",
                    size_bytes=100, sha1="sha_" + filename, mtime=now,
                    taken_at=1704067200, indexed_at=now,
                    tag_model_version=stamp,
                )
                s.add(img)
                await s.flush()
                s.add(FaceCluster(
                    cluster_id=cluster_id, display_name=None, sample_face_id=None,
                    created_at=now, updated_at=now,
                ))
                s.add(FaceEmbedding(
                    image_id=img.id, face_index=0, bbox=bbox,
                    embedding=b"\x00" * 20, confidence=0.9,
                    cluster_id=cluster_id, model_version="w600k-mbf-v1", created_at=now,
                ))
            await s.commit()

    c.portal.call(_seed_covers)

    boxes: list[tuple] = []

    def spy_crop(self, box):
        boxes.append(tuple(box))
        return self  # 不真裁：后续 thumbnail/save 在整图上也能跑通

    monkeypatch.setattr(PILImage.Image, "crop", spy_crop)
    expected = {
        "P002": (2, 2, 58, 58),      # legacy 像素框 +20% 外扩
        "P003": (2, 2, 58, 58),      # 归一化分数还原后应与 legacy 完全一致
        "P004": (0, 0, 24, 12),      # 贴边框外扩被 clamp 到 0
        "P005": (0, 0, 24, 12),
    }
    for cluster_id, want in expected.items():
        r = c.get(f"/api/tags/clusters/{cluster_id}/face.jpg")
        assert r.status_code == 200
        assert boxes[-1] == want
