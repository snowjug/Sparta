"""SQLAlchemy column types: timezone-safe datetimes and transparently encrypted text/JSON."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from sparta.db.crypto import EncryptionUnavailable, FieldCipher

_cipher: FieldCipher | None = None


def set_cipher(cipher: FieldCipher | None) -> None:
    """Install the process-wide cipher used by the encrypted column types (set once at startup)."""
    global _cipher  # noqa: PLW0603
    _cipher = cipher


def _require_cipher() -> FieldCipher:
    if _cipher is None:
        raise EncryptionUnavailable("encryption is not initialised: call set_cipher() at startup")
    return _cipher


class UTCDateTime(TypeDecorator[datetime]):
    """Always stores and returns timezone-aware UTC (SQLite drops tzinfo; PostgreSQL keeps it)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class EncryptedText(TypeDecorator[str]):
    """Text encrypted at rest. ``None`` stays ``NULL`` so absence is queryable without exposing content."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return _require_cipher().encrypt(value.encode("utf-8")).decode("ascii")

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return _require_cipher().decrypt(value.encode("ascii")).decode("utf-8")


class EncryptedJSON(TypeDecorator[Any]):
    """JSON document encrypted at rest."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        return _require_cipher().encrypt(raw.encode("utf-8")).decode("ascii")

    def process_result_value(self, value: str | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        return json.loads(_require_cipher().decrypt(value.encode("ascii")).decode("utf-8"))
