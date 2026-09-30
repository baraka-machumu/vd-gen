"""Integration tests against a real PostgreSQL with pgvector. Set TEST_DATABASE_URL to run them, e.g.

docker run --rm -d -p 55432:5432 -e POSTGRES_PASSWORD=test pgvector/pgvector:pg17
TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/postgres pytest -m integration
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_engine, create_sessionmaker, transaction
from tests.conftest import make_settings

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set"),
]
BACKEND_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture
def database_url(monkeypatch: pytest.MonkeyPatch) -> str:
    assert TEST_DATABASE_URL
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    get_settings.cache_clear()
    return TEST_DATABASE_URL


async def test_migrations_upgrade_and_downgrade(database_url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    # env.py runs its own event loop, so Alembic must run outside this test's loop.
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine = create_engine(make_settings(database_url=database_url))
    try:
        async with engine.connect() as conn:
            installed = await conn.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'"))
            version = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        assert installed == 1
        assert version == "0001"
    finally:
        await engine.dispose()
    await asyncio.to_thread(command.downgrade, cfg, "base")
    await asyncio.to_thread(command.upgrade, cfg, "head")


async def test_transaction_commits_on_success_and_rolls_back_on_error(database_url: str) -> None:
    engine = create_engine(make_settings(database_url=database_url))
    sessionmaker = create_sessionmaker(engine)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE IF NOT EXISTS _tx_probe (v int)"))
            await conn.execute(text("TRUNCATE _tx_probe"))

        async for session in transaction(sessionmaker):
            await session.execute(text("INSERT INTO _tx_probe VALUES (1)"))

        with pytest.raises(RuntimeError):
            async for session in transaction(sessionmaker):
                await session.execute(text("INSERT INTO _tx_probe VALUES (2)"))
                raise RuntimeError("fail inside the unit of work")

        async with engine.connect() as conn:
            rows: list[int] = list((await conn.execute(text("SELECT v FROM _tx_probe ORDER BY v"))).scalars().all())
        assert rows == [1]
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS _tx_probe"))
        await engine.dispose()
