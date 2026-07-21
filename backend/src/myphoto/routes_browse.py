from __future__ import annotations

import base64
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select

from myphoto.deps import current_user
from myphoto.errors import AppError
from myphoto.models import Folder, Gallery, GalleryRoot, Image, User
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
    _user: User = Depends(current_user),
):
    _no_store(response)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        gals = (await s.execute(select(Gallery))).scalars().all()
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
    _user: User = Depends(current_user),
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
    _user: User = Depends(current_user),
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
    _user: User = Depends(current_user),
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


def _encode_cursor(sort_key: str, iid: int) -> str:
    raw = f"{sort_key}\x1f{iid}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        k, i = raw.split("\x1f", 1)
        return k, int(i)
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
    cursor: str | None = None,
    _user: User = Depends(current_user),
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
            return {"items": [], "next_cursor": None}
        q = select(Image).where(Image.folder_id == folder.id)
        if sort == "name_asc":
            q = q.order_by(Image.filename.asc(), Image.id.asc())
        elif sort == "name_desc":
            q = q.order_by(Image.filename.desc(), Image.id.desc())
        elif sort == "taken_at_asc":
            q = q.order_by(Image.taken_at.asc(), Image.id.asc())
        elif sort == "taken_at_desc":
            q = q.order_by(Image.taken_at.desc(), Image.id.desc())
        else:  # size_desc
            q = q.order_by(Image.size_bytes.desc(), Image.id.desc())
        if cursor:
            _, last_id = _decode_cursor(cursor)
            if sort.endswith("_asc"):
                q = q.where(Image.id > last_id)
            else:
                q = q.where(Image.id < last_id)
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
        next_cursor = _encode_cursor(sort, rows[-1].id) if has_more and rows else None
        return {"items": items, "next_cursor": next_cursor}
