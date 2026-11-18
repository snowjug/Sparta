"""Test factories for persistence tests."""

from datetime import UTC, datetime, timedelta

from sparta.db import models as m
from sparta.domain.enums import CallState, CallStatus, Speaker, TurnSource
from sparta.domain.models import CallTurn, ConversationContext

T0 = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)


def call_row(call_id: str, user_id: str = "u1", *, minutes: int = 0, **overrides) -> m.CallSessionRow:
    values = {
        "id": call_id,
        "user_id": user_id,
        "provider": "simulator",
        "mode": "conversational",
        "simulated": True,
        "status": CallStatus.ENDED.value,
        "state": CallState.COMPLETED.value,
        "language_mode": "auto",
        "started_at": T0 + timedelta(minutes=minutes),
        "ended_at": T0 + timedelta(minutes=minutes, seconds=30),
        "duration_ms": 30000,
        "caller_display": "+91 98•••• ••21",
        "category": "unknown",
        "risk_level": "low",
        "risk_score": 0.1,
        "confidence": 0.5,
        "signal_codes": [],
        "languages": ["en-IN"],
        "owner_attention": False,
        "blocked": False,
        "trusted": False,
        "has_content": True,
        "context": ConversationContext(state=CallState.COMPLETED).model_dump(mode="json"),
        "trace_id": "t" * 32,
        "versions": {},
        "metrics": {},
        "event_seq": 0,
    }
    values.update(overrides)
    return m.CallSessionRow(**values)


def turn(call_id: str, seq: int, text: str, speaker: Speaker = Speaker.CALLER) -> CallTurn:
    return CallTurn(
        id=f"turn_{seq}",
        call_id=call_id,
        seq=seq,
        speaker=speaker,
        text=text,
        language="en-IN",
        source=TurnSource.TYPED if speaker is Speaker.CALLER else TurnSource.ASSISTANT,
        created_at=T0 + timedelta(seconds=seq),
    )
