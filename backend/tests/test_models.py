import asyncio
import time

import pytest
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import Gallery, GalleryRoot, Image, Trash, User


@pytest.fixture
async def session():
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as s:
        yield s
    await engine.dispose()


async def test_create_user_and_query(session):
    now = int(time.time())
    session.add(User(
        username="admin",
        password_hash="x",
        role="admin",
        access_scope="lan_only",
        enabled=1,
        created_at=now,
    ))
    await session.commit()
    from sqlalchemy import select
    row = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()
    assert row.role == "admin"


async def test_gallery_root_unique_path_per_gallery(session):
    now = int(time.time())
    g = Gallery(name="A", created_at=now)
    session.add(g)
    await session.flush()
    session.add(GalleryRoot(gallery_id=g.id, label="l1", absolute_path="/x", enabled=1))
    session.add(GalleryRoot(gallery_id=g.id, label="l2", absolute_path="/x", enabled=1))
    with pytest.raises(Exception):
        await session.commit()


async def test_image_unique_relative_path_per_root(session):
    now = int(time.time())
    g = Gallery(name="A", created_at=now)
    session.add(g)
    await session.flush()
    r = GalleryRoot(gallery_id=g.id, label="l", absolute_path="/x", enabled=1)
    session.add(r)
    await session.flush()
    from myphoto.models import Folder
    f = Folder(root_id=r.id, relative_path="", name="", image_count=0, descendant_count=0)
    session.add(f)
    await session.flush()
    session.add(Image(
        root_id=r.id, folder_id=f.id, relative_path="a.jpg", filename="a.jpg",
        ext="jpg", size_bytes=1, sha1="s", mtime=1, is_raw=0, indexed_at=1,
    ))
    session.add(Image(
        root_id=r.id, folder_id=f.id, relative_path="a.jpg", filename="a.jpg",
        ext="jpg", size_bytes=1, sha1="s", mtime=1, is_raw=0, indexed_at=1,
    ))
    with pytest.raises(Exception):
        await session.commit()


async def test_image_exif_json_nullable(session):
    now = int(time.time())
    g = Gallery(name="A", created_at=now)
    session.add(g)
    await session.flush()
    r = GalleryRoot(gallery_id=g.id, label="l", absolute_path="/x", enabled=1)
    session.add(r)
    await session.flush()
    from myphoto.models import Folder
    f = Folder(root_id=r.id, relative_path="", name="", image_count=0, descendant_count=0)
    session.add(f)
    await session.flush()
    # 一张有 exif_json，一张为 NULL
    session.add(Image(
        root_id=r.id, folder_id=f.id, relative_path="with.jpg", filename="with.jpg",
        ext="jpg", size_bytes=1, sha1="s1", mtime=1, is_raw=0, indexed_at=1,
        exif_json='{"Make": "Nikon"}',
    ))
    session.add(Image(
        root_id=r.id, folder_id=f.id, relative_path="without.jpg", filename="without.jpg",
        ext="jpg", size_bytes=1, sha1="s2", mtime=1, is_raw=0, indexed_at=1,
    ))
    await session.commit()

    from sqlalchemy import select
    with_ = (await session.execute(select(Image).where(Image.filename == "with.jpg"))).scalar_one()
    without = (await session.execute(select(Image).where(Image.filename == "without.jpg"))).scalar_one()
    assert with_.exif_json == '{"Make": "Nikon"}'
    assert without.exif_json is None


async def test_trash_crud_and_indexes(session):
    now = int(time.time())
    # 依赖 users.id 外键
    session.add(User(
        username="admin",
        password_hash="x",
        role="admin",
        access_scope="lan_only",
        enabled=1,
        created_at=now,
    ))
    await session.flush()
    from sqlalchemy import select
    admin = (await session.execute(select(User).where(User.username == "admin"))).scalar_one()

    t = Trash(
        gallery_id=1,
        root_id=1,
        original_relative_path="a/b.jpg",
        trash_relative_path="20260722/b.jpg",
        sha1="deadbeef",
        size_bytes=1024,
        deleted_by=admin.id,
        deleted_at=now,
        purge_after=now + 86400 * 30,
    )
    session.add(t)
    await session.commit()

    row = (await session.execute(select(Trash))).scalar_one()
    assert row.original_relative_path == "a/b.jpg"
    assert row.trash_relative_path == "20260722/b.jpg"
    assert row.sha1 == "deadbeef"
    assert row.deleted_by == admin.id
    assert row.purge_after > row.deleted_at

    # 删除
    await session.delete(row)
    await session.commit()
    remaining = (await session.execute(select(Trash))).scalars().all()
    assert remaining == []
