"""FastAPI dependencies: container access, the authenticated owner, rate limits and idempotent execution."""

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.requests import HTTPConnection

from sparta.services.container import Container
from sparta.services.dto import Principal
from sparta.services.errors import Conflict, InvalidInput, NotFound, RateLimited

IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_\-:.]{1,64}")
IDEMPOTENCY_TTL = timedelta(hours=24)
# Routes whose response carries what the caller said or what the owner wrote. A retry only makes sense for a short time,
# so those responses are kept briefly, never when the owner chose not to store transcripts, and are deleted together
# with the call's content (see ``Repository.delete_call_content``).
CONTENT_ROUTE = re.compile(r"^[A-Z]+ \S*/calls/[^/\s]+/(?:turns|audio|silence|feedback)$")
IDEMPOTENCY_CONTENT_TTL = timedelta(minutes=15)
CALL_ID_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"


def get_container(conn: HTTPConnection) -> Container:
    container: Container = conn.app.state.container
    return container


Ctr = Annotated[Container, Depends(get_container)]


async def _hit(request: Request, container: Container, bucket: str, key: str, limit: int) -> None:
    decision = await container.limiter.hit(bucket, key, limit)
    request.state.rate_limit = (decision.limit, decision.remaining)
    if not decision.allowed:
        raise RateLimited("Too many requests. Please slow down.", retry_after_s=decision.retry_after_s)


async def current_owner(request: Request) -> Principal:
    """Authenticate, make sure the owner exists, and apply the per-owner request limit."""
    container = get_container(request)
    principal: Principal = await request.app.state.authenticator.authenticate(request)
    known: set[str] = request.app.state.known_users
    if principal.id not in known:
        locks: dict[str, asyncio.Lock] = request.app.state.user_locks
        lock = locks.setdefault(principal.id, asyncio.Lock())
        async with lock:
            if principal.id not in known:  # a concurrent first request may have provisioned the owner meanwhile
                await container.owner.ensure_user(principal)
                known.add(principal.id)
        locks.pop(principal.id, None)
    await _hit(request, container, "api", principal.id, container.settings.rate_limit_per_minute)
    return principal


Owner = Annotated[Principal, Depends(current_owner)]


async def create_call_limit(request: Request, owner: Owner, container: Ctr) -> None:
    await _hit(request, container, "create_call", owner.id, container.settings.call_create_rate_limit_per_minute)


async def profile_write_limit(request: Request, owner: Owner, container: Ctr) -> None:
    await _hit(request, container, "profile_write", owner.id, container.settings.profile_write_rate_limit_per_minute)


async def require_simulator(container: Ctr) -> None:
    if not container.settings.simulator_enabled:
        raise NotFound("The simulator is not enabled on this server.")


async def run_idempotent[T](
    request: Request,
    owner: Principal,
    container: Container,
    handler: Callable[[], Awaitable[T]],
    *,
    status_code: int = 200,
    body: BaseModel | None = None,
) -> T | JSONResponse:
    """Run ``handler`` once per ``Idempotency-Key``.

    Same key + same owner + same route replays the stored response (header ``Idempotent-Replayed: true``); the same key
    with a different request is a conflict. Failures are not stored, so a retry after an error runs again.
    """
    key = request.headers.get("idempotency-key")
    if key is None:
        return await handler()
    if not IDEMPOTENCY_KEY.fullmatch(key):
        raise InvalidInput("Idempotency-Key must be 1-64 characters: letters, digits, '_', '-', ':' or '.'.")
    route = f"{request.method} {request.url.path}"[:160]
    fingerprint = json.dumps(
        {"route": route, "body": body.model_dump(mode="json") if body is not None else None}, sort_keys=True
    )
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()
    lock = "idem:" + hashlib.sha256(f"{owner.id}|{route}|{key}".encode()).hexdigest()
    async with container.kv.lock(lock, ttl_s=60.0, wait_s=15.0):
        now = container.clock.now()
        async with container.db.uow() as repo:
            row = await repo.get_idempotent(owner.id, route, key, now)
            stored: tuple[str, int, Any] | None = (row.request_hash, row.status_code, row.response) if row else None
        if stored is not None:
            if stored[0] != digest:
                raise Conflict("This Idempotency-Key was already used for a different request.")
            return JSONResponse(stored[2], status_code=stored[1], headers={"Idempotent-Replayed": "true"})
        result = await handler()
        payload = jsonable_encoder(result)
        ttl, stored_status = IDEMPOTENCY_TTL, status_code
        if CONTENT_ROUTE.match(route):
            ttl = IDEMPOTENCY_CONTENT_TTL
            if not (await container.owner.get_preferences(owner)).retention.store_transcripts:
                # Nothing the caller said may be kept: remember only that the request was processed.
                stored_status = 409
                payload = {
                    "error": {
                        "code": "conflict",
                        "message": "This request was already processed. Reload the call to see the result.",
                        "trace_id": None,
                        "details": None,
                    }
                }
        async with container.db.uow() as repo:
            await repo.save_idempotent(owner.id, route, key, digest, stored_status, payload, now, ttl)
        return JSONResponse(jsonable_encoder(result), status_code=status_code)
