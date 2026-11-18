"""Startup checks that turn a missing dependency into a readable message instead of a stack trace.

Used by the command line (``serve``, ``migrate``, ``seed``). The messages name the target without credentials and say
what to do next. Anything unexpected is reported by exception class only: exception text can contain connection details.
"""

import asyncio
import contextlib
import socket

from sqlalchemy import text
from sqlalchemy.engine import make_url

from sparta.config import Settings
from sparta.db.session import Database, is_sqlite

CHECK_TIMEOUT_S = 5.0

_DATABASE_HINT = (
    "Start PostgreSQL (for example `docker compose up -d postgres`) or set SPARTA_DATABASE_URL to a reachable "
    "database. Local development needs no server: the default is a SQLite file."
)
_REDIS_HINT = (
    "Start Redis (for example `docker compose up -d redis`) or set SPARTA_REDIS_URL to a reachable server. "
    "Outside production you can leave it unset."
)


def describe_target(url: str) -> str:
    """Where the URL points, without user name or password."""
    try:
        parsed = make_url(url)
    except Exception:
        return "an unparseable URL"
    if parsed.get_backend_name() == "sqlite":
        return f"SQLite file {parsed.database}" if parsed.database else "an in-memory SQLite database"
    host = parsed.host or "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    name = f"/{parsed.database}" if parsed.database else ""
    return f"{parsed.get_backend_name()} at {host}{port}{name}"


def reason_for(exc: BaseException) -> str:
    """A short, safe explanation of a connection failure (walks the cause chain)."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = type(current).__name__
        detail = str(current).lower()
        if isinstance(current, ConnectionRefusedError) or (
            isinstance(current, OSError) and ("refused" in detail or "connect call failed" in detail)
        ):
            return "connection refused"
        if isinstance(current, socket.gaierror):
            return "host name not found"
        if isinstance(current, TimeoutError):
            return "timed out"
        if name in {"InvalidPasswordError", "InvalidAuthorizationSpecificationError"}:
            return "authentication failed (check the user name and password)"
        if name == "InvalidCatalogNameError":
            return "the database does not exist"
        if name == "AuthenticationError":
            return "authentication failed (check the password)"
        if "unable to open database file" in str(current):
            return "the file cannot be opened (does the folder exist and is it writable?)"
        current = current.__cause__ or current.__context__
    return f"unexpected {type(exc).__name__}"


async def check_database(url: str) -> str | None:
    """``None`` when the database answers, otherwise a message."""
    db = Database(url)
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S), db.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        target = describe_target(url)
        hint = "Check that the folder is writable." if is_sqlite(url) else _DATABASE_HINT
        return f"Cannot reach the database ({target}): {reason_for(exc)}. {hint}"
    finally:
        with contextlib.suppress(Exception):
            await db.dispose()
    return None


async def check_redis(url: str) -> str | None:
    """``None`` when Redis answers PING, otherwise a message."""
    import redis.asyncio as redis

    client = redis.from_url(url, socket_connect_timeout=CHECK_TIMEOUT_S)
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            await client.ping()
    except Exception as exc:
        return f"Cannot reach Redis ({describe_target(url)}): {reason_for(exc)}. {_REDIS_HINT}"
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()
    return None


async def check_dependencies(settings: Settings, *, include_redis: bool = True) -> list[str]:
    """Every dependency problem found, as messages. Empty when the process can start."""
    checks = [check_database(settings.database_url)]
    if include_redis and settings.redis_url:
        checks.append(check_redis(settings.redis_url))
    return [message for message in await asyncio.gather(*checks) if message]
