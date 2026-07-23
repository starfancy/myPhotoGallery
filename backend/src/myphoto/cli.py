from __future__ import annotations

import asyncio
import time
from pathlib import Path

import click
from sqlalchemy import func, select

from myphoto.audit import write_audit
from myphoto.config import load_or_init, resolve_config_path
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import Gallery, GalleryRoot, Image
from myphoto.scanner import Scanner
from myphoto.schema_init import ensure_schema_and_admin


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
        engine, sm, _ = await _bootstrap(ctx.obj["config_path"])
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
            scanner = Scanner(sm)
            for r in roots:
                click.echo(f"scanning {r.label} ({r.absolute_path})...")
                await scanner.scan_root_now(r.id)
                status = scanner.get_status(r.id)
                click.echo(f"  -> {status}")
        finally:
            await engine.dispose()
    _run(_run_it())


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


def main():
    cli(obj={})
