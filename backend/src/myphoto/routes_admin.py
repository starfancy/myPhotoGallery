from __future__ import annotations

import os
import string
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from myphoto.audit import write_audit
from myphoto.deps import admin_required, require_lan_ip
from myphoto.errors import AppError
from myphoto.models import Gallery, GalleryRoot, Image, User

router = APIRouter(prefix="/api/admin", tags=["admin"])

BROWSE_FS_MAX_ENTRIES = 5000


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---- Pydantic schemas ----


class GalleryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None


class GalleryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None


# ---- Gallery CRUD ----


@router.get("/galleries")
async def admin_list_galleries(
    request: Request,
    response: Response,
    _admin: User = Depends(admin_required),
):
    response.headers["Cache-Control"] = "no-store"
    sm = request.app.state.sessionmaker
    async with sm() as s:
        gals = (await s.execute(select(Gallery))).scalars().all()
        out = []
        for g in gals:
            root_count = (
                await s.execute(
                    select(func.count()).select_from(GalleryRoot).where(
                        GalleryRoot.gallery_id == g.id
                    )
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
            out.append({
                "id": g.id,
                "name": g.name,
                "description": g.description,
                "root_count": root_count,
                "image_count": image_count,
            })
        return out


@router.post("/galleries", status_code=201)
async def admin_create_gallery(
    body: GalleryCreate,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        existing = (
            await s.execute(select(Gallery).where(Gallery.name == body.name))
        ).scalar_one_or_none()
        if existing:
            raise AppError("conflict", 409, f"gallery '{body.name}' already exists")
        g = Gallery(
            name=body.name,
            description=body.description,
            created_at=int(time.time()),
        )
        s.add(g)
        await s.flush()
        await write_audit(
            s, "gallery_create", admin.id, _client_ip(request),
            target=f"gallery:{g.id}", detail=f"name={body.name}",
        )
        await s.commit()
        return {"id": g.id, "name": g.name, "description": g.description}


@router.patch("/galleries/{gid}")
async def admin_update_gallery(
    gid: int,
    body: GalleryUpdate,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        g = await s.get(Gallery, gid)
        if g is None:
            raise AppError("not_found", 404, "gallery not found")
        if body.name is not None:
            conflict = (
                await s.execute(
                    select(Gallery).where(Gallery.name == body.name, Gallery.id != gid)
                )
            ).scalar_one_or_none()
            if conflict:
                raise AppError("conflict", 409, f"gallery name '{body.name}' already taken")
            g.name = body.name
        if body.description is not None:
            g.description = body.description
        await write_audit(
            s, "gallery_update", admin.id, _client_ip(request),
            target=f"gallery:{gid}",
        )
        await s.commit()
        return {"id": g.id, "name": g.name, "description": g.description}


@router.delete("/galleries/{gid}", status_code=204)
async def admin_delete_gallery(
    gid: int,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        g = await s.get(Gallery, gid)
        if g is None:
            raise AppError("not_found", 404, "gallery not found")
        await write_audit(
            s, "gallery_delete", admin.id, _client_ip(request),
            target=f"gallery:{gid}", detail=f"name={g.name}",
        )
        await s.delete(g)
        await s.commit()


# ---- Root schemas ----


class RootCreate(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    absolute_path: str = Field(min_length=1)


class RootUpdate(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=128)
    enabled: int | None = Field(None, ge=0, le=1)


# ---- Root CRUD + scan control ----


@router.post("/galleries/{gid}/roots", status_code=201)
async def admin_add_root(
    gid: int,
    body: RootCreate,
    request: Request,
    admin: User = Depends(admin_required),
):
    p = Path(body.absolute_path).resolve()
    if not p.exists() or not p.is_dir():
        raise AppError("path_not_readable", 400, f"path not readable: {body.absolute_path}")

    sm = request.app.state.sessionmaker
    async with sm() as s:
        g = await s.get(Gallery, gid)
        if g is None:
            raise AppError("not_found", 404, "gallery not found")
        existing = (
            await s.execute(
                select(GalleryRoot).where(
                    GalleryRoot.gallery_id == gid,
                    GalleryRoot.absolute_path == str(p),
                )
            )
        ).scalar_one_or_none()
        if existing:
            raise AppError("conflict", 409, "this path is already a root in this gallery")

        r = GalleryRoot(
            gallery_id=gid,
            label=body.label,
            absolute_path=str(p),
            enabled=1,
        )
        s.add(r)
        await s.flush()
        await write_audit(
            s, "root_add", admin.id, _client_ip(request),
            target=f"root:{r.id}", detail=f"gallery={gid} label={body.label}",
        )
        await s.commit()
        await s.refresh(r)

    scanner = request.app.state.scanner
    await scanner.enqueue(r.id)
    return {
        "id": r.id, "gallery_id": r.gallery_id, "label": r.label,
        "absolute_path": r.absolute_path, "enabled": bool(r.enabled),
    }


@router.patch("/galleries/{gid}/roots/{rid}")
async def admin_update_root(
    gid: int,
    rid: int,
    body: RootUpdate,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        r = (
            await s.execute(
                select(GalleryRoot).where(
                    GalleryRoot.id == rid, GalleryRoot.gallery_id == gid
                )
            )
        ).scalar_one_or_none()
        if r is None:
            raise AppError("not_found", 404, "root not found")

        if body.label is not None:
            r.label = body.label
        if body.enabled is not None:
            r.enabled = body.enabled

        await write_audit(
            s, "root_update", admin.id, _client_ip(request),
            target=f"root:{rid}",
        )
        await s.commit()
        return {
            "id": r.id, "gallery_id": r.gallery_id, "label": r.label,
            "absolute_path": r.absolute_path, "enabled": bool(r.enabled),
            "last_scan_at": r.last_scan_at,
            "last_scan_status": r.last_scan_status,
            "last_scan_error": r.last_scan_error,
        }


@router.delete("/galleries/{gid}/roots/{rid}", status_code=204)
async def admin_delete_root(
    gid: int,
    rid: int,
    request: Request,
    admin: User = Depends(admin_required),
):
    """Remove root from gallery. DB only — no filesystem operations (redline #1)."""
    sm = request.app.state.sessionmaker
    async with sm() as s:
        r = (
            await s.execute(
                select(GalleryRoot).where(
                    GalleryRoot.id == rid, GalleryRoot.gallery_id == gid
                )
            )
        ).scalar_one_or_none()
        if r is None:
            raise AppError("not_found", 404, "root not found")

        await write_audit(
            s, "root_remove", admin.id, _client_ip(request),
            target=f"root:{rid}", detail=f"gallery={gid} path={r.absolute_path}",
        )
        await s.delete(r)
        await s.commit()


@router.post("/galleries/{gid}/roots/{rid}/rescan")
async def admin_rescan_root(
    gid: int,
    rid: int,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        r = (
            await s.execute(
                select(GalleryRoot).where(
                    GalleryRoot.id == rid, GalleryRoot.gallery_id == gid
                )
            )
        ).scalar_one_or_none()
        if r is None:
            raise AppError("not_found", 404, "root not found")

    scanner = request.app.state.scanner
    status = scanner.get_status(rid)
    if status["status"] in ("queued", "running"):
        raise AppError("scan_in_progress", 409, f"scan already {status['status']}")

    await scanner.enqueue(rid)
    return {"status": "queued"}


@router.get("/galleries/{gid}/roots/{rid}/scan-status")
async def admin_scan_status(
    gid: int,
    rid: int,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        r = (
            await s.execute(
                select(GalleryRoot).where(
                    GalleryRoot.id == rid, GalleryRoot.gallery_id == gid
                )
            )
        ).scalar_one_or_none()
        if r is None:
            raise AppError("not_found", 404, "root not found")

    scanner = request.app.state.scanner
    status = scanner.get_status(rid)
    return {
        "status": status["status"],
        "last_scan_at": status["last_scan_at"],
        "last_scan_error": status["last_scan_error"],
    }


# ---- browse-fs (directory chooser) ----


class BrowseFsRequest(BaseModel):
    path: str = ""


def _list_drive_letters() -> list[dict]:
    """Windows: return mounted drives via GetLogicalDrives bitmask.

    Uses the kernel32 bitmask rather than probing each letter with `os.path.exists`
    so we do not wake removable media or block on dead network mounts.
    """
    import ctypes
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return []
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if bitmask & (1 << i):
            drive = f"{letter}:\\"
            out.append({"name": f"{letter}:", "path": drive, "is_root": True})
    return out


def _list_directories(parent: Path) -> tuple[list[dict], bool]:
    """List immediate subdirectories of `parent`.

    - excludes files
    - skips symlinks (no resolution)
    - skips hidden entries (name startswith '.')
    - stops after BROWSE_FS_MAX_ENTRIES and reports truncated=True
    """
    entries: list[dict] = []
    truncated = False
    with os.scandir(parent) as it:
        for de in it:
            name = de.name
            if name.startswith("."):
                continue
            try:
                if not de.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if len(entries) >= BROWSE_FS_MAX_ENTRIES:
                truncated = True
                break
            entries.append({"name": name, "path": de.path, "is_root": False})
    entries.sort(key=lambda e: e["name"].lower())
    return entries, truncated


@router.post("/browse-fs")
async def admin_browse_fs(
    body: BrowseFsRequest,
    request: Request,
    response: Response,
    admin: User = Depends(admin_required),
    _lan: None = Depends(require_lan_ip),
):
    response.headers["Cache-Control"] = "no-store"
    raw = body.path or ""
    audit_target = raw or "<root>"
    audit_detail: str | None = None
    sm = request.app.state.sessionmaker

    async def _write_audit(detail: str | None) -> None:
        async with sm() as s:
            await write_audit(
                s, "fs_browse", admin.id, _client_ip(request),
                target=audit_target, detail=detail,
            )
            await s.commit()

    try:
        # Rule 5: reject any '..' segment (checked before resolution / normalization)
        if raw:
            norm_for_check = raw.replace("\\", "/")
            parts = [p for p in norm_for_check.split("/") if p]
            if any(p == ".." for p in parts):
                raise AppError("path_invalid", 400, "path must not contain '..' segments")

        if not raw:
            # Default root
            if sys.platform == "win32":
                entries = _list_drive_letters()
                truncated = False
                result_path = ""
            else:
                root = Path("/")
                entries, truncated = _list_directories(root)
                result_path = str(root)
        else:
            p = Path(raw)
            # Rule 4: reject symlinks (do not resolve)
            try:
                if p.is_symlink():
                    raise AppError("path_invalid", 400, "symlinks are not permitted")
            except OSError:
                raise AppError("path_not_readable", 400, f"path not readable: {raw}")

            if not p.exists() or not p.is_dir():
                raise AppError("path_not_readable", 400, f"path not readable: {raw}")

            try:
                entries, truncated = _list_directories(p)
            except OSError:
                raise AppError("path_not_readable", 400, f"path not readable: {raw}")
            result_path = str(p)
    except AppError as e:
        audit_detail = f"error={e.code}"
        await _write_audit(audit_detail)
        raise

    audit_detail = f"count={len(entries)}"
    if truncated:
        audit_detail += " truncated=1"
    await _write_audit(audit_detail)

    return {"path": result_path, "entries": entries, "truncated": truncated}
