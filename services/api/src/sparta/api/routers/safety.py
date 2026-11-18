"""Safety Center: policy transparency, recent safety events, trusted and blocked callers, audit trail."""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from sparta.api.deps import Ctr, Owner, forget_cached_creations, run_idempotent
from sparta.api.errors import ERROR_RESPONSES
from sparta.domain.models import BlockedCaller, TrustedCaller
from sparta.services.views import AuditEntry, ListNumberRequest, SafetyEventView, SafetyPolicyView

router = APIRouter(tags=["safety"], responses=ERROR_RESPONSES)
EntryId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-]{1,40}$")]


@router.get("/safety/policies", response_model=SafetyPolicyView)
async def policies(owner: Owner, c: Ctr) -> SafetyPolicyView:
    """What Sparta refuses and why, in the terms the policy itself uses (no hidden rules)."""
    return await c.owner.safety_policies(owner)


@router.get("/safety/events", response_model=list[SafetyEventView])
async def safety_events(owner: Owner, c: Ctr, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[SafetyEventView]:
    """Medium and high risk calls with the signal codes that triggered them. Never transcript text."""
    return await c.owner.safety_events(owner, limit)


@router.get("/blocked-callers", response_model=list[BlockedCaller])
async def list_blocked(owner: Owner, c: Ctr) -> list[BlockedCaller]:
    return await c.owner.list_blocked(owner)


@router.post("/blocked-callers", response_model=BlockedCaller, status_code=201)
async def add_blocked(req: ListNumberRequest, request: Request, owner: Owner, c: Ctr) -> BlockedCaller | JSONResponse:
    async def go() -> BlockedCaller:
        return await c.owner.add_blocked(owner, req)

    return await run_idempotent(request, owner, c, go, status_code=201, body=req)


@router.delete("/blocked-callers/{entry_id}", status_code=204)
async def remove_blocked(entry_id: EntryId, request: Request, owner: Owner, c: Ctr) -> Response:
    await c.owner.remove_blocked(owner, entry_id)
    await forget_cached_creations(request, owner, c)
    return Response(status_code=204)


@router.get("/trusted-callers", response_model=list[TrustedCaller])
async def list_trusted(owner: Owner, c: Ctr) -> list[TrustedCaller]:
    return await c.owner.list_trusted(owner)


@router.post("/trusted-callers", response_model=TrustedCaller, status_code=201)
async def add_trusted(req: ListNumberRequest, request: Request, owner: Owner, c: Ctr) -> TrustedCaller | JSONResponse:
    async def go() -> TrustedCaller:
        return await c.owner.add_trusted(owner, req)

    return await run_idempotent(request, owner, c, go, status_code=201, body=req)


@router.delete("/trusted-callers/{entry_id}", status_code=204)
async def remove_trusted(entry_id: EntryId, request: Request, owner: Owner, c: Ctr) -> Response:
    await c.owner.remove_trusted(owner, entry_id)
    await forget_cached_creations(request, owner, c)
    return Response(status_code=204)


@router.get("/audit", response_model=list[AuditEntry])
async def audit(owner: Owner, c: Ctr, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[AuditEntry]:
    """Sensitive actions (deletions, exports, list changes, preference changes). Identifiers only, never content."""
    return await c.owner.audit_log(owner, limit)
