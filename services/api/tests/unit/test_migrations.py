"""Alembic migrations apply, round-trip, and stay in sync with the SQLAlchemy models."""

import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from sparta.db.models import Base
from sparta.db.session import downgrade, run_migrations


def _urls(tmp_path) -> list[str]:
    urls = [f"sqlite+aiosqlite:///{(tmp_path / 'migrations.db').as_posix()}"]
    if postgres := os.environ.get("SPARTA_TEST_POSTGRES_URL"):
        urls.append(postgres)
    return urls


async def _reset(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()


async def _diff(url: str) -> list:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:

            def compare(sync_conn):
                ctx = MigrationContext.configure(sync_conn, opts={"compare_type": True})
                return compare_metadata(ctx, Base.metadata)

            return await conn.run_sync(compare)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migrations_apply_match_the_models_and_downgrade_cleanly(tmp_path):
    for url in _urls(tmp_path):
        await _reset(url)
        await run_migrations(url)
        assert await _diff(url) == [], f"migrations and models have drifted on {url.split(':', 1)[0]}"

        await downgrade(url, "base")
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            tables = (
                (
                    await conn.execute(
                        text("SELECT name FROM sqlite_master WHERE type='table'")
                        if url.startswith("sqlite")
                        else text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
                    )
                )
                .scalars()
                .all()
            )
        await engine.dispose()
        assert set(tables) <= {"alembic_version"}

        await run_migrations(url)  # and upgrades again after a downgrade
        await _reset(url)


@pytest.mark.asyncio
async def test_migrations_run_without_the_source_tree_alembic_ini(tmp_path, monkeypatch):
    """A wheel install bundles the migrations but not alembic.ini; migrating must not depend on it."""
    from sparta.db import session

    monkeypatch.setattr(session, "ALEMBIC_INI", tmp_path / "missing" / "alembic.ini")
    assert (session.MIGRATIONS_DIR / "env.py").is_file() and (session.MIGRATIONS_DIR / "versions").is_dir()
    url = f"sqlite+aiosqlite:///{(tmp_path / 'no-ini.db').as_posix()}"
    await run_migrations(url)
    assert await _diff(url) == []
