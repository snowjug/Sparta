"""The Asterisk provider over the real app: the dialplan's HTTP callbacks, the AudioSocket listener, the audio pipeline,
the safety engine and the call service, with tone-coded fake speech (see ``asterisk_kit.py``).

This is a CONTROLLED integration test, not a SIP test: the "caller" is a TCP client that speaks the AudioSocket wire format
as read from Asterisk's 22.12.0 sources, and the recogniser decodes tones, not speech. What it proves is Sparta's own
behaviour: authentication, single-use media binding, framing, pacing and cancellation, the call lifecycle and clean-up.
The real Asterisk, SIP and G.711 path is exercised by the Docker end-to-end test (``scripts/sip_e2e``).
"""

import asyncio
import base64
import logging
import re
from collections.abc import AsyncIterator

import pytest
from asterisk_kit import ASTERISK, OWNER, SECRET, Kit, basic

from conftest import ApiEnv, running_env
from sparta.observability.metrics import MEDIA_REJECTED, PROVIDER_LATENCY_MS
from sparta.providers.base import AudioChunk, ProviderMeta, ProviderUnavailable, SynthesisRequest
from sparta.providers.fake_tone import line_id_for
from sparta.providers.stt.fake_phrases import id_of
from sparta.telephony.asterisk.protocol import KIND_AUDIO, KIND_UUID, encode

API = "/api/v1"
INCOMING = f"{API}/webhooks/asterisk/incoming"
SCAM_ID = id_of("I'm calling from your bank. Tell me your OTP.")
DELIVERY_ID = 0  # "Hello, I am calling from Amazon delivery ..."
INTERRUPT_ID = 5  # "Yeah, I'm calling from Amazon."


def rejected(env: ApiEnv, reason: str) -> float:
    return env.container.metrics.counter(MEDIA_REJECTED, provider="asterisk", reason=reason)


# ---------------------------------------------------------------------------------------------- routes
async def test_the_asterisk_routes_do_not_exist_unless_asterisk_is_the_provider(env: ApiEnv):
    for path in ("incoming", "next", "ended"):
        reply = await env.client.post(f"{API}/webhooks/asterisk/{path}", content=b"channel=1.1", headers=basic())
        assert reply.status_code == 404


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer " + SECRET},
        {"Authorization": "Basic !!!not-base64!!!"},
        {"Authorization": "Basic " + base64.b64encode(b"no-colon-at-all").decode()},
        basic("not-the-secret-0123456789abcdef"),
        basic(SECRET[:-1]),
        basic(SECRET + "x"),
        basic(SECRET, user="root"),
        basic("", user=""),
    ],
)
async def test_a_callback_without_the_right_secret_is_refused_and_creates_nothing(headers):
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        for path in ("incoming", "next", "ended"):
            reply = await kit.post(path, {"channel": "1700000000.1", "caller": "6001", "exten": "6000"}, headers)
            assert reply.status_code == 401, (path, reply.text)
            assert "ACCEPT" not in reply.text
        assert await kit.calls() == []


async def test_a_callback_from_an_address_that_is_not_asterisk_is_refused_even_with_the_right_secret():
    async with running_env(**{**ASTERISK, "asterisk_media_peers": ["10.9.9.9"]}) as env, Kit(env) as kit:
        reply = await kit.incoming()
        assert reply.status_code == 401
        assert await kit.calls() == []


@pytest.mark.parametrize(
    "fields",
    [
        {"channel": "has space", "caller": "6001", "exten": "6000"},
        {"channel": "line\nbreak", "caller": "6001", "exten": "6000"},
        {"channel": "x" * 65, "caller": "6001", "exten": "6000"},
        {"channel": "", "caller": "6001", "exten": "6000"},
        {"caller": "6001", "exten": "6000"},
    ],
)
async def test_a_malformed_channel_id_is_a_validation_error_not_a_call(fields):
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        reply = await kit.post("incoming", fields)
        assert reply.status_code == 400
        assert await kit.calls() == []


async def test_a_body_that_is_not_form_data_or_has_too_many_fields_is_refused():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        assert (await kit.post("incoming", {}, content=b"\xff\xfe\x00bad")).status_code == 400
        many = "&".join(f"f{n}=1" for n in range(150)) + "&channel=1.1&exten=6000"
        assert (await kit.post("incoming", {}, content=many.encode())).status_code == 400
        assert await kit.calls() == []


async def test_only_the_sparta_extension_is_ever_answered():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        for exten in ("6001", "6002", "9", "00911234567890", "6000;DROP"):
            reply = await kit.incoming(exten=exten)
            assert reply.status_code == 200 and reply.text == "REJECT declined", (exten, reply.text)
        assert await kit.calls() == []


async def test_an_accepted_call_is_a_real_call_and_a_repeat_of_the_same_channel_is_the_same_call():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        channel, media_id = await kit.accept()
        assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", media_id)
        again = await kit.incoming(channel)
        assert again.text == f"ACCEPT {media_id}"  # a retry gets the same answer, never a second call
        call = await kit.only_call()
        assert call["provider"] == "asterisk" and call["simulated"] is False
        assert call["caller_display"] == "SIP 6001"
        assert (await kit.detail(call["id"]))["capabilities"]["takeover_via"] == "sip_extension"


@pytest.mark.parametrize(
    ("caller", "shown"), [("6001", "SIP 6001"), ("6001;rm -rf", "Local SIP caller"), ("", "Local SIP caller")]
)
async def test_the_caller_label_comes_only_from_a_plain_extension(caller, shown):
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        await kit.accept(caller=caller)
        assert (await kit.only_call())["caller_display"] == shown


@pytest.mark.parametrize("limit", [{"max_active_calls": 1}, {"daily_call_cap": 1}])
async def test_calls_over_a_limit_are_refused_as_busy_and_never_answered(limit):
    async with running_env(**ASTERISK, **limit) as env, Kit(env) as kit:
        await kit.accept()
        second = await kit.incoming()
        assert second.text == "REJECT busy"
        assert len(await kit.calls()) == 1


# ---------------------------------------------------------------------------------------- media binding
async def test_the_media_id_can_be_used_once_and_a_second_stream_cannot_replace_the_live_one():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        _channel, media_id = await kit.accept()
        live = await kit.connect(media_id)
        await live.wait_lines(1)
        intruder = await kit.connect(media_id)  # the same id again: a replay, or someone who saw it on the wire
        assert await intruder.wait_closed(3)
        assert rejected(env, "already_used") == 1
        # the legitimate stream is untouched: still connected, still heard, still able to talk
        assert not live.eof.is_set()
        await live.say(DELIVERY_ID)
        await live.wait_lines(2)
        assert (await kit.only_call())["status"] == "active"


async def test_a_guessed_or_unknown_media_id_gets_nothing():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        _, media_id = await kit.accept()
        for guess in ("00000000-0000-4000-8000-000000000000", "12345678-1234-4234-8234-123456789abc"):
            stranger = await kit.connect(guess)
            assert await stranger.wait_closed(3)
            assert stranger.rx == b""
        assert rejected(env, "unknown_id") == 2
        real = await kit.connect(media_id)  # the guesses did not burn the real id
        await real.wait_lines(1)


async def test_garbage_before_the_media_id_is_refused_and_does_not_consume_it():
    async with running_env(**{**ASTERISK, "asterisk_handshake_timeout_s": 0.2}) as env, Kit(env) as kit:
        _, media_id = await kit.accept()
        mute = await kit.connect(None)  # connects and says nothing
        assert await mute.wait_closed(3)
        audio_first = await kit.connect(None)
        await audio_first.send_raw(encode(KIND_AUDIO, b"\x01\x02"))
        assert await audio_first.wait_closed(3)
        assert rejected(env, "handshake_timeout") == 1 and rejected(env, "first_message_not_id") == 1
        real = await kit.connect(media_id)
        await real.wait_lines(1)


async def test_a_call_whose_media_never_connects_is_ended_and_its_id_dies_with_it():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        _channel, media_id = await kit.accept()
        call = await kit.only_call()
        await env.advance(11)  # past the claim time-to-live
        assert (await kit.detail(call["id"]))["status"] != "active"
        late = await kit.connect(media_id)
        assert await late.wait_closed(3)
        assert late.rx == b""
        assert rejected(env, "never_connected") == 1
        assert kit.provider._calls == {} and kit.provider._by_media_id == {}


async def test_a_call_that_ends_before_asterisk_connects_cannot_be_connected_afterwards():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        channel, media_id = await kit.accept()
        await kit.ended(channel)  # the caller hung up before the dialplan reached AudioSocket
        call = await kit.only_call()
        await kit.until_ended(call["id"])
        late = await kit.connect(media_id)
        assert await late.wait_closed(3)
        assert late.rx == b""


# ---------------------------------------------------------------------------------- the conversation
async def test_the_assistant_greets_first_and_the_greeting_is_real_audio_at_8_khz():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        channel, peer = await kit.call()
        state = kit.provider._by_channel[channel]
        await kit.until(lambda: state.quiet.is_set() and not state.playbacks, "the greeting to finish playing")
        call = await kit.only_call()
        speaker, opening = (await kit.transcript(call["id"]))[0]
        assert speaker == "assistant"
        assert "AI call assistant" in opening and "who's calling" in opening
        assert peer.lines()[0][1] == line_id_for(opening)  # the burst of that very line, intact after framing
        assert len(peer.rx) % 320 == 0  # whole 20 ms frames only
        assert peer.audible_ms() >= 3000  # a real line's worth of audio (about four seconds), not a click
        samples = env.container.metrics
        for stage in ("tts_first_audio", "media_connect"):
            assert samples.samples(PROVIDER_LATENCY_MS, provider="asterisk", stage=stage), stage


async def test_a_scam_request_is_refused_by_voice_and_the_call_ends_cleanly():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        _, peer = await kit.call()
        await peer.say(SCAM_ID)
        await peer.wait_lines(2)
        assert await peer.wait_closed()  # after the refusal Sparta hangs up on the media socket
        call = await kit.only_call()
        ended = await kit.until_ended(call["id"])
        assert ended["risk_level"] == "high" and ended["action_taken"] == "refused_and_ended"
        said = [text for speaker, text in await kit.transcript(call["id"]) if speaker == "assistant"]
        assert len(said) == 2 and not any(re.search(r"\d{4,}", text) for text in said)
        assert ended["summary_text"]
        assert kit.provider._calls == {} and kit.provider._by_channel == {}  # nothing left behind


async def test_a_legitimate_caller_is_answered_and_the_caller_hanging_up_completes_the_call():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        channel, peer = await kit.call()
        await peer.say(DELIVERY_ID)
        await peer.wait_lines(2)
        call = await kit.only_call()
        assert call["status"] == "active" and call["risk_level"] != "high"
        await peer.close()  # the caller hangs up: Asterisk closes the media socket
        ended = await kit.until_ended(call["id"])
        assert ended["status"] == "ended" and ended["summary_text"]
        assert kit.provider._calls == {}
        assert (await kit.ended(channel)).text == "OK"  # the dialplan's report arrives late and changes nothing


async def test_a_caller_who_talks_over_the_assistant_stops_it_within_a_few_frames():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        channel, media_id = await kit.accept()
        peer = await kit.connect(media_id)
        state = kit.provider._by_channel[channel]
        await kit.until(lambda: len(peer.rx) >= 320 * 25, "half a second of the greeting")
        kit.media_running.clear()  # freeze virtual time part-way through the line
        await asyncio.sleep(0.05)
        await peer.say(INTERRUPT_ID)  # "Yeah, I'm calling from Amazon." while the assistant is still talking
        await kit.until(lambda: not state.playbacks, "the assistant to stop talking")
        stopped_at = len(peer.rx)
        kit.media_running.set()
        await peer.wait_lines(2)  # it listened and answered the interruption
        first_line_ms = peer.lines()[1][0]
        assert first_line_ms < 1500, "the greeting should have been cut, not played to its end (about four seconds)"
        # what was already on the wire when the caller spoke is all that could not be recalled
        assert stopped_at - 320 * 25 <= 320 * 30
        call = await kit.only_call()
        assert [s for s, _ in await kit.transcript(call["id"])][:2] == ["assistant", "caller"]


async def test_dtmf_digits_are_received_and_never_acted_on():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        _, peer = await kit.call()
        await peer.dtmf("1234#")
        await asyncio.sleep(0.1)
        call = await kit.only_call()
        assert call["status"] == "active"
        assert [s for s, _ in await kit.transcript(call["id"])] == ["assistant"]  # no turn, no menu


@pytest.mark.parametrize(
    ("garbage", "reason"),
    [
        (encode(KIND_AUDIO, b"\x01\x02\x03"), "bad_audio"),
        (encode(0x7F, b"?"), "unexpected_message"),
        (encode(KIND_UUID, bytes(16)), "unexpected_message"),
        (b"\x10\x10\x01" + bytes(4100), "oversized"),
    ],
)
async def test_malformed_audio_ends_the_call_instead_of_corrupting_it(garbage, reason):
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        _, peer = await kit.call()
        await peer.send_raw(garbage)
        assert await peer.wait_closed()
        call = await kit.only_call()
        await kit.until_ended(call["id"])
        assert rejected(env, reason) == 1
        assert kit.provider._calls == {}


async def test_a_media_connection_that_goes_silent_is_closed_and_the_call_ends():
    async with running_env(**{**ASTERISK, "asterisk_idle_timeout_s": 0.3}) as env, Kit(env) as kit:
        _, peer = await kit.call()
        assert await peer.wait_closed(5)
        call = await kit.only_call()
        await kit.until_ended(call["id"])
        assert kit.provider._calls == {}


async def test_a_caller_who_hangs_up_mid_sentence_leaves_nothing_running(caplog):
    caplog.set_level(logging.WARNING)
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        _channel, media_id = await kit.accept()
        peer = await kit.connect(media_id)
        await kit.until(lambda: len(peer.rx) >= 320 * 10, "the greeting to start")
        kit.media_running.clear()
        await peer.close()
        await asyncio.sleep(0.05)
        kit.media_running.set()
        call = await kit.only_call()
        await kit.until_ended(call["id"])
        assert kit.provider._calls == {} and kit.provider._by_media_id == {}
        assert not [r for r in caplog.records if "playback failed" in r.getMessage()]


async def test_two_calls_at_once_stay_apart():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        _, first = await kit.call()
        _, second = await kit.call()
        await first.say(SCAM_ID)
        await first.wait_lines(2)
        assert await first.wait_closed()
        assert not second.eof.is_set()  # the other caller's call is untouched
        by_risk = sorted((c["status"], c["risk_level"]) for c in await kit.calls())
        assert ("active", "unknown") in by_risk and any(risk == "high" for _, risk in by_risk)


# ----------------------------------------------------------------------------- owner actions / takeover
async def test_take_over_rings_the_owner_sip_extension_and_nothing_else():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        channel, peer = await kit.call()
        call = await kit.only_call()
        caps = (await kit.detail(call["id"]))["capabilities"]
        assert caps["can_take_over"] and caps["takeover_via"] == "sip_extension"
        assert caps["two_way_audio"] is True
        assert "6002" in caps["takeover_note"] and "phone number" in caps["takeover_note"]
        took = await kit.owner_action(call["id"], "takeover")
        assert took.status_code == 200, took.text
        await peer.wait_lines(2)  # the hand-over announcement is heard before the line is handed over
        assert await peer.wait_closed()
        assert await kit.next_step(channel) == "DIAL 6002"
        assert await kit.next_step(channel) == "HANGUP"  # asking again must never dial twice
        assert (await kit.ended(channel, "ANSWER")).text == "OK"
        assert (await kit.until_ended(call["id"]))["status"] != "active"
        assert (await kit.ended(channel, "ANSWER")).status_code == 200  # idempotent


async def test_a_takeover_the_owner_does_not_answer_is_reported_and_the_call_still_ends():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        channel, peer = await kit.call()
        call = await kit.only_call()
        assert (await kit.owner_action(call["id"], "takeover")).status_code == 200
        assert await peer.wait_closed()
        assert await kit.next_step(channel) == "DIAL 6002"
        await kit.ended(channel, "NOANSWER")
        await kit.until_ended(call["id"])
        events = (await env.client.get(f"{API}/calls/{call['id']}/events", headers=OWNER)).json()
        assert any("owner's extension was not reached" in str(e) for e in events)


async def test_ending_the_call_from_the_owner_side_hangs_up_on_the_media_socket():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        channel, peer = await kit.call()
        call = await kit.only_call()
        assert (await kit.owner_action(call["id"], "end")).status_code == 200
        assert await peer.wait_closed()
        assert await kit.next_step(channel) == "HANGUP"
        await kit.until_ended(call["id"])
        assert kit.provider._calls == {}


async def test_the_dialplan_follow_ups_for_unknown_calls_do_nothing():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        assert await kit.next_step("9999999999.9") == "HANGUP"
        assert (await kit.ended("9999999999.9", "ANSWER")).text == "OK"
        assert (await kit.ended("not a channel!!", "weird status")).text == "OK"
        assert await kit.calls() == []


# ------------------------------------------------------------------------------------ provider failure
class BrokenTts:
    meta = ProviderMeta("broken-tts", simulated=False)

    async def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[AudioChunk]:
        raise ProviderUnavailable("broken-tts", "tts", "the voice service is down")
        yield  # pragma: no cover

    async def stop_playback(self, playback_id: str) -> None:
        return None

    async def list_voices(self, locale: str | None = None) -> list[object]:
        return []


async def test_a_voice_that_cannot_speak_ends_the_call_instead_of_leaving_it_in_silence():
    async with running_env(**{**ASTERISK, "provider_failure_limit": 1}) as env, Kit(env) as kit:
        kit.provider._tts = BrokenTts()  # type: ignore[assignment]
        _, media_id = await kit.accept()
        await kit.connect(media_id)
        call = await kit.only_call()
        ended = await kit.until_ended(call["id"])
        assert ended["status"] != "active"
        assert kit.provider._calls == {}


async def test_the_provider_reports_what_it_is_honestly(env: ApiEnv):
    async with running_env(**ASTERISK) as asterisk_env:
        status = (await asterisk_env.client.get(f"{API}/system/status", headers=OWNER)).json()
        telephony = status["telephony"]
        assert telephony["provider"] == "asterisk" and telephony["simulated"] is False
        assert telephony["connection"] == "local_sip" and telephony["pstn"] == "not_configured"
        assert telephony["takeover"] == "sip_extension"
        assert "PSTN" in telephony["note"] and "cannot reach Sparta" in telephony["note"]
        home = (await asterisk_env.client.get(f"{API}/home", headers=OWNER)).json()["protection"]
        assert home["connection"] == "local_sip" and home["pstn"] == "not_configured"
    simulated = (await env.client.get(f"{API}/system/status")).json()["telephony"]
    assert simulated["connection"] == "simulated" and simulated["pstn"] == "not_applicable"


async def test_closing_the_app_ends_every_open_call_and_connection():
    async with running_env(**ASTERISK) as env, Kit(env) as kit:
        _, peer = await kit.call()
        await env.container.providers.aclose()
        assert await peer.wait_closed(5)
        assert kit.provider._calls == {}
