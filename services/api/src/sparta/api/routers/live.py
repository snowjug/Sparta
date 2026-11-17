"""Live events over WebSocket, authenticated with single-use tickets.

Browsers cannot attach an ``Authorization`` header to a WebSocket upgrade, so the client first POSTs ``/live/ticket``
(authenticated normally) and then connects with the returned one-time ticket. A ticket is bound to the owner (and to a
call when requested), expires in about a minute and is consumed by the first connection attempt.

Close codes: 4401 bad/expired ticket - 4403 origin not allowed - 4404 call not found - 4429 too many connections.
"""

import asyncio
import contextlib
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Body, Path, Query, WebSocket
from pydantic import Field
from starlette.websockets import WebSocketDisconnect, WebSocketState

from sparta.api.deps import CALL_ID_PATTERN, Ctr, Owner, get_container
from sparta.api.errors import ERROR_RESPONSES
from sparta.domain.models import SpartaModel, StrictInputModel
from sparta.services.dto import Principal
from sparta.services.errors import NotFound
from sparta.services.live import TICKET_TTL_S, Subscription

log = logging.getLogger("sparta.live")
router = APIRouter(tags=["live"])
PING_INTERVAL_S = 20.0
MAX_CONNECTION_S = 3600.0  # forces a periodic fresh ticket, so a revoked owner is not served indefinitely
OK, BAD_TICKET, BAD_ORIGIN, NOT_FOUND, TOO_MANY = 1000, 4401, 4403, 4404, 4429


class TicketRequest(StrictInputModel):
    call_id: str | None = Field(default=None, max_length=64, pattern=CALL_ID_PATTERN)


class TicketResponse(SpartaModel):
    ticket: str
    expires_in: int
    ws_url: str = Field(description="Complete WebSocket URL including the ticket; clients may also build it themselves")


def _ws_base(public_base_url: str) -> str:
    base = public_base_url.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base.removeprefix("https://")
    return "ws://" + base.removeprefix("http://")


@router.post("/live/ticket", response_model=TicketResponse, responses=ERROR_RESPONSES)
async def live_ticket(owner: Owner, c: Ctr, req: Annotated[TicketRequest | None, Body()] = None) -> TicketResponse:
    """A single-use WebSocket ticket for all of the owner's calls, or for one call (`call_id`)."""
    call_id = req.call_id if req else None
    if call_id:
        await c.calls.assert_owner(owner, call_id)
    ticket = await c.hub.issue_ticket(owner.id, call_id)
    path = f"/api/v1/live/{call_id}" if call_id else "/api/v1/live"
    return TicketResponse(
        ticket=ticket,
        expires_in=TICKET_TTL_S,
        ws_url=f"{_ws_base(c.settings.public_base_url)}{path}?ticket={ticket}",
    )


async def _close(ws: WebSocket, code: int) -> None:
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await ws.close(code=code)


async def _drain(ws: WebSocket) -> None:
    """Consume (and ignore) anything the client sends so a disconnect is noticed promptly."""
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            return


async def _serve(ws: WebSocket, ticket: str | None, path_call_id: str | None) -> None:
    c = get_container(ws)
    await ws.accept()  # accept first: only an accepted socket can carry an application close code
    origin = ws.headers.get("origin")
    if origin is not None and origin not in c.settings.ws_origins:
        await _close(ws, BAD_ORIGIN)
        return
    redeemed = await c.hub.redeem_ticket(ticket) if ticket else None
    if redeemed is None:
        await _close(ws, BAD_TICKET)
        return
    user_id, bound_call = redeemed
    if bound_call is not None and bound_call != path_call_id:
        await _close(ws, BAD_TICKET)
        return
    principal = Principal(id=user_id)
    sub = c.hub.subscribe(user_id, path_call_id)  # subscribe before the snapshot so nothing is missed in between
    if sub is None:
        await _close(ws, TOO_MANY)
        return
    reader: asyncio.Task[None] | None = None
    try:
        snapshot_seq = -1
        if path_call_id is not None:
            try:
                snapshot = await c.calls.snapshot_event(principal, path_call_id)
            except NotFound:
                await _close(ws, NOT_FOUND)
                return
            snapshot_seq = snapshot.seq
            await ws.send_text(snapshot.model_dump_json())
        reader = asyncio.create_task(_drain(ws))
        await _stream(ws, sub, reader, path_call_id, snapshot_seq)
    except (WebSocketDisconnect, RuntimeError):
        pass  # the client went away mid-send
    finally:
        c.hub.unsubscribe(sub)
        if reader is not None:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await reader
        if ws.application_state is not WebSocketState.DISCONNECTED:
            await _close(ws, OK)


async def _stream(
    ws: WebSocket, sub: Subscription, reader: asyncio.Task[None], call_id: str | None, snapshot_seq: int
) -> None:
    deadline = time.monotonic() + MAX_CONNECTION_S
    while time.monotonic() < deadline:
        getter = asyncio.ensure_future(sub.queue.get())
        done, _ = await asyncio.wait({getter, reader}, timeout=PING_INTERVAL_S, return_when=asyncio.FIRST_COMPLETED)
        if reader in done:
            getter.cancel()
            return
        if getter not in done:
            getter.cancel()
            await ws.send_text('{"type":"ping"}')
            continue
        event = getter.result()
        if event is None:
            return
        if call_id is not None and event.call_id == call_id and 0 <= event.seq <= snapshot_seq:
            continue  # already contained in the snapshot
        await ws.send_text(event.model_dump_json())


@router.websocket("/live")
async def live_all(ws: WebSocket, ticket: Annotated[str | None, Query(max_length=128)] = None) -> None:
    """All of the owner's calls (`call.created`, risk and state changes ...)."""
    await _serve(ws, ticket, None)


@router.websocket("/live/{call_id}")
async def live_call(
    ws: WebSocket,
    call_id: Annotated[str, Path(pattern=CALL_ID_PATTERN)],
    ticket: Annotated[str | None, Query(max_length=128)] = None,
) -> None:
    """One call: starts with `call.snapshot`, then every event with a higher `seq`."""
    await _serve(ws, ticket, call_id)
