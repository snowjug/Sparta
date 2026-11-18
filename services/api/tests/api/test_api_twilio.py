"""Twilio webhooks and the media socket, over the real app. The Twilio REST API and the synthesiser are faked: nothing
here talks to Twilio, and it says nothing about how a real Twilio account behaves."""

import asyncio
import base64
import dataclasses
import json
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from urllib.parse import urlencode

import httpx
import pytest
import websockets

from conftest import ApiEnv, running_env, serving
from sparta.providers.base import AudioChunk, ProviderMeta, SynthesisRequest
from sparta.telephony.twilio import STATUS_PATH, VOICE_PATH, TwilioTelephonyProvider, stream_token, twilio_signature

API = "/api/v1"
AC_SID = "AC" + "fedcba9876543210" * 2
TOKEN = "twilio-auth-token-for-tests"
BASE = "https://sparta.example.test"
SID = "CA" + "0123456789abcdef" * 2
SID2 = "CA" + "abcdef0123456789" * 2
STREAM = "MZ" + "00112233445566778899aabbccddeeff"
CALLER, CALLED = "+919876543210", "+14155550199"
PHONE_OWNER = {"X-Sparta-Dev-User": "phone-owner"}
TWILIO = {
    "telephony_provider": "twilio",
    "twilio_account_sid": AC_SID,
    "twilio_auth_token": TOKEN,
    "twilio_callback_base_url": BASE,
    "telephony_owner_user_id": "phone-owner",
}


def fields_for(sid: str = SID, **extra: str) -> dict[str, str]:
    return {"CallSid": sid, "From": CALLER, "To": CALLED, "AccountSid": AC_SID, "CallStatus": "ringing", **extra}


class FakeRest:
    def __init__(self) -> None:
        self.hangups: list[str] = []
        self.redirects: list[tuple[str, str]] = []

    async def hang_up(self, call_sid: str) -> None:
        self.hangups.append(call_sid)

    async def redirect(self, call_sid: str, twiml: str) -> None:
        self.redirects.append((call_sid, twiml))


class SpokenTts:
    """A synthesiser that is not simulated: one 40 ms mu-law chunk per request."""

    meta = ProviderMeta("api-test-tts", simulated=False)

    async def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[AudioChunk]:
        assert request.output_format == "mulaw_8k"
        yield AudioChunk(b"\x7f" * 320, 8000, "mulaw", 0, final=True)

    async def stop_playback(self, playback_id: str) -> None:
        return None

    async def list_voices(self, locale: str | None = None) -> list[object]:
        return []


class Kit:
    def __init__(self, env: ApiEnv, *, speak: bool = False) -> None:
        self.env = env
        provider = env.container.providers.telephony
        assert isinstance(provider, TwilioTelephonyProvider)
        self.provider = provider
        self.rest = FakeRest()
        provider._client = self.rest  # no real Twilio calls
        if speak:
            provider._tts = SpokenTts()  # type: ignore[assignment]
            provider.capabilities = dataclasses.replace(provider.capabilities, can_play_audio=True)

    def signed(
        self, path: str, fields: dict[str, str], *, token: str = TOKEN, url: str | None = None
    ) -> tuple[bytes, dict[str, str]]:
        signature = twilio_signature(token, url or f"{BASE}{path}", list(fields.items()))
        return urlencode(fields).encode(), {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": signature,
        }

    async def post(self, path: str, fields: dict[str, str], **kwargs: object) -> httpx.Response:
        body, headers = self.signed(path, fields, **kwargs)  # type: ignore[arg-type]
        return await self.env.client.post(path, content=body, headers=headers)

    async def voice(self, sid: str = SID, **extra: str) -> httpx.Response:
        return await self.post(VOICE_PATH, fields_for(sid, **extra))

    async def status(self, sid: str, status: str) -> httpx.Response:
        return await self.post(STATUS_PATH, {"CallSid": sid, "CallStatus": status, "AccountSid": AC_SID})


async def phone_calls(env: ApiEnv) -> list[dict]:
    return (await env.client.get(f"{API}/calls", headers=PHONE_OWNER)).json()["items"]


def twiml(response: httpx.Response) -> ET.Element:
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/xml"), response.text
    return ET.fromstring(response.text.split("?>", maxsplit=1)[-1])


def media_signature(call_id: str) -> dict[str, str]:
    return {
        "X-Twilio-Signature": twilio_signature(TOKEN, f"wss://sparta.example.test/api/v1/media/twilio/{call_id}", [])
    }


# ------------------------------------------------------------------------------------------------ routes
async def test_twilio_routes_do_not_exist_unless_twilio_is_configured(env: ApiEnv):
    for path in ("/webhooks/twilio/voice", "/webhooks/twilio/status"):
        r = await env.client.post(f"{API}{path}", content=b"CallSid=x")
        assert r.status_code == 404
    async with serving(env) as live:
        with pytest.raises(websockets.exceptions.InvalidStatus) as denied:
            async with websockets.connect(f"{live.ws_base}/api/v1/media/twilio/call_x1"):
                pass
        assert denied.value.response.status_code == 403


async def test_unsigned_or_wrongly_signed_voice_webhooks_are_rejected_and_create_nothing():
    async with running_env(**TWILIO) as env:
        kit = Kit(env)
        fields = fields_for()
        body, good = kit.signed(VOICE_PATH, fields)
        tampered = urlencode({**fields, "From": "+10000000000"}).encode()
        attempts: list[tuple[bytes, dict[str, str]]] = [
            (body, {}),
            (body, {"X-Twilio-Signature": ""}),
            (body, {"X-Twilio-Signature": "nonsense"}),
            (body, kit.signed(VOICE_PATH, fields, token="some-other-token")[1]),
            (body, kit.signed(STATUS_PATH, fields)[1]),  # a signature for a different endpoint
            (body, kit.signed(VOICE_PATH, fields, url="http://sparta.example.test" + VOICE_PATH)[1]),  # not https
            (tampered, good),  # the fields changed after signing
            (body + b"&extra=1", good),
            (b"", good),
            (b"\xff\xfe", good),
        ]
        for content, headers in attempts:
            r = await env.client.post(f"{API}/webhooks/twilio/voice", content=content, headers=headers)
            assert r.status_code in (400, 401), (headers, r.status_code)
            assert "<Stream" not in r.text
        assert await phone_calls(env) == [] and kit.rest.hangups == []


async def test_a_form_with_too_many_fields_is_refused():
    async with running_env(**TWILIO) as env:
        kit = Kit(env)
        crowded = {**fields_for(), **{f"x{i}": "1" for i in range(150)}}
        assert (await kit.post(VOICE_PATH, crowded)).status_code == 400
        assert await phone_calls(env) == []


async def test_a_signed_voice_webhook_creates_a_call_and_answers_with_a_stream_and_is_idempotent():
    async with running_env(**TWILIO) as env:
        kit = Kit(env)
        first = await kit.voice()
        items = await phone_calls(env)
        assert len(items) == 1 and items[0]["provider"] == "other" and items[0]["simulated"] is False
        call_id = items[0]["id"]
        assert items[0]["caller_display"] == "+91 98•••• ••10" and "9876543210" not in str(items)

        stream = twiml(first).find("./Connect/Stream")
        assert stream is not None and stream.attrib == {
            "url": f"wss://sparta.example.test/api/v1/media/twilio/{call_id}"
        }
        parameter = stream.find("Parameter")
        assert parameter is not None and parameter.attrib == {"name": "token", "value": stream_token(TOKEN, call_id)}
        assert TOKEN not in first.text

        detail = (await env.client.get(f"{API}/calls/{call_id}", headers=PHONE_OWNER)).json()
        assert [e["event_type"] for e in detail["provider_events"]] == ["incoming_call"]
        assert detail["capabilities"]["simulated"] is False and detail["capabilities"]["two_way_audio"] is False

        again = await kit.voice()  # Twilio retries a webhook it did not get an answer to
        assert again.text == first.text and len(await phone_calls(env)) == 1


async def test_a_blocked_number_is_rejected_with_twiml_and_never_streamed():
    async with running_env(**TWILIO) as env:
        kit = Kit(env)
        blocked = await env.client.post(f"{API}/blocked-callers", json={"number": CALLER}, headers=PHONE_OWNER)
        assert blocked.is_success
        reply = await kit.voice()
        assert twiml(reply).find("./Reject") is not None and "<Stream" not in reply.text
        items = await phone_calls(env)
        assert len(items) == 1 and items[0]["blocked"] is True and items[0]["status"] == "ended"
        assert kit.rest.hangups == []  # Twilio never connected the call, so there is nothing to hang up


@pytest.mark.parametrize("limit", [{"max_active_calls": 1}, {"daily_call_cap": 1}])
async def test_calls_over_a_limit_are_rejected_as_busy_without_creating_a_second_call(limit):
    async with running_env(**TWILIO, **limit) as env:
        kit = Kit(env)
        assert twiml(await kit.voice(SID)).find("./Connect/Stream") is not None
        busy = twiml(await kit.voice(SID2))
        assert busy.find("./Reject") is not None and busy.find("./Reject").attrib == {"reason": "busy"}  # type: ignore[union-attr]
        assert len(await phone_calls(env)) == 1


async def test_one_number_cannot_spend_the_budget_and_the_daily_minutes_are_capped():
    async with running_env(**TWILIO, per_number_daily_call_cap=2) as env:
        kit = Kit(env)
        for sid in (SID, SID2):
            assert twiml(await kit.voice(sid)).find("./Connect/Stream") is not None
        throttled = twiml(await kit.voice("CA" + "5" * 32))
        assert throttled.find("./Reject") is not None and len(await phone_calls(env)) == 2
        elsewhere = await kit.voice("CA" + "6" * 32, From="+919800000099")  # another number is unaffected
        assert twiml(elsewhere).find("./Connect/Stream") is not None

    async with running_env(**TWILIO, daily_call_minutes_cap=0.2) as env:
        kit = Kit(env)
        assert twiml(await kit.voice(SID)).find("./Connect/Stream") is not None
        await env.advance(90)  # the first call has now used well over the 12 seconds that are allowed
        assert twiml(await kit.voice(SID2)).find("./Reject") is not None
        assert len(await phone_calls(env)) == 1


async def test_a_signed_status_callback_ends_the_call_once_and_others_are_refused():
    async with running_env(**TWILIO) as env:
        kit = Kit(env)
        await kit.voice()
        call_id = (await phone_calls(env))[0]["id"]
        body, _ = kit.signed(STATUS_PATH, {"CallSid": SID, "CallStatus": "completed"})
        assert (await env.client.post(f"{API}/webhooks/twilio/status", content=body)).status_code == 401

        assert (await kit.status(SID, "in-progress")).json() == {"status": "ok"}
        assert (await env.client.get(f"{API}/calls/{call_id}", headers=PHONE_OWNER)).json()["status"] == "active"
        assert (await kit.status(SID, "completed")).json() == {"status": "ok"}
        await env.idle()
        detail = (await env.client.get(f"{API}/calls/{call_id}", headers=PHONE_OWNER)).json()
        assert detail["status"] == "ended" and detail["summary"] is not None
        assert (await kit.status(SID, "completed")).json() == {"status": "duplicate"}
        assert kit.rest.hangups == []  # Twilio already ended it; Sparta does not hang up a call that is over


async def test_take_over_is_offered_only_once_the_owner_has_said_where_to_bridge_the_call():
    async with running_env(**TWILIO) as env:
        kit = Kit(env)
        await kit.voice()
        call_id = (await phone_calls(env))[0]["id"]
        url = f"{API}/calls/{call_id}"
        caps = (await env.client.get(url, headers=PHONE_OWNER)).json()["capabilities"]
        assert caps["can_take_over"] is False and "Assistant Studio" in caps["takeover_note"]
        refused = await env.client.post(f"{url}/takeover", headers=PHONE_OWNER)
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "unsupported_by_provider"
        assert kit.rest.redirects == []

        prefs = (await env.client.get(f"{API}/preferences", headers=PHONE_OWNER)).json()
        saved = await env.client.put(
            f"{API}/preferences", json={**prefs, "takeover_number": "+919812345670"}, headers=PHONE_OWNER
        )
        assert saved.status_code == 200
        caps = (await env.client.get(url, headers=PHONE_OWNER)).json()["capabilities"]
        assert caps["can_take_over"] is True and caps["takeover_note"] is None

        took = await env.client.post(f"{url}/takeover", headers=PHONE_OWNER)
        assert took.status_code == 200 and took.json()["capabilities"]["simulated"] is False
        assert [sid for sid, _ in kit.rest.redirects] == [SID]
        dial = twiml_of(kit.rest.redirects[0][1]).find("./Dial")
        assert dial is not None and dial.findtext("Number") == "+919812345670" and dial.attrib["callerId"] == CALLED


def twiml_of(text: str) -> ET.Element:
    return ET.fromstring(text.split("?>", maxsplit=1)[-1])


async def test_a_takeover_number_is_dialled_as_strict_e164_and_never_completed_with_a_guessed_country():
    async with running_env(**TWILIO) as env:
        kit = Kit(env)
        await kit.voice()
        call_id = (await phone_calls(env))[0]["id"]
        url = f"{API}/calls/{call_id}"

        async def save(number: str) -> None:
            prefs = (await env.client.get(f"{API}/preferences", headers=PHONE_OWNER)).json()
            saved = await env.client.put(
                f"{API}/preferences", json={**prefs, "takeover_number": number}, headers=PHONE_OWNER
            )
            assert saved.status_code == 200, saved.text

        await save("098123 45670")  # accepted as a preference, but it has no country code: not usable
        caps = (await env.client.get(url, headers=PHONE_OWNER)).json()["capabilities"]
        assert caps["can_take_over"] is False and "country code" in caps["takeover_note"]
        refused = await env.client.post(f"{url}/takeover", headers=PHONE_OWNER)
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "unsupported_by_provider"
        assert kit.rest.redirects == []
        detail = (await env.client.get(url, headers=PHONE_OWNER)).json()
        assert detail["status"] == "active"  # the refused tap changed nothing about the call

        await save("+91 (98123) 45-670")  # formatted: dialled as +919812345670
        assert (await env.client.get(url, headers=PHONE_OWNER)).json()["capabilities"]["can_take_over"] is True
        took = await env.client.post(f"{url}/takeover", headers=PHONE_OWNER)
        assert took.status_code == 200, took.text
        dial = twiml_of(kit.rest.redirects[0][1]).find("./Dial")
        assert dial is not None and dial.findtext("Number") == "+919812345670"


# --------------------------------------------------------------------------------------------- media socket
async def test_the_media_socket_refuses_unsigned_upgrades_and_closes_unknown_calls():
    async with running_env(**TWILIO) as env:
        Kit(env)
        async with serving(env) as live:
            url = f"{live.ws_base}/api/v1/media/twilio/call_x1"
            for headers in (
                {},
                {"X-Twilio-Signature": "nonsense"},
                media_signature("call_other"),  # a signature for another call's URL
            ):
                with pytest.raises(websockets.exceptions.InvalidStatus) as denied:
                    async with websockets.connect(url, additional_headers=headers):
                        pass
                assert denied.value.response.status_code == 403
            # a correctly signed upgrade for a call Sparta does not know is accepted, then closed by the provider
            async with websockets.connect(url, additional_headers=media_signature("call_x1")) as ws:
                with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
                    await ws.recv()
                assert closed.value.rcvd is not None and closed.value.rcvd.code == 1008


async def recv_json(ws: websockets.ClientConnection) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), 5.0))


async def test_a_call_runs_end_to_end_over_the_media_socket_and_ends_when_twilio_stops_the_stream():
    async with running_env(**TWILIO) as env:
        kit = Kit(env, speak=True)
        reply = await kit.voice()
        call_id = (await phone_calls(env))[0]["id"]
        token = twiml(reply).find("./Connect/Stream/Parameter").attrib["value"]  # type: ignore[union-attr]
        async with serving(env) as live:
            url = f"{live.ws_base}/api/v1/media/twilio/{call_id}"
            async with websockets.connect(url, additional_headers=media_signature(call_id)) as ws:
                await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
                await ws.send(
                    json.dumps(
                        {
                            "event": "start",
                            "sequenceNumber": "1",
                            "streamSid": STREAM,
                            "start": {
                                "accountSid": AC_SID,
                                "streamSid": STREAM,
                                "callSid": SID,
                                "tracks": ["inbound"],
                                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                                "customParameters": {"token": token},
                            },
                        }
                    )
                )
                spoken = bytearray()
                while True:  # the AI-disclosure greeting arrives as mu-law media messages followed by a mark
                    frame = await recv_json(ws)
                    assert frame["streamSid"] == STREAM
                    if frame["event"] == "media":
                        spoken += base64.b64decode(frame["media"]["payload"])
                    elif frame["event"] == "mark":
                        mark = frame["mark"]["name"]
                        break
                assert len(spoken) >= 320 and set(spoken) == {0x7F}
                await ws.send(json.dumps({"event": "mark", "streamSid": STREAM, "mark": {"name": mark}}))
                silence = base64.b64encode(b"\xff" * 160).decode()
                await ws.send(
                    json.dumps(
                        {"event": "media", "streamSid": STREAM, "media": {"track": "inbound", "payload": silence}}
                    )
                )
                await ws.send(json.dumps({"event": "stop", "streamSid": STREAM, "stop": {"callSid": SID}}))
                for _ in range(200):
                    await env.idle()
                    detail = (await env.client.get(f"{API}/calls/{call_id}", headers=PHONE_OWNER)).json()
                    if detail["status"] == "ended":
                        break
                    await asyncio.sleep(0.01)
            assert detail["status"] == "ended" and detail["summary"] is not None
            assert kit.rest.hangups == []  # Twilio ended the call itself


async def test_a_socket_with_the_wrong_token_is_closed_and_never_ends_the_call():
    async with running_env(**TWILIO) as env:
        kit = Kit(env, speak=True)
        await kit.voice()
        call_id = (await phone_calls(env))[0]["id"]
        async with serving(env) as live:
            url = f"{live.ws_base}/api/v1/media/twilio/{call_id}"
            async with websockets.connect(url, additional_headers=media_signature(call_id)) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "event": "start",
                            "streamSid": STREAM,
                            "start": {
                                "streamSid": STREAM,
                                "callSid": SID,
                                "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                                "customParameters": {"token": "guessed"},
                            },
                        }
                    )
                )
                with pytest.raises(websockets.exceptions.ConnectionClosed):
                    await asyncio.wait_for(ws.recv(), 5.0)
        await env.idle()
        detail = (await env.client.get(f"{API}/calls/{call_id}", headers=PHONE_OWNER)).json()
        assert detail["status"] == "active" and kit.rest.hangups == []
