"""Audit trail for sensitive owner actions. Entries carry identifiers and counts, never call content or numbers."""

from datetime import datetime
from typing import Any

from sparta.db.repository import Repository
from sparta.logging_setup import correlation_id_var

_FORBIDDEN_KEYS = ("text", "transcript", "number", "phone", "name", "note", "message", "token", "key", "secret")
_MAX_VALUE = 80


def _safe_detail(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    if not detail:
        return None
    clean: dict[str, Any] = {}
    for key, value in list(detail.items())[:12]:
        if any(bad in key.lower() for bad in _FORBIDDEN_KEYS):
            continue
        if isinstance(value, bool | int | float) or value is None:
            clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:_MAX_VALUE]
        elif isinstance(value, list | tuple):
            clean[key] = [str(v)[:_MAX_VALUE] for v in list(value)[:12]]
    return clean or None


async def record_audit(
    repo: Repository,
    user_id: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict[str, Any] | None = None,
    *,
    now: datetime,
) -> None:
    await repo.add_audit(user_id, action, target_type, target_id, _safe_detail(detail), correlation_id_var.get(), now)
