from __future__ import annotations

import os
import secrets
import shutil
import string
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from myphoto.audit import write_audit
from myphoto.deps import admin_required, require_lan_ip
from myphoto.errors import AppError
from myphoto.models import AuditLog, Gallery, GalleryRoot, Image, User, UserGallery
from myphoto.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])

BROWSE_FS_MAX_ENTRIES = 5000
STATUS_RECENT_AUDIT_LIMIT = 20
AUDIT_DEFAULT_LIMIT = 50
AUDIT_MAX_LIMIT = 500


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


@router.get("/galleries/{gid}")
async def admin_get_gallery(
    gid: int,
    request: Request,
    response: Response,
    _admin: User = Depends(admin_required),
):
    """Admin-specific gallery detail with full root metadata.

    The browse-facing GET /api/galleries/{gid} omits absolute_path and
    scan status fields for security (viewers shouldn't see local paths).
    This endpoint provides the admin-level view needed by AdminGalleryEdit.
    """
    response.headers["Cache-Control"] = "no-store"
    sm = request.app.state.sessionmaker
    async with sm() as s:
        g = await s.get(Gallery, gid)
        if g is None:
            raise AppError("not_found", 404, "gallery not found")

        roots = (
            await s.execute(select(GalleryRoot).where(GalleryRoot.gallery_id == gid))
        ).scalars().all()

        scanner = request.app.state.scanner
        root_out = []
        for r in roots:
            cnt = (
                await s.execute(
                    select(func.count())
                    .select_from(Image)
                    .where(Image.root_id == r.id)
                )
            ).scalar_one()
            live = scanner.get_status(r.id)
            root_out.append({
                "id": r.id,
                "label": r.label,
                "absolute_path": r.absolute_path,
                "enabled": bool(r.enabled),
                "image_count": cnt,
                "status": live["status"],
                "last_scan_at": live["last_scan_at"] if live["last_scan_at"] is not None else r.last_scan_at,
                "last_scan_status": r.last_scan_status,
                "last_scan_error": live["last_scan_error"] if live["last_scan_error"] is not None else r.last_scan_error,
            })

        return {
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "roots": root_out,
        }


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


# ---- system status / thumb-cache purge / audit query ----


@router.get("/status")
async def admin_status(
    request: Request,
    response: Response,
    _admin: User = Depends(admin_required),
):
    response.headers["Cache-Control"] = "no-store"
    sm = request.app.state.sessionmaker
    async with sm() as s:
        image_count = (await s.execute(select(func.count()).select_from(Image))).scalar_one()
        gallery_count = (await s.execute(select(func.count()).select_from(Gallery))).scalar_one()
        root_count = (await s.execute(select(func.count()).select_from(GalleryRoot))).scalar_one()
        user_count = (await s.execute(select(func.count()).select_from(User))).scalar_one()

        roots = (await s.execute(select(GalleryRoot))).scalars().all()
        scanner = request.app.state.scanner
        scan_statuses = []
        for r in roots:
            live = scanner.get_status(r.id)
            scan_statuses.append({
                "root_id": r.id,
                "gallery_id": r.gallery_id,
                "label": r.label,
                "absolute_path": r.absolute_path,
                "enabled": bool(r.enabled),
                "status": live["status"],
                "last_scan_at": live["last_scan_at"] if live["last_scan_at"] is not None else r.last_scan_at,
                "last_scan_status": r.last_scan_status,
                "last_scan_error": live["last_scan_error"] if live["last_scan_error"] is not None else r.last_scan_error,
            })

        recent = (
            await s.execute(
                select(AuditLog)
                .order_by(AuditLog.ts.desc(), AuditLog.id.desc())
                .limit(STATUS_RECENT_AUDIT_LIMIT)
            )
        ).scalars().all()
        recent_audit = [
            {
                "id": row.id,
                "ts": row.ts,
                "actor_user_id": row.actor_user_id,
                "actor_ip": row.actor_ip,
                "action": row.action,
                "target": row.target,
                "detail": row.detail,
            }
            for row in recent
        ]

    return {
        "stats": {
            "images": image_count,
            "galleries": gallery_count,
            "roots": root_count,
            "users": user_count,
        },
        "scan_statuses": scan_statuses,
        "recent_audit": recent_audit,
    }


@router.post("/thumb-cache/purge", status_code=204)
async def admin_thumb_cache_purge(
    request: Request,
    admin: User = Depends(admin_required),
):
    """Wipe the on-disk thumbnail cache.

    Redline #1 (spec §3.4) — only touches the cache directory, never a gallery
    root. Two in-code guards enforce this:
      1. cache_dir must resolve to a path inside cfg.data_dir/.cache
      2. cache_dir must not be a symlink (would otherwise let an attacker
         redirect the rmtree target)
    """
    cfg = request.app.state.config
    data_dir = Path(cfg.data_dir).resolve()
    cache_root = data_dir / ".cache"
    cache_dir = cache_root / "thumbnails"

    if cache_dir.exists():
        # Refuse to follow symlinks; refuse anything outside data_dir/.cache.
        if cache_dir.is_symlink():
            raise AppError("bad_request", 400, "thumbnail cache path is a symlink; refusing to purge")
        try:
            resolved = cache_dir.resolve(strict=True)
        except OSError:
            raise AppError("bad_request", 400, "thumbnail cache path is not accessible")
        try:
            resolved.relative_to(cache_root.resolve())
        except ValueError:
            raise AppError("bad_request", 400, "thumbnail cache path escapes data dir")
        shutil.rmtree(resolved)
        removed = True
    else:
        removed = False
    cache_dir.mkdir(parents=True, exist_ok=True)

    sm = request.app.state.sessionmaker
    async with sm() as s:
        await write_audit(
            s, "thumb_cache_purge", admin.id, _client_ip(request),
            target="thumb_cache", detail=f"path={cache_dir} removed={int(removed)}",
        )
        await s.commit()


@router.get("/audit")
async def admin_query_audit(
    request: Request,
    response: Response,
    _admin: User = Depends(admin_required),
    action: str | None = Query(None),
    actor: int | None = Query(None),
    from_ts: int | None = Query(None, alias="from"),
    to_ts: int | None = Query(None, alias="to"),
    limit: int = Query(AUDIT_DEFAULT_LIMIT, ge=1, le=AUDIT_MAX_LIMIT),
    cursor: str | None = Query(None),
):
    """Paginated audit log query.

    Ordering: (ts DESC, id DESC). Cursor format: "<ts>_<id>" — returns rows
    strictly older than that (ts,id) tuple, giving stable pagination even when
    multiple rows share the same ts.
    """
    response.headers["Cache-Control"] = "no-store"

    stmt = select(AuditLog).order_by(AuditLog.ts.desc(), AuditLog.id.desc())
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if actor is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor)
    if from_ts is not None:
        stmt = stmt.where(AuditLog.ts >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(AuditLog.ts <= to_ts)
    if cursor is not None:
        try:
            cts_s, cid_s = cursor.split("_", 1)
            if "_" in cts_s or "_" in cid_s:
                raise ValueError("underscore in cursor components")
            cts, cid = int(cts_s), int(cid_s)
        except (ValueError, AttributeError):
            raise AppError("bad_request", 400, "malformed cursor")
        # rows STRICTLY older than the cursor tuple
        stmt = stmt.where(
            (AuditLog.ts < cts) | ((AuditLog.ts == cts) & (AuditLog.id < cid))
        )

    stmt = stmt.limit(limit + 1)

    sm = request.app.state.sessionmaker
    async with sm() as s:
        rows = (await s.execute(stmt)).scalars().all()

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = f"{last.ts}_{last.id}"

    return {
        "entries": [
            {
                "id": r.id,
                "ts": r.ts,
                "actor_user_id": r.actor_user_id,
                "actor_ip": r.actor_ip,
                "action": r.action,
                "target": r.target,
                "detail": r.detail,
            }
            for r in rows
        ],
        "next_cursor": next_cursor,
    }


# ---- P4: users CRUD ----


_PW_ALPHABET = string.ascii_letters + string.digits


def _generate_password(length: int = 12) -> str:
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(length))


async def _guard_last_admin(session, target_user: User, *, will_be_active_admin: bool) -> None:
    """若操作会导致零活跃 admin，抛出 409 last_admin_protected。

    仅当目标当前是活跃 admin 且操作后不再活跃 admin 时才需检查。
    will_be_active_admin=False 表示删除 / 降级 role / 禁用 —— 此时校验是否还有其他活跃 admin。
    """
    if will_be_active_admin:
        return
    if target_user.role != "admin" or target_user.enabled != 1:
        return  # 目标本身就不是活跃 admin，不影响计数
    remaining = (
        await session.execute(
            select(func.count()).select_from(User).where(
                User.role == "admin", User.enabled == 1, User.id != target_user.id,
            )
        )
    ).scalar_one()
    if remaining < 1:
        raise AppError(
            "last_admin_protected", 409,
            "cannot remove or disable the last active admin",
        )


# ---- schemas ----


class UserCreateBody(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str | None = Field(None, min_length=8, max_length=128)
    role: str = Field(pattern=r"^(admin|viewer)$")
    access_scope: str = Field(pattern=r"^(lan_only|remote_allowed)$")
    gallery_ids: list[int] | None = None


class UserUpdateBody(BaseModel):
    role: str | None = Field(None, pattern=r"^(admin|viewer)$")
    access_scope: str | None = Field(None, pattern=r"^(lan_only|remote_allowed)$")
    enabled: int | None = Field(None, ge=0, le=1)
    gallery_ids: list[int] | None = None


class ResetPasswordBody(BaseModel):
    new_password: str | None = Field(None, min_length=8, max_length=128)


# ---- GET /api/admin/users ----

@router.get("/users")
async def admin_list_users(
    request: Request,
    response: Response,
    admin: User = Depends(admin_required),
):
    response.headers["Cache-Control"] = "no-store"
    sm = request.app.state.sessionmaker
    async with sm() as s:
        users = (await s.execute(select(User))).scalars().all()
        out = []
        for u in users:
            gallery_count: int
            if u.role == "admin":
                gallery_count = (
                    await s.execute(select(func.count()).select_from(Gallery))
                ).scalar_one()
            else:
                gallery_count = (
                    await s.execute(
                        select(func.count()).select_from(UserGallery).where(
                            UserGallery.user_id == u.id,
                        )
                    )
                ).scalar_one()
            out.append({
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "access_scope": u.access_scope,
                "enabled": u.enabled,
                "gallery_count": gallery_count,
                "last_login_at": u.last_login_at,
                "created_at": u.created_at,
            })
        return out


# ---- POST /api/admin/users ----

@router.post("/users", status_code=201)
async def admin_create_user(
    body: UserCreateBody,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        existing = (
            await s.execute(select(User).where(User.username == body.username))
        ).scalar_one_or_none()
        if existing is not None:
            raise AppError("conflict", 409, f"username '{body.username}' already exists")

        initial_password = body.password if body.password else _generate_password()
        user = User(
            username=body.username,
            password_hash=hash_password(initial_password),
            role=body.role,
            access_scope=body.access_scope,
            enabled=1,
            created_at=int(time.time()),
        )
        s.add(user)
        await s.flush()

        # viewer 图库授权
        if body.role == "viewer" and body.gallery_ids:
            for gid in body.gallery_ids:
                s.add(UserGallery(
                    user_id=user.id, gallery_id=gid, granted_at=int(time.time()),
                ))

        await write_audit(
            s, "user_create", admin.id, _client_ip(request),
            target=f"user:{user.id}", detail=f"username={body.username} role={body.role}",
        )
        await s.commit()

        resp = {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "access_scope": user.access_scope,
            "enabled": user.enabled,
            "gallery_ids": body.gallery_ids or [],
        }
        if not body.password:
            resp["initial_password"] = initial_password
        return resp


# ---- GET /api/admin/users/{uid} ----

@router.get("/users/{uid}")
async def admin_get_user(
    uid: int,
    request: Request,
    response: Response,
    admin: User = Depends(admin_required),
):
    response.headers["Cache-Control"] = "no-store"
    sm = request.app.state.sessionmaker
    async with sm() as s:
        user = await s.get(User, uid)
        if user is None:
            raise AppError("not_found", 404, "user not found")

        gallery_ids: list[int]
        if user.role == "admin":
            rows = (await s.execute(select(Gallery.id))).scalars().all()
            gallery_ids = list(rows)
        else:
            rows = (
                await s.execute(
                    select(UserGallery.gallery_id).where(UserGallery.user_id == uid)
                )
            ).scalars().all()
            gallery_ids = list(rows)

        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "access_scope": user.access_scope,
            "enabled": user.enabled,
            "gallery_ids": gallery_ids,
            "last_login_at": user.last_login_at,
            "created_at": user.created_at,
        }


# ---- PATCH /api/admin/users/{uid} ----

@router.patch("/users/{uid}")
async def admin_update_user(
    uid: int,
    body: UserUpdateBody,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        user = await s.get(User, uid)
        if user is None:
            raise AppError("not_found", 404, "user not found")

        # 确定操作后是否仍是活跃 admin（用于最后 admin 保护）
        new_role = body.role if body.role is not None else user.role
        new_enabled = body.enabled if body.enabled is not None else user.enabled
        will_be_active = (new_role == "admin" and new_enabled == 1)
        await _guard_last_admin(s, user, will_be_active_admin=will_be_active)

        changed: list[str] = []
        if body.role is not None:
            user.role = body.role
            changed.append(f"role={body.role}")
        if body.access_scope is not None:
            user.access_scope = body.access_scope
            changed.append(f"access_scope={body.access_scope}")
        if body.enabled is not None:
            user.enabled = body.enabled
            changed.append(f"enabled={body.enabled}")

        # gallery_ids：仅 viewer 角色生效；admin 忽略
        if body.gallery_ids is not None and user.role == "viewer":
            await s.execute(delete(UserGallery).where(UserGallery.user_id == uid))
            for gid in body.gallery_ids:
                s.add(UserGallery(
                    user_id=uid, gallery_id=gid, granted_at=int(time.time()),
                ))
            changed.append(f"gallery_ids={body.gallery_ids}")

        # 审计 action 拆分：单独禁用 → user_disable；其他 → user_update
        if (
            len(changed) == 1
            and body.enabled is not None
            and body.role is None
            and body.access_scope is None
            and body.gallery_ids is None
        ):
            audit_action = "user_disable" if body.enabled == 0 else "user_enable"
        else:
            audit_action = "user_update"

        await write_audit(
            s, audit_action, admin.id, _client_ip(request),
            target=f"user:{uid}", detail=",".join(changed) or None,
        )
        await s.commit()

        # 返回更新后的 gallery_ids
        gallery_ids: list[int]
        if user.role == "admin":
            rows = (await s.execute(select(Gallery.id))).scalars().all()
            gallery_ids = list(rows)
        else:
            rows = (
                await s.execute(
                    select(UserGallery.gallery_id).where(UserGallery.user_id == uid)
                )
            ).scalars().all()
            gallery_ids = list(rows)

        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "access_scope": user.access_scope,
            "enabled": user.enabled,
            "gallery_ids": gallery_ids,
        }


# ---- POST /api/admin/users/{uid}/reset-password ----

@router.post("/users/{uid}/reset-password")
async def admin_reset_user_password(
    uid: int,
    body: ResetPasswordBody,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        user = await s.get(User, uid)
        if user is None:
            raise AppError("not_found", 404, "user not found")

        new_pw = body.new_password if body.new_password else _generate_password()
        user.password_hash = hash_password(new_pw)

        await write_audit(
            s, "user_reset_password", admin.id, _client_ip(request),
            target=f"user:{uid}",
        )
        await s.commit()
        return {"new_password": new_pw}


# ---- DELETE /api/admin/users/{uid} ----

@router.delete("/users/{uid}", status_code=204)
async def admin_delete_user(
    uid: int,
    request: Request,
    admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        user = await s.get(User, uid)
        if user is None:
            raise AppError("not_found", 404, "user not found")

        await _guard_last_admin(s, user, will_be_active_admin=False)

        await write_audit(
            s, "user_delete", admin.id, _client_ip(request),
            target=f"user:{uid}", detail=f"username={user.username}",
        )
        await s.delete(user)
        await s.commit()
