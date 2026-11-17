"""Async database access: engine creation, units of work and migrations."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from sparta.db.models import Base

if TYPE_CHECKING:
    from sparta.db.repository import Repository

_PACKAGE_MIGRATIONS = Path(__file__).resolve().parents[1] / "_migrations"  # wheel installs (hatch force-include)
_SOURCE_MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"  # source checkout and editable installs
MIGRATIONS_DIR = _PACKAGE_MIGRATIONS if _PACKAGE_MIGRATIONS.is_dir() else _SOURCE_MIGRATIONS
ALEMBIC_INI = MIGRATIONS_DIR.parent / "alembic.ini"  # present in a source checkout only; logging setup is optional


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


class DatabaseUnavailable(RuntimeError):
    """The database cannot be reached. The message is safe to show: it never includes the connection URL."""


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        kwargs: dict[str, Any] = {"echo": echo}
        if is_sqlite(url):
            if ":memory:" in url or url.endswith("://"):
                kwargs.update(poolclass=StaticPool, connect_args={"check_same_thread": False})
            else:
                parsed = make_url(url)
                if parsed.database:
                    Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        else:
            kwargs.update(pool_size=10, max_overflow=10, pool_pre_ping=True)
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        if is_sqlite(url):

            @event.listens_for(self.engine.sync_engine, "connect")
            def _pragmas(dbapi_conn: Any, _record: Any) -> None:
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                if ":memory:" not in url:
                    cur.execute("PRAGMA journal_mode=WAL")
                cur.close()

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

    async def schema_ready(self) -> bool:
        """The database answers *and* the schema exists (a fresh server that was never migrated is not ready)."""
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1 FROM users LIMIT 1"))
        except Exception:
            return False
        return True

    async def dispose(self) -> None:
        await self.engine.dispose()


def _alembic_config(url: str) -> Any:
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI)) if ALEMBIC_INI.is_file() else Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


async def run_migrations(url: str, revision: str = "head") -> None:
    """Apply Alembic migrations (in a worker thread: Alembic's async env manages its own event loop)."""
    from alembic import command

    cfg = _alembic_config(url)
    await asyncio.to_thread(command.upgrade, cfg, revision)


async def downgrade(url: str, revision: str = "base") -> None:
    from alembic import command

    await asyncio.to_thread(command.downgrade, _alembic_config(url), revision)
