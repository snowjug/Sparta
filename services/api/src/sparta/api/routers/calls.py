"""Call endpoints: create, read, drive turns, owner actions, feedback, export and deletion."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import Field

from sparta.api.deps import CALL_ID_PATTERN, Ctr, Owner, create_call_limit, run_idempotent
from sparta.api.errors import ERROR_RESPONSES
from sparta.db.repository import CallFilter
from sparta.domain.enums import CallCategory, CallStatus, FeedbackKind, OwnerActionType, ProviderKind, RiskLevel
from sparta.domain.models import (
    BlockedCaller,
    CallDetail,
    CallListItem,
    FeedbackRecord,
    LiveEvent,
    SpartaModel,
    StrictInputModel,
    TrustedCaller,
)
from sparta.services.dto import (
    BlockRequest,
    CreateCallRequest,
    InterruptRequest,
    InterruptResult,
    OwnerActionResult,
    PartialRequest,
    TrustRequest,
    TurnRequest,
    TurnResult,
)

router = APIRouter(prefix="/calls", tags=["calls"], responses=ERROR_RESPONSES)
CallId = Annotated[str, Path(pattern=CALL_ID_PATTERN, description="Call id")]


class CallPage(SpartaModel):
    items: list[CallListItem]
    next_cursor: str | None = None


class FeedbackRequest(StrictInputModel):
    kind: FeedbackKind
    note: str | None = Field(default=None, max_length=500)


def _download(payload: Any, filename: str) -> JSONResponse:
    return JSONResponse(payload, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("", status_code=201, response_model=CallDetail, dependencies=[Depends(create_call_limit)])
async def create_call(req: CreateCallRequest, request: Request, owner: Owner, c: Ctr) -> CallDetail | JSONResponse:
    """Start a call through the configured telephony provider.

    Real providers create calls when the provider delivers them, so this answers 409 `unsupported_by_provider` unless
    the provider is the simulator.
    """

    async def go() -> CallDetail:
        if c.settings.telephony_provider == "simulator":
            if not c.settings.simulator_enabled:
                from sparta.services.errors import UnsupportedByProvider

                raise UnsupportedByProvider("The simulator is disabled on this server.")
            return await c.simulator.create_call(owner, req)
        return await c.calls.create_call(owner, req, simulator=False)

    return await run_idempotent(request, owner, c, go, status_code=201, body=req)


@router.get("", response_model=CallPage)
async def list_calls(
    owner: Owner,
    c: Ctr,
    q: Annotated[str | None, Query(max_length=100)] = None,
    risk_level: RiskLevel | None = None,
    category: CallCategory | None = None,
    language: Annotated[str | None, Query(pattern=r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")] = None,
    status: CallStatus | None = None,
    attention: bool | None = None,
    provider: ProviderKind | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> CallPage:
    items, next_cursor = await c.calls.list_calls(
        owner,
        CallFilter(
            q=q,
            risk_level=risk_level.value if risk_level else None,
            category=category.value if category else None,
            language=language,
            status=status.value if status else None,
            attention=attention,
            provider=provider.value if provider else None,
            since=from_,
            until=to,
            limit=limit,
            cursor=cursor,
        ),
    )
    return CallPage(items=items, next_cursor=next_cursor)


@router.get("/{call_id}", response_model=CallDetail)
async def get_call(call_id: CallId, owner: Owner, c: Ctr) -> CallDetail:
    return await c.calls.get_call(owner, call_id)


@router.post("/{call_id}/turns", response_model=TurnResult)
async def submit_turn(
    call_id: CallId, req: TurnRequest, request: Request, owner: Owner, c: Ctr
) -> TurnResult | JSONResponse:
    async def go() -> TurnResult:
        return await c.calls.submit_turn(
            owner,
            call_id,
            req.text,
            source=req.turn_source(),
            language_hint=req.language_hint,
            stt_confidence=req.stt_confidence,
        )

    return await run_idempotent(request, owner, c, go, body=req)


@router.post("/{call_id}/partial", status_code=204)
async def submit_partial(call_id: CallId, req: PartialRequest, owner: Owner, c: Ctr) -> Response:
    """Emit a `transcript.partial` event only (no pipeline run): live captions while the caller is still speaking."""
    await c.calls.submit_partial(owner, call_id, req.text, req.language_hint)
    return Response(status_code=204)


@router.post("/{call_id}/audio", response_model=TurnResult)
async def upload_audio(
    call_id: CallId,
    owner: Owner,
    c: Ctr,
    file: Annotated[UploadFile, File(description="audio/wav, audio/ogg or audio/webm")],
    language_hint: Annotated[str | None, Form(max_length=16)] = None,
    transcript_hint: Annotated[str | None, Form(max_length=1000)] = None,
) -> TurnResult:
    """Transcribe an uploaded clip in memory and run it as a caller turn.

    With the simulator STT there is no acoustic model: send `transcript_hint`, otherwise this is 422 `stt_unavailable`.
    """
    data = await file.read(c.settings.max_audio_bytes + 1)
    return await c.audio.submit_upload(
        owner, call_id, data, file.content_type, language_hint=language_hint, transcript_hint=transcript_hint
    )


@router.post("/{call_id}/interrupt", response_model=InterruptResult)
async def interrupt(call_id: CallId, owner: Owner, c: Ctr, req: InterruptRequest | None = None) -> InterruptResult:
    """Caller barge-in: stops the assistant's playback and keeps the conversation state."""
    return await c.calls.interrupt(owner, call_id, req.spoken_fraction if req else None)


@router.post("/{call_id}/silence", response_model=TurnResult)
async def silence(call_id: CallId, owner: Owner, c: Ctr) -> TurnResult:
    """Fire one silence timeout (what the timer does on a real call)."""
    return await c.calls.silence(owner, call_id)


def _owner_action(action: OwnerActionType) -> Any:
    async def endpoint(call_id: CallId, request: Request, owner: Owner, c: Ctr) -> OwnerActionResult | JSONResponse:
        async def go() -> OwnerActionResult:
            return await c.calls.owner_action(owner, call_id, action)

        return await run_idempotent(request, owner, c, go)

    endpoint.__name__ = action.value
    return endpoint


for _action in (OwnerActionType.TAKEOVER, OwnerActionType.CONTINUE, OwnerActionType.END):
    router.add_api_route(
        f"/{{call_id}}/{_action.value}",
        _owner_action(_action),
        methods=["POST"],
        response_model=OwnerActionResult,
        summary=f"Owner action: {_action.value}",
        description="409 `unsupported_by_provider` when the active telephony provider cannot do this; "
        "`CallDetail.capabilities` says which controls are real.",
    )


@router.post("/{call_id}/block", response_model=BlockedCaller)
async def block(
    call_id: CallId, request: Request, owner: Owner, c: Ctr, req: BlockRequest | None = None
) -> BlockedCaller | JSONResponse:
    async def go() -> BlockedCaller:
        return await c.calls.block(owner, call_id, req.reason if req else None)

    return await run_idempotent(request, owner, c, go, body=req)


@router.post("/{call_id}/trust", response_model=TrustedCaller)
async def trust(
    call_id: CallId, request: Request, owner: Owner, c: Ctr, req: TrustRequest | None = None
) -> TrustedCaller | JSONResponse:
    async def go() -> TrustedCaller:
        return await c.calls.trust(owner, call_id, req.label if req else None)

    return await run_idempotent(request, owner, c, go, body=req)


@router.post("/{call_id}/feedback", response_model=FeedbackRecord)
async def feedback(
    call_id: CallId, req: FeedbackRequest, request: Request, owner: Owner, c: Ctr
) -> FeedbackRecord | JSONResponse:
    """Idempotent per call and kind: repeating a kind updates the note of the existing record."""

    async def go() -> FeedbackRecord:
        return await c.calls.feedback(owner, call_id, req.kind, req.note)

    return await run_idempotent(request, owner, c, go, body=req)


@router.get("/{call_id}/events", response_model=list[LiveEvent])
async def events(call_id: CallId, owner: Owner, c: Ctr, after_seq: Annotated[int, Query(ge=0)] = 0) -> list[LiveEvent]:
    return await c.calls.events(owner, call_id, after_seq)


@router.get("/{call_id}/report")
async def diagnostic_report(call_id: CallId, owner: Owner, c: Ctr) -> JSONResponse:
    """Sanitised diagnostic report: identifiers, states, timings and codes. No transcript text or numbers."""
    await c.calls.record_access(owner, call_id, "call.report_downloaded")
    report = await c.calls.diagnostic_report(owner, call_id)
    return _download(report, f"sparta-report-{call_id}.json")


@router.get("/{call_id}/export")
async def export_call(call_id: CallId, owner: Owner, c: Ctr) -> JSONResponse:
    """Everything stored about one call (owner only). Includes the transcript while it is retained."""
    await c.calls.record_access(owner, call_id, "call.exported")
    detail = await c.calls.get_call(owner, call_id)
    events_ = await c.calls.events(owner, call_id, 0)
    payload = {
        "format_version": 1,
        "exported_at": c.clock.now().isoformat(),
        "call": detail.model_dump(mode="json"),
        "events": [e.model_dump(mode="json") for e in events_],
    }
    return _download(payload, f"sparta-call-{call_id}.json")


@router.delete("/{call_id}/content", status_code=204)
async def delete_content(call_id: CallId, owner: Owner, c: Ctr) -> Response:
    """Remove the transcript, translations, live events, summary, risk explanation, claims and any feedback notes.

    The call record stays (time, duration, status, final risk level and category, blocked/trusted flags).
    """
    await c.calls.delete_content(owner, call_id)
    return Response(status_code=204)


@router.delete("/{call_id}", status_code=204)
async def delete_call(call_id: CallId, owner: Owner, c: Ctr) -> Response:
    await c.calls.delete_call(owner, call_id)
    return Response(status_code=204)


@router.delete("", status_code=204)
async def delete_all(owner: Owner, c: Ctr) -> Response:
    """Remove all of the owner's call content (calls stay as records without transcripts)."""
    await c.calls.delete_all_content(owner)
    return Response(status_code=204)
