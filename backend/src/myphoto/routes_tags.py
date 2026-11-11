"""人物簇 API（tags Phase 3）：簇列表、簇内照片、重命名。

设计文档 §4.4 / §5。簇内照片按年/月分组返回，人物页直接渲染。
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select, update

from myphoto.access import access_scope_guard
from myphoto.errors import AppError
from myphoto.models import (
    FaceCluster,
    FaceEmbedding,
    Image,
    User,
)

router = APIRouter(prefix="/api/tags", tags=["tags"])


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


async def _get_cluster_or_404(s, cluster_id: str) -> FaceCluster:
    c = await s.get(FaceCluster, cluster_id)
    if c is None:
        raise AppError("not_found", 404, "cluster not found")
    return c


@router.get("/clusters")
async def list_clusters(
    request: Request,
    response: Response,
    _user: User = Depends(access_scope_guard),
):
    """人物簇列表：按该簇下照片数降序。"""
    _no_store(response)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        # 每簇照片数 = 该簇人脸去重 image_id 数
        rows = (await s.execute(
            select(
                FaceCluster,
                func.count(func.distinct(FaceEmbedding.image_id)),
            )
            .outerjoin(FaceEmbedding, FaceEmbedding.cluster_id == FaceCluster.cluster_id)
            .group_by(FaceCluster.cluster_id)
            .order_by(func.count(func.distinct(FaceEmbedding.image_id)).desc())
        )).all()
        out = []
        for c, n_images in rows:
            out.append({
                "cluster_id": c.cluster_id,
                "display_name": c.display_name,
                "sample_face_id": c.sample_face_id,
                "image_count": int(n_images or 0),
            })
        return out


@router.get("/clusters/{cluster_id}/images")
async def cluster_images(
    cluster_id: str,
    request: Request,
    response: Response,
    limit: int = Query(200, ge=1, le=500),
    _user: User = Depends(access_scope_guard),
):
    """某簇下的照片（去重 image_id），按年/月分组。

    返回 { groups: [{year, month, images: [...]}], total: n }
    taken_at 缺失的归入 year=0 month=0 的"未知日期"组（§8.7）。
    """
    _no_store(response)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        await _get_cluster_or_404(s, cluster_id)
        image_ids = (await s.execute(
            select(FaceEmbedding.image_id)
            .where(FaceEmbedding.cluster_id == cluster_id)
            .distinct()
        )).scalars().all()
        if not image_ids:
            return {"groups": [], "total": 0}

        rows = (await s.execute(
            select(Image)
            .where(Image.id.in_(image_ids))
            .order_by(Image.taken_at.desc().nullslast(), Image.id.desc())
            .limit(limit)
        )).scalars().all()

        # 按年/月分桶（taken_at 缺失 → 未知组，§8.7；不回退 mtime，
        # 因为 mtime 是文件系统时间，不是拍摄时间，按月分组会误导）
        groups: dict[tuple[int, int], list[dict]] = {}
        for img in rows:
            if img.taken_at:
                lt = time.localtime(img.taken_at)
                key = (lt.tm_year, lt.tm_mon)
            else:
                key = (0, 0)
            item = {
                "id": img.id,
                "filename": img.filename,
                "width": img.width,
                "height": img.height,
                "sha1": img.sha1,
                "taken_at": img.taken_at,
            }
            groups.setdefault(key, []).append(item)

        out_groups = []
        for (year, month), items in sorted(groups.items(), key=lambda kv: kv[0], reverse=True):
            out_groups.append({"year": year, "month": month, "images": items})
        return {"groups": out_groups, "total": len(image_ids)}


@router.put("/clusters/{cluster_id}")
async def rename_cluster(
    cluster_id: str,
    request: Request,
    response: Response,
    payload: dict,
    _user: User = Depends(access_scope_guard),
):
    """重命名人物簇。payload: {"display_name": "张三"}；空串/None = 清除命名。"""
    _no_store(response)
    name = payload.get("display_name")
    if name is not None:
        name = str(name).strip()
        if len(name) > 50:
            raise AppError("bad_request", 400, "name too long (max 50)")
        name = name or None  # 空串 → NULL（未命名）
    sm = request.app.state.sessionmaker
    async with sm() as s:
        await _get_cluster_or_404(s, cluster_id)
        await s.execute(
            update(FaceCluster)
            .where(FaceCluster.cluster_id == cluster_id)
            .values(display_name=name, updated_at=int(time.time()))
        )
        await s.commit()
        c = await _get_cluster_or_404(s, cluster_id)
        return {"cluster_id": c.cluster_id, "display_name": c.display_name}
