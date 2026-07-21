from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select

from myphoto.deps import current_user
from myphoto.errors import AppError
from myphoto.models import GalleryRoot, Image, User
from myphoto.paths import PathTraversalError, resolve_within_root
from myphoto.thumbnails import ALLOWED_SIZES, ThumbnailError

router = APIRouter(prefix="/api", tags=["media"])


def _guess_mime(filename: str) -> str:
    mt, _ = mimetypes.guess_type(filename)
    return mt or "application/octet-stream"


@router.get("/thumb/{sha1}")
async def get_thumb(
    sha1: str,
    request: Request,
    size: int = Query(200),
    _user: User = Depends(current_user),
):
    if size not in ALLOWED_SIZES:
        raise AppError("path_invalid", 400, f"size {size} not allowed")
    sm = request.app.state.sessionmaker
    async with sm() as s:
        img = (
            await s.execute(select(Image).where(Image.sha1 == sha1).limit(1))
        ).scalar_one_or_none()
        if img is None:
            raise AppError("not_found", 404, "image not found")
        root = await s.get(GalleryRoot, img.root_id)
    try:
        src = resolve_within_root(root.absolute_path, img.relative_path)
    except PathTraversalError:
        raise AppError("path_invalid", 400, "invalid path")
    if not src.exists():
        raise AppError("not_found", 404, "image not found")
    gen = request.app.state.thumbnails
    try:
        out = await gen.ensure(sha1, size, str(src), is_raw=bool(img.is_raw))
    except ThumbnailError as exc:
        raise AppError("internal_error", 500, f"thumb generation failed: {exc}")
    return FileResponse(
        out,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": sha1,
        },
    )


@router.get("/image/{image_id}")
async def get_image(
    image_id: int,
    request: Request,
    download: int = Query(0),
    _user: User = Depends(current_user),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        img = await s.get(Image, image_id)
        if img is None:
            raise AppError("not_found", 404, "image not found")
        root = await s.get(GalleryRoot, img.root_id)
    try:
        src = resolve_within_root(root.absolute_path, img.relative_path)
    except PathTraversalError:
        raise AppError("path_invalid", 400, "invalid path")
    if not src.exists():
        raise AppError("not_found", 404, "image not found")

    headers = {
        "Cache-Control": "private, max-age=86400",
        "ETag": img.sha1,
        "Accept-Ranges": "bytes",
    }
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{img.filename}"'
    media_type = _guess_mime(img.filename)

    range_header = request.headers.get("range")
    file_size = src.stat().st_size
    if range_header and range_header.startswith("bytes="):
        try:
            spec = range_header.split("=", 1)[1]
            start_s, end_s = spec.split("-", 1)
            start = int(start_s) if start_s.strip() else 0
            end = int(end_s) if end_s.strip() else file_size - 1
            end = min(end, file_size - 1)
            if start > end or start >= file_size or start < 0:
                raise ValueError
        except ValueError:
            raise AppError("path_invalid", 416, "invalid Range")
        length = end - start + 1

        def _iter():
            with src.open("rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(length)
        return StreamingResponse(
            _iter(),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )

    return FileResponse(src, media_type=media_type, headers=headers)
