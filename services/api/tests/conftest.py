"""Shared fixtures."""

import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio

# Keep tests hermetic: never read a developer's .env and never write under the repo.
os.environ.setdefault("SPARTA_ENV", "test")
os.environ.setdefault("SPARTA_LOG_JSON", "false")
os.environ.setdefault("SPARTA_DATA_DIR", tempfile.mkdtemp(prefix="sparta-test-"))

from sparta.clock import VirtualClock
from sparta.db.crypto import FieldCipher, generate_key
from sparta.db.models import Base
from sparta.db.session import Database
from sparta.db.types import set_cipher
from sparta.orchestrator.engine import ConversationEngine, EngineConfig


@pytest.fixture(scope="session", autouse=True)
def field_cipher() -> Iterator[FieldCipher]:
    cipher = FieldCipher([generate_key()])
    set_cipher(cipher)
    yield cipher
    set_cipher(None)


@pytest.fixture(scope="session")
def engine() -> ConversationEngine:
    return ConversationEngine()


@pytest.fixture
def cfg() -> EngineConfig:
    return EngineConfig(call_id="call_test0001", owner_name="Atharv")


@pytest.fixture
def clock() -> VirtualClock:
    return VirtualClock()


def _database_params() -> list[object]:
    """SQLite in memory, SQLite in a file (the development default, with real connection concurrency), PostgreSQL."""
    file_db = Path(tempfile.mkdtemp(prefix="sparta-test-db-")) / "sparta-test.db"
    params = [
        pytest.param("sqlite+aiosqlite:///:memory:", id="sqlite-memory"),
        pytest.param(f"sqlite+aiosqlite:///{file_db.as_posix()}", id="sqlite-file"),
    ]
    if postgres := os.environ.get("SPARTA_TEST_POSTGRES_URL"):
        params.append(pytest.param(postgres, id="postgresql"))
    return params


@pytest_asyncio.fixture(params=_database_params())
async def db(request: pytest.FixtureRequest) -> AsyncIterator[Database]:
    """A fresh schema on every database engine available (SQLite always; PostgreSQL when configured)."""
    database = Database(request.param)
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()
