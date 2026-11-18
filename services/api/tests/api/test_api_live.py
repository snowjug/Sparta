"""WebSocket live events: tickets, origins, snapshots, ordering, isolation, limits and keep-alives."""

import asyncio
import json

import pytest
import websockets
from websockets.exceptions import ConnectionClosed

from conftest import DELIVERY, SCAM, ApiEnv, LiveServer
from sparta.api.routers import live as live_router

API = "/api/v1"
ORIGIN = "http://localhost:3000"


async def ticket(env: ApiEnv, call_id: str | None = None, user: str | None = None) -> dict:
    headers = {"X-Sparta-Dev-User": user} if user else None
    r = await env.client.post(f"{API}/live/ticket", json={"call_id": call_id} if call_id else {}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def ws_url(live: LiveServer, path: str, tkt: str | None) -> str:
    return f"{live.ws_base}{path}" + (f"?ticket={tkt}" if tkt else "")


async def recv_json(ws, wait_s: float = 5.0) -> dict:  # type: ignore[no-untyped-def]
    return json.loads(await asyncio.wait_for(ws.recv(), wait_s))


async def close_code(ws, wait_s: float = 5.0) -> int:  # type: ignore[no-untyped-def]
    with pytest.raises(ConnectionClosed) as closed:
        await asyncio.wait_for(ws.recv(), wait_s)
    assert closed.value.rcvd is not None
    return int(closed.value.rcvd.code)


async def test_a_call_socket_starts_with_a_snapshot_then_streams_ordered_events(env: ApiEnv, live: LiveServer):
    call = await env.new_call(caller_number="+919876543210")
    t = await ticket(env, call["id"])
    assert t["expires_in"] == 60 and t["ws_url"].endswith(f"/api/v1/live/{call['id']}?ticket={t['ticket']}")
    async with websockets.connect(ws_url(live, f"/api/v1/live/{call['id']}", t["ticket"]), origin=ORIGIN) as ws:
        snapshot = await recv_json(ws)
        assert snapshot["type"] == "call.snapshot" and snapshot["data"]["call"]["id"] == call["id"]
        assert snapshot["simulated"] is True and len(snapshot["data"]["call"]["turns"]) == 1
        assert "9876543210" not in json.dumps(snapshot)

        await env.say(call["id"], SCAM)
        await env.advance(60)
        events: list[dict] = []
        while not events or events[-1]["type"] != "summary.created":
            events.append(await recv_json(ws))
    types = [e["type"] for e in events]
    for expected in ("transcript.final", "risk.updated", "assistant.speaking", "call.ended", "summary.created"):
        assert expected in types
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(set(seqs)) and seqs[0] > snapshot["seq"]  # strictly increasing, nothing replayed
    assert types.index("risk.updated") < types.index("call.ended")
    assert all(e["call_id"] == call["id"] for e in events)


async def test_events_published_before_connecting_are_not_replayed_but_are_in_the_snapshot(
    env: ApiEnv, live: LiveServer
):
    call = await env.new_call()
    await env.say(call["id"], DELIVERY)
    t = await ticket(env, call["id"])
    async with websockets.connect(ws_url(live, f"/api/v1/live/{call['id']}", t["ticket"]), origin=ORIGIN) as ws:
        snapshot = await recv_json(ws)
        assert snapshot["data"]["call"]["state"] == "ESCALATE" and snapshot["data"]["call"]["owner_attention_required"]
        stored = (await env.client.get(f"{API}/calls/{call['id']}/events")).json()
        assert snapshot["seq"] == stored[-1]["seq"]  # the snapshot already contains everything stored so far
        with pytest.raises(TimeoutError):
            await recv_json(ws, wait_s=0.4)


async def test_tickets_are_single_use_and_bound_to_their_owner_and_call(env: ApiEnv, live: LiveServer):
    mine = await env.new_call(user="owner-a")
    other = await env.new_call(user="owner-a")
    t = await ticket(env, mine["id"], user="owner-a")
    async with websockets.connect(ws_url(live, f"/api/v1/live/{mine['id']}", t["ticket"]), origin=ORIGIN) as ws:
        assert (await recv_json(ws))["type"] == "call.snapshot"
    async with websockets.connect(ws_url(live, f"/api/v1/live/{mine['id']}", t["ticket"]), origin=ORIGIN) as ws:
        assert await close_code(ws) == 4401  # the first attempt consumed it

    bound = await ticket(env, mine["id"], user="owner-a")
    async with websockets.connect(ws_url(live, f"/api/v1/live/{other['id']}", bound["ticket"]), origin=ORIGIN) as ws:
        assert await close_code(ws) == 4401  # a ticket for one call does not open another
    bound = await ticket(env, mine["id"], user="owner-a")
    async with websockets.connect(ws_url(live, "/api/v1/live", bound["ticket"]), origin=ORIGIN) as ws:
        assert await close_code(ws) == 4401  # nor the all-calls stream

    stolen = await env.client.post(
        f"{API}/live/ticket", json={"call_id": mine["id"]}, headers={"X-Sparta-Dev-User": "owner-b"}
    )
    assert stolen.status_code == 404  # another owner cannot even obtain a ticket for it
    b_ticket = await ticket(env, user="owner-b")
    async with websockets.connect(ws_url(live, f"/api/v1/live/{mine['id']}", b_ticket["ticket"]), origin=ORIGIN) as ws:
        assert await close_code(ws) == 4404  # and a valid ticket of theirs finds nothing at that call id


async def test_bad_origins_missing_tickets_and_unknown_calls_get_distinct_close_codes(env: ApiEnv, live: LiveServer):
    call = await env.new_call()
    t = await ticket(env, call["id"])
    async with websockets.connect(
        ws_url(live, f"/api/v1/live/{call['id']}", t["ticket"]), origin="http://evil.example"
    ) as ws:
        assert await close_code(ws) == 4403
    async with websockets.connect(ws_url(live, f"/api/v1/live/{call['id']}", None), origin=ORIGIN) as ws:
        assert await close_code(ws) == 4401
    async with websockets.connect(ws_url(live, f"/api/v1/live/{call['id']}", "not-a-real-ticket"), origin=ORIGIN) as ws:
        assert await close_code(ws) == 4401
    free = await ticket(env)
    async with websockets.connect(ws_url(live, "/api/v1/live/call_doesnotexist", free["ticket"]), origin=ORIGIN) as ws:
        assert await close_code(ws) == 4404
    # a native client sends no Origin header: it relies on the ticket alone
    t2 = await ticket(env, call["id"])
    async with websockets.connect(ws_url(live, f"/api/v1/live/{call['id']}", t2["ticket"])) as ws:
        assert (await recv_json(ws))["type"] == "call.snapshot"


async def test_an_unused_ticket_expires(env: ApiEnv, live: LiveServer):
    call = await env.new_call()
    t = await ticket(env, call["id"])
    await env.clock.advance(61)
    async with websockets.connect(ws_url(live, f"/api/v1/live/{call['id']}", t["ticket"]), origin=ORIGIN) as ws:
        assert await close_code(ws) == 4401


async def test_the_all_calls_stream_only_carries_the_owners_own_calls(env: ApiEnv, live: LiveServer):
    t = await ticket(env, user="owner-a")
    async with websockets.connect(ws_url(live, "/api/v1/live", t["ticket"]), origin=ORIGIN) as ws:
        await env.new_call(user="owner-b")  # someone else's call
        with pytest.raises(TimeoutError):
            await recv_json(ws, wait_s=0.4)
        mine = await env.new_call(user="owner-a")
        created = await recv_json(ws)
        assert created["type"] == "call.created" and created["data"]["call"]["id"] == mine["id"]
        assert "snapshot" not in created["type"]


async def test_the_number_of_sockets_per_owner_is_capped_and_released_on_disconnect(env: ApiEnv, live: LiveServer):
    env.container.hub._max_per_user = 2
    sockets = []
    try:
        for _ in range(2):
            t = await ticket(env)
            ws = await websockets.connect(ws_url(live, "/api/v1/live", t["ticket"]), origin=ORIGIN)
            sockets.append(ws)
        for _ in range(50):
            if env.container.hub.connection_count() == 2:
                break
            await asyncio.sleep(0.02)
        assert env.container.hub.connection_count() == 2
        t = await ticket(env)
        async with websockets.connect(ws_url(live, "/api/v1/live", t["ticket"]), origin=ORIGIN) as extra:
            assert await close_code(extra) == 4429
    finally:
        for ws in sockets:
            await ws.close()
    for _ in range(100):
        if env.container.hub.connection_count() == 0:
            break
        await asyncio.sleep(0.02)
    assert env.container.hub.connection_count() == 0


async def test_idle_connections_receive_ping_frames(env: ApiEnv, live: LiveServer, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(live_router, "PING_INTERVAL_S", 0.2)
    call = await env.new_call()
    t = await ticket(env, call["id"])
    async with websockets.connect(ws_url(live, f"/api/v1/live/{call['id']}", t["ticket"]), origin=ORIGIN) as ws:
        await recv_json(ws)  # snapshot
        assert await recv_json(ws, wait_s=3) == {"type": "ping"}


async def test_a_reader_that_falls_behind_is_told_to_resync_instead_of_blocking_calls(env: ApiEnv):
    hub = env.container.hub
    sub = hub.subscribe("owner-x", None)
    assert sub is not None
    from sparta.domain.models import LiveEvent

    for seq in range(1, 400):  # nobody is reading: the 256-slot queue overflows
        await hub.publish("owner-x", LiveEvent(type="transcript.partial", call_id="call_1", seq=seq))
    drained = []
    while not sub.queue.empty():
        drained.append(sub.queue.get_nowait())
    assert "stream.resync" in [e.type for e in drained]  # the backlog was replaced by a marker telling it to refetch
    assert drained[-1].seq == 399  # ...and the newest events still arrive after it
    assert len(drained) < 256  # the call-handling side never blocked or grew without bound
    hub.unsubscribe(sub)
