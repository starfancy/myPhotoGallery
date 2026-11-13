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
    scene_major: str | None = Query(None, description="场景一级筛选"),
    scene_minor: str | None = Query(None, description="场景二级筛选"),
    date_from: int | None = Query(None, description="拍摄时间下限 Unix 秒"),
    date_to: int | None = Query(None, description="拍摄时间上限 Unix 秒"),
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

        # 场景筛选：统计每个直接子文件夹【整个子树】内的匹配图片数，
        # 只返回 >0 的子文件夹（分面下钻：父层只显示包含该分类的子文件夹）。
        # 注意用显式 active 标志：零匹配时 matching 为空 dict（falsy），
        # 不能靠 dict 真假判断筛选是否生效。
        filter_active = bool(scene_major or scene_minor or date_from or date_to)
        matching: dict[str, int] = {}
        if filter_active:
            mq = select(Image.relative_path).where(Image.root_id == rid)
            if scene_major:
                mq = mq.where(Image.scene_major == scene_major)
            if scene_minor:
                mq = mq.where(Image.scene_minor == scene_minor)
            if date_from is not None:
                mq = mq.where(Image.taken_at >= date_from)
            if date_to is not None:
                mq = mq.where(Image.taken_at <= date_to)
            matched_paths = (await s.execute(mq)).scalars().all()
            base = f"{rel}/" if rel else ""
            for p in matched_paths:
                if not p.startswith(base):
                    continue
                rest = p[len(base):]
                if "/" not in rest:
                    continue  # 当前文件夹自身的图片不属于任何子文件夹
                child_name = rest.split("/", 1)[0]
                child_rel = f"{base}{child_name}"
                matching[child_rel] = matching.get(child_rel, 0) + 1

        out = []
        for c in children:
            if filter_active and c.relative_path not in matching:
                continue
            cover = (
                await s.execute(
                    select(Image.sha1)
                    .where(Image.folder_id == c.id)
                    .order_by(Image.filename.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            item = {
                "name": c.name,
                "relative_path": c.relative_path,
                "image_count": c.image_count,
                "descendant_count": c.descendant_count,
                "cover_thumb_sha1": cover,
            }
            if filter_active:
                # 筛选态额外给匹配数；无筛选时响应结构不变，兼容旧消费方
                item["matching_count"] = matching[c.relative_path]
            out.append(item)
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


def _escape_like(term: str) -> str:
    """转义 SQLite LIKE 的通配符（% _）与转义符本身；配合 ESCAPE 反斜杠。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _subtree_clause(column, rel: str):
    """relative_path 位于 rel 子树内（含自身）；rel 为空时恒真（返回 None）。"""
    if rel == "":
        return None
    return or_(
        column == rel,
        column.like(_escape_like(rel) + "/%", escape="\\"),
    )


def _image_payload(r: Image) -> dict:
    return {
        "id": r.id,
        "filename": r.filename,
        "width": r.width,
        "height": r.height,
        "sha1": r.sha1,
        "size_bytes": r.size_bytes,
        "taken_at": r.taken_at,
        "mtime": r.mtime,
        "is_raw": bool(r.is_raw),
        "scene_major": r.scene_major,
        "scene_minor": r.scene_minor,
    }


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
    scene_major: str | None = Query(None, description="一级场景筛选，如 自然风光"),
    scene_minor: str | None = Query(None, description="二级场景筛选，如 山景"),
    date_from: int | None = Query(None, description="拍摄时间下限 Unix 秒"),
    date_to: int | None = Query(None, description="拍摄时间上限 Unix 秒"),
    _user: User = Depends(gallery_scope_guard),
):
    _no_store(response)
    if date_from is not None and date_to is not None and date_from > date_to:
        raise AppError("bad_request", 400, "date_from must be <= date_to")
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
        # 场景+日期筛选：二级必须配一级；日期基于 taken_at，NULL 自然排除
        extra_filters = []
        if scene_major:
            extra_filters.append(Image.scene_major == scene_major)
        if scene_minor:
            extra_filters.append(Image.scene_minor == scene_minor)
        if date_from is not None:
            extra_filters.append(Image.taken_at >= date_from)
        if date_to is not None:
            extra_filters.append(Image.taken_at <= date_to)
        total_q = select(func.count()).select_from(Image).where(Image.folder_id == folder.id)
        q = select(Image).where(Image.folder_id == folder.id)
        for f in extra_filters:
            total_q = total_q.where(f)
            q = q.where(f)
        total = (await s.execute(total_q)).scalar_one()
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
        items = [_image_payload(r) for r in rows]
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


@router.get("/galleries/{gid}/roots/{rid}/search")
async def search(
    gid: int,
    rid: int,
    request: Request,
    response: Response,
    q: str = Query(""),
    path: str = "",
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = None,
    scene_major: str | None = Query(None),
    scene_minor: str | None = Query(None),
    date_from: int | None = Query(None, description="拍摄时间下限，Unix 秒（含）"),
    date_to: int | None = Query(None, description="拍摄时间上限，Unix 秒（含）"),
    _user: User = Depends(gallery_scope_guard),
):
    _no_store(response)
    term = q.strip()
    if term and len(term) > 100:
        raise AppError("bad_request", 400, "query too long")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise AppError("bad_request", 400, "date_from must be <= date_to")
    rel = _norm_or_400(path)
    # q 可选：无关键词时必须带至少一个筛选条件，否则不做全量倾倒
    has_filter = bool(term or scene_major or scene_minor or date_from or date_to)
    sm = request.app.state.sessionmaker
    async with sm() as s:
        await _get_root_or_404(s, gid, rid)
        anchor = (
            await s.execute(
                select(Folder.id).where(
                    Folder.root_id == rid, Folder.relative_path == rel
                )
            )
        ).scalar_one_or_none()
        empty = {
            "q": term, "path": rel, "folders": [],
            "folders_truncated": False, "images": [], "next_cursor": None,
        }
        if anchor is None or not has_filter:
            return empty

        # ---- 文件夹命中：严格后代，固定 50 条上限；仅有关键词时才查 ----
        folders_out = []
        frows = []
        if term:
            needle = f"%{_escape_like(term.lower())}%"
            fq = select(Folder).where(Folder.root_id == rid, Folder.name != "")
            if rel:
                fq = fq.where(
                    Folder.relative_path.like(
                        _escape_like(rel) + "/%", escape="\\"
                    )
                )
            fq = (
                fq.where(func.lower(Folder.name).like(needle, escape="\\"))
                .order_by(Folder.name.asc(), Folder.id.asc())
                .limit(51)
            )
            frows = (await s.execute(fq)).scalars().all()
            for f in frows[:50]:
                cover = (
                    await s.execute(
                        select(Image.sha1)
                        .where(Image.folder_id == f.id)
                        .order_by(Image.filename.asc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                folders_out.append({
                    "name": f.name,
                    "relative_path": f.relative_path,
                    "image_count": f.image_count,
                    "descendant_count": f.descendant_count,
                    "cover_thumb_sha1": cover,
                })

        # ---- 图片命中：子树 + 关键词 + 场景 + 日期，keyset 分页 ----
        iq = (
            select(Image)
            .join(Folder, Image.folder_id == Folder.id)
            .where(Image.root_id == rid)
        )
        if term:
            iq = iq.where(
                func.lower(Image.filename).like(
                    f"%{_escape_like(term.lower())}%", escape="\\"
                )
            )
        subtree = _subtree_clause(Folder.relative_path, rel)
        if subtree is not None:
            iq = iq.where(subtree)
        if scene_major:
            iq = iq.where(Image.scene_major == scene_major)
        if scene_minor:
            iq = iq.where(Image.scene_minor == scene_minor)
        if date_from is not None:
            iq = iq.where(Image.taken_at >= date_from)
        if date_to is not None:
            iq = iq.where(Image.taken_at <= date_to)
        if cursor:
            last_val, last_id = _decode_cursor(cursor)
            iq = iq.where(or_(
                Image.filename > last_val,
                and_(Image.filename == last_val, Image.id > last_id),
            ))
        iq = iq.order_by(Image.filename.asc(), Image.id.asc()).limit(limit + 1)
        irows = (await s.execute(iq)).scalars().all()
        has_more = len(irows) > limit
        irows = irows[:limit]
        images_out = []
        for r in irows:
            item = _image_payload(r)
            item["relative_path"] = r.relative_path
            images_out.append(item)
        next_cursor = None
        if has_more and irows:
            next_cursor = _encode_cursor("search", irows[-1].filename, irows[-1].id)

        return {
            "q": term,
            "path": rel,
            "folders": folders_out,
            "folders_truncated": len(frows) > 50,
            "images": images_out,
            "next_cursor": next_cursor,
        }


@router.get("/tags/stats")
async def tags_stats(
    request: Request,
    response: Response,
    gallery_id: int | None = Query(None, description="限定图库"),
    root_id: int | None = Query(None, description="限定 root（需配合 path）"),
    path: str = Query("", description="文件夹相对路径（空=该 root 全部）"),
    _user: User = Depends(access_scope_guard),
):
    """标签分布统计：一级 + 其下二级计数。

    - 不给任何参数：全库分布
    - gallery_id：限定图库
    - root_id + path：限定某 root 下某文件夹子树（浏览页筛选用）
    """
    _no_store(response)
    sm = request.app.state.sessionmaker
    rel = _norm_or_400(path) if root_id is not None else ""
    async with sm() as s:
        q = select(Image.scene_major, Image.scene_minor, func.count(Image.id)).where(
            Image.scene_major.is_not(None)
        )
        if root_id is not None:
            q = q.where(Image.root_id == root_id)
            if rel:
                subtree = _subtree_clause(Folder.relative_path, rel)
                if subtree is not None:
                    q = q.join(Folder, Image.folder_id == Folder.id).where(subtree)
        elif gallery_id is not None:
            q = q.join(GalleryRoot, Image.root_id == GalleryRoot.id).where(
                GalleryRoot.gallery_id == gallery_id
            )
        rows = (await s.execute(q.group_by(Image.scene_major, Image.scene_minor))).all()

    # 按 HIERARCHY 顺序输出；未见过的组合追加在后
    from myphoto.tagger import HIERARCHY

    counts: dict[str, dict[str, int]] = {}
    for major, minor, n in rows:
        counts.setdefault(major, {})[minor or ""] = int(n)
    majors = []
    known = list(HIERARCHY.keys())
    ordered = [m for m in known if m in counts] + sorted(
        m for m in counts if m not in known
    )
    for major in ordered:
        minors = counts[major]
        minor_list = [
            {"name": name, "count": cnt}
            for name, cnt in sorted(minors.items(), key=lambda kv: -kv[1])
        ]
        majors.append({
            "name": major,
            "count": sum(minors.values()),
            "minors": minor_list,
        })
    return {"majors": majors}
