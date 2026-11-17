"""Shared fixtures."""

import os
import tempfile
from collections.abc import AsyncIterator, Iterator

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


def _database_urls() -> list[str]:
    urls = ["sqlite+aiosqlite:///:memory:"]
    if postgres := os.environ.get("SPARTA_TEST_POSTGRES_URL"):
        urls.append(postgres)
    return urls


@pytest_asyncio.fixture(params=_database_urls(), ids=lambda url: url.split(":", 1)[0].split("+", 1)[0])
async def db(request: pytest.FixtureRequest) -> AsyncIterator[Database]:
    """A fresh schema on every database engine available (SQLite always; PostgreSQL when configured)."""
    database = Database(request.param)
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()
