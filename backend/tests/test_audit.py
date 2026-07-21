from __future__ import annotations

import pytest
from sqlalchemy import select

from myphoto.audit import write_audit
from myphoto.db import create_all, make_engine, make_sessionmaker
from myphoto.models import AuditLog


@pytest.fixture
async def session():
    engine = await make_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    sm = await make_sessionmaker(engine)
    async with sm() as s:
        yield s
    await engine.dispose()


async def test_audit_log_insert_and_query(session):
    await write_audit(
        session, "login_success", actor_user_id=1, actor_ip="192.168.1.1",
        target="user:admin", detail="{}",
    )
    await session.commit()
    rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "login_success"
    assert rows[0].actor_ip == "192.168.1.1"
    assert rows[0].target == "user:admin"
    assert rows[0].detail == "{}"


async def test_audit_with_nulls(session):
    await write_audit(
        session, "scan_start", actor_user_id=None, actor_ip="127.0.0.1",
        target="root:42",
    )
    await session.commit()
    row = (await session.execute(select(AuditLog))).scalar_one()
    assert row.actor_user_id is None
    assert row.detail is None


async def test_audit_failure_does_not_propagate(session, monkeypatch):
    original_add = session.add

    def bad_add(*a, **kw):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(session, "add", bad_add)
    # Must not raise
    await write_audit(session, "test", 1, "127.0.0.1")
