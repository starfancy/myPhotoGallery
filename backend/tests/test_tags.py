"""tags upgrade Phase 1 单测：tagger 聚合纯函数、打标作业、聚类、CLI、scanner 挂钩。

真实模型不参与这些测试（单测秒级）；用 fake tagger / 合成向量覆盖逻辑分支。
"""

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image as PILImage
from sqlalchemy import select, update

from myphoto.cli import cli
from myphoto.core.db import create_all, make_engine, make_sessionmaker
from myphoto.core.models import (
    FaceCluster,
    FaceEmbedding,
    Folder,
    Gallery,
    GalleryRoot,
    Image,
    ImageEmbedding,
)
from myphoto.services.scanner import Scanner
from myphoto.services.tagger import HIERARCHY, TAG_MODEL_VERSION, TagResult, classify_scene, flatten_prompts


# ---------- helpers ----------


def _unit_vec(dim: int, first: int) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[first % dim] = 1.0
    return v


@dataclass
class FakeTagResult:
    scene_major: str = "自然风光"
    scene_minor: str = "山景"
    scene_conf: float = 0.87
    person_count: int = 0
    image_embedding: np.ndarray | None = None
    faces: list = None


class FakeTagger:
    """不加载任何模型的假打标器；tag() 返回固定结果（可逐文件定制）。"""

    def __init__(self, result: FakeTagResult | None = None, fail: bool = False):
        self._result = result or FakeTagResult(image_embedding=_unit_vec(512, 1))
        self.fail = fail
        self.calls: list[str] = []

    def tag(self, image: PILImage.Image) -> TagResult:
        self.calls.append(str(image.size))
        if self.fail:
            raise RuntimeError("fake boom")
        from myphoto.services.tagger import FaceResult

        faces = []
        for i in range(self._result.person_count):
            faces.append(FaceResult(
                bbox=(i, i, i + 10, i + 10), confidence=0.9,
                embedding=_unit_vec(512, i + 1),
            ))
        return TagResult(
            scene_major=self._result.scene_major,
            scene_minor=self._result.scene_minor,
            scene_conf=self._result.scene_conf,
            person_count=self._result.person_count,
            image_embedding=self._result.image_embedding,
            faces=faces,
        )

    def classify_embedding(self, emb):
        return self._result.scene_major, self._result.scene_minor, self._result.scene_conf


def _jpg(path: Path, w: int = 40, h: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    PILImage.new("RGB", (w, h), (10, 20, 30)).save(path, "JPEG")


def test_decode_and_tag_routes_by_extension(tmp_path, monkeypatch):
    """普通图与 RAW 走统一解码入口，is_raw 由扩展名判定。"""
    from myphoto.services.tagging_jobs import _decode_and_tag

    calls: list[tuple[str, bool]] = []

    def fake_load(path, is_raw):
        calls.append((Path(path).name, is_raw))
        return PILImage.new("RGB", (32, 24))

    monkeypatch.setattr("myphoto.services.tagging_jobs.load_pil_image", fake_load)
    raw = tmp_path / "shot.ORF"
    jpg = tmp_path / "shot.jpg"
    raw.write_bytes(b"x")
    _jpg(jpg)

    _decode_and_tag(FakeTagger(), raw)
    _decode_and_tag(FakeTagger(), jpg)
    assert calls == [("shot.ORF", True), ("shot.jpg", False)]


@pytest.fixture
async def env(tmp_path):
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    root_dir = tmp_path / "photos"
    root_dir.mkdir()
    async with sm() as session:
        gallery = Gallery(name="G", created_at=int(time.time()))
        session.add(gallery)
        await session.flush()
        gallery_id = gallery.id
        root = GalleryRoot(
            gallery_id=gallery_id,
            label="R",
            absolute_path=str(root_dir.resolve()),
            enabled=1,
        )
        session.add(root)
        await session.commit()
        await session.refresh(root)
        root_id = root.id
    yield root_dir, sm, root_id, gallery_id
    await engine.dispose()


async def _add_image(sm, root_id: int, rel_path: str, sha1: str = "abc123",
                     tag_error: str | None = None) -> int:
    async with sm() as s:
        folder_path = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
        folder = (await s.execute(
            select(Folder).where(Folder.root_id == root_id, Folder.relative_path == folder_path)
        )).scalar_one_or_none()
        if folder is None:
            folder = Folder(root_id=root_id, relative_path=folder_path, name=folder_path.rsplit("/", 1)[-1] if folder_path else "")
            s.add(folder)
            await s.flush()
        img = Image(
            root_id=root_id, folder_id=folder.id, relative_path=rel_path,
            filename=rel_path.rsplit("/", 1)[-1], ext="jpg", size_bytes=100,
            sha1=sha1, mtime=1000, indexed_at=int(time.time()), tag_error=tag_error,
        )
        s.add(img)
        await s.commit()
        await s.refresh(img)
        return img.id


# ---------- classify_scene（纯函数，不碰模型） ----------


def test_classify_scene_picks_top_major_and_minor_inside_it():
    prompts = flatten_prompts()
    sims = np.zeros(len(prompts))
    # 把"山景"下第一个 prompt 打到最高
    mountain_idx = prompts.index(("自然风光", "山景", HIERARCHY["自然风光"]["山景"][0]))
    sims[mountain_idx] = 1.0
    major, minor, conf = classify_scene(sims)
    assert major == "自然风光"
    assert minor == "山景"
    assert conf == pytest.approx(1.0)


def test_classify_scene_minor_max_within_major_ignores_other_majors():
    prompts = flatten_prompts()
    sims = np.zeros(len(prompts))
    # "湖泊" prompt 打 0.9；"海滩海岸" 两个 prompt 分别 0.7 / 0.8（组内 max=0.8）
    lake = prompts.index(("自然风光", "湖泊", HIERARCHY["自然风光"]["湖泊"][0]))
    beach0 = prompts.index(("自然风光", "海滩海岸", HIERARCHY["自然风光"]["海滩海岸"][0]))
    beach1 = prompts.index(("自然风光", "海滩海岸", HIERARCHY["自然风光"]["海滩海岸"][1]))
    sims[lake] = 0.9
    sims[beach0] = 0.7
    sims[beach1] = 0.8
    major, minor, conf = classify_scene(sims)
    # 一级得分：自然风光 = max(0.9, 0.8) = 0.9；其它一级都是 0 → 自然风光胜出
    assert major == "自然风光"
    # top1 一级内：湖泊 0.9 > 海滩 0.8
    assert minor == "湖泊"
    assert conf == pytest.approx(0.9)


# ---------- tag_images ----------


async def test_tag_images_writes_tags_and_embeddings(env):
    from myphoto.services.tagging_jobs import tag_images

    root_dir, sm, root_id, _gallery_id = env
    _jpg(root_dir / "a.jpg")
    _jpg(root_dir / "b.jpg")
    id_a = await _add_image(sm, root_id, "a.jpg")
    id_b = await _add_image(sm, root_id, "b.jpg")

    stats = await tag_images(sm, FakeTagger())
    assert stats.total == 2
    assert stats.tagged == 2
    assert stats.failed == 0

    async with sm() as s:
        for img_id in (id_a, id_b):
            img = await s.get(Image, img_id)
            assert img.scene_major == "自然风光"
            assert img.scene_minor == "山景"
            assert img.tagged_sha1 == img.sha1
            assert img.tagged_at is not None
            assert img.tag_error is None
            emb = await s.get(ImageEmbedding, img_id)
            assert emb is not None
            assert emb.model_version == TAG_MODEL_VERSION


async def test_tag_images_skips_history_failed_until_force(env):
    from myphoto.services.tagging_jobs import tag_images

    root_dir, sm, root_id, _gallery_id = env
    _jpg(root_dir / "a.jpg")
    await _add_image(sm, root_id, "a.jpg", tag_error="corrupt")

    # 默认模式：历史失败的图被跳过（§8.4 防死循环）
    stats = await tag_images(sm, FakeTagger())
    assert stats.total == 0
    assert stats.tagged == 0

    # force：范围内全量重打
    stats = await tag_images(sm, FakeTagger(), force=True)
    assert stats.total == 1
    assert stats.tagged == 1
    async with sm() as s:
        img = (await s.execute(select(Image))).scalar_one()
        assert img.tag_error is None


async def test_tag_images_retry_failed_only_picks_error_rows(env):
    from myphoto.services.tagging_jobs import tag_images

    root_dir, sm, root_id, _gallery_id = env
    _jpg(root_dir / "ok.jpg")
    _jpg(root_dir / "broken.jpg")
    _jpg(root_dir / "fresh.jpg")
    await _add_image(sm, root_id, "ok.jpg", sha1="s1")  # 已成功（默认跑一次）
    await tag_images(sm, FakeTagger())
    await _add_image(sm, root_id, "broken.jpg", sha1="s2", tag_error="RAW decode failed")
    fresh_id = await _add_image(sm, root_id, "fresh.jpg", sha1="s3")  # 从未打标

    stats = await tag_images(sm, FakeTagger(), retry_failed=True)
    assert stats.total == 1 and stats.tagged == 1

    async with sm() as s:
        broken = (await s.execute(select(Image).where(Image.filename == "broken.jpg"))).scalar_one()
        fresh = await s.get(Image, fresh_id)
        assert broken.tag_error is None and broken.tagged_at is not None
        assert fresh.tagged_at is None  # 未打标的不在 retry-failed 范围


async def test_tag_images_hash_changed_retags_but_unchanged_skips(env):
    from myphoto.services.tagging_jobs import tag_images

    root_dir, sm, root_id, _gallery_id = env
    _jpg(root_dir / "a.jpg")
    img_id = await _add_image(sm, root_id, "a.jpg", sha1="oldsha")

    # 第一次打标：tagged_sha1 = oldsha
    await tag_images(sm, FakeTagger())
    async with sm() as s:
        img = await s.get(Image, img_id)
        assert img.tagged_sha1 == "oldsha"

    # sha1 变了 → 待打标（§8.1 hash 联动）
    async with sm() as s:
        await s.execute(update(Image).where(Image.id == img_id).values(sha1="newsha"))
        await s.commit()
    stats = await tag_images(sm, FakeTagger())
    assert stats.total == 1
    async with sm() as s:
        img = await s.get(Image, img_id)
        assert img.tagged_sha1 == "newsha"

    # 再跑一次：已打标且 sha1 一致 → 0 待处理
    stats = await tag_images(sm, FakeTagger())
    assert stats.total == 0


async def test_tag_images_single_failure_does_not_abort(env):
    from myphoto.services.tagging_jobs import tag_images

    root_dir, sm, root_id, _gallery_id = env
    _jpg(root_dir / "good.jpg")
    _jpg(root_dir / "bad.jpg")
    id_good = await _add_image(sm, root_id, "good.jpg")
    await _add_image(sm, root_id, "bad.jpg")

    # tag() 对所有图都抛 → 两张都记 tag_error，不炸
    stats = await tag_images(sm, FakeTagger(fail=True))
    assert stats.failed == 2
    assert stats.tagged == 0
    async with sm() as s:
        rows = (await s.execute(select(Image))).scalars().all()
        assert all(r.tag_error == "fake boom" for r in rows)
        assert all(r.tagged_at is None for r in rows)


# ---------- cluster_faces ----------


async def _insert_face(sm, image_id: int, vec: np.ndarray, cluster_id: str | None = None):
    from myphoto.services.tagging_jobs import _emb_to_bytes

    async with sm() as s:
        s.add(FaceEmbedding(
            image_id=image_id, face_index=0,
            embedding=_emb_to_bytes(vec), confidence=0.9,
            cluster_id=cluster_id, model_version="v1", created_at=int(time.time()),
        ))
        await s.commit()


async def test_cluster_faces_reuses_existing_cluster_id(env):
    from myphoto.services.tagging_jobs import cluster_faces

    _root_dir, sm, root_id, _gallery_id = env
    img1 = await _add_image(sm, root_id, "a.jpg")

    # 已分配：P001 簇里有 vecA；P002 里有 vecB
    vecA = _unit_vec(512, 0)
    vecB = _unit_vec(512, 10)
    await _insert_face(sm, img1, vecA, cluster_id="P001")
    await _insert_face(sm, img1, vecB, cluster_id="P002")
    async with sm() as s:
        s.add(FaceCluster(cluster_id="P001", created_at=1, updated_at=1))
        s.add(FaceCluster(cluster_id="P002", created_at=1, updated_at=1))
        await s.commit()

    # 未分配：vecA' ≈ vecA（cosine=1）应归入 P001；vecStranger 应开新簇
    vecA2 = vecA.copy()
    vecA2[0] = 0.99
    vecA2[1] = 0.1
    vecA2 /= np.linalg.norm(vecA2)
    await _insert_face(sm, img1, vecA2)            # 与 P001 同源
    await _insert_face(sm, img1, _unit_vec(512, 200))  # 陌生人

    stats = await cluster_faces(sm)
    assert stats.assigned == 2
    assert stats.new_clusters == 1  # 陌生人开了新簇，P001/P002 复用

    async with sm() as s:
        rows = (await s.execute(
            select(FaceEmbedding).where(FaceEmbedding.cluster_id.is_(None))
        )).all()
        assert rows == []
        clusters = (await s.execute(select(FaceCluster))).scalars().all()
        ids = {c.cluster_id for c in clusters}
        assert "P001" in ids and "P002" in ids
        new = ids - {"P001", "P002"}
        assert len(new) == 1
        new_id = new.pop()
        assert new_id.startswith("P")
        # 新编号必须 > 现有最大（P002 → P003）
        assert new_id == "P003"


# ---------- prune_orphan_clusters ----------


async def test_prune_removes_unnamed_orphans_but_keeps_used_and_named(env):
    from myphoto.services.tagging_jobs import prune_orphan_clusters

    _root_dir, sm, root_id, _gid = env
    img = await _add_image(sm, root_id, "a.jpg")
    now = int(time.time())
    async with sm() as s:
        # P001 有 face 指向（正常簇）；P002 孤儿未命名；P003 孤儿但已命名
        s.add(FaceCluster(cluster_id="P001", created_at=now, updated_at=now))
        s.add(FaceCluster(cluster_id="P002", created_at=now, updated_at=now))
        s.add(FaceCluster(cluster_id="P003", display_name="张三",
                          created_at=now, updated_at=now))
        await s.commit()
    await _insert_face(sm, img, _unit_vec(512, 0), cluster_id="P001")

    # 默认：只删未命名孤儿 P002，保留 P001（在用）和 P003（命名）
    removed = await prune_orphan_clusters(sm)
    assert removed == ["P002"]
    async with sm() as s:
        ids = set((await s.execute(select(FaceCluster.cluster_id))).scalars().all())
    assert ids == {"P001", "P003"}

    # include_named：连命名孤儿 P003 也删，在用的 P001 仍保留
    removed = await prune_orphan_clusters(sm, include_named=True)
    assert removed == ["P003"]
    async with sm() as s:
        ids = set((await s.execute(select(FaceCluster.cluster_id))).scalars().all())
    assert ids == {"P001"}


# ---------- tag_status ----------


async def test_tag_status_counts(env):
    from myphoto.services.tagging_jobs import tag_images, tag_status

    root_dir, sm, root_id, _gallery_id = env
    _jpg(root_dir / "a.jpg")
    _jpg(root_dir / "b.jpg")
    await _add_image(sm, root_id, "a.jpg")
    await _add_image(sm, root_id, "b.jpg", tag_error="corrupt")

    rows = await tag_status(sm)
    assert len(rows) == 1
    assert rows[0]["total"] == 2
    assert rows[0]["tagged"] == 0
    assert rows[0]["failed"] == 1
    assert rows[0]["pending"] == 1  # 减 tagged 与 failed

    stats = await tag_images(sm, FakeTagger(), force=True)
    assert stats.tagged == 2  # force：两张都重打（含历史失败那张）
    rows = await tag_status(sm)
    assert rows[0]["tagged"] == 2
    assert rows[0]["failed"] == 0  # force 重打后 tag_error 清空


# ---------- scanner 挂钩 ----------


async def test_scanner_hook_tags_changed_images_not_unchanged(env):
    from myphoto.services.tagging_jobs import tag_images

    root_dir, sm, root_id, _gallery_id = env
    _jpg(root_dir / "a.jpg")

    tagger = FakeTagger()
    scanner = Scanner(sm, tagger=tagger)
    await scanner.scan_root_now(root_id)
    assert len(tagger.calls) == 1  # 只有 a.jpg 被打标

    async with sm() as s:
        img = (await s.execute(select(Image))).scalar_one()
        assert img.scene_major == "自然风光"
        assert img.tagged_sha1 == img.sha1

    # 第二次扫描：mtime+size 未变 → unchanged 分支，不重跑 tagger
    tagger.calls.clear()
    await scanner.scan_root_now(root_id)
    assert tagger.calls == []


async def test_scanner_hook_tag_failure_does_not_break_scan(env):
    root_dir, sm, root_id, _gallery_id = env
    _jpg(root_dir / "a.jpg")

    scanner = Scanner(sm, tagger=FakeTagger(fail=True))
    await scanner.scan_root_now(root_id)  # 不炸

    async with sm() as s:
        img = (await s.execute(select(Image))).scalar_one()
        assert img.tag_error == "fake boom"
        assert img.scene_major is None  # 标签没落上
        # 但图片本身入库正常
        assert img.filename == "a.jpg"


# ---------- CLI ----------


def test_cli_tag_status_outputs_gallery_row(tmp_path):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    assert runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"]).exit_code == 0
    assert runner.invoke(cli, [
        "--config", str(cfg), "add-root", "Home", "R", str(photos.resolve()),
    ]).exit_code == 0
    assert runner.invoke(cli, ["--config", str(cfg), "rescan"]).exit_code == 0

    r = runner.invoke(cli, ["--config", str(cfg), "tag", "status"])
    assert r.exit_code == 0, r.output
    assert "Home" in r.output
    assert "total" in r.output
    # tmp config 的 models_dir 不存在 → models ready: NO
    assert "models ready" in r.output


def test_cli_tag_run_friendly_error_when_models_missing(tmp_path):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    runner.invoke(cli, ["--config", str(cfg), "add-root", "Home", "R", str(photos.resolve())])
    runner.invoke(cli, ["--config", str(cfg), "rescan"])

    r = runner.invoke(cli, ["--config", str(cfg), "tag", "run"])
    assert r.exit_code != 0
    assert "tagger 不可用" in r.output


def test_cli_tag_status_reports_backend_line(tmp_path):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    runner.invoke(cli, ["--config", str(cfg), "add-root", "Home", "R", str(photos.resolve())])
    runner.invoke(cli, ["--config", str(cfg), "rescan"])

    r = runner.invoke(cli, ["--config", str(cfg), "tag", "status"])
    assert r.exit_code == 0, r.output
    assert "inference backend" in r.output


def test_cli_tag_run_force_and_retry_failed_are_mutually_exclusive(tmp_path):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    runner.invoke(cli, ["--config", str(cfg), "add-root", "Home", "R", str(photos.resolve())])

    r = runner.invoke(cli, ["--config", str(cfg), "tag", "run", "--force", "--retry-failed"])
    assert r.exit_code != 0
    assert "retry-failed" in r.output or "互斥" in r.output


def test_cli_tag_run_zero_result_hints_retry_failed(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    cfg = tmp_path / "config.toml"
    runner = CliRunner()
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    runner.invoke(cli, ["--config", str(cfg), "add-root", "Home", "R", str(photos.resolve())])
    runner.invoke(cli, ["--config", str(cfg), "rescan"])
    # 无模型文件的 tmp 环境：注入 FakeTagger 让命令走到主循环
    import myphoto.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_build_tagger", lambda cfg_, cp: (FakeTagger(), None))
    # 手工把唯一图片置为历史失败
    import sqlite3
    con = sqlite3.connect(tmp_path / "app.db")
    con.execute("UPDATE images SET tag_error = 'RAW decode failed'")
    con.commit()
    con.close()

    r = runner.invoke(cli, ["--config", str(cfg), "tag", "run"])
    assert r.exit_code == 0, r.output
    assert "scanned=0" in r.output
    assert "retry-failed" in r.output


def test_cli_tag_run_explicit_cuda_unavailable_has_hint(tmp_path, monkeypatch):
    photos = tmp_path / "photos"
    _jpg(photos / "a.jpg")
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[app]\njwt_secret="secret-value-of-sufficient-length-xxxxx"\n'
        '[tagging]\ndevice = "cuda"\n',
        encoding="utf-8",
    )
    import onnxruntime as ort
    monkeypatch.setattr(ort, "get_available_providers", lambda: ["CPUExecutionProvider"])

    runner = CliRunner()
    runner.invoke(cli, ["--config", str(cfg), "add-gallery", "Home"])
    runner.invoke(cli, ["--config", str(cfg), "add-root", "Home", "R", str(photos.resolve())])
    runner.invoke(cli, ["--config", str(cfg), "rescan"])
    r = runner.invoke(cli, ["--config", str(cfg), "tag", "run"])
    assert r.exit_code != 0
    assert "CUDAExecutionProvider" in r.output
    assert "onnxruntime-gpu" in r.output
