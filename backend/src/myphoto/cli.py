from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from pathlib import Path

import click
import uvicorn
from sqlalchemy import func, select

from myphoto.audit import write_audit
from myphoto.config import load_or_init, resolve_config_path, resolve_models_dir
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.formats import classify
from myphoto.models import Gallery, GalleryRoot, Image, User
from myphoto.scanner import Scanner, _process_file
from myphoto.schema_init import ensure_schema_and_admin
from myphoto.security import hash_password

_cli_log = logging.getLogger("myphoto.cli")


def _run(coro):
    return asyncio.run(coro)


async def _bootstrap(config_path: str | None):
    cfg = load_or_init(resolve_config_path(config_path))
    db = Path(cfg.data_dir) / "app.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    engine = await make_engine(f"sqlite+aiosqlite:///{db.as_posix()}")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    created, pw = await ensure_schema_and_admin(engine, sm)
    if created and pw:
        click.echo(f"[myphoto] initial admin created. username=admin password={pw}")
    return engine, sm, cfg


@click.group()
@click.option("--config", "config_path", default=None, type=click.Path(path_type=str))
@click.pass_context
def cli(ctx, config_path):
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


@cli.command("add-gallery")
@click.argument("name")
@click.option("--description", default=None)
@click.pass_context
def add_gallery(ctx, name, description):
    async def _run_it():
        engine, sm, _ = await _bootstrap(ctx.obj["config_path"])
        try:
            async with sm() as s:
                if (await s.execute(select(Gallery).where(Gallery.name == name))).scalar_one_or_none():
                    raise click.ClickException(f"gallery '{name}' already exists")
                g = Gallery(name=name, description=description, created_at=int(time.time()))
                s.add(g)
                await s.flush()
                await write_audit(
                    s, "gallery_create", None, "cli",
                    target=f"gallery:{g.id}", detail=f"name={name}",
                )
                await s.commit()
                click.echo(f"gallery '{name}' created")
        finally:
            await engine.dispose()
    _run(_run_it())


@cli.command("add-root")
@click.argument("gallery_name")
@click.argument("label")
@click.argument("absolute_path")
@click.pass_context
def add_root(ctx, gallery_name, label, absolute_path):
    p = Path(absolute_path).resolve()
    if not p.exists() or not p.is_dir():
        raise click.ClickException(f"path not readable: {p}")

    async def _run_it():
        engine, sm, _ = await _bootstrap(ctx.obj["config_path"])
        try:
            async with sm() as s:
                g = (await s.execute(select(Gallery).where(Gallery.name == gallery_name))).scalar_one_or_none()
                if g is None:
                    raise click.ClickException(f"gallery '{gallery_name}' not found")
                r = GalleryRoot(gallery_id=g.id, label=label, absolute_path=str(p), enabled=1)
                s.add(r)
                await s.flush()
                await write_audit(
                    s, "root_add", None, "cli",
                    target=f"root:{r.id}",
                    detail=f"gallery={gallery_name} label={label} path={p}",
                )
                await s.commit()
                click.echo(f"root '{label}' added to '{gallery_name}' -> {p}")
        finally:
            await engine.dispose()
    _run(_run_it())


@cli.command("rescan")
@click.argument("gallery_name", required=False)
@click.argument("root_label", required=False)
@click.pass_context
def rescan(ctx, gallery_name, root_label):
    async def _run_it():
        engine, sm, cfg = await _bootstrap(ctx.obj["config_path"])
        try:
            async with sm() as s:
                q = select(GalleryRoot).where(GalleryRoot.enabled == 1)
                if gallery_name:
                    g = (await s.execute(select(Gallery).where(Gallery.name == gallery_name))).scalar_one_or_none()
                    if g is None:
                        raise click.ClickException(f"gallery '{gallery_name}' not found")
                    q = q.where(GalleryRoot.gallery_id == g.id)
                if root_label:
                    q = q.where(GalleryRoot.label == root_label)
                roots = (await s.execute(q)).scalars().all()
            scanner = Scanner(sm, hash_workers=cfg.scanner_hash_workers)
            for r in roots:
                click.echo(f"scanning {r.label} ({r.absolute_path})...")
                await scanner.scan_root_now(r.id)
                status = scanner.get_status(r.id)
                click.echo(f"  -> {status}")
        finally:
            await engine.dispose()
    _run(_run_it())


@cli.command("rescan-exif")
@click.argument("gallery_name", required=False)
@click.argument("root_label", required=False)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="重跑所有图片（默认只处理 exif_json IS NULL 的图片）。",
)
@click.pass_context
def rescan_exif(ctx, gallery_name, root_label, force):
    """回填已入库图片的 exif_json 字段，并修正 width/height。

    与 [rescan] 不同：不改 sha1/mtime/size/taken_at，也不重算目录 count；
    只逐张重新读一次元数据，更新 images 表的 exif_json 与宽高（宽高按
    EXIF Orientation 转正，用于修复历史入库的竖版照片宽高颠倒）。默认只
    处理 `exif_json IS NULL` 的图片；`--force` 全量重跑。图片文件不存在
    或读取失败时跳过。
    """

    async def _run_it():
        engine, sm, _ = await _bootstrap(ctx.obj["config_path"])
        try:
            async with sm() as s:
                q = select(GalleryRoot).where(GalleryRoot.enabled == 1)
                if gallery_name:
                    g = (await s.execute(
                        select(Gallery).where(Gallery.name == gallery_name)
                    )).scalar_one_or_none()
                    if g is None:
                        raise click.ClickException(f"gallery '{gallery_name}' not found")
                    q = q.where(GalleryRoot.gallery_id == g.id)
                if root_label:
                    q = q.where(GalleryRoot.label == root_label)
                roots = (await s.execute(q)).scalars().all()

            total_updated = 0
            total_skipped = 0
            total_missing = 0
            for r in roots:
                click.echo(f"rescan-exif {r.label} ({r.absolute_path})...")
                updated, skipped, missing = await _rescan_exif_root(sm, r, force=force)
                total_updated += updated
                total_skipped += skipped
                total_missing += missing
                click.echo(
                    f"  -> updated={updated} skipped={skipped} missing={missing}"
                )

            # 汇总审计（CLI 触发，actor_user_id=None，actor_ip='cli'）
            async with sm() as s:
                await write_audit(
                    s, "rescan_exif", None, "cli",
                    target=(
                        f"gallery:{gallery_name}" if gallery_name else "all"
                    ),
                    detail=(
                        f"updated={total_updated} skipped={total_skipped} "
                        f"missing={total_missing} force={int(force)}"
                    ),
                )
                await s.commit()
        finally:
            await engine.dispose()
    _run(_run_it())


async def _rescan_exif_root(
    sm, root: GalleryRoot, *, force: bool
) -> tuple[int, int, int]:
    """回填一个 root 下的 exif_json；返回 (updated, skipped, missing)。"""
    updated = 0
    skipped = 0
    missing = 0
    async with sm() as s:
        stmt = select(Image).where(Image.root_id == root.id)
        if not force:
            stmt = stmt.where(Image.exif_json.is_(None))
        images = (await s.execute(stmt)).scalars().all()

        for image in images:
            path = Path(root.absolute_path) / image.relative_path
            if not path.exists():
                missing += 1
                continue
            try:
                # sha1/taken_at 已在 rescan 时算过，本命令不覆盖（避免把
                # taken_at 意外置空）；exif_json 回填，width/height 顺带按
                # EXIF Orientation 修正（历史入库的竖版照片宽高可能颠倒）。
                _sha1, _w, _h, _taken, exif_json = await asyncio.to_thread(
                    _process_file,
                    path,
                    classify(image.filename) == "raw",
                )
            except Exception:
                _cli_log.warning("rescan-exif failed for %s", path, exc_info=True)
                skipped += 1
                continue
            if exif_json is None and image.exif_json is None:
                # 无 EXIF 又本就是空，无需变更；也不算 "updated"
                continue
            image.exif_json = exif_json
            if _w and _h:
                image.width = _w
                image.height = _h
            updated += 1
        await s.commit()
    return updated, skipped, missing



@cli.command("list")
@click.pass_context
def list_all(ctx):
    async def _run_it():
        engine, sm, _ = await _bootstrap(ctx.obj["config_path"])
        try:
            async with sm() as s:
                gals = (await s.execute(select(Gallery))).scalars().all()
                for g in gals:
                    click.echo(f"gallery: {g.name} (id={g.id})")
                    roots = (await s.execute(select(GalleryRoot).where(GalleryRoot.gallery_id == g.id))).scalars().all()
                    for r in roots:
                        cnt = (await s.execute(select(func.count()).select_from(Image).where(Image.root_id == r.id))).scalar_one()
                        click.echo(f"  root: {r.label} -> {r.absolute_path} ({cnt} images)")
        finally:
            await engine.dispose()
    _run(_run_it())


@cli.command("reset-password")
@click.option("--username", default="admin", help="username to reset (default: admin)")
@click.option("--password", default=None, help="new password; auto-generated if omitted")
@click.pass_context
def reset_password(ctx, username, password):
    """Reset a user's password (bypasses old-password check)."""

    async def _run_it():
        engine, sm, _ = await _bootstrap(ctx.obj["config_path"])
        try:
            async with sm() as s:
                u = (await s.execute(select(User).where(User.username == username))).scalar_one_or_none()
                if u is None:
                    raise click.ClickException(f"user '{username}' not found")
                auto_generated = password is None
                new_pw = password
                if auto_generated:
                    alphabet = (
                        "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz"
                        "23456789!@#$%"
                    )
                    new_pw = "".join(secrets.choice(alphabet) for _ in range(16))
                u.password_hash = hash_password(new_pw)
                await s.commit()
                if auto_generated:
                    click.echo(f"password for '{username}' has been reset to: {new_pw}")
                else:
                    click.echo(f"password for '{username}' has been reset.")
        finally:
            await engine.dispose()

    _run(_run_it())


# ---------- 智能标签（tags upgrade Phase 1） ----------


def _build_tagger(cfg, config_path: str | None) -> tuple:
    """返回 (tagger, reason)：成功 (tagger, None)，不可用 (None, 中文原因)。"""
    if not cfg.tagging_enabled:
        return None, "[tagging].enabled=false，智能标签已关闭"
    from myphoto.tagger import Tagger

    tagger = Tagger(
        resolve_models_dir(cfg, resolve_config_path(config_path)),
        device=cfg.tagging_device,
    )
    if tagger.available():
        return tagger, None
    return None, tagger.unavailable_reason() or "tagger models missing"


def _fmt_duration(seconds: float) -> str:
    """秒 → '42s' / '3m05s' / '1h12m'。"""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _make_progress_echo():
    """生成带起始时间的进度回调：百分比 + 已用 + ETA + 当前项。"""
    start = time.perf_counter()

    async def _echo(done: int, total: int, current) -> None:
        elapsed = time.perf_counter() - start
        pct = done * 100 // max(total, 1)
        eta = elapsed / done * (total - done) if done else 0.0
        tail = f"  {current}" if current else ""
        click.echo(
            f"  [{done}/{total}] {pct:3d}%  已用 {_fmt_duration(elapsed)}  "
            f"剩余 {_fmt_duration(eta)}{tail}"
        )

    return _echo


async def _gallery_id_by_name(s, name: str) -> int:
    g = (await s.execute(select(Gallery).where(Gallery.name == name))).scalar_one_or_none()
    if g is None:
        raise click.ClickException(f"gallery '{name}' not found")
    return g.id


@cli.group("tag")
def tag_group():
    """智能标签：status / run / cluster / relabel（见 docs/tags-upgrade-design.md）。"""


@tag_group.command("status")
@click.option("--gallery", default=None, help="只看指定图库")
@click.pass_context
def tag_status_cmd(ctx, gallery):
    """列出所有图库的打标进度（total/tagged/pending/failed）。"""

    async def _run_it():
        engine, sm, cfg = await _bootstrap(ctx.obj["config_path"])
        try:
            from myphoto.tagging_jobs import tag_status

            rows = await tag_status(sm)
            if gallery:
                rows = [r for r in rows if r["gallery"] == gallery]
                if not rows:
                    raise click.ClickException(f"gallery '{gallery}' not found")
            # status 命令无论模型是否就位都展示解析出的后端计划（Tagger 构造
            # 只做文件检查、不加载模型，零重负载），便于排查配置问题。
            from myphoto.tagger import Tagger

            if not cfg.tagging_enabled:
                click.echo("models ready: NO（[tagging].enabled=false，智能标签已关闭）")
            else:
                diag = Tagger(
                    resolve_models_dir(cfg, resolve_config_path(ctx.obj["config_path"])),
                    device=cfg.tagging_device,
                )
                if diag.backend_plan == "cuda":
                    click.echo("inference backend: cuda (ONNX Runtime GPU)")
                else:
                    click.echo("inference backend: openvino (Intel GPU/CPU auto)")
                if diag.available():
                    click.echo("models ready: yes")
                else:
                    click.echo(f"models ready: NO（{diag.unavailable_reason()}）")
            click.echo(f"{'gallery':20s} {'total':>7s} {'tagged':>7s} {'pending':>8s} {'failed':>7s}")
            click.echo("-" * 55)
            for r in rows:
                click.echo(
                    f"{r['gallery']:20s} {r['total']:7d} {r['tagged']:7d} "
                    f"{r['pending']:8d} {r['failed']:7d}"
                )
        finally:
            await engine.dispose()

    _run(_run_it())


@tag_group.command("run")
@click.option("--gallery", default=None, help="指定图库（默认全部）")
@click.option("--folder", default=None, help="图库内文件夹前缀，如 '旅行-OLD/成都'")
@click.option("--force", is_flag=True, default=False, help="强制重打（含已打标与历史失败）")
@click.pass_context
def tag_run_cmd(ctx, gallery, folder, force):
    """给待打标图片打标；结束后自动增量聚类。"""

    async def _run_it():
        engine, sm, cfg = await _bootstrap(ctx.obj["config_path"])
        try:
            tagger, reason = _build_tagger(cfg, ctx.obj["config_path"])
            if tagger is None:
                raise click.ClickException(f"tagger 不可用：{reason}")
            from myphoto.tagging_jobs import cluster_faces, tag_images

            async with sm() as s:
                gallery_id = await _gallery_id_by_name(s, gallery) if gallery else None

            click.echo(f"tagging (force={force}) ...")
            stats = await tag_images(
                sm, tagger,
                gallery_id=gallery_id, folder=folder, force=force,
                progress_cb=_make_progress_echo(),
            )
            click.echo(
                f"tagged={stats.tagged} failed={stats.failed} "
                f"missing={stats.skipped_missing} (scanned={stats.total})"
            )
            cs = await cluster_faces(sm, progress_cb=_make_progress_echo())
            click.echo(f"clustered: assigned={cs.assigned} new_clusters={cs.new_clusters}")

            async with sm() as s:
                await write_audit(
                    s, "tag_run", None, "cli",
                    target=f"gallery:{gallery or 'all'}",
                    detail=(
                        f"tagged={stats.tagged} failed={stats.failed} "
                        f"missing={stats.skipped_missing} force={int(force)}"
                    ),
                )
                await s.commit()
        finally:
            await engine.dispose()

    _run(_run_it())


@tag_group.command("cluster")
@click.pass_context
def tag_cluster_cmd(ctx):
    """对所有未分配人脸向量做增量聚类（cosine > 0.5 归入已有簇）。"""

    async def _run_it():
        engine, sm, _cfg = await _bootstrap(ctx.obj["config_path"])
        try:
            from myphoto.tagging_jobs import cluster_faces

            cs = await cluster_faces(sm, progress_cb=_make_progress_echo())
            click.echo(f"assigned={cs.assigned} new_clusters={cs.new_clusters}")
            async with sm() as s:
                await write_audit(s, "tag_cluster", None, "cli", target="all",
                                  detail=f"assigned={cs.assigned} new={cs.new_clusters}")
                await s.commit()
        finally:
            await engine.dispose()

    _run(_run_it())


@tag_group.command("relabel")
@click.pass_context
def tag_relabel_cmd(ctx):
    """基于已有 image_embeddings 重算场景标签（不跑视觉模型）。"""

    async def _run_it():
        engine, sm, cfg = await _bootstrap(ctx.obj["config_path"])
        try:
            tagger, reason = _build_tagger(cfg, ctx.obj["config_path"])
            if tagger is None:
                raise click.ClickException(f"tagger 不可用：{reason}")
            from myphoto.tagging_jobs import relabel

            n = await relabel(sm, tagger, progress_cb=_make_progress_echo())
            click.echo(f"relabeled={n}")
            async with sm() as s:
                await write_audit(s, "tag_relabel", None, "cli", target="all",
                                  detail=f"updated={n}")
                await s.commit()
        finally:
            await engine.dispose()

    _run(_run_it())


@tag_group.command("gc")
@click.option("--include-named", is_flag=True, default=False,
              help="同时删除已命名的孤儿簇（默认保留命名簇，只清未命名的）")
@click.pass_context
def tag_gc_cmd(ctx, include_named):
    """清理无任何人脸指向的孤儿人物簇（--force 重打后的残留）。"""

    async def _run_it():
        engine, sm, _cfg = await _bootstrap(ctx.obj["config_path"])
        try:
            from myphoto.tagging_jobs import prune_orphan_clusters

            removed = await prune_orphan_clusters(sm, include_named=include_named)
            if removed:
                click.echo(f"removed {len(removed)} orphan cluster(s): {', '.join(removed)}")
            else:
                click.echo("no orphan clusters")
            async with sm() as s:
                await write_audit(
                    s, "tag_gc", None, "cli", target="all",
                    detail=f"removed={len(removed)} include_named={int(include_named)}",
                )
                await s.commit()
        finally:
            await engine.dispose()

    _run(_run_it())


@cli.command("serve")
@click.option("--host", default=None, help="覆盖 config.toml 中的 listen_host")
@click.option("--port", default=None, type=int, help="覆盖 config.toml 中的 listen_port")
@click.option("--reload", "reload", is_flag=True, default=False, help="开发模式：代码变更自动重启")
@click.pass_context
def serve(ctx, host, port, reload):
    """启动 Web 服务；host/port 默认取 config.toml [app] 段。"""
    cfg_path = resolve_config_path(ctx.obj["config_path"])
    cfg = load_or_init(cfg_path)
    # main.py 在 import 时读 MYPHOTO_CONFIG；--reload 的子进程会重新 import app，
    # 把解析后的绝对路径钉进环境变量，保证自定义 --config 在 reload 后依然生效
    os.environ["MYPHOTO_CONFIG"] = str(cfg_path)
    uvicorn.run(
        "myphoto.main:app",
        host=host or cfg.listen_host,
        port=port or cfg.listen_port,
        reload=reload,
        # 只监视 backend/ 目录，避免从项目根启动时 watch .venv、frontend/node_modules
        reload_dirs=[str(Path(__file__).resolve().parents[2])] if reload else None,
    )


# Console-script entry point declared in pyproject.toml (`myphoto = "myphoto.cli:main"`).
main = cli
