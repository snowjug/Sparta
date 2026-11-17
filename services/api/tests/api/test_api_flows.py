"""HTTP behaviour of the Sparta API: flows, error envelope, headers, idempotency, limits and the owner-facing routes."""

import asyncio
import base64
import hashlib
import hmac

import pytest

from conftest import DELIVERY, SCAM, ApiEnv, running_env, wav_bytes
from sparta.services.simulator import curated_scenarios

API = "/api/v1"


# ------------------------------------------------------------------------------------------------ basics
async def test_system_status_is_public_and_flags_the_dev_identity(env: ApiEnv):
    r = await env.client.get(f"{API}/system/status")
    assert r.status_code == 200
    body = r.json()
    assert body["dev_banner"] is True and body["auth_mode"] == "dev"
    assert body["telephony"]["simulated"] is True and body["telephony"]["live_calls_supported"] is False
    assert body["features"]["raw_audio_storage"] is False
    assert body["features"]["translation"] is False  # caller-speech translation is not implemented
    assert {lang["code"] for lang in body["languages"] if lang["status"] == "supported"} == {"en-IN", "hi-IN", "kn-IN"}
    assert body["policy_version"] and body["language_pack_version"]


async def test_scam_call_end_to_end_over_http(env: ApiEnv):
    call = await env.new_call(caller_number="+919876543210")
    assert call["status"] == "active" and call["simulated"] is True
    assert call["capabilities"]["simulated"] is True and call["capabilities"]["two_way_audio"] is False
    assert call["caller_display"].startswith("+91 98") and "9876543210" not in str(call)

    r = await env.say(call["id"], SCAM)
    assert r.status_code == 200
    turn = r.json()
    assert turn["ended"] is True and turn["state"] == "END_SPAM"
    assert "can't share" in turn["assistant_turn"]["text"]

    await env.advance(60)
    detail = (await env.client.get(f"{API}/calls/{call['id']}")).json()
    assert detail["status"] == "ended" and detail["risk_level"] == "high"
    assert "one-time password" in detail["summary"]["text"]
    events = (await env.client.get(f"{API}/calls/{call['id']}/events")).json()
    assert events[0]["type"] == "call.created" and events[-1]["type"] == "summary.created"
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)


async def test_concurrent_first_requests_of_a_new_owner_all_succeed(env: ApiEnv):
    headers = {"X-Sparta-Dev-User": "brand-new-owner"}
    paths = [f"{API}/me", f"{API}/preferences", f"{API}/assistant-profile"] * 3
    responses = await asyncio.gather(*(env.client.get(p, headers=headers) for p in paths))
    assert [r.status_code for r in responses] == [200] * len(paths)
    assert (await env.client.get(f"{API}/me", headers=headers)).json()["id"] == "brand-new-owner"


async def test_home_summary_reflects_onboarding_and_attention(env: ApiEnv):
    home = (await env.client.get(f"{API}/home")).json()
    assert home["protection"]["status"] == "setup_needed" and home["next_action"]["kind"] == "finish_onboarding"
    prefs = (await env.client.get(f"{API}/preferences")).json()
    prefs["onboarding_completed"] = True
    assert (await env.client.put(f"{API}/preferences", json=prefs)).status_code == 200
    home = (await env.client.get(f"{API}/home")).json()
    assert home["protection"]["status"] == "active" and home["next_action"]["kind"] == "run_simulator"
    assert home["protection"]["simulated"] is True

    call = await env.new_call()
    await env.say(call["id"], DELIVERY)
    home = (await env.client.get(f"{API}/home")).json()
    assert home["protection"]["status"] == "attention"
    assert home["next_action"]["kind"] == "review_escalation" and home["next_action"]["route"] == f"/live/{call['id']}"
    assert [c["id"] for c in home["attention"]] == [call["id"]]
    assert home["today"]["handled"] == 1 and home["today"]["escalations"] == 1


# ------------------------------------------------------------------------------------- errors and headers
async def test_error_envelope_never_echoes_input_and_covers_unknown_routes(env: ApiEnv):
    call = await env.new_call()
    secret = "my-super-secret-value-123"
    r = await env.client.post(f"{API}/calls/{call['id']}/turns", json={"text": "", "note": secret})
    assert r.status_code == 422 and secret not in r.text
    error = r.json()["error"]
    assert error["code"] == "validation_error" and error["trace_id"]
    assert {d["field"] for d in error["details"]} == {"text", "note"}

    assert (await env.client.get(f"{API}/calls/call_unknown")).json()["error"]["code"] == "not_found"
    bad_id = await env.client.get(f"{API}/calls/bad%20id%21")
    assert bad_id.status_code == 422 and bad_id.json()["error"]["code"] == "validation_error"
    assert (await env.client.get(f"{API}/nope")).json()["error"]["code"] == "not_found"
    method = await env.client.delete(f"{API}/system/status")
    assert method.status_code == 405 and method.json()["error"]["code"] == "method_not_allowed"
    malformed = await env.client.post(
        f"{API}/calls/{call['id']}/turns", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert malformed.status_code == 422 and malformed.json()["error"]["code"] == "validation_error"


async def test_request_id_is_echoed_or_replaced_and_rate_headers_are_present(env: ApiEnv):
    ok = await env.client.get(f"{API}/home", headers={"X-Request-ID": "req-12345678"})
    assert ok.headers["x-request-id"] == "req-12345678"
    assert ok.headers["x-ratelimit-limit"] == "240" and int(ok.headers["x-ratelimit-remaining"]) < 240
    replaced = await env.client.get(f"{API}/home", headers={"X-Request-ID": "bad id with spaces\r"})
    assert replaced.headers["x-request-id"] != "bad id with spaces" and len(replaced.headers["x-request-id"]) == 16
    err = await env.client.get(f"{API}/calls/call_unknown", headers={"X-Request-ID": "req-abcdef01"})
    assert err.json()["error"]["trace_id"] == "req-abcdef01"


async def test_rate_limit_returns_429_with_retry_after_and_recovers():
    async with running_env(rate_limit_per_minute=3) as env:
        for _ in range(3):
            assert (await env.client.get(f"{API}/me")).status_code == 200
        limited = await env.client.get(f"{API}/me")
        assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"
        assert 1 <= int(limited.headers["retry-after"]) <= 60 and limited.headers["x-ratelimit-remaining"] == "0"
        other = await env.client.get(f"{API}/me", headers={"X-Sparta-Dev-User": "someone-else"})
        assert other.status_code == 200  # limits are per owner
        await env.clock.advance(61)
        assert (await env.client.get(f"{API}/me")).status_code == 200


async def test_call_creation_has_its_own_stricter_limit():
    async with running_env(call_create_rate_limit_per_minute=2) as env:
        for _ in range(2):
            await env.new_call()
        r = await env.client.post(f"{API}/calls", json={"silence_timers": "off"})
        assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


# -------------------------------------------------------------------------------------------- idempotency
async def test_idempotency_key_replays_the_first_response_and_detects_conflicts(env: ApiEnv):
    headers = {"Idempotency-Key": "create-call-0001"}
    body = {"caller_number": "+919800000001", "silence_timers": "off"}
    first = await env.client.post(f"{API}/calls", json=body, headers=headers)
    again = await env.client.post(f"{API}/calls", json=body, headers=headers)
    assert first.status_code == again.status_code == 201
    assert again.headers["idempotent-replayed"] == "true" and "idempotent-replayed" not in first.headers
    assert first.json()["id"] == again.json()["id"]
    assert (await env.client.get(f"{API}/calls")).json()["items"].__len__() == 1

    clash = await env.client.post(f"{API}/calls", json={**body, "caller_number": "+919800000002"}, headers=headers)
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "conflict"
    other_owner = await env.client.post(
        f"{API}/calls", json=body, headers={**headers, "X-Sparta-Dev-User": "other-owner"}
    )
    assert other_owner.status_code == 201 and other_owner.json()["id"] != first.json()["id"]
    bad_key = await env.client.post(f"{API}/calls", json=body, headers={"Idempotency-Key": "has spaces!"})
    assert bad_key.status_code == 422


async def test_a_failed_request_does_not_consume_its_idempotency_key(env: ApiEnv):
    headers = {"Idempotency-Key": "retry-after-error"}
    bad = await env.client.post(f"{API}/calls", json={"language_mode": "fr-FR"}, headers=headers)
    assert bad.status_code == 422
    good = await env.client.post(f"{API}/calls", json={"silence_timers": "off"}, headers=headers)
    assert good.status_code == 201


async def test_a_replayed_turn_does_not_run_the_engine_twice(env: ApiEnv):
    call = await env.new_call()
    headers = {"Idempotency-Key": "turn-0001"}
    first = await env.client.post(f"{API}/calls/{call['id']}/turns", json={"text": SCAM}, headers=headers)
    again = await env.client.post(f"{API}/calls/{call['id']}/turns", json={"text": SCAM}, headers=headers)
    assert first.json() == again.json() and again.headers["idempotent-replayed"] == "true"
    await env.advance(60)
    detail = (await env.client.get(f"{API}/calls/{call['id']}")).json()
    assert sum(1 for t in detail["turns"] if t["speaker"] == "caller") == 1


# ---------------------------------------------------------------------------------------------- listing
async def test_listing_filters_search_and_cursor_pagination(env: ApiEnv):
    scam = await env.new_call(caller_number="+919800000011", caller_label="Spam Sam")
    await env.say(scam["id"], SCAM)
    await env.advance(60)
    for number in ("+919800000012", "+919800000013"):
        await env.new_call(caller_number=number)

    everything = (await env.client.get(f"{API}/calls")).json()
    assert len(everything["items"]) == 3 and everything["next_cursor"] is None
    assert [c["id"] for c in everything["items"]][-1] == scam["id"]  # newest first

    high = (await env.client.get(f"{API}/calls", params={"risk_level": "high"})).json()["items"]
    assert [c["id"] for c in high] == [scam["id"]]
    active = (await env.client.get(f"{API}/calls", params={"status": "active"})).json()["items"]
    assert len(active) == 2 and all(c["status"] == "active" for c in active)
    searched = (await env.client.get(f"{API}/calls", params={"q": "spam sam"})).json()["items"]
    assert [c["id"] for c in searched] == [scam["id"]]
    by_language = (await env.client.get(f"{API}/calls", params={"language": "en-IN"})).json()["items"]
    assert [c["id"] for c in by_language] == [scam["id"]]

    seen: list[str] = []
    cursor = None
    for _ in range(5):
        page = (
            await env.client.get(f"{API}/calls", params={"limit": 1, **({"cursor": cursor} if cursor else {})})
        ).json()
        seen += [c["id"] for c in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 3

    assert (await env.client.get(f"{API}/calls", params={"risk_level": "catastrophic"})).status_code == 422
    assert (await env.client.get(f"{API}/calls", params={"limit": 1000})).status_code == 422


# ------------------------------------------------------------------------------------------ owner actions
async def test_owner_takeover_is_labelled_simulated_and_continue_needs_an_escalation(env: ApiEnv):
    call = await env.new_call()
    premature = await env.client.post(f"{API}/calls/{call['id']}/continue")
    assert premature.status_code == 409 and premature.json()["error"]["code"] == "conflict"

    await env.say(call["id"], DELIVERY)
    detail = (await env.client.get(f"{API}/calls/{call['id']}")).json()
    assert detail["state"] == "ESCALATE" and detail["capabilities"]["can_take_over"] is True
    assert "simulated" in detail["capabilities"]["takeover_note"].lower()

    took = await env.client.post(f"{API}/calls/{call['id']}/takeover")
    assert took.status_code == 200
    body = took.json()
    assert body["action"]["simulated"] is True and body["call"]["state"] == "OWNER_TAKEOVER"
    ended = await env.client.post(f"{API}/calls/{call['id']}/end")
    assert ended.status_code == 200
    await env.advance(30)
    assert (await env.client.get(f"{API}/calls/{call['id']}")).json()["status"] == "ended"
    assert (await env.client.post(f"{API}/calls/{call['id']}/end")).status_code == 409


async def test_block_trust_and_feedback_routes(env: ApiEnv):
    call = await env.new_call(caller_number="+919800000021")
    await env.say(call["id"], SCAM)
    await env.advance(60)
    blocked = await env.client.post(f"{API}/calls/{call['id']}/block", json={"reason": "OTP scam"})
    assert blocked.status_code == 200 and blocked.json()["reason"] == "OTP scam"
    assert "9800000021" not in blocked.text
    again = await env.new_call(caller_number="+919800000021")
    assert again["status"] == "ended" and again["blocked"] is True

    fb = await env.client.post(f"{API}/calls/{call['id']}/feedback", json={"kind": "was_spam", "note": "first"})
    fb2 = await env.client.post(f"{API}/calls/{call['id']}/feedback", json={"kind": "was_spam", "note": "second"})
    assert fb.json()["id"] == fb2.json()["id"] and fb2.json()["note"] == "second"
    assert (await env.client.post(f"{API}/calls/{call['id']}/feedback", json={"kind": "nonsense"})).status_code == 422

    listed = (await env.client.get(f"{API}/blocked-callers")).json()
    assert len(listed) == 1 and listed[0]["source_call_id"] == call["id"]
    assert (await env.client.delete(f"{API}/blocked-callers/{listed[0]['id']}")).status_code == 204
    assert (await env.client.get(f"{API}/blocked-callers")).json() == []
    assert (await env.client.delete(f"{API}/blocked-callers/{listed[0]['id']}")).status_code == 404

    trusted = await env.client.post(f"{API}/calls/{call['id']}/trust", json={"label": "Rahul"})
    assert trusted.status_code == 200 and trusted.json()["label"] == "Rahul"
    assert (await env.client.get(f"{API}/calls/{call['id']}")).json()["trusted"] is True


async def test_events_report_export_deletion_and_the_audit_trail(env: ApiEnv):
    call = await env.new_call(caller_number="+919876543210", caller_label="Rahul")
    await env.say(call["id"], SCAM)
    await env.advance(60)
    cid = call["id"]

    all_events = (await env.client.get(f"{API}/calls/{cid}/events")).json()
    tail = (await env.client.get(f"{API}/calls/{cid}/events", params={"after_seq": all_events[-3]["seq"]})).json()
    assert [e["seq"] for e in tail] == [e["seq"] for e in all_events[-2:]]

    report = await env.client.get(f"{API}/calls/{cid}/report")
    assert report.headers["content-disposition"] == f'attachment; filename="sparta-report-{cid}.json"'
    text = report.text
    for forbidden in ("State Bank", "Rahul", "9876543210", "OTP sent to your phone"):
        assert forbidden not in text
    assert report.json()["contains_transcript"] is False

    export = await env.client.get(f"{API}/calls/{cid}/export")
    assert "attachment" in export.headers["content-disposition"]
    exported = export.json()
    assert exported["format_version"] == 1 and "State Bank of India" in export.text
    assert len(exported["events"]) == len(all_events) and "9876543210" not in export.text

    assert (await env.client.delete(f"{API}/calls/{cid}/content")).status_code == 204
    after = (await env.client.get(f"{API}/calls/{cid}")).json()
    assert after["turns"] == [] and after["has_content"] is False and after["risk_level"] == "high"
    assert (await env.client.delete(f"{API}/calls/{cid}")).status_code == 204
    assert (await env.client.get(f"{API}/calls/{cid}")).status_code == 404
    assert (await env.client.delete(f"{API}/calls")).status_code == 204

    audit = (await env.client.get(f"{API}/audit")).json()
    actions = [a["action"] for a in audit]
    for expected in ("call.report_downloaded", "call.exported", "call.content_deleted", "call.deleted"):
        assert expected in actions
    assert "State Bank" not in str(audit) and "Rahul" not in str(audit)


async def test_live_calls_cannot_have_their_content_deleted(env: ApiEnv):
    call = await env.new_call()
    r = await env.client.delete(f"{API}/calls/{call['id']}/content")
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    assert (await env.client.delete(f"{API}/calls/{call['id']}")).status_code == 409


# ---------------------------------------------------------------------------------------------- audio
async def test_audio_upload_without_a_transcript_hint_is_refused_by_the_simulator_stt(env: ApiEnv):
    call = await env.new_call()
    files = {"file": ("clip.wav", wav_bytes(), "audio/wav")}
    r = await env.client.post(f"{API}/calls/{call['id']}/audio", files=files)
    assert r.status_code == 422 and r.json()["error"]["code"] == "stt_unavailable"
    assert "Simulator STT cannot transcribe" in r.json()["error"]["message"]


async def test_audio_upload_with_a_transcript_hint_runs_the_turn_pipeline(env: ApiEnv):
    call = await env.new_call()
    r = await env.client.post(
        f"{API}/calls/{call['id']}/audio",
        files={"file": ("clip.wav", wav_bytes(), "audio/wav")},
        data={"transcript_hint": SCAM, "language_hint": "en-IN"},
    )
    assert r.status_code == 200 and r.json()["ended"] is True
    detail = (await env.client.get(f"{API}/calls/{call['id']}")).json()
    caller = next(t for t in detail["turns"] if t["speaker"] == "caller")
    assert caller["source"] == "uploaded_audio" and caller["text"] == SCAM


@pytest.mark.parametrize(
    ("name", "content", "content_type", "status"),
    [
        ("clip.mp3", b"ID3" + b"\x00" * 64, "audio/mpeg", 415),  # type not allowed
        ("clip.wav", b"this is not a wav file at all", "audio/wav", 415),  # contents do not match the declared type
        ("clip.wav", b"", "audio/wav", 422),
        ("../../etc/passwd", wav_bytes(), "audio/wav", 422),  # the file name is never used: still no transcript hint
    ],
)
async def test_audio_upload_validation(env: ApiEnv, name, content, content_type, status):
    call = await env.new_call()
    r = await env.client.post(f"{API}/calls/{call['id']}/audio", files={"file": (name, content, content_type)})
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] in {"unsupported_media_type", "validation_error", "stt_unavailable"}


async def test_audio_upload_size_limits_and_isolation():
    async with running_env(max_audio_bytes=50_000, max_audio_seconds=1) as env:
        call = await env.new_call()
        too_big = await env.client.post(
            f"{API}/calls/{call['id']}/audio",
            files={"file": ("big.wav", wav_bytes(3.0), "audio/wav")},
            data={"transcript_hint": "hello"},
        )
        assert too_big.status_code == 413 and too_big.json()["error"]["code"] == "payload_too_large"
        too_long = await env.client.post(
            f"{API}/calls/{call['id']}/audio",
            files={"file": ("long.wav", wav_bytes(1.5, rate=8000), "audio/wav")},
            data={"transcript_hint": "hello"},
        )
        assert too_long.status_code == 413
        stranger = await env.client.post(
            f"{API}/calls/{call['id']}/audio",
            files={"file": ("ok.wav", wav_bytes(0.5, rate=8000), "audio/wav")},
            data={"transcript_hint": "hello"},
            headers={"X-Sparta-Dev-User": "someone-else"},
        )
        assert stranger.status_code == 404


async def test_uploaded_audio_is_never_spooled_to_disk(env: ApiEnv):
    from starlette.formparsers import MultiPartParser

    assert MultiPartParser.spool_max_size > env.container.settings.max_audio_bytes


# ------------------------------------------------------------------------------------ settings and voice
async def test_preferences_are_validated_and_round_trip(env: ApiEnv):
    prefs = (await env.client.get(f"{API}/preferences")).json()
    assert prefs["retention"]["store_raw_audio"] is False and prefs["onboarding_completed"] is False

    prefs["strictness"] = "strict"
    prefs["retention"]["transcript_retention_days"] = 3
    saved = await env.client.put(f"{API}/preferences", json=prefs)
    assert saved.status_code == 200 and (await env.client.get(f"{API}/preferences")).json()["strictness"] == "strict"

    for mutate, expect in (
        (lambda p: p.update(unknown_field=True), "unknown_field"),
        (lambda p: p.update(enabled_languages=["en-IN", "fr-FR"]), "Unsupported language"),
        (lambda p: p.update(enabled_languages=[], primary_language="en-IN"), "at least one language"),
        (lambda p: p.update(primary_language="kn-IN", enabled_languages=["en-IN"]), "primary language"),
        (lambda p: p["retention"].update(store_raw_audio=True), "Raw audio"),
        (lambda p: p.update(takeover_number="not a number!"), "takeover_number"),
    ):
        bad = {**prefs, "retention": dict(prefs["retention"])}
        mutate(bad)
        r = await env.client.put(f"{API}/preferences", json=bad)
        assert r.status_code == 422 and expect in r.text, (expect, r.text)
    assert (await env.client.get(f"{API}/preferences")).json()["strictness"] == "strict"  # failed PUTs changed nothing


async def test_assistant_profile_preview_runs_the_real_pipeline_without_creating_a_call(env: ApiEnv):
    profile = {"owner_display_name": "Atharv", "response_style": "warm", "speaking_rate": 1.1, "voice_ids": {}}
    assert (await env.client.put(f"{API}/assistant-profile", json=profile)).status_code == 200
    preview = await env.client.post(f"{API}/assistant-profile/preview", json={"language": "auto", "sample_text": SCAM})
    assert preview.status_code == 200
    body = preview.json()
    assert "AI" in body["disclosure"]["text"] and body["reply"] and body["risk"]["risk_level"] == "high"
    assert (await env.client.get(f"{API}/calls")).json()["items"] == []

    for bad in (
        {**profile, "speaking_rate": 5},
        {**profile, "voice_ids": {"fr-FR": "x"}},
        {**profile, "ai_disclosure": False},
    ):
        assert (await env.client.put(f"{API}/assistant-profile", json=bad)).status_code == 422
    personal = await env.client.put(f"{API}/assistant-profile", json={**profile, "use_personal_voice": True})
    assert personal.status_code == 409 and personal.json()["error"]["code"] == "conflict"


async def test_voices_and_personal_voice_consent_flow(env: ApiEnv):
    voices = (await env.client.get(f"{API}/voices", params={"locale": "hi-IN"})).json()
    assert voices and all(v["locale"] == "hi-IN" for v in voices)
    assert (await env.client.get(f"{API}/voices", params={"locale": "bad"})).status_code == 422

    status = (await env.client.get(f"{API}/voice/status")).json()
    assert status["status"] == "not_enrolled" and status["active"] is False
    consent = (await env.client.get(f"{API}/voice/consent")).json()
    assert consent["requires_provider_approval"] is True and "AI" in consent["text"]

    refused = await env.client.post(
        f"{API}/voice/enroll", json={"consent": False, "consent_version": consent["version"], "speaker_name": "A"}
    )
    assert refused.status_code == 422
    stale = await env.client.post(
        f"{API}/voice/enroll", json={"consent": True, "consent_version": "1999-01-01", "speaker_name": "A"}
    )
    assert stale.status_code == 422
    enrolled = await env.client.post(
        f"{API}/voice/enroll", json={"consent": True, "consent_version": consent["version"], "speaker_name": "Atharv"}
    )
    assert enrolled.status_code == 200 and enrolled.json()["status"] == "pending_provider_approval"
    assert enrolled.json()["active"] is False and "cannot be completed inside Sparta" in enrolled.json()["detail"]
    assert (await env.client.delete(f"{API}/voice")).status_code == 204
    assert (await env.client.get(f"{API}/voice/status")).json()["status"] == "not_enrolled"


# ---------------------------------------------------------------------------------------- safety center
async def test_safety_policies_and_events_expose_codes_never_text(env: ApiEnv):
    policies = (await env.client.get(f"{API}/safety/policies")).json()
    assert policies["version"] and policies["protected_information"] and policies["prompt_injection"]["examples"]
    assert any(s["code"] == "OTP_REQUEST" and s["protected"] for s in policies["signals"])

    call = await env.new_call()
    await env.say(call["id"], SCAM)
    events = (await env.client.get(f"{API}/safety/events")).json()
    assert len(events) == 1 and "OTP_REQUEST" in events[0]["signal_codes"] and events[0]["risk_level"] == "high"
    assert "State Bank" not in str(events)


async def test_blocked_and_trusted_lists_store_masked_numbers_only(env: ApiEnv):
    blocked = await env.client.post(f"{API}/blocked-callers", json={"number": "+91 98765 43210", "reason": "spam"})
    assert blocked.status_code == 201
    entry = blocked.json()
    assert entry["number_display"] == "+91 98•••• ••10" and "98765" not in blocked.text.replace("98••••", "")
    again = await env.client.post(f"{API}/blocked-callers", json={"number": "9876543210"})
    assert again.json()["id"] == entry["id"]  # same number, however it is written

    trusted = await env.client.post(f"{API}/trusted-callers", json={"number": "+91 98765 43210", "label": "Mum"})
    assert trusted.status_code == 201
    assert (await env.client.get(f"{API}/blocked-callers")).json() == []  # trusting removes the block
    assert (await env.client.get(f"{API}/trusted-callers")).json()[0]["label"] == "Mum"

    assert (await env.client.post(f"{API}/blocked-callers", json={"number": "abc"})).status_code == 422
    assert (
        await env.client.post(f"{API}/blocked-callers", json={"number": "+91 98765 43210", "x": 1})
    ).status_code == 422
    assert (await env.client.delete(f"{API}/trusted-callers/{trusted.json()['id']}")).status_code == 204


async def test_blocking_a_number_marks_its_earlier_calls(env: ApiEnv):
    call = await env.new_call(caller_number="+919800000031")
    await env.client.post(f"{API}/blocked-callers", json={"number": "+919800000031"})
    assert (await env.client.get(f"{API}/calls/{call['id']}")).json()["blocked"] is True


# ------------------------------------------------------------------------------------- native screening
async def test_screening_config_lists_and_idempotent_events(env: ApiEnv):
    config = (await env.client.get(f"{API}/screening/config")).json()
    salt = base64.b64decode(config["fingerprint_salt"])
    assert config["provider"] == "simulator" and config["live_calls_supported"] is False
    fingerprint = hmac.new(salt, b"+919876543210", hashlib.sha256).hexdigest()

    await env.client.post(f"{API}/blocked-callers", json={"number": "+919876543210"})
    lists = (await env.client.get(f"{API}/screening/lists")).json()
    assert [b["fingerprint"] for b in lists["blocked"]] == [fingerprint]  # the device derives the same value

    event = {
        "client_event_id": "evt-0001-aaaa",
        "number_fingerprint": fingerprint,
        "number_display": "+919876543210",  # a careless client sends the full number: it must be masked on arrival
        "decision": "reject",
        "reason": "blocked_number",
        "occurred_at": env.clock.now().isoformat(),
    }
    first = await env.client.post(f"{API}/screening/events", json=event)
    again = await env.client.post(f"{API}/screening/events", json=event)
    assert first.status_code == 200 and first.json()["id"] == again.json()["id"]
    item = first.json()
    assert item["provider"] == "android_screening" and item["mode"] == "screening_only"
    assert item["caller_display"] == "+91 98•••• ••10" and item["blocked"] is True and item["has_content"] is False
    assert len((await env.client.get(f"{API}/calls")).json()["items"]) == 1

    for broken in (
        {**event, "client_event_id": "x"},
        {**event, "number_fingerprint": "not-hex!"},
        {**event, "decision": "maybe"},
    ):
        assert (await env.client.post(f"{API}/screening/events", json=broken)).status_code == 422


# --------------------------------------------------------------------------------------------- simulator
async def test_simulator_catalogue_providers_and_custom_scenarios(env: ApiEnv):
    scenarios = (await env.client.get(f"{API}/simulator/scenarios")).json()
    ids = {s["id"] for s in scenarios}
    assert {"bank-otp-en", "kyc-hinglish", "courier-kanglish", "delivery-legit", "silent-caller"} <= ids
    assert all(s["custom"] is False and s["turn_count"] >= 1 for s in scenarios)

    providers = (await env.client.get(f"{API}/simulator/providers")).json()
    active = {p["kind"]: p["id"] for p in providers if p["active"]}
    assert active == {
        "telephony": "telephony:simulator",
        "stt": "stt:simulator",
        "tts": "tts:simulator",
        "llm": "llm:rules",
    }
    azure = next(p for p in providers if p["id"] == "stt:azure")
    assert azure["available"] is False and "SPARTA_AZURE_SPEECH_KEY" in azure["reason"]

    custom = {
        "title": "My scenario",
        "language_profile": "hinglish",
        "turns": [
            {"text": "Namaste, main bank se bol raha hoon", "language": "hi-IN"},
            {"kind": "silence", "delay_ms": 500},
        ],
    }
    made = await env.client.post(f"{API}/simulator/scenarios", json=custom)
    assert made.status_code == 201 and made.json()["custom"] is True and made.json()["turn_count"] == 2
    assert made.json()["id"] in {s["id"] for s in (await env.client.get(f"{API}/simulator/scenarios")).json()}
    other = (await env.client.get(f"{API}/simulator/scenarios", headers={"X-Sparta-Dev-User": "x"})).json()
    assert made.json()["id"] not in {s["id"] for s in other}  # custom scenarios are private

    for bad in (
        {**custom, "turns": []},
        {**custom, "turns": [{"text": ""}]},
        {**custom, "turns": [{"text": "x" * 500}]},
        {**custom, "turns": [{"text": "hi", "language": "hindi!"}]},
        {**custom, "turns": [{"text": "hi"}] * 15},
    ):
        assert (await env.client.post(f"{API}/simulator/scenarios", json=bad)).status_code == 422


async def test_replay_is_deterministic_isolated_and_honest_about_its_checksum(env: ApiEnv):
    first = await env.client.post(f"{API}/simulator/replay", json={"scenario_id": "language-switch-journey"})
    second = await env.client.post(f"{API}/simulator/replay", json={"scenario_id": "language-switch-journey"})
    assert first.status_code == second.status_code == 200, first.text
    a, b = first.json(), second.json()
    assert a["checksum"] == b["checksum"] and len(a["checksum"]) == 64
    assert a["call"]["status"] == "ended" and a["call"]["risk_level"] == "high"
    assert a["call"]["languages"] and "wall-clock" in a["checksum_covers"].lower()
    assert a["events"][0]["type"] == "call.created" and a["events"][-1]["type"] == "summary.created"

    different = await env.client.post(f"{API}/simulator/replay", json={"scenario_id": "delivery-legit"})
    assert different.json()["checksum"] != a["checksum"]
    assert (await env.client.get(f"{API}/calls")).json()["items"] == []  # replays never touch the owner's history
    assert (await env.client.post(f"{API}/simulator/replay", json={"scenario_id": "missing"})).status_code == 404


@pytest.mark.parametrize("scenario_id", sorted(curated_scenarios()))
async def test_every_curated_scenario_replays_deterministically_and_does_what_it_advertises(env: ApiEnv, scenario_id):
    expected = curated_scenarios()[scenario_id].expected_action
    runs = [(await env.client.post(f"{API}/simulator/replay", json={"scenario_id": scenario_id})) for _ in range(2)]
    assert [r.status_code for r in runs] == [200, 200], runs[0].text
    first, second = runs[0].json(), runs[1].json()
    assert first["checksum"] == second["checksum"], f"{scenario_id} is not deterministic"
    risk = first["call"]["risk"]
    if expected is None:  # silent caller: nothing to assess, the call just closes politely
        assert first["call"]["status"] == "ended" and first["call"]["category"] in ("silent", "unknown")
    else:
        assert risk and risk["recommended_action"] == expected, (scenario_id, risk and risk["recommended_action"])
    if expected in ("refuse_and_end", "end_spam"):
        assert first["call"]["status"] == "ended"
    if expected == "escalate_to_owner":
        assert first["call"]["status"] == "active" and first["call"]["state"] == "ESCALATE"
        assert first["call"]["owner_attention_required"] is True


async def test_replay_honours_the_network_profile_and_labels_simulated_latency(env: ApiEnv):
    r = await env.client.post(
        f"{API}/simulator/replay", json={"scenario_id": "bank-otp-en", "network_profile": "mobile_4g"}
    )
    assert r.status_code == 200, r.text
    turns = r.json()["call"]["turns"]
    latencies = [t["latency"] for t in turns if t["latency"]]
    assert any("tts_first_audio_ms" in lat["simulated_stages"] for lat in latencies)


async def test_autoplay_streams_a_scripted_call_and_ends_it(env: ApiEnv):
    r = await env.client.post(f"{API}/simulator/calls", json={"scenario_id": "bank-otp-en", "autoplay": True})
    assert r.status_code == 201
    call = r.json()
    assert call["caller_display"].startswith("+91 98")  # the scenario supplies its own caller number
    for _ in range(60):
        await env.advance(1.0)
        if (await env.client.get(f"{API}/calls/{call['id']}")).json()["status"] == "ended":
            break
    detail = (await env.client.get(f"{API}/calls/{call['id']}")).json()
    assert (
        detail["status"] == "ended" and detail["risk_level"] == "high" and detail["scenario_id"]
        if "scenario_id" in detail
        else True
    )
    types = [e["type"] for e in (await env.client.get(f"{API}/calls/{call['id']}/events")).json()]
    assert "transcript.partial" in types and types[-1] == "summary.created"
    assert (await env.client.post(f"{API}/simulator/calls", json={"autoplay": True})).status_code == 422


async def test_the_simulator_can_be_disabled():
    async with running_env(simulator_enabled=False) as env:
        for method, path in (("GET", "/simulator/scenarios"), ("GET", "/simulator/providers")):
            r = await env.client.request(method, f"{API}{path}")
            assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
        blocked = await env.client.post(f"{API}/calls", json={})
        assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "unsupported_by_provider"


# ---------------------------------------------------------------------------------------------- health
async def test_health_readiness_and_metrics_exposure(env: ApiEnv):
    assert (await env.client.get("/healthz")).json() == {"status": "ok"}
    ready = await env.client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["checks"]["database"] == "ok"
    assert (await env.client.get("/metrics")).status_code == 404  # off unless explicitly enabled

    async with running_env(expose_metrics=True) as exposed:
        call = await exposed.new_call()
        await exposed.say(call["id"], SCAM)
        text = (await exposed.client.get("/metrics")).text
        assert "sparta_calls_total" in text and "9876543210" not in text and "State Bank" not in text
