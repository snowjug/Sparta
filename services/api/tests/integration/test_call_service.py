"""End-to-end behaviour of the call service with simulator providers, a virtual clock and an in-memory database."""

import asyncio

import pytest
from call_harness import OTHER, OWNER, Harness, running_container

from sparta.db.repository import CallFilter
from sparta.domain.enums import (
    CallCategory,
    CallState,
    CallStatus,
    EscalationStatus,
    EventType,
    FeedbackKind,
    OwnerActionType,
    RiskLevel,
    TurnSource,
)
from sparta.observability import metrics as mt
from sparta.services.dto import CreateCallRequest
from sparta.services.errors import Conflict, InvalidInput, NotFound, RateLimited

SCAM = "Hello, this is Rahul from State Bank of India. Please share the OTP sent to your phone."
DELIVERY = (
    "Hello, I am calling from Amazon delivery. I am outside your building with your parcel, can someone come down?"
)


def event_types(events) -> list[str]:
    return [e.type for e in events]


# ------------------------------------------------------------------------------------------ scam handling
async def test_otp_scam_is_refused_ended_and_summarised(h: Harness):
    created = await h.start()
    assert created.status is CallStatus.ACTIVE and created.simulated and created.capabilities.simulated
    assert [t.speaker.value for t in created.turns] == ["assistant"]
    assert "AI call assistant" in created.turns[0].text

    result = await h.say(created.id, SCAM)
    assert result.ended and result.state is CallState.END_SPAM
    assert "can't share or accept" in result.assistant_turn.text

    detail = await h.detail(created.id)
    assert detail.status is CallStatus.ENDED and detail.state is CallState.COMPLETED
    assert detail.risk_level is RiskLevel.HIGH and detail.category is CallCategory.POSSIBLE_FINANCIAL_IMPERSONATION
    assert detail.action_taken == "refused_and_ended"
    assert detail.summary and "one-time password" in detail.summary.text
    assert detail.duration_ms is not None and detail.duration_ms > 0
    assert detail.metrics["caller_turns"] == 1
    assert detail.capabilities.can_take_over is False  # nothing to take over once the call has ended
    assert created.id not in h.c.calls._runtimes


@pytest.mark.parametrize(
    ("language", "text", "locale"),
    [
        ("hinglish", "Namaste, main SBI se bol raha hoon. Aapka account block ho jayega, abhi OTP bataiye", "hi-IN"),
        ("kanglish", "Namaskara, nanu bank inda maatadtidini. Nimma account block aagide, OTP heli", "kn-IN"),
        ("kannada", "ನಿಮ್ಮ ಖಾತೆ ಬ್ಲಾಕ್ ಆಗಿದೆ, ಒಟಿಪಿ ಹೇಳಿ", "kn-IN"),
    ],
)
async def test_scams_in_indian_languages_are_refused_in_the_callers_language(h: Harness, language, text, locale):
    created = await h.start()
    result = await h.say(created.id, text)
    assert result.ended
    assert result.assistant_turn.speech.locale == locale, language
    detail = await h.detail(created.id)
    assert detail.status is CallStatus.ENDED and detail.risk_level is RiskLevel.HIGH
    assert locale in detail.languages


async def test_events_are_persisted_in_order_and_match_what_subscribers_received(h: Harness):
    sub = h.c.hub.subscribe(OWNER.id, None)
    assert sub is not None
    created = await h.start()
    await h.say(created.id, SCAM)
    received = []
    while not sub.queue.empty():
        received.append(sub.queue.get_nowait())
    stored = await h.c.calls.events(OWNER, created.id, 0)
    assert [e.seq for e in stored] == list(range(1, len(stored) + 1))
    assert [(e.type, e.seq) for e in received] == [(e.type, e.seq) for e in stored]
    types = event_types(stored)
    assert types[0] == "call.created" and types[-2:] == ["call.ended", "summary.created"]
    assert types.index("risk.updated") < types.index("call.ended")
    assert all(e.simulated for e in stored)
    assert await h.c.calls.events(OWNER, created.id, stored[-1].seq) == []


async def test_a_noisy_low_confidence_transcript_is_asked_to_repeat_not_assessed_as_safe(h: Harness):
    created = await h.start()
    result = await h.say(created.id, "mm aa hello", stt_confidence=0.3)
    assert result.state is CallState.CLARIFY and not result.ended
    detail = await h.detail(created.id)
    assert detail.risk_level in (RiskLevel.UNKNOWN, RiskLevel.LOW) and detail.status is CallStatus.ACTIVE


# --------------------------------------------------------------------------------- escalation and owner
async def test_legitimate_call_escalates_once_and_owner_can_let_sparta_continue(h: Harness):
    created = await h.start()
    first = await h.say(created.id, DELIVERY)
    assert first.state is CallState.ESCALATE and first.escalation is not None
    detail = await h.detail(created.id)
    assert detail.owner_attention_required and detail.category is CallCategory.LEGITIMATE_DELIVERY
    assert [e.status for e in detail.escalations] == [EscalationStatus.REQUESTED]

    action = await h.c.calls.owner_action(OWNER, created.id, OwnerActionType.CONTINUE)
    await h.settle(created.id)
    assert action.action.simulated is True and action.call.state is CallState.IDENTIFY_PURPOSE
    again = await h.say(created.id, "I am waiting at the gate, it is flat 402")
    assert again.escalation is None and again.state is not CallState.ESCALATE
    detail = await h.detail(created.id)
    assert [e.status for e in detail.escalations] == [EscalationStatus.CONTINUED]
    assert [a.action for a in detail.owner_actions] == [OwnerActionType.CONTINUE]


async def test_owner_notification_is_sent_for_escalation_only(h: Harness):
    created = await h.start()
    await h.say(created.id, DELIVERY)
    sent = h.c.notifier.sent  # type: ignore[attr-defined]
    assert [n.kind for _, n in sent] == ["escalation"]
    assert sent[0][0] == OWNER.id and "(simulated call)" in sent[0][1].body and sent[0][1].call_id == created.id
    scam = await h.start(number="+919811111111")
    await h.say(scam.id, SCAM)
    assert len(h.c.notifier.sent) == 1  # type: ignore[attr-defined]


async def test_takeover_stops_the_assistant_but_keeps_assessing_and_is_labelled_simulated(h: Harness):
    created = await h.start()
    await h.say(created.id, DELIVERY)
    result = await h.c.calls.owner_action(OWNER, created.id, OwnerActionType.TAKEOVER)
    assert result.action.simulated and "Simulated" in (result.action.detail or "")
    assert result.capabilities.takeover_note and "simulated" in result.capabilities.takeover_note.lower()
    await h.settle(created.id)
    spoken_before = len((await h.detail(created.id)).turns)
    reply = await h.say(created.id, "Hello? Please tell me the OTP now")
    assert reply.assistant_turn is None and reply.state is CallState.OWNER_TAKEOVER
    detail = await h.detail(created.id)
    assert len(detail.turns) == spoken_before + 1  # the caller's turn is recorded, nothing was spoken
    assert any(s.code.value == "OTP_REQUEST" for s in (detail.risk.signals if detail.risk else []))
    await h.c.calls.owner_action(OWNER, created.id, OwnerActionType.END)
    await h.settle(created.id)
    ended = await h.detail(created.id)
    assert ended.status is CallStatus.ENDED and ended.action_taken == "owner_ended_call"
    assert "owner.takeover" in event_types(await h.c.calls.events(OWNER, created.id, 0))


async def test_continue_is_refused_when_sparta_is_not_waiting_for_the_owner(h: Harness):
    created = await h.start()
    with pytest.raises(Conflict):
        await h.c.calls.owner_action(OWNER, created.id, OwnerActionType.CONTINUE)


async def test_owner_who_never_answers_gets_replaced_by_a_message_after_the_window(h: Harness):
    created = await h.start()
    await h.say(created.id, DELIVERY, settle=False)  # the 30 s owner window starts with this turn
    await h.advance(29.0, created.id)
    assert (await h.detail(created.id)).state is CallState.ESCALATE
    await h.advance(2.0, created.id)
    detail = await h.detail(created.id)
    assert detail.state is CallState.SAFE_CONTINUE and detail.action_taken == "owner_unavailable_took_message"
    assert [e.status for e in detail.escalations] == [EscalationStatus.EXPIRED]
    assert detail.turns[-1].speaker.value == "assistant" and "message" in detail.turns[-1].text.lower()


async def test_owner_decision_cancels_the_pending_owner_timeout(h: Harness):
    created = await h.start()
    await h.say(created.id, DELIVERY, settle=False)
    await h.c.calls.owner_action(OWNER, created.id, OwnerActionType.TAKEOVER)
    await h.advance(120.0, created.id)
    assert (await h.detail(created.id)).state is CallState.OWNER_TAKEOVER


# ------------------------------------------------------------------------------------ timers and limits
async def test_silence_is_reprompted_once_and_then_the_call_closes(h: Harness):
    created = await h.start(timers="preferences")
    await h.settle(created.id)
    await h.advance(8.5, created.id)
    detail = await h.detail(created.id)
    assert detail.status is CallStatus.ACTIVE and detail.turns[-1].speaker.value == "assistant"
    assert len(detail.turns) == 2
    await h.settle(created.id)
    await h.advance(8.5, created.id)
    await h.settle(created.id)
    final = await h.detail(created.id)
    assert final.status is CallStatus.ENDED and len(final.turns) == 3


async def test_speaking_cancels_the_silence_timer(h: Harness):
    created = await h.start(timers="preferences")
    await h.settle(created.id)
    await h.advance(5.0, created.id)
    await h.say(created.id, "Hi, I am Suresh from the society office", settle=False)
    await h.settle(created.id)
    await h.advance(3.5, created.id)  # 8.5 s since the greeting, but the caller spoke in between
    detail = await h.detail(created.id)
    assert [t.speaker.value for t in detail.turns].count("assistant") == 2


async def test_silent_timers_can_be_disabled_for_scripted_runs(h: Harness):
    created = await h.start(timers="off")
    await h.settle(created.id)
    await h.advance(60.0, created.id)
    assert (await h.detail(created.id)).status is CallStatus.ACTIVE


async def test_the_duration_limit_ends_the_call_gracefully(h: Harness):
    created = await h.start()
    await h.settle(created.id)
    await h.advance(181.0, created.id)
    await h.settle(created.id)
    detail = await h.detail(created.id)
    assert detail.status is CallStatus.ENDED
    assert detail.turns[-1].speaker.value == "assistant"
    assert detail.summary is not None


async def test_barge_in_marks_the_interrupted_assistant_turn_and_lets_the_caller_continue(h: Harness):
    created = await h.start()
    assistant_turn = created.turns[0]
    result = await h.c.calls.interrupt(OWNER, created.id, spoken_fraction=0.4)
    assert result.interrupted and result.turn_id == assistant_turn.id and result.spoken_fraction == 0.4
    detail = await h.detail(created.id)
    assert detail.turns[0].interrupted and detail.turns[0].spoken_fraction == 0.4
    assert detail.turns[0].latency and detail.turns[0].latency.interruption_ms is not None
    assert "assistant.interrupted" in event_types(await h.c.calls.events(OWNER, created.id, 0))
    nothing = await h.c.calls.interrupt(OWNER, created.id)
    assert nothing.interrupted is False
    await h.say(created.id, "Hello, this is Suresh from the society office about maintenance", settle=False)


async def test_speech_that_already_ended_is_finished_before_the_next_caller_turn(h: Harness):
    created = await h.start()
    rt = h.c.calls._runtimes[created.id]
    assert rt.playback_id is not None
    rt.speaking_until = h.clock.monotonic() - 0.01  # the estimate has elapsed but the completion has not been delivered
    result = await h.c.calls.submit_turn(
        OWNER, created.id, "Hello, this is Suresh from the society office", source=TurnSource.SCRIPTED
    )
    assert result.interrupted_turn_id is None
    types = event_types(await h.c.calls.events(OWNER, created.id, 0))
    caller_turn = [i for i, t in enumerate(types) if t == "transcript.final"][1]
    assert types.index("assistant.finished") < caller_turn
    assert types.count("assistant.finished") == 1 and "assistant.interrupted" not in types
    await h.settle(created.id)
    assert event_types(await h.c.calls.events(OWNER, created.id, 0)).count("assistant.interrupted") == 0


async def test_the_call_detail_says_when_the_assistant_is_mid_utterance(h: Harness):
    created = await h.start()
    speaking = await h.detail(created.id)
    assert speaking.assistant_speaking is True and speaking.speaking_turn_id == created.turns[0].id
    snapshot = await h.c.calls.snapshot_event(OWNER, created.id)
    assert snapshot.data["call"]["assistant_speaking"] is True
    await h.settle(created.id)
    done = await h.detail(created.id)
    assert done.assistant_speaking is False and done.speaking_turn_id is None


async def test_a_caller_talking_over_the_assistant_interrupts_it_automatically(h: Harness):
    created = await h.start()
    await h.clock.advance(1.0)
    result = await h.c.calls.submit_turn(OWNER, created.id, "Hello? Is anyone there?", source=TurnSource.SCRIPTED)
    assert result.interrupted_turn_id == created.turns[0].id
    detail = await h.detail(created.id)
    assert detail.turns[0].interrupted and 0.0 < (detail.turns[0].spoken_fraction or 0) < 1.0


async def test_concurrent_turns_are_serialised_and_every_turn_is_persisted_once(h: Harness):
    created = await h.start()
    await h.settle(created.id)
    results = await asyncio.gather(
        *(
            h.c.calls.submit_turn(OWNER, created.id, f"Hello this is caller number {i}", source=TurnSource.SCRIPTED)
            for i in range(4)
        ),
        return_exceptions=True,
    )
    assert not [r for r in results if isinstance(r, Exception)]
    detail = await h.detail(created.id)
    seqs = [t.seq for t in detail.turns]
    assert seqs == sorted(set(seqs)) and len(seqs) == len(detail.turns)
    assert sum(1 for t in detail.turns if t.speaker.value == "caller") == 4


# -------------------------------------------------------------------------------- blocked, trusted, caps
async def test_blocked_numbers_are_ended_without_being_answered(h: Harness):
    first = await h.start(number="+919876500001")
    await h.say(first.id, SCAM)
    entry = await h.c.calls.block(OWNER, first.id, "spam")
    assert entry.reason == "spam" and entry.number_display.startswith("+91")
    second = await h.start(number="+919876500001")
    assert second.status is CallStatus.ENDED and second.blocked and not second.turns
    assert second.summary and "blocked list" in second.summary.text
    assert [e.type for e in await h.c.calls.events(OWNER, second.id, 0)][-2:] == ["call.ended", "summary.created"]
    other_number = await h.start(number="+919876500002")
    assert other_number.status is CallStatus.ACTIVE and not other_number.blocked


async def test_trusted_callers_pass_straight_through_in_the_simulator(h: Harness):
    first = await h.start(number="+919876500003")
    await h.say(first.id, "Hi, this is Suresh from the society office")
    await h.c.calls.trust(OWNER, first.id, "Suresh")
    await h.c.calls.owner_action(OWNER, first.id, OwnerActionType.END)
    await h.settle(first.id)
    second = await h.start(number="+919876500003")
    assert second.status is CallStatus.ENDED and second.trusted and "simulated" in second.summary.text
    assert second.owner_attention_required


async def test_block_during_a_live_call_hangs_up_and_is_recorded(h: Harness):
    created = await h.start(number="+919876500004")
    await h.say(created.id, "Hi this is Suresh from the society office about the water tank")
    assert (await h.detail(created.id)).status is CallStatus.ACTIVE
    await h.c.calls.block(OWNER, created.id, None)
    await h.settle(created.id)
    detail = await h.detail(created.id)
    assert detail.status is CallStatus.ENDED and detail.blocked and detail.action_taken == "owner_blocked_caller"
    assert OwnerActionType.BLOCK in [a.action for a in detail.owner_actions]


async def test_a_call_without_a_number_cannot_be_blocked(h: Harness):
    created = await h.start(number=None)
    assert created.caller_display == "Simulated caller"
    with pytest.raises(Conflict):
        await h.c.calls.block(OWNER, created.id, None)


async def test_daily_call_cap_is_enforced_with_a_retry_hint():
    async with running_container(daily_call_cap=2) as c:
        h = Harness(c)
        for _ in range(2):
            made = await h.start(number=None)
            await c.calls.owner_action(OWNER, made.id, OwnerActionType.END)
            await h.settle(made.id)
        with pytest.raises(RateLimited) as exc:
            await h.start(number=None)
        assert 0 < exc.value.retry_after_s <= 86400


async def test_too_many_simultaneous_calls_are_refused():
    async with running_container(max_active_calls=1) as c:
        h = Harness(c)
        await h.start(number=None)
        with pytest.raises(Conflict):
            await h.start(number=None)


async def test_unsupported_language_mode_is_rejected_clearly(h: Harness):
    with pytest.raises(InvalidInput, match="Unsupported language"):
        await h.start(language_mode="fr-FR")


async def test_empty_turns_and_turns_after_the_call_ended_are_rejected(h: Harness):
    created = await h.start()
    with pytest.raises(InvalidInput):
        await h.c.calls.submit_turn(OWNER, created.id, "   ", source=TurnSource.TYPED)
    await h.say(created.id, SCAM)
    with pytest.raises(Conflict):
        await h.c.calls.submit_turn(OWNER, created.id, "wait", source=TurnSource.TYPED)


async def test_real_providers_cannot_create_calls_through_the_simulator_route(h: Harness):
    # The configured provider is the simulator, so this is allowed; a real provider would raise UnsupportedByProvider.
    detail = await h.c.calls.create_call(OWNER, CreateCallRequest(), simulator=False)
    assert detail.provider.value == "simulator"


# -------------------------------------------------------------------------------- network and latency
async def test_network_profiles_add_simulated_latency_and_label_the_stages(h: Harness):
    ideal = await h.start(network="ideal")
    result = await h.say(ideal.id, SCAM)
    assert result.assistant_turn.latency and result.assistant_turn.latency.simulated_stages == []

    congested = await h.start(number="+919800000009", network="congested")
    task = asyncio.create_task(h.say(congested.id, SCAM))
    for _ in range(40):  # the call service waits on the virtual clock for the simulated network
        await asyncio.sleep(0.01)
        await h.clock.advance(1.0)
        if task.done():
            break
    result = await asyncio.wait_for(task, 5)
    stages = result.assistant_turn.latency.simulated_stages
    assert "tts_first_audio_ms" in stages and result.assistant_turn.latency.total_ms > 800


# ---------------------------------------------------------------------------------------- feedback
async def test_feedback_is_idempotent_per_kind_and_trust_feedback_trusts_the_caller(h: Harness):
    created = await h.start(number="+919876500005")
    await h.say(created.id, "Hi this is Suresh from the society office about the water tank")
    first = await h.c.calls.feedback(OWNER, created.id, FeedbackKind.WAS_LEGITIMATE, "note one")
    again = await h.c.calls.feedback(OWNER, created.id, FeedbackKind.WAS_LEGITIMATE, "note two")
    assert first.id == again.id and again.note == "note two"  # one record per kind; the latest note wins
    await h.c.calls.feedback(OWNER, created.id, FeedbackKind.TRUST_CALLER, None)
    detail = await h.detail(created.id)
    assert {f.kind for f in detail.feedback} == {FeedbackKind.WAS_LEGITIMATE, FeedbackKind.TRUST_CALLER}
    assert detail.trusted and not detail.blocked
    assert h.c.metrics.counter(mt.FEEDBACK_TOTAL, kind="was_legitimate") == 1


# ----------------------------------------------------------------------------------- privacy and data
async def test_full_numbers_are_not_stored_unless_the_owner_opted_in(h: Harness):
    created = await h.start(number="+919876543210")
    async with h.c.db.uow() as repo:
        row = await repo.get_call_row(OWNER.id, created.id)
        assert row.caller_number_enc is None and row.caller_fingerprint
        assert "9876543210" not in (row.caller_display or "")
    dumped = (await h.detail(created.id)).model_dump_json()
    assert "9876543210" not in dumped and "98765" not in dumped


async def test_not_storing_transcripts_keeps_the_summary_but_drops_the_words(h: Harness):
    async with h.c.db.uow() as repo:
        prefs = await repo.get_preferences(OWNER.id)
        prefs.retention.store_transcripts = False
        await repo.ensure_user(OWNER.id, "Atharv", h.clock.now())
        await repo.save_preferences(OWNER.id, prefs, h.clock.now())
    created = await h.start()
    await h.say(created.id, SCAM)
    detail = await h.detail(created.id)
    assert detail.status is CallStatus.ENDED and detail.summary and not detail.has_content
    assert detail.turns == [] and detail.risk_level is RiskLevel.HIGH


async def test_deleting_content_keeps_risk_and_timestamps_and_deleting_the_call_removes_it(h: Harness):
    created = await h.start()
    await h.say(created.id, SCAM)
    await h.c.calls.delete_content(OWNER, created.id)
    detail = await h.detail(created.id)
    assert detail.turns == [] and not detail.has_content and detail.risk_level is RiskLevel.HIGH
    await h.c.calls.delete_call(OWNER, created.id)
    with pytest.raises(NotFound):
        await h.detail(created.id)


async def test_content_of_a_live_call_cannot_be_deleted(h: Harness):
    created = await h.start()
    with pytest.raises(Conflict):
        await h.c.calls.delete_content(OWNER, created.id)
    with pytest.raises(Conflict):
        await h.c.calls.delete_call(OWNER, created.id)


async def test_delete_all_content_covers_every_ended_call(h: Harness):
    for number in ("+919800000011", "+919800000012"):
        made = await h.start(number=number)
        await h.say(made.id, SCAM)
    assert await h.c.calls.delete_all_content(OWNER) == 2
    items, _ = await h.c.calls.list_calls(OWNER, CallFilter())
    assert len(items) == 2 and not any(i.has_content for i in items)


async def test_the_diagnostic_report_has_no_transcript_text_names_or_numbers(h: Harness):
    created = await h.start(number="+919876543210", label="Rahul")
    await h.say(created.id, SCAM)
    report = await h.c.calls.diagnostic_report(OWNER, created.id)
    text = str(report)
    for forbidden in ("Rahul", "State Bank", "9876543210", "OTP sent to your phone", "AI call assistant"):
        assert forbidden not in text
    assert report["contains_transcript"] is False and report["risk"]["level"] == "high"
    assert report["event_counts"]["call.ended"] == 1 and report["latency_ms"]["total_ms"]["count"] >= 1


# ------------------------------------------------------------------------------------------ isolation
async def test_another_owner_cannot_read_drive_or_delete_a_call(h: Harness):
    created = await h.start(number="+919876500006")
    intruder = Harness(h.c, OTHER)
    calls = h.c.calls
    probes = [
        calls.get_call(OTHER, created.id),
        calls.events(OTHER, created.id, 0),
        calls.submit_turn(OTHER, created.id, "hello", source=TurnSource.TYPED),
        calls.silence(OTHER, created.id),
        calls.interrupt(OTHER, created.id),
        calls.owner_action(OTHER, created.id, OwnerActionType.END),
        calls.block(OTHER, created.id, None),
        calls.trust(OTHER, created.id, None),
        calls.feedback(OTHER, created.id, FeedbackKind.WAS_SPAM, None),
        calls.delete_content(OTHER, created.id),
        calls.delete_call(OTHER, created.id),
        calls.diagnostic_report(OTHER, created.id),
    ]
    for probe in probes:
        with pytest.raises(NotFound):
            await probe
    items, _ = await calls.list_calls(OTHER, CallFilter())
    assert items == []
    assert (await intruder.start(number=None)).id != created.id
    assert (await h.detail(created.id)).status is CallStatus.ACTIVE  # untouched


async def test_blocking_is_per_owner(h: Harness):
    first = await h.start(number="+919876500007")
    await h.say(first.id, SCAM)
    await h.c.calls.block(OWNER, first.id, None)
    other = Harness(h.c, OTHER)
    made = await other.start(number="+919876500007")
    assert made.status is CallStatus.ACTIVE and not made.blocked


# -------------------------------------------------------------------------------------- housekeeping
async def test_abandoned_calls_are_reaped_and_active_ones_are_left_alone():
    async with running_container(abandoned_call_timeout_s=60, max_call_duration_s=900) as c:
        h = Harness(c)
        stale = await h.start(number=None)
        await h.settle(stale.id)
        assert await c.calls.reap_abandoned() == 0
        await c.clock.advance(61.0)
        busy = await h.start(number=None)
        await h.settle(busy.id)
        assert await c.calls.reap_abandoned() == 1
        assert (await h.detail(stale.id)).status is CallStatus.ENDED
        assert (await h.detail(busy.id)).status is CallStatus.ACTIVE
        summary = (await h.detail(stale.id)).summary
        assert summary is not None


async def test_a_caller_hanging_up_ends_the_call_without_speaking(h: Harness):
    created = await h.start()
    await h.say(created.id, "Hello, I am calling about your delivery")
    spoken = len((await h.detail(created.id)).turns)
    await h.c.calls.remote_hangup(created.id, "provider hangup")
    detail = await h.detail(created.id)
    assert detail.status is CallStatus.ENDED and len(detail.turns) == spoken
    assert any(e.type == EventType.CALL_ENDED.value for e in await h.c.calls.events(OWNER, created.id, 0))
    await h.c.calls.remote_hangup(created.id, "again")  # idempotent


async def test_runtime_is_rebuilt_from_the_database_after_a_restart(h: Harness):
    created = await h.start()
    await h.settle(created.id)
    h.c.calls._runtimes.clear()  # simulate a process restart: in-memory state is gone, the database remains
    result = await h.say(created.id, SCAM)
    assert result.ended
    assert (await h.detail(created.id)).status is CallStatus.ENDED
