"""Routes for the trash: list, restore, batch-restore, delete-one, purge.

红线 3：物理删除 (`os.remove`) 由 [trash.py] 提供的 [delete_one] / [purge_expired]
统一处理，均带 [is_under_trash_dir] 前缀护栏。本文件不直接调用 `os.remove`。

恢复策略（轻量）：不触发完整 root 扫描——
  1. 从 trash 记录读原路径 + sha1
  2. 若原路径已存在文件（有人重新拍/新扫描进来），在文件名 stem 后追加
     ' (restored YYYYMMDD-HHMMSS)' 以避免覆盖
  3. `os.rename` .trash -> 原路径（跨盘 fallback shutil.move）
  4. 直接写回 images 表；沿 parent_id 链把父目录 image_count/祖先
     descendant_count +1
  5. 删除 trash 行 + 写审计 image_restore
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from myphoto.audit import write_audit
from myphoto.deps import admin_required
from myphoto.errors import AppError
from myphoto.formats import classify
from myphoto.models import Folder, GalleryRoot, Image, Trash, User
from myphoto.trash import delete_one as _trash_delete_one, purge_expired

log = logging.getLogger("myphoto.routes_trash")

router = APIRouter(prefix="/api/trash", tags=["trash"])

BATCH_LIMIT = 500
LIST_DEFAULT_LIMIT = 100
LIST_MAX_LIMIT = 500


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------- helpers ----------


async def _restore_dst(root: GalleryRoot, original_rel: str) -> Path:
    """确定恢复目标路径：若原位已被占用，追加 `(restored YYYYMMDD-HHMMSS)` 后缀。"""
    dst = Path(root.absolute_path) / original_rel
    if not dst.exists():
        return dst
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    stem, dot, ext = dst.name.partition(".")
    suffix = f" (restored {stamp})"
    new_name = f"{stem}{suffix}{dot}{ext}" if dot else f"{dst.name}{suffix}"
    return dst.with_name(new_name)


def _move_from_trash(src: Path, dst: Path) -> None:
    """同盘 `os.rename`；跨盘 fallback `shutil.move`。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dst)
    except OSError:
        shutil.move(os.fspath(src), os.fspath(dst))


async def _ensure_folder_chain(
    session, root_id: int, relative_dir: str
) -> Folder:
    """确保 `relative_dir` 及其所有祖先 folder 都在 DB 中存在，返回叶节点。

    与 scanner._ensure_folders 独立以避免依赖循环；仅创建，不 flush 之外的额外
    副作用。空字符串 `""` 表示 root folder。
    """
    parts = [p for p in relative_dir.split("/") if p] if relative_dir else []
    existing = {
        f.relative_path: f for f in (
            await session.execute(select(Folder).where(Folder.root_id == root_id))
        ).scalars().all()
    }
    parent: Folder | None = None
    cur = ""
    # 保证 root folder 也存在
    if "" not in existing:
        root_folder = Folder(
            root_id=root_id, relative_path="", name="",
            parent_id=None, image_count=0, descendant_count=0,
        )
        session.add(root_folder)
        await session.flush()
        existing[""] = root_folder
    parent = existing[""]
    for name in parts:
        cur = f"{cur}/{name}" if cur else name
        f = existing.get(cur)
        if f is None:
            f = Folder(
                root_id=root_id, relative_path=cur, name=name,
                parent_id=parent.id, image_count=0, descendant_count=0,
            )
            session.add(f)
            await session.flush()
            existing[cur] = f
        parent = f
    return parent


async def _increment_folder_counts(session, folder: Folder) -> None:
    """恢复一张图片后：直接父 image_count +=1；沿 parent_id 链祖先 descendant_count += 1。

    与 [routes_images._decrement_folder_counts] 对称。
    """
    folder.image_count += 1
    cursor: Folder | None = folder
    while cursor is not None:
        cursor.descendant_count += 1
        if cursor.parent_id is None:
            break
        cursor = await session.get(Folder, cursor.parent_id)


async def _restore_one(
    session, trash_row: Trash, admin: User, request: Request,
) -> dict:
    """恢复一条 trash：文件搬回 + insert images + 增量 counts + 审计 image_restore + 删 trash 行。

    返回 ``{"trash_id": int, "status": "restored"|"missing_source"|"not_found_root", "image_id": int|None, "restored_to": str}``
    """
    root = await session.get(GalleryRoot, trash_row.root_id)
    if root is None:
        return {
            "trash_id": trash_row.id,
            "status": "not_found_root",
            "image_id": None,
            "restored_to": None,
        }

    src = Path(root.absolute_path) / trash_row.trash_relative_path
    if not src.exists():
        # trash 文件已消失（外部误删）；DB 里 trash 行留着以便调查
        return {
            "trash_id": trash_row.id,
            "status": "missing_source",
            "image_id": None,
            "restored_to": None,
        }

    dst = await _restore_dst(root, trash_row.original_relative_path)
    try:
        _move_from_trash(src, dst)
    except OSError as exc:
        log.exception("restore failed for trash_id=%s", trash_row.id)
        raise AppError("internal_error", 500, f"restore failed: {exc}")

    # dst 相对 root 的路径 = 恢复后的 image.relative_path
    restored_rel = dst.relative_to(Path(root.absolute_path)).as_posix()
    parent_rel = restored_rel.rsplit("/", 1)[0] if "/" in restored_rel else ""
    folder = await _ensure_folder_chain(session, root.id, parent_rel)

    stat = os.stat(dst)
    filename = dst.name
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    kind = classify(filename)
    now = int(time.time())
    # 试图从图片本身读一次尺寸和 EXIF；失败则用默认（不阻断）
    width, height, taken_at, exif_json = None, None, None, None
    try:
        from myphoto.scanner import _process_file

        _sha1, w, h, t, e = _process_file(dst, kind == "raw")
        width, height, taken_at, exif_json = w, h, t, e
    except Exception:
        log.warning("could not re-read metadata for restored file %s", dst, exc_info=True)

    image = Image(
        root_id=root.id,
        folder_id=folder.id,
        relative_path=restored_rel,
        filename=filename,
        ext=ext,
        size_bytes=int(stat.st_size),
        width=width,
        height=height,
        sha1=trash_row.sha1,
        mtime=int(stat.st_mtime),
        taken_at=taken_at,
        is_raw=int(kind == "raw"),
        indexed_at=now,
        exif_json=exif_json,
    )
    session.add(image)
    await session.flush()

    await _increment_folder_counts(session, folder)

    await write_audit(
        session,
        "image_restore",
        admin.id,
        _client_ip(request),
        target=f"trash:{trash_row.id}",
        detail=f"image={image.id} root={root.id} path={restored_rel}",
    )
    await session.delete(trash_row)
    return {
        "trash_id": trash_row.id,
        "status": "restored",
        "image_id": image.id,
        "restored_to": restored_rel,
    }


# ---------- routes ----------


TrashSort = Literal["deleted_at_desc", "deleted_at_asc"]


@router.get("")
async def list_trash(
    request: Request,
    gallery_id: Optional[int] = None,
    root_id: Optional[int] = None,
    sort: TrashSort = "deleted_at_desc",
    limit: int = Query(LIST_DEFAULT_LIMIT, ge=1, le=LIST_MAX_LIMIT),
    cursor: Optional[int] = None,
    admin: User = Depends(admin_required),
) -> dict:
    """分页列出回收站。cursor 用最后一行的 trash id（简单 keyset 分页）。"""
    sm = request.app.state.sessionmaker
    async with sm() as s:
        stmt = select(Trash)
        if gallery_id is not None:
            stmt = stmt.where(Trash.gallery_id == gallery_id)
        if root_id is not None:
            stmt = stmt.where(Trash.root_id == root_id)
        if sort == "deleted_at_desc":
            stmt = stmt.order_by(Trash.deleted_at.desc(), Trash.id.desc())
            if cursor is not None:
                stmt = stmt.where(Trash.id < cursor)
        else:
            stmt = stmt.order_by(Trash.deleted_at.asc(), Trash.id.asc())
            if cursor is not None:
                stmt = stmt.where(Trash.id > cursor)
        stmt = stmt.limit(limit + 1)
        rows = (await s.execute(stmt)).scalars().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        entries = [
            {
                "id": t.id,
                "gallery_id": t.gallery_id,
                "root_id": t.root_id,
                "original_relative_path": t.original_relative_path,
                "trash_relative_path": t.trash_relative_path,
                "sha1": t.sha1,
                "size_bytes": t.size_bytes,
                "deleted_by": t.deleted_by,
                "deleted_at": t.deleted_at,
                "purge_after": t.purge_after,
            }
            for t in rows
        ]
        next_cursor = rows[-1].id if has_more and rows else None
        return {"entries": entries, "next_cursor": next_cursor}


@router.post("/{trash_id}/restore")
async def restore_trash(
    trash_id: int,
    request: Request,
    admin: User = Depends(admin_required),
) -> dict:
    sm = request.app.state.sessionmaker
    async with sm() as s:
        row = await s.get(Trash, trash_id)
        if row is None:
            raise AppError("not_found", 404, "trash entry not found")
        result = await _restore_one(s, row, admin, request)
        if result["status"] == "missing_source":
            raise AppError("not_found", 404, "trash file missing on disk")
        if result["status"] == "not_found_root":
            raise AppError("not_found", 404, "gallery root missing")
        await s.commit()
        return result


class BatchRestoreBody(BaseModel):
    trash_ids: list[int] = Field(..., min_length=1, max_length=BATCH_LIMIT)


@router.post("/batch-restore")
async def batch_restore_trash(
    body: BatchRestoreBody,
    request: Request,
    admin: User = Depends(admin_required),
) -> dict:
    """批量恢复。逐条独立事务，部分失败不阻断；返回 {restored, failed}。"""
    sm = request.app.state.sessionmaker
    restored: list[dict] = []
    failed: list[dict] = []
    for trash_id in body.trash_ids:
        try:
            async with sm() as s:
                row = await s.get(Trash, trash_id)
                if row is None:
                    failed.append({"id": trash_id, "error": "not_found"})
                    continue
                result = await _restore_one(s, row, admin, request)
                if result["status"] != "restored":
                    failed.append({"id": trash_id, "error": result["status"]})
                    continue
                await s.commit()
                restored.append(result)
        except Exception as exc:
            log.exception("batch restore failed for trash_id=%s", trash_id)
            failed.append({"id": trash_id, "error": str(exc)[:200]})
    return {"restored": restored, "failed": failed}


@router.delete("/{trash_id}", status_code=204)
async def delete_trash_entry(
    trash_id: int,
    request: Request,
    admin: User = Depends(admin_required),
):
    """物理删除单条回收站条目——委托给 trash.delete_one（红线 3 单点）。"""
    sm = request.app.state.sessionmaker
    async with sm() as s:
        result = await _trash_delete_one(
            s, trash_id,
            actor_user_id=admin.id,
            actor_ip=_client_ip(request),
        )
        status = result["status"]
        if status == "not_found":
            raise AppError("not_found", 404, "trash entry not found")
        if status == "blocked":
            await s.commit()  # 提交护栏审计
            raise AppError("forbidden", 403, "trash entry path outside TRASH_DIR")
        if status == "errors":
            raise AppError("internal_error", 500, "delete failed")
        await s.commit()


class PurgeBody(BaseModel):
    gallery_id: Optional[int] = None
    root_id: Optional[int] = None
    before: Optional[int] = None
    confirm: bool = False


@router.post("/purge")
async def purge_trash(
    body: PurgeBody,
    request: Request,
    admin: User = Depends(admin_required),
) -> dict:
    """按 purge_after 过期规则清理。必须 `confirm=true`。"""
    if not body.confirm:
        raise AppError(
            "confirmation_required", 400,
            "purge requires confirm=true",
        )
    sm = request.app.state.sessionmaker
    async with sm() as s:
        result = await purge_expired(
            s,
            gallery_id=body.gallery_id,
            root_id=body.root_id,
            before=body.before,
            actor_user_id=admin.id,
            actor_ip=_client_ip(request),
        )
        # 总审计（成功 + 失败情况都写一条）
        await write_audit(
            s, "trash_purge", admin.id, _client_ip(request),
            target=(
                f"gallery:{body.gallery_id}" if body.gallery_id is not None
                else "all"
            ),
            detail=(
                f"purged={result['purged']} blocked={result['blocked']} "
                f"missing={result['missing']} errors={result['errors']}"
            ),
        )
        await s.commit()
        return result
