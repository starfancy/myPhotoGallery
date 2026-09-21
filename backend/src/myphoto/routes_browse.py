from __future__ import annotations

import base64
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import and_, func, or_, select

from myphoto.access import access_scope_guard, gallery_scope_guard
from myphoto.errors import AppError
from myphoto.models import Folder, Gallery, GalleryRoot, Image, User, UserGallery
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
    r = (
        await s.execute(
            select(GalleryRoot).where(
                GalleryRoot.id == rid, GalleryRoot.gallery_id == gid
            )
        )
    ).scalar_one_or_none()
    if r is None or r.enabled != 1:
        raise AppError("not_found", 404, "root not found")
    return r


@router.get("/galleries")
async def list_galleries(
    request: Request,
    response: Response,
    user: User = Depends(access_scope_guard),
):
    _no_store(response)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        if user.role == "admin":
            gals = (await s.execute(select(Gallery))).scalars().all()
        else:
            # viewer：仅列出 user_galleries 中授权的图库
            gals = (
                await s.execute(
                    select(Gallery)
                    .join(UserGallery, UserGallery.gallery_id == Gallery.id)
                    .where(UserGallery.user_id == user.id)
                )
            ).scalars().all()
        out = []
        for g in gals:
            root_count = (
                await s.execute(
                    select(func.count())
                    .select_from(GalleryRoot)
                    .where(GalleryRoot.gallery_id == g.id)
                )
            ).scalar_one()
            image_count = (
                await s.execute(
                    select(func.count())
                    .select_from(Image)
                    .join(GalleryRoot, GalleryRoot.id == Image.root_id)
                    .where(GalleryRoot.gallery_id == g.id)
                )
            ).scalar_one()
            out.append(
                {
                    "id": g.id,
                    "name": g.name,
                    "description": g.description,
                    "root_count": root_count,
                    "image_count": image_count,
                }
            )
        return out


@router.get("/galleries/{gid}")
async def gallery_detail(
    gid: int,
    request: Request,
    response: Response,
    _user: User = Depends(gallery_scope_guard),
):
    _no_store(response)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        g = await s.get(Gallery, gid)
        if g is None:
            raise AppError("not_found", 404, "gallery not found")
        roots = (
            await s.execute(select(GalleryRoot).where(GalleryRoot.gallery_id == gid))
        ).scalars().all()
        root_out = []
        for r in roots:
            cnt = (
                await s.execute(
                    select(func.count())
                    .select_from(Image)
                    .where(Image.root_id == r.id)
                )
            ).scalar_one()
            root_out.append(
                {
                    "id": r.id,
                    "label": r.label,
                    "image_count": cnt,
                    "offline": r.last_scan_status == "error",
                    "enabled": bool(r.enabled),
                }
            )
        return {
            "gallery": {
                "id": g.id,
                "name": g.name,
                "description": g.description,
            },
            "roots": root_out,
        }


@router.get("/galleries/{gid}/roots/{rid}/folders")
async def list_folders(
    gid: int,
    rid: int,
    request: Request,
    response: Response,
    path: str = "",
    _user: User = Depends(gallery_scope_guard),
):
    _no_store(response)
    rel = _norm_or_400(path)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        await _get_root_or_404(s, gid, rid)
        parent = (
            await s.execute(
                select(Folder).where(
                    Folder.root_id == rid, Folder.relative_path == rel
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            return []
        children = (
            await s.execute(
                select(Folder)
                .where(Folder.root_id == rid, Folder.parent_id == parent.id)
                .order_by(Folder.name.asc())
            )
        ).scalars().all()
        out = []
        for c in children:
            cover = (
                await s.execute(
                    select(Image.sha1)
                    .where(Image.folder_id == c.id)
                    .order_by(Image.filename.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            out.append(
                {
                    "name": c.name,
                    "relative_path": c.relative_path,
                    "image_count": c.image_count,
                    "descendant_count": c.descendant_count,
                    "cover_thumb_sha1": cover,
                }
            )
        return out


@router.get("/galleries/{gid}/roots/{rid}/breadcrumbs")
async def breadcrumbs(
    gid: int,
    rid: int,
    request: Request,
    response: Response,
    path: str = "",
    _user: User = Depends(gallery_scope_guard),
):
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


def _encode_cursor(sort: str, sort_key_value, last_id: int) -> str:
    raw = f"{sort}\x1f{sort_key_value}\x1f{last_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        parts = raw.split("\x1f", 2)
        sort_val = parts[1]
        last_id = int(parts[2])
        return sort_val, last_id
    except Exception:
        raise AppError("path_invalid", 400, "invalid cursor")


@router.get("/galleries/{gid}/roots/{rid}/images")
async def list_images(
    gid: int,
    rid: int,
    request: Request,
    response: Response,
    path: str = "",
    sort: Sort = "name_asc",
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    cursor: str | None = None,
    _user: User = Depends(gallery_scope_guard),
):
    _no_store(response)
    rel = _norm_or_400(path)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        await _get_root_or_404(s, gid, rid)
        folder = (
            await s.execute(
                select(Folder).where(
                    Folder.root_id == rid, Folder.relative_path == rel
                )
            )
        ).scalar_one_or_none()
        if folder is None:
            return {"items": [], "next_cursor": None, "total": 0}
        total = (
            await s.execute(
                select(func.count())
                .select_from(Image)
                .where(Image.folder_id == folder.id)
            )
        ).scalar_one()
        q = select(Image).where(Image.folder_id == folder.id)
        if sort == "name_asc":
            q = q.order_by(Image.filename.asc(), Image.id.asc())
            if cursor:
                last_val, last_id = _decode_cursor(cursor)
                q = q.where(or_(
                    Image.filename > last_val,
                    and_(Image.filename == last_val, Image.id > last_id)
                ))
        elif sort == "name_desc":
            q = q.order_by(Image.filename.desc(), Image.id.desc())
            if cursor:
                last_val, last_id = _decode_cursor(cursor)
                q = q.where(or_(
                    Image.filename < last_val,
                    and_(Image.filename == last_val, Image.id < last_id)
                ))
        elif sort == "taken_at_asc":
            q = q.order_by(Image.taken_at.asc().nullsfirst(), Image.id.asc())
            if cursor:
                last_val, last_id = _decode_cursor(cursor)
                last_val_int = int(last_val) if last_val != "None" else None
                if last_val_int is not None:
                    q = q.where(or_(
                        Image.taken_at > last_val_int,
                        and_(Image.taken_at == last_val_int, Image.id > last_id)
                    ))
                else:
                    q = q.where(Image.taken_at.isnot(None))
                    q = q.where(Image.id > last_id)
        elif sort == "taken_at_desc":
            q = q.order_by(Image.taken_at.desc().nullslast(), Image.id.desc())
            if cursor:
                last_val, last_id = _decode_cursor(cursor)
                if last_val != "None":
                    q = q.where(or_(
                        Image.taken_at < int(last_val),
                        and_(Image.taken_at == int(last_val), Image.id < last_id)
                    ))
                else:
                    q = q.where(Image.taken_at.is_(None))
        else:  # size_desc
            q = q.order_by(Image.size_bytes.desc(), Image.id.desc())
            if cursor:
                last_val, last_id = _decode_cursor(cursor)
                q = q.where(or_(
                    Image.size_bytes < int(last_val),
                    and_(Image.size_bytes == int(last_val), Image.id < last_id)
                ))
        # cursor 为旧的“加载更多” keyset 分页；不传时按 offset 分页（页码跳转）
        if not cursor:
            q = q.offset(offset)
        q = q.limit(limit + 1)
        rows = (await s.execute(q)).scalars().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            {
                "id": r.id,
                "filename": r.filename,
                "width": r.width,
                "height": r.height,
                "sha1": r.sha1,
                "size_bytes": r.size_bytes,
                "taken_at": r.taken_at,
                "is_raw": bool(r.is_raw),
            }
            for r in rows
        ]
        if has_more and rows:
            if sort in ("name_asc", "name_desc"):
                next_cursor = _encode_cursor(sort, rows[-1].filename, rows[-1].id)
            elif sort in ("taken_at_asc", "taken_at_desc"):
                next_cursor = _encode_cursor(
                    sort,
                    str(rows[-1].taken_at) if rows[-1].taken_at is not None else "None",
                    rows[-1].id,
                )
            else:  # size_desc
                next_cursor = _encode_cursor(sort, str(rows[-1].size_bytes), rows[-1].id)
            return {"items": items, "next_cursor": next_cursor, "total": total}
        return {"items": items, "next_cursor": None, "total": total}
