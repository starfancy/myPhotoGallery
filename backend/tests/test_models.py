import asyncio
import time

import pytest
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import Gallery, GalleryRoot, Image, User


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
