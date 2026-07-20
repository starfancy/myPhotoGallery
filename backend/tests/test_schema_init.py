import pytest
from sqlalchemy import select
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import User
from myphoto.schema_init import ensure_schema_and_admin
from myphoto.security import verify_password


@pytest.fixture
async def engine_and_sm():
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    yield engine, sm
    await engine.dispose()


async def test_creates_admin_when_none(engine_and_sm):
    engine, sm = engine_and_sm
    created, pw = await ensure_schema_and_admin(engine, sm)
    assert created is True
    assert pw is not None
    assert len(pw) >= 12
    async with sm() as s:
        u = (await s.execute(select(User).where(User.username == "admin"))).scalar_one()
        assert u.role == "admin"
        assert verify_password(pw, u.password_hash)


async def test_noop_when_admin_exists(engine_and_sm):
    engine, sm = engine_and_sm
    await ensure_schema_and_admin(engine, sm)
    created, pw = await ensure_schema_and_admin(engine, sm)
    assert created is False
    assert pw is None
