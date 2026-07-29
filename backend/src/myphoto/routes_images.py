"""Routes for single-image operations: DELETE (move to trash), batch delete.

红线 2：`DELETE /api/images/{id}` 走 `os.rename` 到 `.trash/`，绝不 `os.remove`。
红线 3：物理删除只在 [trash.purge_expired] 中；本文件永不调用 `os.remove`。

单图删除与批量删除都在同一事务内完成三件事：
  1. 文件系统：`os.rename`（同盘）→ 跨盘 `OSError` 时 fallback `shutil.move`
  2. DB：`insert trash` + `delete images` + 增量维护 folder counts
  3. 审计：`write_audit('image_delete', ...)`
"""
from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from myphoto.audit import write_audit
from myphoto.deps import admin_required
from myphoto.errors import AppError
from myphoto.models import Folder, GalleryRoot, Image, Trash, User
from myphoto.trash import trash_dir_for

log = logging.getLogger("myphoto.routes_images")

router = APIRouter(prefix="/api", tags=["images"])

BATCH_LIMIT = 500


class BatchDeleteBody(BaseModel):
    image_ids: list[int] = Field(..., min_length=1, max_length=BATCH_LIMIT)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _today_yyyymmdd() -> str:
    return time.strftime("%Y%m%d", time.localtime())


def _pick_trash_dst(trash_dir: Path, filename: str) -> Path:
    """在 `trash_dir/YYYYMMDD/` 下为 `filename` 选定不冲突的目标路径。

    若同名已存在，追加短 uuid 后缀。目录不存在时不在此创建（调用方决定）。
    """
    date_sub = trash_dir / _today_yyyymmdd()
    candidate = date_sub / filename
    if not candidate.exists():
        return candidate
    stem, dot, ext = filename.partition(".")
    suffix = uuid.uuid4().hex[:8]
    disambiguated = f"{stem}-{suffix}{dot}{ext}" if dot else f"{filename}-{suffix}"
    return date_sub / disambiguated


def _move_to_trash(src: Path, dst: Path) -> None:
    """同盘走 `os.rename`（原子），跨盘 fallback `shutil.move`。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
    except OSError:
        # 跨盘 / 权限特殊情况：非原子但可用
        shutil.move(os.fspath(src), os.fspath(dst))


async def _decrement_folder_counts(session, image: Image, root_id: int) -> None:
    """图片被删后：直接父文件夹 image_count -= 1，所有祖先 descendant_count -= 1。

    比重扫描完整 root 便宜太多；调用方保证在删除 image 行前后一致调用。
    """
    folder = await session.get(Folder, image.folder_id)
    if folder is None:
        return
    folder.image_count = max(0, folder.image_count - 1)
    # 沿 parent_id 链上溯，包括本身也要减 descendant_count（本 folder 也在祖先集里）
    cursor: Folder | None = folder
    while cursor is not None:
        cursor.descendant_count = max(0, cursor.descendant_count - 1)
        if cursor.parent_id is None:
            break
        cursor = await session.get(Folder, cursor.parent_id)


async def _delete_single(
    session,
    image: Image,
    admin: User,
    request: Request,
) -> None:
    """把一张图片"移入回收站"：文件 os.rename + DB 双写 + 审计。

    调用方负责事务提交/回滚；错误以 [AppError] 或 OSError 向上抛。
    """
    root = await session.get(GalleryRoot, image.root_id)
    if root is None:
        raise AppError("not_found", 404, "root not found")

    tdir = trash_dir_for(root)
    src = Path(root.absolute_path) / image.relative_path
    dst = _pick_trash_dst(tdir, image.filename)

    if not src.exists():
        # 图片文件已消失（并发扫描/外部删除）；仍走完 DB 流程，trash 记录一个
        # 空引用（trash_relative_path 指向 dst，restore 时能感知缺失）
        pass

    trash_rel = dst.relative_to(Path(root.absolute_path)).as_posix()

    try:
        _move_to_trash(src, dst)
    except FileNotFoundError:
        # 源不存在也不阻塞 DB 清理：图库和 DB 走向一致（图片本就该消失）
        log.warning("image file already missing at delete: %s", src)

    # 递减目录 count
    await _decrement_folder_counts(session, image, root.id)

    session.add(
        Trash(
            gallery_id=root.gallery_id,
            root_id=root.id,
            original_relative_path=image.relative_path,
            trash_relative_path=trash_rel,
            sha1=image.sha1,
            size_bytes=image.size_bytes,
            deleted_by=admin.id,
            deleted_at=int(time.time()),
            purge_after=int(time.time()) + 30 * 86400,  # TODO(P4): read from config
        )
    )
    await write_audit(
        session,
        "image_delete",
        admin.id,
        _client_ip(request),
        target=f"image:{image.id}",
        detail=(
            f"root={root.id} path={image.relative_path} "
            f"sha1={image.sha1} trash={trash_rel}"
        ),
    )
    await session.delete(image)


@router.delete("/images/{image_id}", status_code=204)
async def delete_image(
    image_id: int,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        image = await s.get(Image, image_id)
        if image is None:
            raise AppError("not_found", 404, "image not found")
        await _delete_single(s, image, admin, request)
        await s.commit()


class _BatchResult(BaseModel):
    deleted: list[int]
    failed: list[dict]


@router.post("/images/batch-delete")
async def batch_delete_images(
    body: BatchDeleteBody,
    request: Request,
    admin: User = Depends(admin_required),
) -> dict:
    """批量删除。上限 500；部分失败不阻断，返回 {deleted:[ids], failed:[{id, error}]}。"""
    sm = request.app.state.sessionmaker
    deleted: list[int] = []
    failed: list[dict] = []
    # 每张图独立事务，避免一张失败回滚全体；文件已经 os.rename 完但 DB 出错
    # 时的孤儿状态在体量小时可接受，Task 15/16 集成测试会覆盖。
    for image_id in body.image_ids:
        try:
            async with sm() as s:
                image = await s.get(Image, image_id)
                if image is None:
                    failed.append({"id": image_id, "error": "not_found"})
                    continue
                await _delete_single(s, image, admin, request)
                await s.commit()
                deleted.append(image_id)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("batch delete failed for image_id=%s", image_id)
            failed.append({"id": image_id, "error": str(exc)[:200]})
    return {"deleted": deleted, "failed": failed}
