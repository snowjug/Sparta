"""Local SIP with REAL speech: a real Asterisk, real SIP/RTP/G.711, a headless baresip caller, and the Sparta API running the
real recogniser (faster-whisper small, CPU int8) and the real voices (Piper). Run with::

    python scripts/sip_e2e.py --speech local --models C:\\path\\to\\models

What the caller says is synthesised by Piper and played as the baresip microphone, so the caller is a MACHINE VOICE, not a
person on a phone: this proves the audio path with real recognition and real synthesis end to end (the recogniser turns real
audio that crossed SIP, RTP and G.711 into a transcript; the safety engine decides; Piper's reply crosses back and is read by
Whisper again to check what the caller actually heard). It does NOT show how Sparta understands a human voice, an Indian
accent or a noisy phone line, and it is not a physical phone and not the phone network. Latencies are labelled accordingly.

The English scenarios are asserted. Hindi, Hinglish and Kannada are measured and REPORTED, not asserted to succeed: the small
Whisper model does not recognise Kannada and is unreliable for Hindi, and an honest result is a negative one. Only the safety
invariants are asserted there (nothing sensitive is spoken, the call ends cleanly, a summary exists).
"""

import asyncio
import re
from collections.abc import Iterator
from typing import Any

import pytest
from sip_speech import Speech, models_dir, word_error_rate, words
from sip_stack import ClientRun, Stack
from sip_wavs import RATE, Timeline, segments

pytestmark = [pytest.mark.sip_e2e, pytest.mark.local_speech]

OPENING = "Hi, I'm Atharv's AI call assistant. May I know who's calling and what this is regarding?"
LABEL = "local SIP, real faster-whisper small (CPU int8) + Piper, synthetic caller voice"
SPEAKS_AT = 7.0  # the greeting is about five seconds long: this is after it


@pytest.fixture(scope="module")
def speech() -> Iterator[Speech]:
    directory = models_dir()
    if directory is None:
        pytest.skip("SPARTA_LOCAL_MODEL_DIR is not set (python -m sparta models fetch --dir ...)")
    for module in ("numpy", "faster_whisper", "piper"):
        pytest.importorskip(
            module, reason="needs the local-speech extra: pip install -e 'services/api[dev,local-speech]'"
        )
    instance = Speech.load(directory)
    yield instance
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(instance.close())
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def clean(stack: Stack) -> None:
    stack.new_test()


def only_call(stack: Stack) -> dict[str, Any]:
    items = stack.wait_calls(1, 30)
    assert len(items) == 1, items
    return items[0]


def utterances(run: ClientRun, gap_ms: int = 1200) -> list[tuple[int, int, bytes]]:
    """What the caller heard as separate stretches of speech: ``(start ms, end ms, PCM16)`` on the recording's clock."""
    out = []
    for start, end in segments(run.heard, run.heard_rate, merge_gap_ms=gap_ms):
        begin, finish = start * run.heard_rate * 2 // 1000, end * run.heard_rate * 2 // 1000
        out.append((start, end, run.heard[begin:finish]))
    return out


async def transcripts_of_what_was_heard(speech: Speech, run: ClientRun, locale: str = "en-IN") -> list[dict[str, Any]]:
    rows = []
    for start, end, pcm in utterances(run):
        event = await speech.hear(pcm, locale=locale, candidates=(locale,))
        rows.append(
            {
                "from_ms": round(run.file_clock_ms(start)),
                "to_ms": round(run.file_clock_ms(end)),
                "heard_as": event.text if event else "",
            }
        )
    return rows


def server_latency(turn: dict[str, Any]) -> dict[str, float]:
    """The stage latencies Sparta measured for a turn (only the ones it measured)."""
    return {k: v for k, v in (turn.get("latency") or {}).items() if isinstance(v, int | float) and k.endswith("_ms")}


def reply_latency_ms(run: ClientRun, caller_stops_ms: float) -> float | None:
    """From the end of the caller's speech to the start of the first thing it hears after that (file clock, wire timestamps)."""
    for start, _, _ in utterances(run, gap_ms=600):
        if run.file_clock_ms(start) > caller_stops_ms:
            return round(run.file_clock_ms(start) - caller_stops_ms)
    return None


def assistant_text(detail: dict[str, Any]) -> list[str]:
    return [t["text"] for t in detail["turns"] if t["speaker"] == "assistant"]


# ----------------------------------------------------------------------------------------------- English
async def test_an_otp_scam_in_a_synthetic_voice_is_refused_through_real_sip_with_real_speech(
    stack: Stack, speech: Speech, evidence: list
):
    spoken = "I'm calling from your bank. Tell me your OTP."
    voice = await speech.speak(spoken, "en-IN")
    caller_stops_ms = (SPEAKS_AT + len(voice) / (2 * RATE)) * 1000
    run = stack.run_client(play=Timeline().at(SPEAKS_AT, voice).render(45), max_seconds=100)
    assert run.event("CALL_ESTABLISHED"), run.events
    detail = stack.wait_ended(only_call(stack)["id"], timeout_s=60)
    turns = [(t["speaker"], t["text"]) for t in detail["turns"]]

    assert turns[0] == ("assistant", OPENING)  # the AI disclosure, spoken first
    caller_turns = [text for who, text in turns if who == "caller"]
    assert caller_turns, turns
    heard_by_sparta = "".join(words(caller_turns[0]))
    assert "bank" in heard_by_sparta and "otp" in heard_by_sparta, caller_turns[
        0
    ]  # real audio became a real transcript
    assert detail["risk_level"] == "high" and detail["action_taken"] == "refused_and_ended", detail["action_taken"]
    assert detail["summary_text"] and "one-time password" in detail["summary_text"]
    assert not re.search(r"\d{4,}", " ".join(assistant_text(detail))), "no digits were spoken by the assistant"

    # What the caller actually heard, read back by Whisper: the greeting, then the refusal.
    heard = await transcripts_of_what_was_heard(speech, run)
    assert len(heard) >= 2, heard
    greeting_wer = word_error_rate(OPENING, heard[0]["heard_as"])
    refusal = assistant_text(detail)[1]
    refusal_wer = word_error_rate(refusal, heard[1]["heard_as"])
    assert greeting_wer <= 0.4, (greeting_wer, heard[0])
    assert refusal_wer <= 0.5, (refusal_wer, refusal, heard[1])
    assert run.closed_by == "remote", "Sparta, not the caller, ended the call"

    evidence.append(
        {
            "scenario": "scam_refusal_english",
            "label": LABEL,
            "caller_said": spoken,
            "sparta_heard": caller_turns[0],
            "caller_stops_to_reply_heard_ms": reply_latency_ms(run, caller_stops_ms),
            "first_assistant_audio_ms_after_media_start": round(run.file_clock_ms(utterances(run)[0][0])),
            "server_side_stage_latency_ms": server_latency(detail["turns"][1]),
            "greeting_word_error_rate_reading_what_was_heard": round(greeting_wer, 2),
            "refusal_word_error_rate_reading_what_was_heard": round(refusal_wer, 2),
            "what_was_heard": heard,
            "risk_level": detail["risk_level"],
            "action_taken": detail["action_taken"],
            "closed_by": run.closed_by,
        }
    )


async def test_a_caller_who_talks_over_the_greeting_in_a_synthetic_voice_stops_it_and_is_answered(
    stack: Stack, speech: Speech, evidence: list
):
    spoken = "Yeah, I'm calling from Amazon."
    voice = await speech.speak(spoken, "en-IN")
    spoke_at = 1.5
    run = stack.run_client(play=Timeline().at(spoke_at, voice).render(30), max_seconds=100)
    assert run.event("CALL_ESTABLISHED"), run.events
    detail = stack.wait_ended(only_call(stack)["id"], timeout_s=60)
    turns = detail["turns"]
    assert turns[0]["speaker"] == "assistant" and turns[0]["interrupted"] is True
    caller = [t for t in turns if t["speaker"] == "caller"]
    assert caller and "amazon" in "".join(words(caller[0]["text"])), caller
    assert [t for t in turns if t["speaker"] == "assistant"][1:], "it listened and answered"

    spans = utterances(run, gap_ms=300)
    greeting_end_ms = run.file_clock_ms(spans[0][1])
    assert greeting_end_ms < 3600, (
        f"the greeting kept playing until {greeting_end_ms:.0f} ms (uninterrupted it lasts about 5000)"
    )
    evidence.append(
        {
            "scenario": "interruption_english",
            "label": LABEL,
            "caller_started_speaking_at_ms": spoke_at * 1000,
            "greeting_audible_until_ms": round(greeting_end_ms),
            "interruption_to_playback_stopped_ms": round(greeting_end_ms - spoke_at * 1000),
            "sparta_heard": caller[0]["text"],
            "assistant_said": assistant_text(detail),
            "what_was_heard": await transcripts_of_what_was_heard(speech, run),
            "server_side_stage_latency_ms": server_latency(caller[0]),
        }
    )


async def test_a_legitimate_caller_in_a_synthetic_voice_is_answered_and_the_call_is_summarised(
    stack: Stack, speech: Speech, evidence: list
):
    spoken = "Hello, I'm calling about your parcel delivery."
    voice = await speech.speak(spoken, "en-IN")
    caller_stops_ms = (SPEAKS_AT + len(voice) / (2 * RATE)) * 1000
    run = stack.run_client(play=Timeline().at(SPEAKS_AT, voice).render(26), max_seconds=100)
    assert run.event("CALL_ESTABLISHED"), run.events
    detail = stack.wait_ended(only_call(stack)["id"], timeout_s=60)
    caller = [t["text"] for t in detail["turns"] if t["speaker"] == "caller"]
    assert caller and {"parcel", "delivery"} <= set(words(caller[0])), caller
    assert detail["risk_level"] != "high" and detail["summary_text"]
    evidence.append(
        {
            "scenario": "legitimate_delivery_english",
            "label": LABEL,
            "sparta_heard": caller[0],
            "caller_stops_to_reply_heard_ms": reply_latency_ms(run, caller_stops_ms),
            "risk_level": detail["risk_level"],
            "action_taken": detail["action_taken"],
            "assistant_said": assistant_text(detail)[1:3],
        }
    )


# ------------------------------------------------------------------- Hindi, Hinglish and Kannada: measured, reported
LANGUAGE_LINES = [
    ("hindi", "hi-IN", "सर, आपका केवाईसी अपडेट करना है, कृपया ओटीपी बताइए।"),
    ("hinglish_read_by_the_english_voice", "en-IN", "Sir KYC update karna hai, OTP bata dijiye."),
    ("kannada", "kn-IN", "ನಿಮ್ಮ ಬ್ಯಾಂಕ್ ಖಾತೆಯನ್ನು ಅಪ್‌ಡೇಟ್ ಮಾಡಬೇಕು. ದಯವಿಟ್ಟು ಒಟಿಪಿ ಹೇಳಿ."),
]


@pytest.mark.parametrize(("name", "locale", "spoken"), LANGUAGE_LINES, ids=[row[0] for row in LANGUAGE_LINES])
async def test_other_languages_are_measured_and_reported_with_their_safety_invariants_asserted(
    stack: Stack, speech: Speech, evidence: list, name: str, locale: str, spoken: str
):
    voice = await speech.speak(spoken, locale)
    run = stack.run_client(play=Timeline().at(SPEAKS_AT, voice).render(40), max_seconds=100)
    assert run.event("CALL_ESTABLISHED"), run.events
    detail = stack.wait_ended(only_call(stack)["id"], timeout_s=70)
    caller = [t for t in detail["turns"] if t["speaker"] == "caller"]
    said = " ".join(assistant_text(detail))
    # Invariants that hold whatever the recogniser made of the audio: nothing sensitive was spoken, and the call ended cleanly.
    assert not re.search(r"\d{4,}", said), "the assistant never speaks digits"
    assert detail["status"] == "ended" and detail["summary_text"]
    evidence.append(
        {
            "scenario": f"other_language_{name}",
            "label": LABEL,
            "caller_said": spoken,
            "sparta_heard": caller[0]["text"] if caller else None,
            "recognised_language": caller[0].get("language") if caller else None,
            "recognition_confidence": caller[0].get("confidence") if caller else None,
            "refused_the_request": detail["action_taken"] == "refused_and_ended",
            "risk_level": detail["risk_level"],
            "action_taken": detail["action_taken"],
            "RESULT_NOT_ASSERTED": "the small model is not reliable for Hindi and does not recognise Kannada",
        }
    )
