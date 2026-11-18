"""Native Android call screening: configuration, offline lists (fingerprints only) and decision events."""

from fastapi import APIRouter

from sparta.api.deps import Ctr, Owner
from sparta.api.errors import ERROR_RESPONSES
from sparta.domain.models import CallListItem
from sparta.services.views import ScreeningConfig, ScreeningEventRequest, ScreeningLists

router = APIRouter(prefix="/screening", tags=["screening"], responses=ERROR_RESPONSES)


@router.get("/config", response_model=ScreeningConfig)
async def config(owner: Owner, c: Ctr) -> ScreeningConfig:
    """`fingerprint_salt` is the base64 HMAC key the device uses to fingerprint numbers. Treat it as a secret."""
    return await c.owner.screening_config(owner)


@router.get("/lists", response_model=ScreeningLists)
async def lists(owner: Owner, c: Ctr) -> ScreeningLists:
    return await c.owner.screening_lists(owner)


@router.post("/events", response_model=CallListItem)
async def event(req: ScreeningEventRequest, owner: Owner, c: Ctr) -> CallListItem:
    """Records what the device decided as a `screening_only` call. Idempotent on `client_event_id`: native screening
    cannot answer a call or hear its audio, so such a call has no transcript."""
    return await c.owner.record_screening_event(owner, req)
