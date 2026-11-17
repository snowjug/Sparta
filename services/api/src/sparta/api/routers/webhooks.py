"""Provider callbacks. Not for UI clients, and deliberately absent from the OpenAPI document.

Every handler authenticates *before* parsing anything: Event Grid and ACS requests carry a verified JWT, the generic
provider webhook an HMAC signature with timestamp, nonce and replay protection. Nothing unsigned is ever acted on, and
rejections are generic (the specific reason goes to the log as a static label only).
"""

import json
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sparta.api.deps import CALL_ID_PATTERN, get_container
from sparta.api.errors import error_response
from sparta.providers.base import ProviderError
from sparta.services.container import Container
from sparta.services.kv import KeyValueStore
from sparta.telephony.azure_acs import AzureAcsTelephonyProvider
from sparta.telephony.base import IncomingCall
from sparta.telephony.webhooks import (
    INCOMING_CALL_EVENT,
    WebhookRejected,
    bearer_token,
    parse_event_grid,
    subscription_validation_response,
    verify_generic_hmac,
)

log = logging.getLogger("sparta.webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"], include_in_schema=False)
media_router = APIRouter(prefix="/media", tags=["webhooks"], include_in_schema=False)
CallId = Annotated[str, Path(pattern=CALL_ID_PATTERN)]
REPLAY_TTL_S = 700


class KvReplayGuard:
    """Replay protection shared by every API instance (uses the same store as rate limits)."""

    def __init__(self, kv: KeyValueStore) -> None:
        self._kv = kv

    async def seen(self, key: str, ttl_s: int) -> bool:
        return await self._kv.incr(f"replay:{key}", ttl_s) > 1


def _rejected(exc: WebhookRejected, what: str) -> JSONResponse:
    log.warning("webhook rejected", extra={"endpoint": what, "reason": exc.reason, "status": exc.status_code})
    status = exc.status_code
    code = {400: "validation_error", 401: "unauthorized", 413: "payload_too_large", 503: "provider_unavailable"}.get(
        status, "unauthorized"
    )
    message = "The request could not be accepted." if status != 401 else "Authentication failed."
    return error_response(status, code, message, headers={"WWW-Authenticate": "Bearer"} if status == 401 else None)


def _acs(c: Container) -> AzureAcsTelephonyProvider | None:
    provider = c.providers.telephony
    return provider if isinstance(provider, AzureAcsTelephonyProvider) else None


def _not_configured() -> JSONResponse:
    return error_response(404, "not_found", "Not Found")


# ------------------------------------------------------------------------------------------- Event Grid
@router.post("/acs/events")
async def acs_events(request: Request) -> JSONResponse:
    """Event Grid delivery (Event Grid schema): the validation handshake and ``IncomingCall`` events."""
    c = get_container(request)
    provider = _acs(c)
    if provider is None:
        return _not_configured()
    body = await request.body()
    try:
        await provider.event_grid_verifier().verify(bearer_token(request.headers.get("authorization")))
        events = parse_event_grid(body)
        handshake = subscription_validation_response(events)
    except WebhookRejected as exc:
        return _rejected(exc, "acs_events")
    if handshake is not None:
        return JSONResponse(handshake)
    handled = 0
    for event in events:
        if event.eventType != INCOMING_CALL_EVENT:
            continue
        async with c.db.uow() as repo:
            if await repo.has_provider_event("azure", event.id):
                continue  # a redelivery of something already handled (also across restarts)
        try:
            call_id = await provider.handle_incoming(event)
        except WebhookRejected as exc:
            return _rejected(exc, "acs_events")
        async with c.db.uow() as repo:
            await repo.add_provider_event("azure", event.id, "incoming_call", None, None, c.clock.now())
            await repo.attach_provider_event("azure", event.id, call_id)
        handled += 1
    return JSONResponse({"handled": handled})


# ----------------------------------------------------------------------------------- Call Automation
@router.post("/acs/callbacks/{call_id}")
async def acs_callbacks(call_id: CallId, request: Request) -> JSONResponse:
    c = get_container(request)
    provider = _acs(c)
    if provider is None:
        return _not_configured()
    body = await request.body()
    try:
        await provider.callback_verifier().verify(bearer_token(request.headers.get("authorization")))
    except WebhookRejected as exc:
        return _rejected(exc, "acs_callbacks")
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return error_response(400, "validation_error", "The request could not be accepted.")
    await provider.handle_callback_event(call_id, payload)
    return JSONResponse({"status": "ok"})


@media_router.websocket("/acs/{call_id}")
async def acs_media(ws: WebSocket, call_id: CallId) -> None:
    """Bidirectional audio. The upgrade must carry a valid ACS token; otherwise it is refused before it is accepted."""
    c = get_container(ws)
    provider = _acs(c)
    if provider is None:
        await ws.close(code=1008)
        return
    try:
        await provider.media_verifier().verify(bearer_token(ws.headers.get("authorization")))
    except WebhookRejected as exc:
        log.warning("media socket rejected", extra={"reason": exc.reason})
        await ws.close(code=1008)
        return
    await ws.accept()
    try:
        await provider.attach_media(call_id, ws)
    except ProviderError:
        await ws.close(code=1008)


# --------------------------------------------------------------------------------- generic (HMAC signed)
class GenericEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_\-:.]+$")
    type: Literal["call.incoming", "call.ended", "playback.finished", "caller.transcript"]
    call_id: str | None = Field(default=None, max_length=64, pattern=CALL_ID_PATTERN)
    provider_call_id: str | None = Field(default=None, max_length=256)
    caller_number: str | None = Field(default=None, max_length=32)
    called_number: str | None = Field(default=None, max_length=32)
    display_name: str | None = Field(default=None, max_length=64)
    playback_id: str | None = Field(default=None, max_length=64)
    text: str | None = Field(default=None, max_length=1000)
    language: str | None = Field(default=None, max_length=16)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str | None = Field(default=None, max_length=64)


@router.post("/generic")
async def generic(request: Request) -> JSONResponse:
    """Signed events from another telephony provider (`TELEPHONY_PROVIDER=other`).

    Headers: `X-Sparta-Timestamp` (unix seconds), `X-Sparta-Nonce` (unique per request) and `X-Sparta-Signature`
    (hex HMAC-SHA256 of ``"{timestamp}.{nonce}." + body`` with `SPARTA_WEBHOOK_SECRET`).
    """
    c = get_container(request)
    secret = c.settings.webhook_secret
    if c.settings.telephony_provider != "other" or secret is None:
        return _not_configured()
    body = await request.body()
    h = request.headers
    try:
        await verify_generic_hmac(
            secret.get_secret_value(),
            h.get("x-sparta-timestamp", ""),
            h.get("x-sparta-nonce", ""),
            body,
            h.get("x-sparta-signature", ""),
            now=c.clock.now().timestamp(),
            replay=KvReplayGuard(c.kv),
        )
    except WebhookRejected as exc:
        return _rejected(exc, "generic")
    try:
        event = GenericEvent.model_validate_json(body)
    except ValidationError:
        return error_response(422, "validation_error", "The event is not valid.")
    async with c.db.uow() as repo:
        if await repo.has_provider_event("other", event.event_id):
            return JSONResponse({"status": "duplicate"})
    try:
        result = await _dispatch(c, event)
    except WebhookRejected as exc:
        return _rejected(exc, "generic")
    async with c.db.uow() as repo:
        await repo.add_provider_event("other", event.event_id, event.type, result.get("call_id"), None, c.clock.now())
    return JSONResponse({"status": "ok", **result})


async def _dispatch(c: Container, event: GenericEvent) -> dict[str, str | None]:
    calls = c.calls
    if event.type == "call.incoming":
        if not event.provider_call_id:
            raise WebhookRejected("incoming call without provider_call_id", status_code=400)
        call_id = await calls.incoming_call(
            IncomingCall(
                provider="other",
                provider_call_id=event.provider_call_id,
                caller_number=event.caller_number,
                called_number=event.called_number,
                display_name=event.display_name,
                correlation_id=event.event_id,
                received_at=c.clock.now(),
            )
        )
        return {"call_id": call_id}
    if not event.call_id:
        raise WebhookRejected("event without call_id", status_code=400)
    if event.type == "call.ended":
        await calls.remote_hangup(event.call_id, event.reason or "provider_hangup")
    elif event.type == "playback.finished" and event.playback_id:
        await calls.playback_finished(event.call_id, event.playback_id)
    elif event.type == "caller.transcript" and event.text:
        await calls.submit_provider_turn(
            event.call_id, event.text, language_hint=event.language, stt_confidence=event.confidence
        )
    return {"call_id": event.call_id}
