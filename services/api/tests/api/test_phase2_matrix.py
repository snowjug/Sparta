"""Phase 2 controlled test matrix: whole calls through the Twilio adapter, the media socket, the audio pipeline and the
call service. The caller is a scripted test client speaking mu-law frames over a real WebSocket; recognition and
synthesis are scripted fakes and Twilio's REST API is a fake.

This is a CONTROLLED test, not an external one: no Twilio, Azure Speech or Azure OpenAI service is involved, so nothing
here says anything about real recognition quality, real latency or a real phone line. Latencies measured here are the
local processing time of Sparta's own code with zero-latency fakes. Set ``SPARTA_WRITE_EVIDENCE=<path>`` to write the
sanitised evidence that docs/PHASE2_CONTROLLED_RESULTS.md is generated from.
"""

import asyncio
import base64
import json
import os
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import websockets
from test_api_twilio import (
    AC_SID,
    API,
    PHONE_OWNER,
    SID,
    STREAM,
    TWILIO,
    Kit,
    SpokenTts,
    media_signature,
    phone_calls,
    twiml,
)
from tests.audio_fakes import FakeStt, Script

from conftest import ApiEnv, running_env, serving
from sparta.observability.metrics import PROVIDER_LATENCY_MS, STAGE_LATENCY_MS
from sparta.providers.base import ProviderError, ProviderMeta, ProviderUnavailable
from sparta.telephony.g711 import pcm16_to_ulaw

VOICED = pcm16_to_ulaw(b"\xb8\x0b" * 160)  # 20 ms at 8 kHz, amplitude 3000
SILENT = b"\xff" * 160
EVIDENCE: list[dict] = []
SAMPLES: dict[str, list[float]] = {}
PROTECTED_ASK = re.compile(
    r"(please|kindly|can you|could you|tell me|share|read out|bataiye|heli)\W+.{0,40}\b(otp|pin|cvv|password)\b",
    re.IGNORECASE,
)

SCAM_EN = "Hello, this is Rahul from State Bank of India. Sir your KYC is pending, tell me the OTP sent to your phone right now."
KYC_HINGLISH = (
    "Namaste sir, main SBI bank se bol raha hoon, aapka KYC pending hai. Account block ho jayega, abhi OTP bataiye."
)
KANGLISH = (
    "Namaskara sir, nanu bank inda maatadtidini, nimma KYC pending ide. Account block aagutte, eega UPI PIN heli."
)
DELIVERY = (
    "Hello, I am calling from Amazon delivery. I am outside your building with your parcel, can someone come down?"
)
DELIVERY_2 = "My name is Suresh. I cannot find the building, please come down to the gate."


class RecordingTts(SpokenTts):
    """The synthesiser: records what Sparta asked it to say (and in which language); can be made to fail."""

    def __init__(self, error: ProviderError | None = None) -> None:
        self.requests: list = []
        self.error = error

    async def synthesize_stream(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        async for chunk in super().synthesize_stream(request):
            yield chunk


class BrokenStt:
    """A recogniser that is down: every utterance fails to start."""

    meta = ProviderMeta(provider="fake-stt-down", simulated=False)

    def __init__(self) -> None:
        self.attempts = 0

    async def start_stream(self, *, candidate_locales, locale_hint, trace_id, sample_rate=16000):
        self.attempts += 1
        raise ProviderUnavailable("fake-stt-down", "stt", "the speech service is unavailable")


class DownModel:
    """A language model that is down: every call fails (the deterministic engine must carry on without it)."""

    meta = ProviderMeta(provider="fake-llm-down", simulated=False, model="none")

    def __getattr__(self, name: str) -> Any:
        async def fail(*args: Any, **kwargs: Any) -> Any:
            raise ProviderUnavailable("fake-llm-down", name, "the model is unavailable")

        return fail


@dataclass
class Line:
    """A caller on the phone: speaks mu-law frames on the media socket and answers Twilio's mark messages."""

    env: ApiEnv
    kit: Kit
    live: Any
    stt: Any
    tts: RecordingTts
    echo_marks: bool = True
    call_id: str = ""
    ws: Any = None
    media_frames: int = 0
    marks: list[str] = field(default_factory=list)
    clears: int = 0
    first_audio_at: float | None = None
    reader: asyncio.Task | None = None

    async def start(self, sid: str = SID, number: str = "+919876543210") -> None:
        reply = await self.kit.voice(sid, From=number)
        stream = twiml(reply).find("./Connect/Stream")
        assert stream is not None
        self.call_id = stream.attrib["url"].rsplit("/", 1)[-1]
        token = stream.find("Parameter").attrib["value"]  # type: ignore[union-attr]
        await self.connect(sid, token)

    async def connect(self, sid: str, token: str) -> None:
        url = f"{self.live.ws_base}/api/v1/media/twilio/{self.call_id}"
        self.ws = await websockets.connect(url, additional_headers=media_signature(self.call_id))
        await self.ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await self.ws.send(
            json.dumps(
                {
                    "event": "start",
                    "sequenceNumber": "1",
                    "streamSid": STREAM,
                    "start": {
                        "accountSid": AC_SID,
                        "streamSid": STREAM,
                        "callSid": sid,
                        "tracks": ["inbound"],
                        "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                        "customParameters": {"token": token},
                    },
                }
            )
        )
        self.reader = asyncio.create_task(self._read(self.ws))

    async def _read(self, ws: Any) -> None:
        try:
            async for raw in ws:
                frame = json.loads(raw)
                if frame["event"] == "media":
                    self.media_frames += 1
                    if self.first_audio_at is None:
                        self.first_audio_at = time.perf_counter()
                elif frame["event"] == "clear":
                    self.clears += 1
                elif frame["event"] == "mark":
                    name = frame["mark"]["name"]
                    self.marks.append(name)
                    if self.echo_marks:
                        await ws.send(json.dumps({"event": "mark", "streamSid": STREAM, "mark": {"name": name}}))
        except websockets.ConnectionClosed:
            return

    async def _frames(self, payload: bytes, count: int) -> None:
        message = json.dumps(
            {
                "event": "media",
                "streamSid": STREAM,
                "media": {"track": "inbound", "payload": base64.b64encode(payload).decode()},
            }
        )
        for index in range(count):
            await self.ws.send(message)
            if index % 10 == 9:
                await asyncio.sleep(0)

    async def speak(self, voiced_ms: int = 400, silence_ms: int = 800) -> float:
        """Speak, then fall silent; returns the instant the last frame was sent (the end of the caller's turn)."""
        self.first_audio_at = None
        await self._frames(VOICED, voiced_ms // 20)
        await self._frames(SILENT, silence_ms // 20)
        return time.perf_counter()

    async def stop(self) -> None:
        """What Twilio sends when the call is over: a ``stop`` message, then the socket closes."""
        if self.ws is not None and not self.ws.close_code:
            try:
                await self.ws.send(json.dumps({"event": "stop", "streamSid": STREAM, "stop": {"callSid": SID}}))
                await self.ws.close()
            except websockets.ConnectionClosed:
                pass
        if self.reader is not None:
            await asyncio.gather(self.reader, return_exceptions=True)

    async def detail(self) -> dict:
        return (await self.env.client.get(f"{API}/calls/{self.call_id}", headers=PHONE_OWNER)).json()

    async def events(self) -> list[dict]:
        return (await self.env.client.get(f"{API}/calls/{self.call_id}/events", headers=PHONE_OWNER)).json()

    async def until(self, predicate, what: str) -> None:
        deadline = time.perf_counter() + 8.0
        while time.perf_counter() < deadline:
            await self.env.idle()
            if await predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"timed out waiting for {what}")

    async def spoke(self, count: int) -> None:
        async def enough() -> bool:
            return len(self.tts.requests) >= count

        await self.until(enough, f"{count} spoken lines")

    async def ended(self) -> dict:
        async def over() -> bool:
            return (await self.detail())["status"] == "ended"

        await self.until(over, "the call to end")
        return await self.detail()

    @property
    def said(self) -> list[str]:
        return [request.text for request in self.tts.requests]


def record(label: str, detail: dict, *, line: Line, sent_at: float | None = None, notes: str = "") -> None:
    risk = detail.get("risk") or {}
    latency = None
    if sent_at is not None and line.first_audio_at is not None:
        latency = round((line.first_audio_at - sent_at) * 1000, 1)
    metrics = line.env.container.metrics

    def per_turn(stage: str) -> list[float]:
        return [
            t["latency"][stage]
            for t in detail["turns"]
            if t["speaker"] == "assistant" and (t.get("latency") or {}).get(stage) is not None
        ]

    for name, samples in (
        ("final_transcript_ms", per_turn("stt_ms")),
        ("engine_decision_ms", per_turn("policy_ms")),
        ("model_ms", per_turn("model_ms")),
        ("tts_first_audio_ms", metrics.samples(PROVIDER_LATENCY_MS, provider="twilio", stage="tts_first_audio")),
        ("service_turn_total_ms", metrics.samples(STAGE_LATENCY_MS, stage="turn_total")),
        ("interruption_stop_ms", metrics.samples(STAGE_LATENCY_MS, stage="interruption")),
    ):
        SAMPLES.setdefault(name, []).extend(float(v) for v in samples)
    if latency is not None:
        SAMPLES.setdefault("turn_end_to_first_assistant_audio_ms", []).append(latency)
    EVIDENCE.append(
        {
            "scenario": label,
            "call_id": detail["id"],
            "provider_correlation": "fake CallSid (controlled test)",
            "state_timeline": [
                step["label"] for step in detail.get("timeline", []) if step["kind"] in ("state", "risk")
            ],
            "risk_level": detail.get("risk_level"),
            "risk_category": risk.get("category") if isinstance(risk, dict) else None,
            "risk_signals": [s["code"] for s in risk.get("signals", [])] if isinstance(risk, dict) else [],
            "action_taken": detail.get("action_taken"),
            "summary": ((detail.get("summary") or {}).get("text") or ""),
            "spoken_lines": len(line.tts.requests),
            "turn_end_to_first_assistant_audio_ms": latency,
            "result": "PASS",
            "notes": notes,
        }
    )


def percentiles(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50": round(statistics.median(ordered), 2),
        "p95": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 2),
        "max": round(ordered[-1], 2),
    }


@pytest.fixture(scope="module", autouse=True)
def write_evidence():
    yield
    target = os.environ.get("SPARTA_WRITE_EVIDENCE")
    if target and EVIDENCE:
        payload: dict[str, Any] = {
            "controlled": True,
            "caveat": "Fake Twilio, fake recognition and synthesis with zero latency and no language model: these are "
            "Sparta's own local processing times, not what a real call would measure.",
            "rows": EVIDENCE,
            "latency_ms": {name: percentiles(values) for name, values in SAMPLES.items() if values},
        }
        Path(target).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def new_line(env: ApiEnv, live: Any, *scripts: Script, stt: Any = None, tts: RecordingTts | None = None) -> Line:
    kit = Kit(env, speak=True)
    stt = stt or (FakeStt(*scripts) if scripts else FakeStt())
    tts = tts or RecordingTts()
    kit.provider._tts = tts  # type: ignore[assignment]
    env.container.calls.stt = stt
    return Line(env, kit, live, stt, tts)


def never_asks_for_protected_details(line: Line) -> None:
    for text in line.said:
        assert not PROTECTED_ASK.search(text), text


# ------------------------------------------------------------------------------------------------------------- A
async def test_a_a_legitimate_delivery_call_escalates_and_the_owner_can_take_over():
    async with running_env(**TWILIO) as env, serving(env) as live:
        prefs = (await env.client.get(f"{API}/preferences", headers=PHONE_OWNER)).json()
        await env.client.put(
            f"{API}/preferences", json={**prefs, "takeover_number": "+919812345670"}, headers=PHONE_OWNER
        )
        line = await new_line(
            env,
            live,
            Script(text=DELIVERY, language="en-IN", confidence=0.92),
            Script(text=DELIVERY_2, language="en-IN"),
        )
        await line.start()
        await line.spoke(1)
        assert "AI" in line.said[0]  # the disclosure comes first
        sent = await line.speak()
        await line.spoke(2)
        await line.speak()
        await line.spoke(3)
        detail = await line.detail()
        assert detail["risk_level"] == "low" and detail["state"] == "ESCALATE" and detail["owner_attention_required"]
        assert [e["status"] for e in detail["escalations"]] == ["requested"]
        assert detail["escalations"][0]["reason"] == "Delivery coordination"
        never_asks_for_protected_details(line)

        seen: dict[str, int] = {}
        real_redirect = line.kit.rest.redirect

        async def redirect(call_sid: str, twiml_text: str) -> None:
            seen["lines"], seen["heard"] = len(line.tts.requests), len(line.marks)
            await real_redirect(call_sid, twiml_text)

        line.kit.rest.redirect = redirect  # type: ignore[method-assign]
        took = await env.client.post(f"{API}/calls/{line.call_id}/takeover", headers=PHONE_OWNER)
        assert took.status_code == 200
        assert len(line.kit.rest.redirects) == 1 and "<Dial" in line.kit.rest.redirects[0][1]
        assert seen["heard"] == seen["lines"]  # every line, the takeover announcement included, was heard first
        await line.stop()  # the redirect replaced the stream, so Twilio ends it
        final = await line.ended()
        assert final["action_taken"] == "owner_took_over" and "owner took over" in final["summary"]["text"]
        assert line.kit.rest.hangups == []  # a bridged call is never hung up by Sparta
        record("A English legitimate delivery, owner takes over", final, line=line, sent_at=sent)


async def test_a_the_owner_can_let_sparta_continue_after_an_escalation():
    async with running_env(**TWILIO) as env, serving(env) as live:
        line = await new_line(
            env,
            live,
            Script(text=DELIVERY, language="en-IN", confidence=0.92),
            Script(text=DELIVERY_2, language="en-IN"),
        )
        await line.start()
        await line.spoke(1)
        await line.speak()
        await line.spoke(2)
        assert (await line.detail())["state"] == "ESCALATE"
        decided = await env.client.post(f"{API}/calls/{line.call_id}/continue", headers=PHONE_OWNER)
        assert decided.status_code == 200
        await line.spoke(3)
        sent = await line.speak()
        await line.spoke(4)
        await line.stop()
        final = await line.ended()
        assert "let Sparta continue" in final["summary"]["text"] and final["risk_level"] != "high"
        never_asks_for_protected_details(line)
        record("A English legitimate delivery, Sparta continues", final, line=line, sent_at=sent)


# ------------------------------------------------------------------------------------------------------------- B
async def test_b_an_english_otp_scam_is_refused_and_the_call_ended():
    async with running_env(**TWILIO) as env, serving(env) as live:
        line = await new_line(env, live, Script(text=SCAM_EN, language="en-IN", confidence=0.9))
        await line.start()
        await line.spoke(1)
        sent = await line.speak()
        final = await line.ended()
        assert final["risk_level"] == "high" and final["action_taken"] == "refused_and_ended"
        assert "OTP_REQUEST" in [s["code"] for s in final["risk"]["signals"]]
        assert "one-time password" in final["summary"]["text"]
        never_asks_for_protected_details(line)
        assert "AI" in line.said[0] and len(line.said) == 2
        assert line.kit.rest.hangups == [SID]  # the call was ended at Twilio exactly once
        record("B English OTP scam", final, line=line, sent_at=sent)
        await line.stop()


# -------------------------------------------------------------------------------------------------------- C and D
async def test_c_a_hinglish_kyc_scam_is_handled_safely():
    async with running_env(**TWILIO) as env, serving(env) as live:
        line = await new_line(env, live, Script(text=KYC_HINGLISH, language="hi-IN", confidence=0.84))
        await line.start()
        await line.spoke(1)
        sent = await line.speak()
        final = await line.ended()
        assert final["risk_level"] == "high" and final["action_taken"] == "refused_and_ended"
        assert "hi-IN" in final["languages"] and "OTP_REQUEST" in [s["code"] for s in final["risk"]["signals"]]
        assert line.tts.requests[-1].locale == "hi-IN"  # refused in the language the caller used
        never_asks_for_protected_details(line)
        record("C Hinglish KYC scam", final, line=line, sent_at=sent)
        await line.stop()


async def test_d_a_kannada_kanglish_upi_pin_request_is_detected():
    async with running_env(**TWILIO) as env, serving(env) as live:
        line = await new_line(env, live, Script(text=KANGLISH, language="kn-IN", confidence=0.8))
        await line.start()
        await line.spoke(1)
        sent = await line.speak()
        final = await line.ended()
        assert final["risk_level"] == "high" and final["action_taken"] == "refused_and_ended"
        assert "kn-IN" in final["languages"] and final["risk"]["signals"]
        assert line.tts.requests[-1].locale == "kn-IN"  # refused in Kannada, a supported language
        never_asks_for_protected_details(line)
        record("D Kannada/Kanglish UPI PIN request", final, line=line, sent_at=sent)
        await line.stop()


# ------------------------------------------------------------------------------------------------------------- E
async def test_e_a_low_confidence_caller_gets_a_short_clarification_not_invented_understanding():
    async with running_env(**TWILIO) as env, serving(env) as live:
        line = await new_line(env, live, Script(text="hello hello mm", language="en-IN", confidence=0.3))
        await line.start()
        await line.spoke(1)
        sent = await line.speak()
        await line.spoke(2)
        detail = await line.detail()
        assert detail["status"] == "active" and detail["state"] == "CLARIFY"
        assert "say that again" in line.said[1]  # a short clarification, not a guess
        assert detail["risk_level"] == "unknown" and not detail["purpose"]
        assert not any((detail["caller_claim"] or {}).values())  # nothing was invented about who is calling
        record("E low-confidence caller", detail, line=line, sent_at=sent)
        await line.stop()


# ------------------------------------------------------------------------------------------------------------- F
async def test_f_a_caller_who_interrupts_makes_sparta_stop_and_the_call_carries_on():
    async with running_env(**TWILIO) as env, serving(env) as live:
        line = await new_line(env, live, Script(text=DELIVERY, language="en-IN", confidence=0.92))
        line.echo_marks = False  # the greeting is still "playing" on the line
        await line.start()
        await line.spoke(1)
        await line.until(lambda: _frames_seen(line), "the greeting audio")
        sent = await line.speak(voiced_ms=300, silence_ms=800)  # the caller talks over it
        await line.spoke(2)
        await line.until(lambda: _interrupted(line), "the interruption")
        assert line.clears >= 1  # Twilio was told to drop its audio buffer
        detail = await line.detail()
        assert detail["status"] == "active" and detail["turns"][0]["interrupted"] is True
        assert [t["speaker"] for t in detail["turns"][:2]] == ["assistant", "caller"]
        for name in list(line.marks):  # Twilio echoes the marks of what it dropped: they must change nothing
            await line.ws.send(json.dumps({"event": "mark", "streamSid": STREAM, "mark": {"name": name}}))
        await asyncio.sleep(0.05)
        assert (await line.detail())["status"] == "active"
        record("F barge-in", detail, line=line, sent_at=sent, notes=f"{line.clears} clear message(s) sent")
        await line.stop()


async def _frames_seen(line: Line) -> bool:
    return line.media_frames > 0


async def _interrupted(line: Line) -> bool:
    return any(e["type"] == "assistant.interrupted" for e in await line.events())


# ------------------------------------------------------------------------------------------------------------- G
async def test_g_a_recogniser_that_is_down_ends_the_call_with_a_clear_summary():
    async with running_env(**TWILIO) as env, serving(env) as live:
        stt = BrokenStt()
        line = await new_line(env, live, stt=stt)
        await line.start()
        await line.spoke(1)
        await line.speak()
        await line.speak()
        final = await line.ended()
        assert stt.attempts >= 2 and "could not hear or speak" in final["summary"]["text"]
        assert final["summary"]["owner_action_required"] is True
        events = await line.events()
        assert any(e["type"] == "provider.error" and e["data"]["stage"] == "stt" for e in events)
        assert line.kit.rest.hangups == [SID]
        record("G speech recognition down", final, line=line)
        await line.stop()


async def test_g_a_synthesiser_that_is_down_ends_the_call_instead_of_leaving_it_silent():
    async with running_env(**TWILIO) as env, serving(env) as live:
        tts = RecordingTts(error=ProviderError("fake-tts-down", "tts", "synthesis is unavailable"))
        line = await new_line(env, live, tts=tts)
        await line.start()
        await line.spoke(1)  # the greeting could not be spoken

        async def listening() -> bool:
            return any(e["type"] == "call.listening" for e in await line.events())

        await line.until(listening, "the call to carry on after the failed greeting")
        await env.advance(15)  # the silence prompt cannot be spoken either
        final = await line.ended()
        assert "could not hear or speak" in final["summary"]["text"] and "AI disclosure" in final["summary"]["text"]
        events = await line.events()
        assert any(e["type"] == "provider.error" and e["data"]["stage"] == "play" for e in events)
        assert line.kit.rest.hangups == [SID]
        record("G speech synthesis down", final, line=line)
        await line.stop()


async def test_g_one_transient_failure_does_not_end_the_call():
    async with running_env(**TWILIO) as env, serving(env) as live:
        tts = RecordingTts(error=ProviderError("fake-tts", "tts", "a transient synthesis error"))
        line = await new_line(env, live, Script(text=DELIVERY, language="en-IN", confidence=0.92), tts=tts)
        await line.start()
        await line.spoke(1)  # the greeting fails once ...

        async def listening() -> bool:
            return any(e["type"] == "call.listening" for e in await line.events())

        await line.until(listening, "the call to carry on after the failed greeting")
        tts.error = None  # ... and the synthesiser recovers
        await line.speak()
        await line.spoke(2)
        runtime = env.container.calls._runtimes[line.call_id]

        async def recovered() -> bool:
            return not runtime.stage_failures

        await line.until(recovered, "the failure count to reset once the caller heard something")
        assert (await line.detail())["status"] == "active" and line.kit.rest.hangups == []
        await line.stop()


async def test_g_a_model_that_is_down_does_not_change_the_deterministic_safety_decision():
    async with running_env(**TWILIO) as env, serving(env) as live:
        env.container.calls.llm = DownModel()  # type: ignore[assignment]
        line = await new_line(env, live, Script(text=SCAM_EN, language="en-IN", confidence=0.9))
        await line.start()
        await line.spoke(1)
        sent = await line.speak()
        final = await line.ended()
        assert final["risk_level"] == "high" and final["action_taken"] == "refused_and_ended"
        never_asks_for_protected_details(line)
        record(
            "G language model down", final, line=line, sent_at=sent, notes="the engine decides; the model is advisory"
        )
        await line.stop()


# ------------------------------------------------------------------------------------------------------------- H
async def test_h_duplicate_provider_deliveries_change_nothing_twice():
    async with running_env(**TWILIO) as env, serving(env) as live:
        line = await new_line(env, live, Script(text=DELIVERY, language="en-IN", confidence=0.92))
        first = await line.kit.voice(SID)
        again = await line.kit.voice(SID)  # Twilio retried the webhook
        assert again.text == first.text and len(await phone_calls(env)) == 1
        line.call_id = (await phone_calls(env))[0]["id"]
        token = twiml(first).find("./Connect/Stream/Parameter").attrib["value"]  # type: ignore[union-attr]
        await line.connect(SID, token)
        await line.spoke(1)
        spoken_before = len(line.tts.requests)
        # the media socket reconnects: the greeting is not played a second time
        old = line.ws
        await line.connect(SID, token)
        await asyncio.sleep(0.1)
        await old.close()
        assert len(line.tts.requests) == spoken_before and (await line.detail())["status"] == "active"
        await line.speak()
        await line.spoke(2)
        # duplicate takeover requests with one idempotency key cause one transfer
        prefs = (await env.client.get(f"{API}/preferences", headers=PHONE_OWNER)).json()
        await env.client.put(
            f"{API}/preferences", json={**prefs, "takeover_number": "+919812345670"}, headers=PHONE_OWNER
        )
        headers = {**PHONE_OWNER, "Idempotency-Key": "takeover-1"}
        one = await env.client.post(f"{API}/calls/{line.call_id}/takeover", headers=headers)
        two = await env.client.post(f"{API}/calls/{line.call_id}/takeover", headers=headers)
        assert one.status_code == 200 and two.status_code == 200
        assert len(line.kit.rest.redirects) == 1
        # duplicate end-of-call events end it once
        await line.stop()
        for _ in range(2):
            assert (await line.kit.status(SID, "completed")).status_code == 200
        final = await line.ended()
        assert line.kit.rest.hangups == [] and len(await phone_calls(env)) == 1
        record("H duplicate webhook / media / takeover / status events", final, line=line)
