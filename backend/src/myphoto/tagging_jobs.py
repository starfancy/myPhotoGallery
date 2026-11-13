"""打标作业：DB 读写层（与 tagger.py 引擎层分离，方便单测 fake tagger）。

设计文档：docs/tags-upgrade-design.md §3、§8。
- 增量打标串行单张处理，单张失败写 tag_error 不中断（§8.4）
- 已失败图片默认跳过（--force 重试，避免 corrupt 图死循环）
- 人脸聚类增量：与已分配人脸 cosine > 0.5 归入已有簇，否则新建 Pxxx（§8.3）
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image as PILImage
from sqlalchemy import case, delete, func, or_, select, update

from myphoto.models import (
    FaceCluster,
    FaceEmbedding,
    Gallery,
    GalleryRoot,
    Image,
    ImageEmbedding,
)
from myphoto.tagger import FACE_MODEL_VERSION, TAG_MODEL_VERSION, TagResult

log = logging.getLogger("myphoto.tagging_jobs")

# §8.3：新脸与已有簇相似度 > 0.5 归入已有簇（簇构建阶段的阈值更宽松 0.45
# 留在原型；生产只做增量，用 0.5 保守合并）。
CLUSTER_ASSIGN_THRESHOLD = 0.5
_WRITE_BATCH = 50  # 每 N 张提交一次，与 scanner 短事务原则一致


def _report_interval(total: int) -> int:
    """进度回调间隔：约总量 5%，夹在 [10,100]。

    大库（万张）每 100 张一行不刷屏；小库（几十张）间隔 10，配合
    _should_report 的首条/末条规则，3 张这种批量也能看到中间反馈。
    """
    if total <= 1:
        return 1
    return min(100, max(10, total // 20))


def _should_report(done: int, total: int) -> bool:
    """首条（done=1）、末条（done=total）立即报；中间按自适应间隔。"""
    return done == 1 or done == total or done % _report_interval(total) == 0


@dataclass
class TagRunStats:
    total: int = 0
    tagged: int = 0
    failed: int = 0
    skipped_missing: int = 0


@dataclass
class ClusterStats:
    assigned: int = 0
    new_clusters: int = 0


def _emb_to_bytes(emb: np.ndarray) -> bytes:
    return np.asarray(emb, dtype=np.float32).reshape(-1).tobytes()


def _bytes_to_emb(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.float32)


def _pending_query(gallery_id: int | None, folder: str | None, force: bool):
    """构造待打标查询（不执行；调用方在自己的 session 里跑，保证对象绑定）。

    默认模式：``tagged_at IS NULL OR tagged_sha1 != sha1``，且跳过历史失败
    （tag_error IS NOT NULL，§8.4 防 corrupt 图死循环）。
    force 模式：范围内全部重打。
    """
    q = select(Image).join(GalleryRoot, Image.root_id == GalleryRoot.id)
    if gallery_id is not None:
        q = q.where(GalleryRoot.gallery_id == gallery_id)
    if folder:
        # 文件夹前缀：folder/ 下所有文件。LIKE 转义 %/_ 防误命中。
        prefix = folder.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        q = q.where(Image.relative_path.like(f"{prefix}/%", escape="\\"))
    if not force:
        q = q.where(
            or_(Image.tagged_at.is_(None), Image.tagged_sha1 != Image.sha1),
            Image.tag_error.is_(None),
        )
    return q


def _decode_and_tag(tagger, path: Path) -> TagResult:
    with PILImage.open(path) as im:
        return tagger.tag(im)


async def tag_images(
    sm,
    tagger,
    *,
    gallery_id: int | None = None,
    folder: str | None = None,
    force: bool = False,
    progress_cb=None,
) -> TagRunStats:
    """逐张打标主循环。tagger 为 None 时抛 RuntimeError（调用方应先检查）。

    整个循环用同一个 session（每 _WRITE_BATCH 张提交一次）——ORM 对象必须
    绑定在写 session 上，否则 detached 修改不会落库。长任务持有一个
    WAL 连接，对读无影响。
    """
    if tagger is None:
        raise RuntimeError("tagger 不可用（模型未就位）")

    now = int(time.time())
    stats = TagRunStats()
    dirty = 0

    async with sm() as s:
        images = (await s.execute(_pending_query(gallery_id, folder, force))).scalars().all()
        stats.total = len(images)
        roots = {
            r.id: r.absolute_path
            for r in (await s.execute(select(GalleryRoot))).scalars().all()
        }

        for idx, image in enumerate(images):
            abs_root = roots.get(image.root_id)
            path = Path(abs_root) / image.relative_path if abs_root else None
            if path is None or not path.exists():
                image.tag_error = "file missing"[:500]
                stats.skipped_missing += 1
            else:
                try:
                    result = await asyncio.to_thread(_decode_and_tag, tagger, path)
                except Exception as exc:
                    log.warning("tag failed for %s: %s", path, exc)
                    image.tag_error = str(exc)[:500]
                    stats.failed += 1
                else:
                    image.scene_major = result.scene_major
                    image.scene_minor = result.scene_minor
                    image.scene_conf = result.scene_conf
                    image.person_count = result.person_count
                    image.tagged_at = now
                    image.tag_model_version = TAG_MODEL_VERSION
                    image.tagged_sha1 = image.sha1
                    image.tag_error = None
                    await _persist_embeddings(s, image.id, result, now)
                    stats.tagged += 1

            dirty += 1
            if dirty >= _WRITE_BATCH:
                await s.commit()
                dirty = 0
            if progress_cb is not None and _should_report(idx + 1, stats.total):
                await progress_cb(idx + 1, stats.total, image.relative_path)
        await s.commit()

    return stats


async def _persist_embeddings(s, image_id: int, result: TagResult, now: int) -> None:
    """upsert image_embeddings；face_embeddings 先清后插（force 重打场景）。"""
    existing = await s.get(ImageEmbedding, image_id)
    if existing is None:
        s.add(ImageEmbedding(
            image_id=image_id,
            embedding=_emb_to_bytes(result.image_embedding),
            model_version=TAG_MODEL_VERSION,
            created_at=now,
        ))
    else:
        existing.embedding = _emb_to_bytes(result.image_embedding)
        existing.model_version = TAG_MODEL_VERSION

    await s.execute(
        delete(FaceEmbedding).where(FaceEmbedding.image_id == image_id)
    )
    for face_index, face in enumerate(result.faces):
        s.add(FaceEmbedding(
            image_id=image_id,
            face_index=face_index,
            bbox=str(list(face.bbox)),
            embedding=_emb_to_bytes(face.embedding),
            confidence=face.confidence,
            cluster_id=None,
            model_version=FACE_MODEL_VERSION,
            created_at=now,
        ))


async def cluster_faces(sm, progress_cb=None) -> ClusterStats:
    """增量人脸聚类：只处理 cluster_id IS NULL 的人脸。

    - 与任一已分配人脸 cosine > 0.5 → 归入该人脸的簇（不建新 ID，§8.3）
    - 否则新建簇 Pxxx（编号取现有最大 +1）
    """
    stats = ClusterStats()
    now = int(time.time())

    async with sm() as s:
        assigned_rows = (await s.execute(
            select(FaceEmbedding.id, FaceEmbedding.cluster_id, FaceEmbedding.embedding)
            .where(FaceEmbedding.cluster_id.is_not(None))
        )).all()
        unassigned = (await s.execute(
            select(FaceEmbedding).where(FaceEmbedding.cluster_id.is_(None))
            .order_by(FaceEmbedding.id)
        )).scalars().all()
        if not unassigned:
            return stats

        max_n = 0
        existing_clusters = (await s.execute(select(FaceCluster))).scalars().all()
        for c in existing_clusters:
            if c.cluster_id.startswith("P"):
                try:
                    max_n = max(max_n, int(c.cluster_id[1:]))
                except ValueError:
                    pass
        for _rid, cid, _emb in assigned_rows:
            if cid.startswith("P"):
                try:
                    max_n = max(max_n, int(cid[1:]))
                except ValueError:
                    pass

        # 已分配矩阵（动态追加）
        assigned_embs: list[np.ndarray] = [
            _bytes_to_emb(raw) for _rid, _cid, raw in assigned_rows
        ]
        assigned_cluster_ids: list[str] = [cid for _rid, cid, _raw in assigned_rows]

        to_update: list[tuple[str, int]] = []  # (cluster_id, face_id)
        new_clusters: dict[str, list[int]] = {}

        for idx, face in enumerate(unassigned):
            emb = _bytes_to_emb(face.embedding)
            chosen: str | None = None
            if assigned_embs:
                matrix = np.stack(assigned_embs)
                sims = matrix @ emb
                best = int(sims.argmax())
                if sims[best] > CLUSTER_ASSIGN_THRESHOLD:
                    chosen = assigned_cluster_ids[best]
            if chosen is None:
                max_n += 1
                chosen = f"P{max_n:03d}"
                new_clusters.setdefault(chosen, []).append(face.id)
                stats.new_clusters += 1
            to_update.append((chosen, face.id))
            assigned_embs.append(emb)
            assigned_cluster_ids.append(chosen)
            stats.assigned += 1
            if progress_cb is not None and _should_report(idx + 1, len(unassigned)):
                await progress_cb(idx + 1, len(unassigned), chosen)

        for cluster_id, face_id in to_update:
            await s.execute(
                update(FaceEmbedding)
                .where(FaceEmbedding.id == face_id)
                .values(cluster_id=cluster_id)
            )
        for cluster_id, face_ids in new_clusters.items():
            s.add(FaceCluster(
                cluster_id=cluster_id,
                display_name=None,
                sample_face_id=face_ids[0],
                created_at=now,
                updated_at=now,
            ))
        await s.commit()

    return stats


async def relabel(sm, tagger, progress_cb=None) -> int:
    """基于已有 image_embeddings 重算场景标签（不跑视觉模型）。"""
    if tagger is None:
        raise RuntimeError("tagger 不可用（模型未就位）")
    updated = 0
    async with sm() as s:
        rows = (await s.execute(
            select(ImageEmbedding.image_id, ImageEmbedding.embedding, Image)
            .join(Image, Image.id == ImageEmbedding.image_id)
        )).all()
        for idx, (image_id, raw, image) in enumerate(rows):
            try:
                major, minor, conf = tagger.classify_embedding(_bytes_to_emb(raw))
            except Exception as exc:
                log.warning("relabel failed for image %s: %s", image_id, exc)
                continue
            image.scene_major = major
            image.scene_minor = minor
            image.scene_conf = conf
            updated += 1
            if progress_cb is not None and _should_report(idx + 1, len(rows)):
                await progress_cb(idx + 1, len(rows), None)
        await s.commit()
    return updated


async def tag_status(sm) -> list[dict]:
    """每图库打标状态：total / tagged / failed / pending。"""
    tagged_cnt = func.sum(case((Image.tagged_at.is_not(None), 1), else_=0))
    failed_cnt = func.sum(case((Image.tag_error.is_not(None), 1), else_=0))
    async with sm() as s:
        rows = (await s.execute(
            select(
                Gallery.name,
                func.count(Image.id),
                tagged_cnt,
                failed_cnt,
            )
            .join(GalleryRoot, Image.root_id == GalleryRoot.id)
            .join(Gallery, Gallery.id == GalleryRoot.gallery_id)
            .group_by(Gallery.name)
        )).all()
    return [
        {
            "gallery": name,
            "total": int(total),
            "tagged": int(tagged or 0),
            "failed": int(failed or 0),
            "pending": int(total or 0) - int(tagged or 0) - int(failed or 0),
        }
        for name, total, tagged, failed in rows
    ]
