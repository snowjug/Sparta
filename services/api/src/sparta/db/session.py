"""Async database access: engine creation, units of work and migrations."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from sparta.db.models import Base

if TYPE_CHECKING:
    from sparta.db.repository import Repository

SchemaState = Literal["ok", "unavailable", "migrations_pending"]

_PACKAGE_MIGRATIONS = Path(__file__).resolve().parents[1] / "_migrations"  # wheel installs (hatch force-include)
_SOURCE_MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"  # source checkout and editable installs
MIGRATIONS_DIR = _PACKAGE_MIGRATIONS if _PACKAGE_MIGRATIONS.is_dir() else _SOURCE_MIGRATIONS
ALEMBIC_INI = MIGRATIONS_DIR.parent / "alembic.ini"  # present in a source checkout only; logging setup is optional


SQLITE_BUSY_TIMEOUT_MS = 15_000  # how long a writer waits for another one before "database is locked"


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def is_sqlite_file(url: str) -> bool:
    return is_sqlite(url) and ":memory:" not in url and not url.endswith("://")


class DatabaseUnavailable(RuntimeError):
    """The database cannot be reached. The message is safe to show: it never includes the connection URL."""


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        kwargs: dict[str, Any] = {"echo": echo}
        if is_sqlite(url):
            if not is_sqlite_file(url):
                # One connection holds the whole in-memory database (every test and the deterministic replay), so
                # units of work must take turns on it: sharing it between overlapping transactions lets one commit
                # or roll back another's work.
                kwargs.update(
                    poolclass=AsyncAdaptedQueuePool,
                    pool_size=1,
                    max_overflow=0,
                    connect_args={"check_same_thread": False},
                )
            else:
                parsed = make_url(url)
                if parsed.database:
                    Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        else:
            kwargs.update(pool_size=10, max_overflow=10, pool_pre_ping=True)
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        if is_sqlite(url):
            file_backed = is_sqlite_file(url)

            @event.listens_for(self.engine.sync_engine, "connect")
            def _pragmas(dbapi_conn: Any, _record: Any) -> None:
                if file_backed:
                    dbapi_conn.isolation_level = None  # transactions are started explicitly, see _begin_immediate
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                if file_backed:
                    cur.execute("PRAGMA journal_mode=WAL")
                    cur.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
                cur.close()

            if file_backed:

                @event.listens_for(self.engine.sync_engine, "begin")
                def _begin_immediate(conn: Any) -> None:
                    # A deferred transaction that reads and later writes fails at once with "database is locked" when
                    # another connection committed in between, and no busy timeout helps. Taking the write lock when
                    # the transaction begins makes writers queue instead. Every unit of work here is short and never
                    # waits on another one (see tests/unit/test_transactions.py), so queueing cannot deadlock.
                    conn.exec_driver_sql("BEGIN IMMEDIATE")

        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def uow(self) -> "AsyncIterator[Repository]":
        """One transaction: commits on success, rolls back on any exception."""
        from sparta.db.repository import Repository

        async with self._sessions() as session, session.begin():
            yield Repository(session)

    async def create_all(self) -> None:
        """Create tables directly from the models. Used for in-memory databases (tests, deterministic replay)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def ping(self) -> bool:
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            return False
        return True

    async def schema_state(self) -> SchemaState:
        """Whether this instance may take traffic: the database answers, the schema exists, and the migrations applied
        are the ones this code expects. A database *ahead* of the code (a rollback) is fine: migrations are additive and
        a later release removes what is no longer used."""
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1 FROM users LIMIT 1"))
                try:
                    applied = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
                except Exception:
                    applied = None  # created without migrations (tests, deterministic replay): nothing to compare
        except Exception:
            return "unavailable"
        head, known = expected_revisions()
        if head is not None and applied in known and applied != head:
            return "migrations_pending"
        return "ok"

    async def schema_ready(self) -> bool:
        return await self.schema_state() == "ok"

    async def dispose(self) -> None:
        await self.engine.dispose()


def _alembic_config(url: str) -> Any:
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI)) if ALEMBIC_INI.is_file() else Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@lru_cache(maxsize=1)
def expected_revisions() -> tuple[str | None, frozenset[str]]:
    """The migration head this code expects and every revision it knows. ``(None, empty)`` when the migration scripts
    cannot be read or have several heads: readiness then does not compare revisions."""
    try:
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
        heads = script.get_heads()
        if len(heads) != 1:
            return None, frozenset()
        return heads[0], frozenset(revision.revision for revision in script.walk_revisions())
    except Exception:
        return None, frozenset()


async def run_migrations(url: str, revision: str = "head") -> None:
    """Apply Alembic migrations (in a worker thread: Alembic's async env manages its own event loop)."""
    from alembic import command

    cfg = _alembic_config(url)
    await asyncio.to_thread(command.upgrade, cfg, revision)


async def downgrade(url: str, revision: str = "base") -> None:
    from alembic import command

    await asyncio.to_thread(command.downgrade, _alembic_config(url), revision)
