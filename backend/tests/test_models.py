import asyncio
import time

import pytest
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import Gallery, GalleryRoot, Image, Trash, User, UserGallery


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


# ---- P4: UserGallery (spec §4.2) ----

async def test_user_gallery_create_and_query(session):
    """P4: UserGallery 行可创建并按 (user_id, gallery_id) 查询。"""
    now = int(time.time())
    u = User(username="alice", password_hash="x", role="viewer",
             access_scope="lan_only", enabled=1, created_at=now)
    g = Gallery(name="G", created_at=now)
    session.add_all([u, g])
    await session.flush()

    ug = UserGallery(user_id=u.id, gallery_id=g.id, granted_at=now)
    session.add(ug)
    await session.commit()

    from sqlalchemy import select
    row = (
        await session.execute(
            select(UserGallery).where(
                UserGallery.user_id == u.id,
                UserGallery.gallery_id == g.id,
            )
        )
    ).scalar_one()
    assert row.user_id == u.id
    assert row.gallery_id == g.id
    assert row.granted_at == now


async def test_user_gallery_composite_pk_blocks_duplicate(session):
    """P4: (user_id, gallery_id) 联合主键，重复插入失败。"""
    now = int(time.time())
    u = User(username="alice", password_hash="x", role="viewer",
             access_scope="lan_only", enabled=1, created_at=now)
    g = Gallery(name="G", created_at=now)
    session.add_all([u, g])
    await session.flush()

    session.add(UserGallery(user_id=u.id, gallery_id=g.id, granted_at=now))
    await session.commit()

    session.add(UserGallery(user_id=u.id, gallery_id=g.id, granted_at=now + 1))
    with pytest.raises(Exception):
        await session.commit()


async def test_user_gallery_cascade_on_user_delete(session):
    """P4: 删除 user 时 user_galleries 行级联消失。"""
    now = int(time.time())
    u = User(username="alice", password_hash="x", role="viewer",
             access_scope="lan_only", enabled=1, created_at=now)
    g1 = Gallery(name="G1", created_at=now)
    g2 = Gallery(name="G2", created_at=now)
    session.add_all([u, g1, g2])
    await session.flush()

    session.add_all([
        UserGallery(user_id=u.id, gallery_id=g1.id, granted_at=now),
        UserGallery(user_id=u.id, gallery_id=g2.id, granted_at=now),
    ])
    await session.commit()

    from sqlalchemy import select, func
    before = (
        await session.execute(
            select(func.count()).select_from(UserGallery).where(UserGallery.user_id == u.id)
        )
    ).scalar_one()
    assert before == 2

    await session.delete(u)
    await session.commit()

    after = (
        await session.execute(
            select(func.count()).select_from(UserGallery).where(UserGallery.user_id == u.id)
        )
    ).scalar_one()
    assert after == 0


async def test_user_gallery_cascade_on_gallery_delete(session):
    """P4: 删除 gallery 时 user_galleries 行级联消失。"""
    now = int(time.time())
    u1 = User(username="u1", password_hash="x", role="viewer",
              access_scope="lan_only", enabled=1, created_at=now)
    u2 = User(username="u2", password_hash="x", role="viewer",
              access_scope="lan_only", enabled=1, created_at=now)
    g = Gallery(name="G", created_at=now)
    session.add_all([u1, u2, g])
    await session.flush()

    session.add_all([
        UserGallery(user_id=u1.id, gallery_id=g.id, granted_at=now),
        UserGallery(user_id=u2.id, gallery_id=g.id, granted_at=now),
    ])
    await session.commit()

    from sqlalchemy import select, func
    before = (
        await session.execute(
            select(func.count()).select_from(UserGallery).where(UserGallery.gallery_id == g.id)
        )
    ).scalar_one()
    assert before == 2

    await session.delete(g)
    await session.commit()

    after = (
        await session.execute(
            select(func.count()).select_from(UserGallery).where(UserGallery.gallery_id == g.id)
        )
    ).scalar_one()
    assert after == 0


async def test_user_gallery_table_created_by_create_all():
    """P4: create_all() 自动建表，复合主键 (user_id, gallery_id) 存在。"""
    from sqlalchemy import text
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    try:
        async with engine.begin() as conn:
            rows = (await conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='user_galleries'"
            )).all()
            assert len(rows) == 1, "user_galleries 表未创建"

            pk_rows = (await conn.exec_driver_sql(
                "SELECT name FROM pragma_table_info('user_galleries') WHERE pk > 0 ORDER BY pk"
            )).all()
            pk_cols = {r[0] for r in pk_rows}
            assert pk_cols == {"user_id", "gallery_id"}, (
                f"联合主键应为 (user_id, gallery_id)，实际为 {pk_cols}"
            )
    finally:
        await engine.dispose()
