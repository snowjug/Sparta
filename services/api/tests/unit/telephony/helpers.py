"""Test doubles for the telephony tests: scripted HTTP, locally generated RSA signing keys and token builders."""

import asyncio
import base64
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from sparta.providers.base import AudioChunk, ProviderError, ProviderMeta, SynthesisRequest
from sparta.telephony.webhooks import WebhookRejected

Scripted = httpx.Response | Callable[[httpx.Request], httpx.Response] | Exception


class FastClock:
    """Sleeps instantly but records every requested delay (for retry/back-off paths where nothing may wait)."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self.t)

    def monotonic(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds
        await asyncio.sleep(0)


class MockHttp:
    """An ``httpx.AsyncClient`` over a scripted ``MockTransport``. The last scripted item repeats once reached."""

    def __init__(self, *script: Scripted) -> None:
        self.requests: list[httpx.Request] = []
        self._script = list(script)
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(self._handle))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self._script.pop(0) if len(self._script) > 1 else self._script[0]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(request)
        return httpx.Response(item.status_code, headers=item.headers, content=item.content)


class SigningKey:
    """A locally generated RSA key pair that can mint tokens and publish itself as a JWK."""

    def __init__(self, kid: str) -> None:
        self.kid = kid
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.public = self.private.public_key()

    def jwk(self, **extra: Any) -> dict[str, Any]:
        data = json.loads(RSAAlgorithm.to_jwk(self.public))
        return {**data, "kid": self.kid, "use": "sig", **extra}

    def public_pem(self) -> bytes:
        return self.public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def token(self, claims: dict[str, Any], *, kid: str | None = "", headers: dict[str, Any] | None = None) -> str:
        header: dict[str, Any] = {}
        if kid != "":  # "" means "use my own kid"; None means "no kid header at all"
            if kid is not None:
                header["kid"] = kid
        else:
            header["kid"] = self.kid
        return jwt.encode(claims, self.private, algorithm="RS256", headers={**header, **(headers or {})})


class WeakPublicKey:
    """The public half of a 1024-bit RSA key, written out directly.

    A verifier must refuse RSA signing keys shorter than 2048 bits, and proving that only takes the *public* JWK in a key
    set: nothing is generated and nothing is signed with it. The modulus is exactly ``bits`` bits long and odd, which is
    all that loading the key checks; it is not (and does not need to be) a product of two primes.
    """

    def __init__(self, kid: str, bits: int = 1024) -> None:
        self.kid = kid
        self._bits = bits

    def jwk(self, **extra: Any) -> dict[str, Any]:
        modulus = ((1 << (self._bits - 1)) | 1).to_bytes(self._bits // 8, "big")
        n = base64.urlsafe_b64encode(modulus).rstrip(b"=").decode()
        return {"kty": "RSA", "n": n, "e": "AQAB", "kid": self.kid, "use": "sig", **extra}


class StaticJwks:
    """A JwksProvider over fixed keys that records which key ids were asked for."""

    def __init__(self, *keys: SigningKey) -> None:
        self.keys = {key.kid: PyJWK(key.jwk()) for key in keys}
        self.asked: list[str] = []

    async def get_key(self, kid: str) -> PyJWK:
        self.asked.append(kid)
        if kid not in self.keys:
            raise WebhookRejected("unknown signing key")
        return self.keys[kid]


def claims(issuer: str, audience: str | list[str], **overrides: Any) -> dict[str, Any]:
    """Valid claims for ``issuer``/``audience`` issued now and valid for five minutes. ``None`` removes a claim."""
    now = int(time.time())
    base: dict[str, Any] = {"iss": issuer, "aud": audience, "iat": now, "nbf": now, "exp": now + 300, "sub": "subject"}
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def hs256_token(secret: bytes, payload: dict[str, Any], kid: str) -> str:
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid}).encode())
    body = b64(json.dumps(payload).encode())
    signature = b64(hmac.new(secret, f"{header}.{body}".encode(), hashlib.sha256).digest())
    return f"{header}.{body}.{signature}"


def unsigned_token(payload: dict[str, Any], kid: str | None) -> str:
    header: dict[str, Any] = {"alg": "none", "typ": "JWT"}
    if kid is not None:
        header["kid"] = kid
    return f"{b64(json.dumps(header).encode())}.{b64(json.dumps(payload).encode())}."


def jwks_response(*keys: SigningKey, **extra: Any) -> httpx.Response:
    return httpx.Response(200, json={"keys": [key.jwk(**extra) for key in keys]})


# ------------------------------------------------------------------------------- ACS adapter test doubles
class FakeAcsClient:
    """Records Call Automation operations; failures can be queued per operation (popped one per call)."""

    def __init__(self, connection_id: str = "conn-1") -> None:
        self.connection_id = connection_id
        self.answers: list[tuple[str, str, str]] = []
        self.hangups: list[tuple[str, bool]] = []
        self.transfers: list[tuple[str, str]] = []
        self.answer_errors: list[BaseException] = []
        self.hangup_errors: list[BaseException] = []
        self.transfer_errors: list[BaseException] = []
        self.answer_gate: asyncio.Event | None = None
        self.closed = False

    async def answer_call(self, incoming_call_context: str, callback_url: str, media_streaming_ws_url: str) -> str:
        self.answers.append((incoming_call_context, callback_url, media_streaming_ws_url))
        if self.answer_gate is not None:
            await self.answer_gate.wait()
        if self.answer_errors:
            raise self.answer_errors.pop(0)
        return self.connection_id

    async def hang_up(self, provider_call_id: str, for_everyone: bool) -> None:
        self.hangups.append((provider_call_id, for_everyone))
        if self.hangup_errors:
            raise self.hangup_errors.pop(0)

    async def transfer_to_phone(self, provider_call_id: str, destination: str) -> None:
        self.transfers.append((provider_call_id, destination))
        if self.transfer_errors:
            raise self.transfer_errors.pop(0)

    async def aclose(self) -> None:
        self.closed = True


class FakeSink:
    """A TelephonyEventSink that records everything. ``on_incoming`` can mimic the real call service, which answers
    and starts speaking from *inside* ``incoming_call`` before it returns the call id."""

    def __init__(self, call_id: str = "call_test0001") -> None:
        self.call_id = call_id
        self.incoming: list[Any] = []
        self.audio: list[tuple[str, bytes, int]] = []
        self.dtmf: list[tuple[str, str]] = []
        self.finished: list[tuple[str, str]] = []
        self.hangups: list[tuple[str, str]] = []
        self.errors: list[tuple[str | None, str, str]] = []
        self.on_incoming: Callable[[Any], Awaitable[None]] | None = None
        self.incoming_error: BaseException | None = None
        self.audio_error: BaseException | None = None

    async def incoming_call(self, call: Any) -> str:
        self.incoming.append(call)
        if self.incoming_error is not None:
            raise self.incoming_error
        if self.on_incoming is not None:
            await self.on_incoming(call)
        return self.call_id

    async def caller_audio(self, call_id: str, pcm16: bytes, sample_rate: int) -> None:
        if self.audio_error is not None:
            raise self.audio_error
        self.audio.append((call_id, pcm16, sample_rate))

    async def caller_dtmf(self, call_id: str, digit: str) -> None:
        self.dtmf.append((call_id, digit))

    async def playback_finished(self, call_id: str, playback_id: str) -> None:
        self.finished.append((call_id, playback_id))

    async def remote_hangup(self, call_id: str, reason: str) -> None:
        self.hangups.append((call_id, reason))

    async def provider_error(self, call_id: str | None, stage: str, message: str) -> None:
        self.errors.append((call_id, stage, message))


class FakeWebSocket:
    """A duck-typed text WebSocket. ``feed`` queues frames ACS would send; ``disconnect`` ends ``receive_text``."""

    def __init__(self, clock: Any = None) -> None:
        self.incoming: asyncio.Queue[str | BaseException | None] = asyncio.Queue()
        self.sent: list[str] = []
        self.sent_at: list[float] = []
        self.fail_send = False
        self._clock = clock

    async def receive_text(self) -> str:
        item = await self.incoming.get()
        if item is None:
            raise ConnectionError("websocket closed")
        if isinstance(item, BaseException):
            raise item
        return item

    async def send_text(self, data: str) -> None:
        if self.fail_send:
            raise ConnectionError("websocket closed")
        self.sent.append(data)
        self.sent_at.append(self._clock.monotonic() if self._clock is not None else 0.0)

    def feed(self, *messages: str | dict[str, Any]) -> None:
        for message in messages:
            self.incoming.put_nowait(message if isinstance(message, str) else json.dumps(message))

    def disconnect(self) -> None:
        self.incoming.put_nowait(None)

    @property
    def frames(self) -> list[dict[str, Any]]:
        return [json.loads(text) for text in self.sent]


class FakeTts:
    """A real-looking (not simulated) TTS: yields ``frames`` 20 ms PCM16 frames in ``chunk_frames``-frame chunks."""

    def __init__(self, *, frames: int = 10, chunk_frames: int = 5, simulated: bool = False) -> None:
        self.meta = ProviderMeta("fake-tts", simulated=simulated)
        self.frames = frames
        self.chunk_frames = chunk_frames
        self.requests: list[SynthesisRequest] = []
        self.stopped: list[str] = []
        self.gate: asyncio.Event | None = None  # when set, the stream blocks here after the first chunk
        self.error: ProviderError | None = None
        self.closed_streams = 0
        self.frame_value = 7

    async def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[AudioChunk]:
        self.requests.append(request)
        rate = {"pcm16_8k": 8000, "pcm16_16k": 16000, "pcm16_24k": 24000}[request.output_format]
        frame = bytes([self.frame_value]) * (rate * 20 // 1000 * 2)
        try:
            if self.error is not None:
                raise self.error
            sent = 0
            seq = 0
            while sent < self.frames:
                count = min(self.chunk_frames, self.frames - sent)
                sent += count
                yield AudioChunk(frame * count, rate, "pcm16", seq, final=sent >= self.frames)
                seq += 1
                if self.gate is not None and seq == 1:
                    await self.gate.wait()
        finally:
            self.closed_streams += 1

    async def stop_playback(self, playback_id: str) -> None:
        self.stopped.append(playback_id)

    async def list_voices(self, locale: str | None = None) -> list[Any]:
        return []
