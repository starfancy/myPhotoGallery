from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from myphoto.deps import admin_required, current_user
from myphoto.errors import AppError
from myphoto.models import Lut, User

router = APIRouter(prefix="/api", tags=["luts"])


def _luts_dir(request: Request) -> Path:
    cfg = request.app.state.config
    return Path(cfg.data_dir) / "luts"


@router.get("/luts")
async def list_enabled_luts(
    request: Request,
    _user: User = Depends(current_user),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        rows = (
            await s.execute(
                select(Lut).where(Lut.enabled == 1).order_by(Lut.group, Lut.sort_order, Lut.slug)
            )
        ).scalars().all()
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(r.group, []).append({
            "slug": r.slug, "label": r.label, "sort_order": r.sort_order,
        })

    # group=""（未分组）排最前，其他组按字母序
    def group_key(g: str) -> str:
        return f"0~{g}" if g == "" else f"1~{g}"

    return [
        {"group": g, "items": items}
        for g, items in sorted(grouped.items(), key=lambda kv: group_key(kv[0]))
    ]


@router.get("/luts/{slug}/cube")
async def get_lut_cube(
    slug: str,
    request: Request,
    _user: User = Depends(current_user),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        row = (await s.execute(select(Lut).where(Lut.slug == slug))).scalar_one_or_none()
        if row is None or row.enabled != 1:
            raise AppError("not_found", 404, "lut not found")
        rel = row.file_path
    cube_path = _luts_dir(request) / rel
    if not cube_path.exists():
        raise AppError("not_found", 404, "lut file missing")
    return PlainTextResponse(cube_path.read_text(encoding="utf-8"))


# ---- admin ----

@router.get("/admin/luts")
async def list_all_luts(
    request: Request,
    _admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        rows = (
            await s.execute(select(Lut).order_by(Lut.group, Lut.sort_order, Lut.slug))
        ).scalars().all()
    return [{
        "slug": r.slug, "label": r.label, "group": r.group,
        "enabled": r.enabled, "sort_order": r.sort_order,
        "source": r.source, "license": r.license,
        "file_path": r.file_path, "created_at": r.created_at,
    } for r in rows]


@router.patch("/admin/luts/{slug}")
async def update_lut(
    slug: str,
    payload: dict,
    request: Request,
    _admin: User = Depends(admin_required),
):
    sm = request.app.state.sessionmaker
    async with sm() as s:
        row = (await s.execute(select(Lut).where(Lut.slug == slug))).scalar_one_or_none()
        if row is None:
            raise AppError("not_found", 404, "lut not found")
        if "enabled" in payload:
            row.enabled = 1 if payload["enabled"] else 0
        if "label" in payload:
            row.label = str(payload["label"])[:100]
        if "sort_order" in payload:
            row.sort_order = int(payload["sort_order"])
        await s.commit()
        return {
            "slug": row.slug, "label": row.label, "enabled": row.enabled,
            "sort_order": row.sort_order,
        }
