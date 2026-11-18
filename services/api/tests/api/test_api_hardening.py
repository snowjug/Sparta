"""Hardening found by the security review: limits, retention of cached responses, and bounded background work."""

import hashlib
import json
from datetime import timedelta

import pytest
from call_harness import OWNER, Harness, running_container
from pydantic import SecretStr
from sqlalchemy import select

from conftest import SCAM, ApiEnv, running_env
from sparta.db import models as m
from sparta.services import retention
from sparta.services.views import ListNumberRequest

API = "/api/v1"


async def idempotency_rows(env: ApiEnv) -> list[m.IdempotencyRow]:
    async with env.container.db.uow() as repo:
        return list((await repo.s.scalars(select(m.IdempotencyRow))).all())


# ------------------------------------------------------------------------------------ profile saves
async def test_assistant_profile_saves_are_rate_limited_and_build_the_new_name_off_the_event_loop():
    async with running_env(profile_write_rate_limit_per_minute=3) as env:
        profile = (await env.client.get(f"{API}/assistant-profile")).json()
        profile["owner_display_name"] = "Zeenat Qureshi"
        first = await env.client.put(f"{API}/assistant-profile", json=profile)
        assert first.status_code == 200
        assert env.container.engine.is_warm("Zeenat Qureshi")  # built during the save, not on the first call
        assert (await env.client.put(f"{API}/assistant-profile", json=profile)).status_code == 200
        assert (await env.client.put(f"{API}/assistant-profile", json=profile)).status_code == 200
        blocked = await env.client.put(f"{API}/assistant-profile", json=profile)
        assert blocked.status_code == 429 and "retry-after" in blocked.headers
        assert (await env.client.get(f"{API}/assistant-profile")).status_code == 200  # reads are not limited here


async def test_creating_a_call_warms_the_owners_matchers():
    async with running_container() as c:
        assert not c.engine.is_warm(OWNER.display_name)
        await Harness(c).start(number="+919800000061")
        assert c.engine.is_warm(OWNER.display_name)


# -------------------------------------------------------------------------- cached request responses
async def test_cached_turn_responses_are_forgotten_with_the_calls_content(env: ApiEnv):
    call = await env.new_call(caller_number="+919876543210")
    key = {"Idempotency-Key": "turn-0001"}
    hello = await env.client.post(
        f"{API}/calls/{call['id']}/turns", json={"text": "Hello, I am calling about the water tank"}, headers=key
    )
    assert hello.status_code == 200
    assert [r.route for r in await idempotency_rows(env)] == [f"POST {API}/calls/{call['id']}/turns"]
    replay = await env.client.post(
        f"{API}/calls/{call['id']}/turns", json={"text": "Hello, I am calling about the water tank"}, headers=key
    )
    assert replay.headers["idempotent-replayed"] == "true"

    await env.say(call["id"], SCAM)
    await env.advance(60)
    assert (await env.client.delete(f"{API}/calls/{call['id']}/content")).status_code == 204
    assert await idempotency_rows(env) == []


async def end_call(env: ApiEnv, call_id: str) -> None:
    assert (await env.client.post(f"{API}/calls/{call_id}/end", json={})).status_code == 200
    await env.advance(60)


async def test_deleting_a_call_forgets_the_cached_response_that_created_it(env: ApiEnv):
    key = {"Idempotency-Key": "create-0001"}
    body = {"caller_number": "+919876543213", "silence_timers": "off"}
    created = await env.client.post(f"{API}/calls", json=body, headers=key)
    assert created.status_code == 201
    call_id = created.json()["id"]
    assert [r.call_id for r in await idempotency_rows(env)] == [call_id]
    again = await env.client.post(f"{API}/calls", json=body, headers=key)
    assert again.headers["idempotent-replayed"] == "true" and again.json()["id"] == call_id

    await end_call(env, call_id)
    assert (await env.client.delete(f"{API}/calls/{call_id}")).status_code == 204
    assert await idempotency_rows(env) == []
    fresh = await env.client.post(f"{API}/calls", json=body, headers=key)  # nothing replays the deleted call
    assert fresh.status_code == 201 and "idempotent-replayed" not in fresh.headers and fresh.json()["id"] != call_id


async def test_deleting_only_the_content_also_forgets_the_creation_response(env: ApiEnv):
    key = {"Idempotency-Key": "create-0002"}
    body = {"caller_number": "+919876543214", "silence_timers": "off"}
    call_id = (await env.client.post(f"{API}/calls", json=body, headers=key)).json()["id"]
    await end_call(env, call_id)
    assert (await env.client.delete(f"{API}/calls/{call_id}/content")).status_code == 204
    assert await idempotency_rows(env) == []


async def test_cached_turn_responses_are_short_lived(env: ApiEnv):
    call = await env.new_call(caller_number="+919876543211")
    await env.client.post(
        f"{API}/calls/{call['id']}/turns",
        json={"text": "Hello, calling about the tuition"},
        headers={"Idempotency-Key": "turn-0002"},
    )
    (row,) = await idempotency_rows(env)
    assert row.expires_at - row.created_at <= timedelta(minutes=15)


async def test_with_transcript_storage_off_the_cache_remembers_only_that_the_request_ran(env: ApiEnv):
    prefs = (await env.client.get(f"{API}/preferences")).json()
    prefs["retention"]["store_transcripts"] = False
    assert (await env.client.put(f"{API}/preferences", json=prefs)).status_code == 200
    call = await env.new_call(caller_number="+919876543212")
    body = {"text": "Hello, this is Rahul from State Bank"}
    key = {"Idempotency-Key": "turn-0003"}
    first = await env.client.post(f"{API}/calls/{call['id']}/turns", json=body, headers=key)
    assert first.status_code == 200
    (row,) = await idempotency_rows(env)
    assert row.status_code == 409 and "Rahul" not in str(row.response) and "State Bank" not in str(row.response)
    replay = await env.client.post(f"{API}/calls/{call['id']}/turns", json=body, headers=key)
    assert replay.status_code == 409 and replay.headers["idempotent-replayed"] == "true"


async def test_the_stored_request_fingerprint_cannot_confirm_a_guessed_phone_number():
    """It used to be a bare SHA-256 of route + body, so anyone who could read the table could test guessed numbers."""
    number = "+919876543210"
    route = f"POST {API}/blocked-callers"
    key = {"Idempotency-Key": "block-hash-0001"}
    unkeyed = hashlib.sha256(
        json.dumps(
            {"route": route, "body": ListNumberRequest(number=number).model_dump(mode="json")}, sort_keys=True
        ).encode()
    ).hexdigest()
    stored: list[str] = []
    for pepper in ("first-pepper-for-the-test", "second-pepper-for-the-test"):
        async with running_env(pepper=SecretStr(pepper)) as env:
            first = await env.client.post(f"{API}/blocked-callers", json={"number": number}, headers=key)
            assert first.status_code == 201
            (row,) = await idempotency_rows(env)
            assert row.request_hash != unkeyed
            stored.append(row.request_hash)
            replay = await env.client.post(f"{API}/blocked-callers", json={"number": number}, headers=key)
            assert replay.headers["idempotent-replayed"] == "true"  # the keyed fingerprint still identifies a retry
            other = await env.client.post(f"{API}/blocked-callers", json={"number": "+919876543299"}, headers=key)
            assert other.status_code == 409  # and still tells a different request apart
    assert stored[0] != stored[1]  # it depends on the pepper, which is not in the database


@pytest.mark.parametrize("kind", ["blocked", "trusted"])
async def test_removing_a_list_entry_forgets_the_cached_response_that_added_it(env: ApiEnv, kind: str):
    key = {"Idempotency-Key": f"{kind}-add-0001"}
    body = {"number": "+919876543211"}
    added = await env.client.post(f"{API}/{kind}-callers", json=body, headers=key)
    assert added.status_code == 201
    entry_id = added.json()["id"]
    assert (await env.client.post(f"{API}/{kind}-callers", json=body, headers=key)).headers["idempotent-replayed"]

    assert (await env.client.delete(f"{API}/{kind}-callers/{entry_id}")).status_code == 204
    assert await idempotency_rows(env) == []
    again = await env.client.post(f"{API}/{kind}-callers", json=body, headers=key)
    assert again.status_code == 201 and "idempotent-replayed" not in again.headers
    assert again.json()["id"] != entry_id  # a real new entry, not the removed one shown as present


# --------------------------------------------------------------------------------- screening events
async def test_screening_events_have_a_daily_cap_but_replays_still_succeed():
    async with running_env(daily_screening_event_cap=2) as env:

        def event(n: int) -> dict:
            return {
                "client_event_id": f"evt-cap-{n:04d}",
                "number_fingerprint": f"{n:064x}",
                "number_display": "+91 98•••• ••10",
                "decision": "silence",
                "reason": "unknown_caller",
                "occurred_at": env.clock.now().isoformat(),
            }

        assert (await env.client.post(f"{API}/screening/events", json=event(1))).status_code == 200
        assert (await env.client.post(f"{API}/screening/events", json=event(2))).status_code == 200
        over = await env.client.post(f"{API}/screening/events", json=event(3))
        assert over.status_code == 429 and int(over.headers["retry-after"]) >= 1
        assert (
            await env.client.post(f"{API}/screening/events", json=event(1))
        ).status_code == 200  # an idempotent replay


async def test_backdating_screening_events_does_not_get_around_the_daily_cap():
    """The cap counts what the server received today, not the time the client says the call happened."""
    async with running_env(daily_screening_event_cap=2) as env:

        def backdated(n: int) -> dict:
            return {
                "client_event_id": f"evt-old-{n:04d}",
                "number_fingerprint": f"{n:064x}",
                "number_display": "+91 98•••• ••10",
                "decision": "reject",
                "reason": "spam",
                "occurred_at": (env.clock.now() - timedelta(days=3)).isoformat(),
            }

        assert (await env.client.post(f"{API}/screening/events", json=backdated(1))).status_code == 200
        assert (await env.client.post(f"{API}/screening/events", json=backdated(2))).status_code == 200
        assert (await env.client.post(f"{API}/screening/events", json=backdated(3))).status_code == 429


# --------------------------------------------------------------------------------------- retention
async def test_a_retention_run_keeps_going_in_batches_until_the_backlog_is_gone(monkeypatch):
    monkeypatch.setattr(retention, "MAX_PER_USER_PER_BATCH", 2)
    async with running_container() as c:
        h = Harness(c)
        async with c.db.uow() as repo:
            await repo.ensure_user(OWNER.id, "Atharv", c.clock.now())
            prefs = await repo.get_preferences(OWNER.id)
            prefs.retention.transcript_retention_days = 1
            await repo.save_preferences(OWNER.id, prefs, c.clock.now())
        ids = []
        for n in range(5):
            created = await h.start(number=f"+91980000007{n}")
            await h.say(created.id, SCAM)
            await h.settle(created.id)
            ids.append(created.id)
        await c.clock.advance(timedelta(days=2).total_seconds())
        report = await c.retention.run_once()
        assert report.content_deleted == 5
        for call_id in ids:
            assert (await h.detail(call_id)).has_content is False
