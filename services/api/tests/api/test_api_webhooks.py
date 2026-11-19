"""Provider callbacks: nothing unsigned is ever acted on, and genuine deliveries flow through to real calls."""

import hashlib
import hmac
import json
import secrets
import time

import pytest
import websockets
from jwt_kit import Idp

from conftest import SCAM, ApiEnv, running_env, serving
from sparta.telephony.azure_acs import AzureAcsTelephonyProvider
from sparta.telephony.webhooks import ACS_ISSUER, JwtVerifier

API = "/api/v1"
SECRET = "test-webhook-secret-123456"
OTHER = {
    "telephony_provider": "other",
    "telephony_plugin": "fake_other_provider:factory",
    "webhook_secret": SECRET,
    "telephony_owner_user_id": "phone-owner",
}
PHONE_OWNER = {"X-Sparta-Dev-User": "phone-owner"}


# ----------------------------------------------------------------------------------------- generic HMAC
def signed(
    env: ApiEnv, payload: dict | bytes, *, secret: str = SECRET, ts: int | None = None, nonce: str | None = None
):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    stamp = str(ts if ts is not None else int(env.clock.now().timestamp()))
    nonce = nonce or secrets.token_hex(8)
    signature = hmac.new(secret.encode(), f"{stamp}.{nonce}.".encode() + body, hashlib.sha256).hexdigest()
    headers = {
        "X-Sparta-Timestamp": stamp,
        "X-Sparta-Nonce": nonce,
        "X-Sparta-Signature": signature,
        "Content-Type": "application/json",
    }
    return body, headers


def incoming(event_id: str = "evt-incoming-1", number: str = "+919876543210") -> dict:
    return {
        "event_id": event_id,
        "type": "call.incoming",
        "provider_call_id": f"prov-{event_id}",
        "caller_number": number,
    }


async def post_generic(env: ApiEnv, payload: dict | bytes, **kwargs):  # type: ignore[no-untyped-def]
    body, headers = signed(env, payload, **kwargs)
    return await env.client.post(f"{API}/webhooks/generic", content=body, headers=headers)


async def phone_calls(env: ApiEnv) -> list[dict]:
    return (await env.client.get(f"{API}/calls", headers=PHONE_OWNER)).json()["items"]


async def test_the_generic_webhook_does_not_exist_unless_the_other_provider_is_configured(env: ApiEnv):
    r = await post_generic(env, incoming())
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


async def test_a_signed_incoming_call_creates_a_real_provider_call_for_the_configured_owner():
    async with running_env(**OTHER) as env:
        r = await post_generic(env, incoming())
        assert r.status_code == 200 and r.json()["status"] == "ok"
        items = await phone_calls(env)
        assert len(items) == 1 and items[0]["id"] == r.json()["call_id"]
        assert items[0]["provider"] == "other" and items[0]["simulated"] is False
        assert items[0]["caller_display"] == "+91 98•••• ••10" and "9876543210" not in str(items)
        assert (await env.client.get(f"{API}/calls")).json()["items"] == []  # not visible to anyone else

        again = await post_generic(env, incoming())  # a redelivery of the same event id
        assert again.json() == {"status": "duplicate"}
        assert len(await phone_calls(env)) == 1


async def test_transcripts_hangups_and_playback_events_drive_the_call():
    async with running_env(**OTHER) as env:
        call_id = (await post_generic(env, incoming())).json()["call_id"]
        turn = await post_generic(
            env,
            {
                "event_id": "evt-tr-0001",
                "type": "caller.transcript",
                "call_id": call_id,
                "text": SCAM,
                "language": "en-IN",
                "confidence": 0.93,
            },
        )
        assert turn.status_code == 200
        detail = (await env.client.get(f"{API}/calls/{call_id}", headers=PHONE_OWNER)).json()
        caller = next(t for t in detail["turns"] if t["speaker"] == "caller")
        assert caller["source"] == "provider_stt" and caller["confidence"] == 0.93
        assert detail["risk_level"] == "high"

        await post_generic(
            env,
            {"event_id": "evt-pb-0001", "type": "playback.finished", "call_id": call_id, "playback_id": "pb_unknown"},
        )
        ended = await post_generic(
            env, {"event_id": "evt-end-0001", "type": "call.ended", "call_id": call_id, "reason": "caller_hung_up"}
        )
        assert ended.status_code == 200
        assert (await env.client.get(f"{API}/calls/{call_id}", headers=PHONE_OWNER)).json()["status"] == "ended"
        late = await post_generic(
            env, {"event_id": "evt-tr-0002", "type": "caller.transcript", "call_id": call_id, "text": "hello"}
        )
        assert late.status_code == 200  # events for a finished call are ignored, never an error


@pytest.mark.parametrize(
    "case",
    [
        "missing_headers",
        "bad_signature",
        "wrong_secret",
        "tampered_body",
        "stale_timestamp",
        "future_timestamp",
        "bad_nonce_characters",
        "short_signature",
        "non_numeric_timestamp",
    ],
)
async def test_forged_generic_webhooks_are_rejected_and_create_nothing(case: str):
    async with running_env(**OTHER) as env:
        body, headers = signed(env, incoming())
        now = int(env.clock.now().timestamp())
        match case:
            case "missing_headers":
                headers = {"Content-Type": "application/json"}
            case "bad_signature":
                headers["X-Sparta-Signature"] = "0" * 64
            case "wrong_secret":
                body, headers = signed(env, incoming(), secret="not-the-secret-at-all-12345")
            case "tampered_body":
                body = body.replace(b"+919876543210", b"+919999999999")
            case "stale_timestamp":
                body, headers = signed(env, incoming(), ts=now - 3600)
            case "future_timestamp":
                body, headers = signed(env, incoming(), ts=now + 3600)
            case "bad_nonce_characters":
                body, headers = signed(env, incoming(), nonce="has.dots.in.it")
            case "short_signature":
                headers["X-Sparta-Signature"] = "abcd"
            case "non_numeric_timestamp":
                headers["X-Sparta-Timestamp"] = "yesterday"
        r = await env.client.post(f"{API}/webhooks/generic", content=body, headers=headers)
        assert r.status_code == 401, (case, r.text)
        assert r.json()["error"]["code"] == "unauthorized" and "signature" not in r.text.lower()
        assert await phone_calls(env) == []


async def test_a_replayed_request_is_rejected_even_with_a_valid_signature():
    async with running_env(**OTHER) as env:
        body, headers = signed(env, incoming())
        first = await env.client.post(f"{API}/webhooks/generic", content=body, headers=headers)
        replay = await env.client.post(f"{API}/webhooks/generic", content=body, headers=headers)
        assert first.status_code == 200 and replay.status_code == 401
        assert len(await phone_calls(env)) == 1


async def test_a_signed_but_malformed_event_is_a_validation_error_not_a_crash():
    async with running_env(**OTHER) as env:
        for payload in (
            b"{not json",
            json.dumps({"event_id": "evt-bad-0001", "type": "call.explode"}).encode(),
            json.dumps({**incoming("evt-bad-0002"), "surprise": 1}).encode(),
            json.dumps({"event_id": "evt-bad-0003", "type": "call.incoming"}).encode(),  # no provider_call_id
            json.dumps({"event_id": "evt-bad-0004", "type": "call.ended"}).encode(),  # no call_id
        ):
            r = await post_generic(env, payload)
            assert r.status_code in (400, 422), (payload, r.status_code, r.text)
        assert await phone_calls(env) == []


# ---------------------------------------------------------------------------------------------------- ACS
ACS = {
    "telephony_provider": "azure",
    "acs_connection_string": "endpoint=https://acs-test.communication.azure.com/;accesskey=ZmFrZQ==",
    "acs_callback_base_url": "https://sparta.example.test",
    "acs_resource_id": "11111111-2222-3333-4444-555555555555",
    "entra_tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "event_grid_audience": "api://sparta-eventgrid",
    "telephony_owner_user_id": "phone-owner",
}
EG_ISSUER = f"https://login.microsoftonline.com/{ACS['entra_tenant_id']}/v2.0"


class FakeAcs:
    def __init__(self) -> None:
        self.answered: list[tuple[str, str, str]] = []
        self.hung_up: list[tuple[str, bool]] = []

    async def answer_call(self, incoming_call_context: str, callback_url: str, media_streaming_ws_url: str) -> str:
        self.answered.append((incoming_call_context, callback_url, media_streaming_ws_url))
        return "conn-1"

    async def hang_up(self, provider_call_id: str, for_everyone: bool) -> None:
        self.hung_up.append((provider_call_id, for_everyone))

    async def transfer_to_phone(self, provider_call_id: str, destination: str) -> None:
        return None


class AcsKit:
    def __init__(self, env: ApiEnv) -> None:
        self.env = env
        self.provider = env.container.providers.telephony
        assert isinstance(self.provider, AzureAcsTelephonyProvider)
        self.acs_client = FakeAcs()
        self.event_grid = Idp(EG_ISSUER, str(ACS["event_grid_audience"]))
        self.acs = Idp(ACS_ISSUER, str(ACS["acs_resource_id"]))
        self.provider._client = self.acs_client  # no real Azure calls
        verifiers = self.provider._verifiers
        verifiers["event_grid"] = JwtVerifier([EG_ISSUER], [self.event_grid.audience], self.event_grid.jwks())
        verifiers["callback"] = JwtVerifier([ACS_ISSUER], [self.acs.audience], self.acs.jwks(), max_lifetime_s=600)
        verifiers["media"] = JwtVerifier([ACS_ISSUER], [self.acs.audience], self.acs.jwks(), max_lifetime_s=87_000)

    def eg_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.event_grid.token()}"}

    def cb_headers(self) -> dict[str, str]:
        # Call Automation callback tokens are short lived (documented as 5 minutes); the verifier enforces a cap.
        return {"Authorization": f"Bearer {self.acs.token(exp=int(time.time()) + 300)}"}


def incoming_call_event(
    event_id: str = "evt-1", server_call_id: str = "server-call-1", number: str = "+919876543210"
) -> list[dict]:
    return [
        {
            "id": event_id,
            "topic": "/subscriptions/x/resourceGroups/y/providers/Microsoft.Communication/communicationServices/z",
            "subject": "/caller/s/recipient/r",
            "eventType": "Microsoft.Communication.IncomingCall",
            "eventTime": "2026-01-01T00:00:00Z",
            "dataVersion": "1.0",
            "data": {
                "incomingCallContext": "ctx-secret-token-123",
                "serverCallId": server_call_id,
                "from": {"kind": "phoneNumber", "rawId": f"4:{number}", "phoneNumber": {"value": number}},
                "to": {"kind": "phoneNumber", "rawId": "4:+918000000000", "phoneNumber": {"value": "+918000000000"}},
                "callerDisplayName": "Mr Caller",
                "correlationId": "corr-1",
            },
        }
    ]


async def test_acs_routes_are_hidden_unless_azure_telephony_is_configured(env: ApiEnv):
    for path in ("/webhooks/acs/events", "/webhooks/acs/callbacks/call_x1"):
        r = await env.client.post(f"{API}{path}", json=[])
        assert r.status_code == 404


async def test_unsigned_or_wrongly_signed_acs_requests_are_rejected_and_create_nothing():
    async with running_env(**ACS) as env:
        kit = AcsKit(env)
        body = incoming_call_event()
        other_key = Idp(EG_ISSUER, "api://sparta-eventgrid")
        wrong_audience = Idp(EG_ISSUER, "api://someone-else")
        attempts = [
            {},
            {"Authorization": "Bearer garbage"},
            {"Authorization": f"Bearer {other_key.token()}"},  # right claims, someone else's key
            {"Authorization": f"Bearer {kit.event_grid.token(aud='api://someone-else')}"},
            {"Authorization": f"Bearer {kit.event_grid.hs256_confusion_token()}"},
            {"Authorization": f"Bearer {kit.event_grid.unsigned_token()}"},
            {"Authorization": f"Bearer {wrong_audience.token()}"},
            {"Authorization": f"Token {kit.event_grid.token()}"},
        ]
        for headers in attempts:
            r = await env.client.post(f"{API}/webhooks/acs/events", json=body, headers=headers)
            assert r.status_code == 401, (headers, r.text)
        for headers in (
            {},
            {"Authorization": f"Bearer {kit.event_grid.token()}"},  # an Event Grid token is not an ACS token
            {"Authorization": f"Bearer {kit.acs.token()}"},  # right issuer, but a lifetime far beyond what ACS issues
        ):
            r = await env.client.post(f"{API}/webhooks/acs/callbacks/call_x1", json=[], headers=headers)
            assert r.status_code == 401
        assert kit.acs_client.answered == [] and await phone_calls(env) == []


async def test_the_event_grid_handshake_needs_a_valid_token_and_returns_the_code():
    async with running_env(**ACS) as env:
        kit = AcsKit(env)
        handshake = [
            {
                "id": "v-1",
                "eventType": "Microsoft.EventGrid.SubscriptionValidationEvent",
                "subject": "",
                "data": {"validationCode": "abc123XYZ"},
            }
        ]
        denied = await env.client.post(f"{API}/webhooks/acs/events", json=handshake)
        assert denied.status_code == 401
        ok = await env.client.post(f"{API}/webhooks/acs/events", json=handshake, headers=kit.eg_headers())
        assert ok.status_code == 200 and ok.json() == {"validationResponse": "abc123XYZ"}
        bad_code = [{**handshake[0], "data": {"validationCode": "../../etc"}}]
        assert (
            await env.client.post(f"{API}/webhooks/acs/events", json=bad_code, headers=kit.eg_headers())
        ).status_code == 400


async def test_an_incoming_call_event_creates_a_call_answers_it_and_is_idempotent():
    async with running_env(**ACS) as env:
        kit = AcsKit(env)
        r = await env.client.post(f"{API}/webhooks/acs/events", json=incoming_call_event(), headers=kit.eg_headers())
        assert r.status_code == 200 and r.json() == {"handled": 1}
        items = await phone_calls(env)
        assert len(items) == 1 and items[0]["provider"] == "azure" and items[0]["simulated"] is False
        assert "Mr Caller" not in items[0]["caller_display"]  # the carrier-supplied name is not shown beside the number
        call_id = items[0]["id"]

        assert len(kit.acs_client.answered) == 1
        context, callback_url, ws_url = kit.acs_client.answered[0]
        assert context == "ctx-secret-token-123"
        assert callback_url == f"https://sparta.example.test/api/v1/webhooks/acs/callbacks/{call_id}"
        assert ws_url == f"wss://sparta.example.test/api/v1/media/acs/{call_id}"

        detail = (await env.client.get(f"{API}/calls/{call_id}", headers=PHONE_OWNER)).json()
        assert [e["event_type"] for e in detail["provider_events"]] == ["incoming_call"]
        assert detail["capabilities"]["simulated"] is False and detail["capabilities"]["two_way_audio"] is False
        assert "ctx-secret" not in json.dumps(detail)  # the single-use answer context never leaves the provider
        events = (await env.client.get(f"{API}/calls/{call_id}/events", headers=PHONE_OWNER)).json()
        errors = [e for e in events if e["type"] == "provider.error"]
        assert errors and errors[0]["data"]["stage"] == "play" and errors[0]["data"]["degraded"] is True

        again = await env.client.post(
            f"{API}/webhooks/acs/events", json=incoming_call_event(), headers=kit.eg_headers()
        )
        assert again.json() == {"handled": 0}
        assert len(await phone_calls(env)) == 1 and len(kit.acs_client.answered) == 1


async def test_call_automation_callbacks_end_the_call_and_unknown_calls_are_ignored():
    async with running_env(**ACS) as env:
        kit = AcsKit(env)
        await env.client.post(f"{API}/webhooks/acs/events", json=incoming_call_event(), headers=kit.eg_headers())
        call_id = (await phone_calls(env))[0]["id"]
        url = f"{API}/webhooks/acs/callbacks/{call_id}"

        connected = [
            {"id": "cb-1", "type": "Microsoft.Communication.CallConnected", "data": {"callConnectionId": "conn-1"}}
        ]
        assert (await env.client.post(url, json=connected, headers=kit.cb_headers())).status_code == 200
        assert (await env.client.post(url, content=b"{broken", headers=kit.cb_headers())).status_code == 400
        assert (
            await env.client.post(f"{API}/webhooks/acs/callbacks/call_nope", json=connected, headers=kit.cb_headers())
        ).status_code == 200

        gone = [
            {"id": "cb-2", "type": "Microsoft.Communication.CallDisconnected", "data": {"callConnectionId": "conn-1"}}
        ]
        assert (await env.client.post(url, json=gone, headers=kit.cb_headers())).status_code == 200
        detail = (await env.client.get(f"{API}/calls/{call_id}", headers=PHONE_OWNER)).json()
        assert detail["status"] == "ended" and detail["action_taken"] is not None


async def test_the_media_socket_refuses_unauthenticated_upgrades():
    async with running_env(**ACS) as env:
        kit = AcsKit(env)
        async with serving(env) as live:
            url = f"{live.ws_base}/api/v1/media/acs/call_x1"
            with pytest.raises(websockets.exceptions.InvalidStatus) as denied:
                async with websockets.connect(url):
                    pass
            assert denied.value.response.status_code == 403
            with pytest.raises(websockets.exceptions.InvalidStatus):
                async with websockets.connect(url, additional_headers={"Authorization": "Bearer nonsense"}):
                    pass
            # a valid token for a call Sparta does not know is accepted, then refused by the provider
            async with websockets.connect(url, additional_headers=kit.cb_headers()) as ws:
                with pytest.raises(websockets.exceptions.ConnectionClosed) as closed:
                    await ws.recv()
                assert closed.value.rcvd is not None and closed.value.rcvd.code == 1008
