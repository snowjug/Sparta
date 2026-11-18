"""Persistence operations.

Every method that touches user data takes ``user_id`` and filters on it: ownership is enforced in the query, not by the
caller remembering to check. Rows are converted to the Pydantic domain models here, so nothing above this layer sees
SQLAlchemy objects or ciphertext.
"""

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sparta.db import models as m
from sparta.domain.enums import (
    CallCategory,
    CallMode,
    CallState,
    CallStatus,
    EscalationStatus,
    FeedbackKind,
    OwnerActionType,
    ProviderKind,
    RiskLevel,
    Speaker,
    TurnSource,
    VoiceStatus,
)
from sparta.domain.models import (
    AssistantProfile,
    BlockedCaller,
    CallDetail,
    CallerClaim,
    CallListItem,
    CallSummary,
    CallTurn,
    ConversationContext,
    Escalation,
    FeedbackRecord,
    LanguageSegment,
    LatencyBreakdown,
    LiveEvent,
    OwnerAction,
    ProviderEventRecord,
    RiskAssessment,
    SpeechPlan,
    TrustedCaller,
    UserPreferences,
    VersionInfo,
    VoiceProfileView,
    utcnow,
)

SCAN_WINDOW = 500


@dataclass
class CallFilter:
    q: str | None = None
    risk_level: str | None = None
    category: str | None = None
    language: str | None = None
    status: str | None = None
    attention: bool | None = None
    provider: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 25
    cursor: str | None = None


def encode_cursor(started_at: datetime, call_id: str) -> str:
    raw = json.dumps([started_at.isoformat(), call_id]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[datetime, str] | None:
    try:
        ts, call_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(ts), str(call_id)
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------------------------- conversions
def turn_from_row(r: m.CallTurnRow) -> CallTurn:
    return CallTurn(
        id=r.id,
        call_id=r.call_id,
        seq=r.seq,
        speaker=Speaker(r.speaker),
        text=r.text,
        transliteration=r.transliteration,
        translation=r.translation,
        language=r.language,
        language_confidence=r.language_confidence,
        language_profile=r.language_profile,
        segments=[LanguageSegment(**s) for s in (r.segments or [])],
        is_final=r.is_final,
        confidence=r.confidence,
        source=TurnSource(r.source),
        interrupted=r.interrupted,
        spoken_fraction=r.spoken_fraction,
        state_after=CallState(r.state_after) if r.state_after else None,
        created_at=r.created_at,
        latency=LatencyBreakdown(**r.latency) if r.latency else None,
        speech=SpeechPlan(**r.speech) if r.speech else None,
    )


def turn_to_row(t: CallTurn) -> m.CallTurnRow:
    return m.CallTurnRow(
        call_id=t.call_id,
        id=t.id,
        seq=t.seq,
        speaker=t.speaker.value,
        text=t.text,
        transliteration=t.transliteration,
        translation=t.translation,
        language=t.language,
        language_confidence=t.language_confidence,
        language_profile=t.language_profile,
        segments=[s.model_dump(mode="json") for s in t.segments],
        is_final=t.is_final,
        confidence=t.confidence,
        source=t.source.value,
        interrupted=t.interrupted,
        spoken_fraction=t.spoken_fraction,
        state_after=t.state_after.value if t.state_after else None,
        created_at=t.created_at,
        latency=t.latency.model_dump(mode="json") if t.latency else None,
        speech=t.speech.model_dump(mode="json") if t.speech else None,
    )


def list_item_from_row(r: m.CallSessionRow) -> CallListItem:
    claim = CallerClaim(**(r.claim or {}))
    return CallListItem(
        id=r.id,
        provider=ProviderKind(r.provider),
        mode=CallMode(r.mode),
        simulated=r.simulated,
        status=CallStatus(r.status),
        state=CallState(r.state),
        started_at=r.started_at,
        ended_at=r.ended_at,
        duration_ms=r.duration_ms,
        caller_display=r.caller_display,
        caller_claim=claim,
        purpose=r.purpose,
        category=CallCategory(r.category),
        risk_level=RiskLevel(r.risk_level),
        risk_score=r.risk_score,
        confidence=r.confidence,
        languages=list(r.languages or []),
        language_profile=r.language_profile,
        summary_text=r.summary_text,
        action_taken=r.action_taken,
        owner_attention_required=r.owner_attention,
        blocked=r.blocked,
        trusted=r.trusted,
        has_content=r.has_content,
    )


def escalation_from_row(r: m.EscalationRow) -> Escalation:
    return Escalation(
        id=r.id,
        call_id=r.call_id,
        reason=r.reason,
        status=EscalationStatus(r.status),
        created_at=r.created_at,
        resolved_at=r.resolved_at,
        important_lines=list(r.important_lines or []),
    )


def action_from_row(r: m.OwnerActionRow) -> OwnerAction:
    return OwnerAction(
        id=r.id,
        call_id=r.call_id,
        action=OwnerActionType(r.action),
        created_at=r.created_at,
        simulated=r.simulated,
        result=r.result,
        detail=r.detail,
    )


def summary_from_row(r: m.CallSummaryRow) -> CallSummary:
    return CallSummary(
        call_id=r.call_id,
        text=r.text,
        category=CallCategory(r.category),
        risk_level=RiskLevel(r.risk_level),
        action_taken=r.action_taken,
        owner_action_required=r.owner_action_required,
        generated_by=r.generated_by,
        created_at=r.created_at,
    )


def feedback_from_row(r: m.FeedbackRow) -> FeedbackRecord:
    return FeedbackRecord(id=r.id, call_id=r.call_id, kind=FeedbackKind(r.kind), note=r.note, created_at=r.created_at)


def _trusted_entry(r: m.TrustedCallerRow) -> TrustedCaller:
    return TrustedCaller(
        id=r.id,
        number_display=r.number_display,
        label=r.label,
        created_at=r.created_at,
        source_call_id=r.source_call_id,
    )


def _blocked_entry(r: m.BlockedCallerRow) -> BlockedCaller:
    return BlockedCaller(
        id=r.id,
        number_display=r.number_display,
        reason=r.reason,
        created_at=r.created_at,
        source_call_id=r.source_call_id,
    )


def _rowcount(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


class Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    # =========================================================================================== users
    async def ensure_user(self, user_id: str, display_name: str, now: datetime) -> None:
        """Create the owner row on first sight. Safe under concurrent first requests (the loser's insert is ignored)."""
        if await self.s.get(m.UserRow, user_id) is not None:
            return
        try:
            async with self.s.begin_nested():
                self.s.add(m.UserRow(id=user_id, display_name=display_name[:120], created_at=now))
                await self.s.flush()
        except IntegrityError:
            return  # another request created it between our read and our insert

    async def user_ids(self) -> list[str]:
        return list((await self.s.scalars(select(m.UserRow.id))).all())

    # ============================================================================== preferences / profile
    async def get_preferences(self, user_id: str) -> UserPreferences:
        row = await self.s.get(m.UserPreferenceRow, user_id)
        return UserPreferences.model_validate(row.data) if row and row.data else UserPreferences()

    async def save_preferences(self, user_id: str, prefs: UserPreferences, now: datetime) -> None:
        data = prefs.model_dump(mode="json")
        row = await self.s.get(m.UserPreferenceRow, user_id)
        if row is None:
            self.s.add(m.UserPreferenceRow(user_id=user_id, data=data, updated_at=now))
        else:
            row.data, row.updated_at = data, now
        await self.s.flush()

    async def get_assistant_profile(self, user_id: str) -> AssistantProfile | None:
        row = await self.s.get(m.AssistantProfileRow, user_id)
        return AssistantProfile.model_validate(row.data) if row and row.data else None

    async def save_assistant_profile(self, user_id: str, profile: AssistantProfile, now: datetime) -> None:
        data = profile.model_dump(mode="json")
        row = await self.s.get(m.AssistantProfileRow, user_id)
        if row is None:
            self.s.add(m.AssistantProfileRow(user_id=user_id, data=data, updated_at=now))
        else:
            row.data, row.updated_at = data, now
        await self.s.flush()

    # ===================================================================================== voice profile
    async def get_voice_profile(self, user_id: str) -> VoiceProfileView:
        row = await self.s.get(m.VoiceProfileRow, user_id)
        if row is None or row.status == VoiceStatus.DELETED.value:
            return VoiceProfileView()
        return VoiceProfileView(
            status=VoiceStatus(row.status),
            consent_recorded_at=row.consent_recorded_at,
            consent_version=row.consent_version,
            provider_voice_id=row.provider_voice_id,
            active=row.status == VoiceStatus.READY.value,
            detail=row.detail,
        )

    async def save_voice_profile(
        self,
        user_id: str,
        *,
        status: VoiceStatus,
        consent_version: str | None,
        speaker_name: str | None,
        detail: str,
        now: datetime,
        provider_voice_id: str | None = None,
    ) -> None:
        row = await self.s.get(m.VoiceProfileRow, user_id)
        if row is None:
            row = m.VoiceProfileRow(user_id=user_id)
            self.s.add(row)
        row.status = status.value
        row.consent_version = consent_version
        row.consent_recorded_at = now if consent_version else None
        row.speaker_name = speaker_name
        row.provider_voice_id = provider_voice_id
        row.detail = detail
        row.updated_at = now
        await self.s.flush()

    async def delete_voice_profile(self, user_id: str) -> None:
        await self.s.execute(delete(m.VoiceProfileRow).where(m.VoiceProfileRow.user_id == user_id))

    # ============================================================================ trusted / blocked lists
    async def list_blocked(self, user_id: str) -> list[BlockedCaller]:
        rows = (
            await self.s.scalars(
                select(m.BlockedCallerRow)
                .where(m.BlockedCallerRow.user_id == user_id)
                .order_by(m.BlockedCallerRow.created_at.desc())
            )
        ).all()
        return [_blocked_entry(r) for r in rows]

    async def list_trusted(self, user_id: str) -> list[TrustedCaller]:
        rows = (
            await self.s.scalars(
                select(m.TrustedCallerRow)
                .where(m.TrustedCallerRow.user_id == user_id)
                .order_by(m.TrustedCallerRow.created_at.desc())
            )
        ).all()
        return [_trusted_entry(r) for r in rows]

    async def screening_lists(
        self, user_id: str
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str, str | None]]]:
        blocked = (await self.s.scalars(select(m.BlockedCallerRow).where(m.BlockedCallerRow.user_id == user_id))).all()
        trusted = (await self.s.scalars(select(m.TrustedCallerRow).where(m.TrustedCallerRow.user_id == user_id))).all()
        return (
            [(r.id, r.fingerprint, r.number_display) for r in blocked],
            [(r.id, r.fingerprint, r.number_display, r.label) for r in trusted],
        )

    async def add_blocked(
        self,
        user_id: str,
        entry_id: str,
        fingerprint: str,
        display: str,
        number: str | None,
        reason: str | None,
        source_call_id: str | None,
        now: datetime,
    ) -> BlockedCaller:
        existing = await self.s.scalar(
            select(m.BlockedCallerRow).where(
                m.BlockedCallerRow.user_id == user_id, m.BlockedCallerRow.fingerprint == fingerprint
            )
        )
        if existing is None:
            existing = m.BlockedCallerRow(
                id=entry_id,
                user_id=user_id,
                fingerprint=fingerprint,
                number_display=display,
                number_enc=number,
                reason=reason,
                source_call_id=source_call_id,
                created_at=now,
            )
            self.s.add(existing)
            await self.s.flush()
        await self.s.execute(
            delete(m.TrustedCallerRow).where(
                m.TrustedCallerRow.user_id == user_id, m.TrustedCallerRow.fingerprint == fingerprint
            )
        )
        await self.s.execute(
            update(m.CallSessionRow)
            .where(m.CallSessionRow.user_id == user_id, m.CallSessionRow.caller_fingerprint == fingerprint)
            .values(blocked=True, trusted=False)
        )
        return _blocked_entry(existing)

    async def add_trusted(
        self,
        user_id: str,
        entry_id: str,
        fingerprint: str,
        display: str,
        number: str | None,
        label: str | None,
        source_call_id: str | None,
        now: datetime,
    ) -> TrustedCaller:
        existing = await self.s.scalar(
            select(m.TrustedCallerRow).where(
                m.TrustedCallerRow.user_id == user_id, m.TrustedCallerRow.fingerprint == fingerprint
            )
        )
        if existing is None:
            existing = m.TrustedCallerRow(
                id=entry_id,
                user_id=user_id,
                fingerprint=fingerprint,
                number_display=display,
                number_enc=number,
                label=label,
                source_call_id=source_call_id,
                created_at=now,
            )
            self.s.add(existing)
            await self.s.flush()
        await self.s.execute(
            delete(m.BlockedCallerRow).where(
                m.BlockedCallerRow.user_id == user_id, m.BlockedCallerRow.fingerprint == fingerprint
            )
        )
        await self.s.execute(
            update(m.CallSessionRow)
            .where(m.CallSessionRow.user_id == user_id, m.CallSessionRow.caller_fingerprint == fingerprint)
            .values(trusted=True, blocked=False)
        )
        return _trusted_entry(existing)

    async def remove_blocked(self, user_id: str, entry_id: str) -> bool:
        fp = await self.s.scalar(
            select(m.BlockedCallerRow.fingerprint).where(
                m.BlockedCallerRow.user_id == user_id, m.BlockedCallerRow.id == entry_id
            )
        )
        res = await self.s.execute(
            delete(m.BlockedCallerRow).where(m.BlockedCallerRow.user_id == user_id, m.BlockedCallerRow.id == entry_id)
        )
        if fp:
            await self.s.execute(
                update(m.CallSessionRow)
                .where(m.CallSessionRow.user_id == user_id, m.CallSessionRow.caller_fingerprint == fp)
                .values(blocked=False)
            )
        return _rowcount(res) > 0

    async def remove_trusted(self, user_id: str, entry_id: str) -> bool:
        fp = await self.s.scalar(
            select(m.TrustedCallerRow.fingerprint).where(
                m.TrustedCallerRow.user_id == user_id, m.TrustedCallerRow.id == entry_id
            )
        )
        res = await self.s.execute(
            delete(m.TrustedCallerRow).where(m.TrustedCallerRow.user_id == user_id, m.TrustedCallerRow.id == entry_id)
        )
        if fp:
            await self.s.execute(
                update(m.CallSessionRow)
                .where(m.CallSessionRow.user_id == user_id, m.CallSessionRow.caller_fingerprint == fp)
                .values(trusted=False)
            )
        return _rowcount(res) > 0

    async def caller_status(self, user_id: str, fingerprint: str) -> tuple[bool, bool]:
        blocked = await self.s.scalar(
            select(func.count())
            .select_from(m.BlockedCallerRow)
            .where(m.BlockedCallerRow.user_id == user_id, m.BlockedCallerRow.fingerprint == fingerprint)
        )
        trusted = await self.s.scalar(
            select(func.count())
            .select_from(m.TrustedCallerRow)
            .where(m.TrustedCallerRow.user_id == user_id, m.TrustedCallerRow.fingerprint == fingerprint)
        )
        return bool(blocked), bool(trusted)

    # ======================================================================================= calls: write
    async def create_call(self, row: m.CallSessionRow) -> None:
        self.s.add(row)
        await self.s.flush()

    async def get_call_row(self, user_id: str, call_id: str, *, for_update: bool = False) -> m.CallSessionRow | None:
        stmt = select(m.CallSessionRow).where(m.CallSessionRow.id == call_id, m.CallSessionRow.user_id == user_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.s.scalar(stmt)

    async def get_call_row_any_user(self, call_id: str) -> m.CallSessionRow | None:
        """For trusted server-side paths only (provider callbacks, reaper). Never expose the result to a user."""
        return await self.s.get(m.CallSessionRow, call_id)

    async def find_call_by_external_id(self, provider: str, external_id: str) -> m.CallSessionRow | None:
        return await self.s.scalar(
            select(m.CallSessionRow).where(
                m.CallSessionRow.provider == provider, m.CallSessionRow.external_id == external_id
            )
        )

    async def find_call_by_client_event(self, user_id: str, client_event_id: str) -> m.CallSessionRow | None:
        return await self.s.scalar(
            select(m.CallSessionRow).where(
                m.CallSessionRow.user_id == user_id, m.CallSessionRow.client_event_id == client_event_id
            )
        )

    async def next_event_seq(self, call_id: str) -> int:
        """Allocate the next live-event sequence number of a call.

        A single ``UPDATE ... RETURNING``: concurrent allocators (the partial-transcript path runs without the per-call
        lock, as do timers and other workers) are serialised by the database instead of reading the same counter and
        colliding on the ``(call_id, seq)`` key.
        """
        seq = await self.s.scalar(
            update(m.CallSessionRow)
            .where(m.CallSessionRow.id == call_id)
            .values(event_seq=m.CallSessionRow.event_seq + 1)
            .returning(m.CallSessionRow.event_seq)
            .execution_options(synchronize_session=False)
        )
        if seq is None:
            raise LookupError(f"call {call_id} does not exist")
        return int(seq)

    async def add_turns(self, turns: list[CallTurn]) -> None:
        for t in turns:
            self.s.add(turn_to_row(t))
        await self.s.flush()

    async def list_turns(self, call_id: str) -> list[CallTurn]:
        rows = (
            await self.s.scalars(
                select(m.CallTurnRow).where(m.CallTurnRow.call_id == call_id).order_by(m.CallTurnRow.seq)
            )
        ).all()
        return [turn_from_row(r) for r in rows]

    async def last_caller_turn(self, call_id: str) -> tuple[str, str] | None:
        row = await self.s.scalar(
            select(m.CallTurnRow)
            .where(m.CallTurnRow.call_id == call_id, m.CallTurnRow.speaker == Speaker.CALLER.value)
            .order_by(m.CallTurnRow.seq.desc())
            .limit(1)
        )
        return (row.id, row.text) if row else None

    async def recent_turns(self, call_id: str, limit: int = 6) -> list[tuple[str, str]]:
        rows = (
            await self.s.scalars(
                select(m.CallTurnRow)
                .where(m.CallTurnRow.call_id == call_id)
                .order_by(m.CallTurnRow.seq.desc())
                .limit(limit)
            )
        ).all()
        return [(r.speaker, r.text) for r in reversed(rows)]

    async def update_turn(self, call_id: str, turn_id: str, **fields: Any) -> None:
        await self.s.execute(
            update(m.CallTurnRow).where(m.CallTurnRow.call_id == call_id, m.CallTurnRow.id == turn_id).values(**fields)
        )

    async def get_turn(self, call_id: str, turn_id: str) -> CallTurn | None:
        row = await self.s.get(m.CallTurnRow, (call_id, turn_id))
        return turn_from_row(row) if row else None

    async def save_risk(self, call_id: str, risk: RiskAssessment, now: datetime) -> None:
        self.s.add(m.RiskAssessmentRow(call_id=call_id, created_at=now, data=risk.model_dump(mode="json")))
        await self.s.flush()

    async def latest_risk(self, call_id: str) -> RiskAssessment | None:
        row = await self.s.scalar(
            select(m.RiskAssessmentRow)
            .where(m.RiskAssessmentRow.call_id == call_id)
            .order_by(m.RiskAssessmentRow.id.desc())
            .limit(1)
        )
        return RiskAssessment.model_validate(row.data) if row else None

    async def risk_history(self, call_id: str) -> list[RiskAssessment]:
        rows = (
            await self.s.scalars(
                select(m.RiskAssessmentRow)
                .where(m.RiskAssessmentRow.call_id == call_id)
                .order_by(m.RiskAssessmentRow.id)
            )
        ).all()
        return [RiskAssessment.model_validate(r.data) for r in rows]

    async def add_escalation(self, e: Escalation) -> None:
        self.s.add(
            m.EscalationRow(
                id=e.id,
                call_id=e.call_id,
                reason=e.reason,
                status=e.status.value,
                created_at=e.created_at,
                resolved_at=e.resolved_at,
                important_lines=e.important_lines,
            )
        )
        await self.s.flush()

    async def resolve_escalation(self, escalation_id: str, status: EscalationStatus, now: datetime) -> None:
        await self.s.execute(
            update(m.EscalationRow)
            .where(m.EscalationRow.id == escalation_id)
            .values(status=status.value, resolved_at=now)
        )

    async def list_escalations(self, call_id: str) -> list[Escalation]:
        rows = (
            await self.s.scalars(
                select(m.EscalationRow).where(m.EscalationRow.call_id == call_id).order_by(m.EscalationRow.created_at)
            )
        ).all()
        return [escalation_from_row(r) for r in rows]

    async def add_owner_action(self, a: OwnerAction) -> None:
        self.s.add(
            m.OwnerActionRow(
                id=a.id,
                call_id=a.call_id,
                action=a.action.value,
                created_at=a.created_at,
                simulated=a.simulated,
                result=a.result,
                detail=a.detail,
            )
        )
        await self.s.flush()

    async def list_owner_actions(self, call_id: str) -> list[OwnerAction]:
        rows = (
            await self.s.scalars(
                select(m.OwnerActionRow)
                .where(m.OwnerActionRow.call_id == call_id)
                .order_by(m.OwnerActionRow.created_at)
            )
        ).all()
        return [action_from_row(r) for r in rows]

    async def save_summary(self, s: CallSummary) -> None:
        row = await self.s.get(m.CallSummaryRow, s.call_id)
        if row is None:
            row = m.CallSummaryRow(call_id=s.call_id)
            self.s.add(row)
        row.text, row.category, row.risk_level = s.text, s.category.value, s.risk_level.value
        row.action_taken, row.owner_action_required = s.action_taken, s.owner_action_required
        row.generated_by, row.created_at = s.generated_by, s.created_at
        await self.s.flush()

    async def get_summary(self, call_id: str) -> CallSummary | None:
        row = await self.s.get(m.CallSummaryRow, call_id)
        return summary_from_row(row) if row else None

    async def add_feedback(self, f: FeedbackRecord, user_id: str) -> tuple[FeedbackRecord, bool]:
        """Idempotent per (call, kind). Returns ``(record, created)``."""
        existing = await self.s.scalar(
            select(m.FeedbackRow).where(m.FeedbackRow.call_id == f.call_id, m.FeedbackRow.kind == f.kind.value)
        )
        if existing is not None:
            if f.note is not None:
                existing.note = f.note
            return feedback_from_row(existing), False
        self.s.add(
            m.FeedbackRow(
                id=f.id, call_id=f.call_id, user_id=user_id, kind=f.kind.value, note=f.note, created_at=f.created_at
            )
        )
        await self.s.flush()
        return f, True

    async def list_feedback(self, call_id: str) -> list[FeedbackRecord]:
        rows = (
            await self.s.scalars(
                select(m.FeedbackRow).where(m.FeedbackRow.call_id == call_id).order_by(m.FeedbackRow.created_at)
            )
        ).all()
        return [feedback_from_row(r) for r in rows]

    async def feedback_counts(self, user_id: str) -> dict[str, int]:
        rows = (
            await self.s.execute(
                select(m.FeedbackRow.kind, func.count())
                .where(m.FeedbackRow.user_id == user_id)
                .group_by(m.FeedbackRow.kind)
            )
        ).all()
        return {k: int(n) for k, n in rows}

    # ============================================================================== provider events / live
    async def add_provider_event(
        self, provider: str, external_id: str, event_type: str, call_id: str | None, detail: str | None, now: datetime
    ) -> bool:
        """``False`` when this provider event id was already processed (duplicate webhook delivery)."""
        try:
            async with self.s.begin_nested():
                self.s.add(
                    m.ProviderEventRow(
                        provider=provider,
                        external_id=external_id[:160],
                        call_id=call_id,
                        event_type=event_type[:64],
                        received_at=now,
                        detail=(detail or "")[:200] or None,
                    )
                )
                await self.s.flush()
        except IntegrityError:
            return False
        return True

    async def has_provider_event(self, provider: str, external_id: str) -> bool:
        found = await self.s.scalar(
            select(func.count())
            .select_from(m.ProviderEventRow)
            .where(m.ProviderEventRow.provider == provider, m.ProviderEventRow.external_id == external_id[:160])
        )
        return bool(found)

    async def provider_event_call_id(self, provider: str, external_id: str) -> str | None:
        """The Sparta call a recorded provider event created (``None`` when unknown or not linked yet)."""
        return await self.s.scalar(
            select(m.ProviderEventRow.call_id).where(
                m.ProviderEventRow.provider == provider, m.ProviderEventRow.external_id == external_id[:160]
            )
        )

    async def attach_provider_event(self, provider: str, external_id: str, call_id: str) -> None:
        """Link an already recorded provider event to the call it created (so the call detail can show it)."""
        await self.s.execute(
            update(m.ProviderEventRow)
            .where(m.ProviderEventRow.provider == provider, m.ProviderEventRow.external_id == external_id[:160])
            .values(call_id=call_id)
        )

    async def list_provider_events(self, call_id: str, limit: int = 50) -> list[ProviderEventRecord]:
        rows = (
            await self.s.scalars(
                select(m.ProviderEventRow)
                .where(m.ProviderEventRow.call_id == call_id)
                .order_by(m.ProviderEventRow.id.desc())
                .limit(limit)
            )
        ).all()
        return [
            ProviderEventRecord(
                id=str(r.id),
                provider=r.provider,
                event_type=r.event_type,
                external_id=r.external_id,
                received_at=r.received_at,
                detail=r.detail,
            )
            for r in reversed(rows)
        ]

    async def add_live_event(self, e: LiveEvent) -> None:
        self.s.add(
            m.LiveEventRow(call_id=e.call_id, seq=e.seq, type=e.type, ts=e.ts, simulated=e.simulated, data=e.data)
        )
        await self.s.flush()

    async def list_live_events(self, call_id: str, after_seq: int = 0, limit: int = 1000) -> list[LiveEvent]:
        rows = (
            await self.s.scalars(
                select(m.LiveEventRow)
                .where(m.LiveEventRow.call_id == call_id, m.LiveEventRow.seq > after_seq)
                .order_by(m.LiveEventRow.seq)
                .limit(limit)
            )
        ).all()
        return [
            LiveEvent(type=r.type, call_id=r.call_id, seq=r.seq, ts=r.ts, simulated=r.simulated, data=r.data or {})
            for r in rows
        ]

    # ======================================================================================== calls: read
    async def update_call(self, call_id: str, **fields: Any) -> None:
        """Attribute-level update so the session's identity map (and any row already loaded) stays consistent."""
        row = await self.s.get(m.CallSessionRow, call_id)
        if row is None:
            return
        for name, value in fields.items():
            setattr(row, name, value)
        await self.s.flush()

    async def list_calls(self, user_id: str, f: CallFilter) -> tuple[list[CallListItem], str | None]:
        stmt = select(m.CallSessionRow).where(m.CallSessionRow.user_id == user_id)
        if f.risk_level:
            stmt = stmt.where(m.CallSessionRow.risk_level == f.risk_level)
        if f.category:
            stmt = stmt.where(m.CallSessionRow.category == f.category)
        if f.status:
            stmt = stmt.where(m.CallSessionRow.status == f.status)
        if f.provider:
            stmt = stmt.where(m.CallSessionRow.provider == f.provider)
        if f.attention is not None:
            stmt = stmt.where(m.CallSessionRow.owner_attention == f.attention)
        if f.since:
            stmt = stmt.where(m.CallSessionRow.started_at >= f.since)
        if f.until:
            stmt = stmt.where(m.CallSessionRow.started_at <= f.until)
        if f.cursor and (cur := decode_cursor(f.cursor)):
            ts, cid = cur
            stmt = stmt.where(
                or_(
                    m.CallSessionRow.started_at < ts, and_(m.CallSessionRow.started_at == ts, m.CallSessionRow.id < cid)
                )
            )
        stmt = stmt.order_by(m.CallSessionRow.started_at.desc(), m.CallSessionRow.id.desc()).limit(SCAN_WINDOW)
        rows = (await self.s.scalars(stmt)).all()

        # Encrypted columns cannot be filtered in SQL: language and free-text search run on the bounded window.
        needle = f.q.casefold().strip() if f.q else None
        picked: list[m.CallSessionRow] = []
        more = False
        for row in rows:
            if f.language and f.language not in (row.languages or []):
                continue
            if needle and needle not in _haystack(row):
                continue
            if len(picked) == f.limit:
                more = True
                break
            picked.append(row)
        next_cursor: str | None = None
        if more and picked:
            last = picked[-1]
            next_cursor = encode_cursor(last.started_at, last.id)
        elif len(rows) == SCAN_WINDOW and rows:
            tail = rows[-1]
            next_cursor = encode_cursor(tail.started_at, tail.id)
        return [list_item_from_row(r) for r in picked], next_cursor

    async def count_calls_since(self, user_id: str, since: datetime, *, simulated: bool | None = None) -> int:
        """Conversational calls only: native screening events do not count against the daily call cap."""
        stmt = (
            select(func.count())
            .select_from(m.CallSessionRow)
            .where(
                m.CallSessionRow.user_id == user_id,
                m.CallSessionRow.started_at >= since,
                m.CallSessionRow.mode == CallMode.CONVERSATIONAL.value,
            )
        )
        if simulated is not None:
            stmt = stmt.where(m.CallSessionRow.simulated == simulated)
        return int(await self.s.scalar(stmt) or 0)

    async def count_screening_events_since(self, user_id: str, since: datetime) -> int:
        """Native screening events the server *received* since ``since``. Their ``started_at`` is the client's claim
        (clamped, but backdatable by a week), so it cannot be what the daily cap counts."""
        stmt = (
            select(func.count())
            .select_from(m.ProviderEventRow)
            .join(m.CallSessionRow, m.ProviderEventRow.call_id == m.CallSessionRow.id)
            .where(
                m.CallSessionRow.user_id == user_id,
                m.CallSessionRow.mode == CallMode.SCREENING_ONLY.value,
                m.ProviderEventRow.received_at >= since,
            )
        )
        return int(await self.s.scalar(stmt) or 0)

    async def count_active_calls(self, user_id: str) -> int:
        stmt = (
            select(func.count())
            .select_from(m.CallSessionRow)
            .where(m.CallSessionRow.user_id == user_id, m.CallSessionRow.status == CallStatus.ACTIVE.value)
        )
        return int(await self.s.scalar(stmt) or 0)

    async def real_call_seconds_since(self, user_id: str, since: datetime, now: datetime) -> float:
        """Seconds of real (not simulated) conversational calls started since ``since``: finished calls by their
        recorded duration, calls still running by the time elapsed so far. What the daily minute cap counts."""
        rows = await self.s.execute(
            select(m.CallSessionRow.status, m.CallSessionRow.duration_ms, m.CallSessionRow.started_at).where(
                m.CallSessionRow.user_id == user_id,
                m.CallSessionRow.started_at >= since,
                m.CallSessionRow.mode == CallMode.CONVERSATIONAL.value,
                m.CallSessionRow.simulated.is_(False),
            )
        )
        total = 0.0
        for status, duration_ms, started_at in rows.all():
            if status == CallStatus.ACTIVE.value:
                total += max(0.0, (now - started_at).total_seconds())
            else:
                total += (duration_ms or 0) / 1000.0
        return total

    async def count_real_calls_from_since(self, user_id: str, fingerprint: str, since: datetime) -> int:
        """Real conversational calls from one caller number (by fingerprint) since ``since``."""
        stmt = (
            select(func.count())
            .select_from(m.CallSessionRow)
            .where(
                m.CallSessionRow.user_id == user_id,
                m.CallSessionRow.caller_fingerprint == fingerprint,
                m.CallSessionRow.started_at >= since,
                m.CallSessionRow.mode == CallMode.CONVERSATIONAL.value,
                m.CallSessionRow.simulated.is_(False),
            )
        )
        return int(await self.s.scalar(stmt) or 0)

    async def today_stats(self, user_id: str, since: datetime) -> dict[str, float]:
        rows = (
            await self.s.scalars(
                select(m.CallSessionRow).where(
                    m.CallSessionRow.user_id == user_id, m.CallSessionRow.started_at >= since
                )
            )
        ).all()
        escalations = int(
            await self.s.scalar(
                select(func.count())
                .select_from(m.EscalationRow)
                .join(m.CallSessionRow, m.EscalationRow.call_id == m.CallSessionRow.id)
                .where(m.CallSessionRow.user_id == user_id, m.EscalationRow.created_at >= since)
            )
            or 0
        )
        return {
            "handled": float(len(rows)),
            "high_risk": float(sum(1 for r in rows if r.risk_level == RiskLevel.HIGH.value)),
            "escalations": float(escalations),
            "ended_spam": float(sum(1 for r in rows if r.recommended_action in ("end_spam", "refuse_and_end"))),
            "minutes_handled": round(sum((r.duration_ms or 0) for r in rows) / 60000.0, 2),
        }

    async def safety_events(self, user_id: str, limit: int = 20) -> list[m.CallSessionRow]:
        stmt = (
            select(m.CallSessionRow)
            .where(
                m.CallSessionRow.user_id == user_id,
                m.CallSessionRow.risk_level.in_([RiskLevel.MEDIUM.value, RiskLevel.HIGH.value]),
            )
            .order_by(m.CallSessionRow.started_at.desc())
            .limit(min(limit, 100))
        )
        return list((await self.s.scalars(stmt)).all())

    async def active_call_rows(self) -> list[m.CallSessionRow]:
        return list(
            (
                await self.s.scalars(select(m.CallSessionRow).where(m.CallSessionRow.status == CallStatus.ACTIVE.value))
            ).all()
        )

    async def load_detail(self, user_id: str, call_id: str) -> CallDetail | None:
        row = await self.get_call_row(user_id, call_id)
        if row is None:
            return None
        item = list_item_from_row(row)
        versions = VersionInfo(**(row.versions or {}))
        return CallDetail(
            **item.model_dump(),
            language_mode=row.language_mode,
            turns=await self.list_turns(call_id),
            risk=await self.latest_risk(call_id),
            escalations=await self.list_escalations(call_id),
            owner_actions=await self.list_owner_actions(call_id),
            summary=await self.get_summary(call_id),
            feedback=await self.list_feedback(call_id),
            provider_events=await self.list_provider_events(call_id),
            versions=versions,
            trace_id=row.trace_id,
            metrics={k: float(v) for k, v in (row.metrics or {}).items()},
        )

    def context_of(self, row: m.CallSessionRow) -> ConversationContext:
        return ConversationContext.model_validate(row.context) if row.context else ConversationContext()

    # ================================================================================= deletion / retention
    async def delete_transcript(self, call_id: str) -> None:
        """Drop what the caller said (turns, event log, quoted evidence, escalation quotes) and keep the rest.

        Kept: the summary, the caller's claimed name/organisation, and the structured risk explanation (signal codes,
        reasons and scores, none of which quote the caller). Used when transcripts are not stored for an owner and when
        a transcript passes its retention period. The owner's explicit "delete content" is the stronger operation
        (``delete_call_content``): it removes the summary and explanation as well.
        """
        await self.s.execute(delete(m.CallTurnRow).where(m.CallTurnRow.call_id == call_id))
        await self.s.execute(delete(m.LiveEventRow).where(m.LiveEventRow.call_id == call_id))
        await self.s.execute(
            update(m.EscalationRow).where(m.EscalationRow.call_id == call_id).values(important_lines=[])
        )
        assessments = (
            await self.s.scalars(select(m.RiskAssessmentRow).where(m.RiskAssessmentRow.call_id == call_id))
        ).all()
        for assessment in assessments:
            data = dict(assessment.data or {})
            data["signals"] = [{**s, "evidence_excerpt": None} for s in data.get("signals", [])]
            assessment.data = data
        row = await self.s.get(m.CallSessionRow, call_id)
        if row is not None:
            ctx = self.context_of(row)
            for signal in ctx.signals:
                signal.evidence_excerpt = None
            if ctx.risk is not None:
                for signal in ctx.risk.signals:
                    signal.evidence_excerpt = None
            row.context = ctx.model_dump(mode="json")
            row.has_content = False
        await self.s.flush()

    async def delete_idempotent_for_call(self, user_id: str, call_id: str) -> None:
        """Forget cached responses about one call: requests made against it, and the request that created it."""
        stmt = delete(m.IdempotencyRow).where(
            m.IdempotencyRow.user_id == user_id,
            or_(
                m.IdempotencyRow.call_id == call_id,
                m.IdempotencyRow.route.contains(f"/calls/{call_id}/", autoescape=True),
                m.IdempotencyRow.route.endswith(f"/calls/{call_id}", autoescape=True),
            ),
        )
        await self.s.execute(stmt)

    async def delete_idempotent_route(self, user_id: str, route: str) -> None:
        """Forget every cached response stored for one route, for example the POSTs that added list entries."""
        await self.s.execute(
            delete(m.IdempotencyRow).where(m.IdempotencyRow.user_id == user_id, m.IdempotencyRow.route == route)
        )

    async def delete_call_content(self, user_id: str, call_id: str) -> bool:
        row = await self.get_call_row(user_id, call_id)
        if row is None:
            return False
        await self.delete_idempotent_for_call(user_id, call_id)
        await self.s.execute(delete(m.CallTurnRow).where(m.CallTurnRow.call_id == call_id))
        await self.s.execute(delete(m.LiveEventRow).where(m.LiveEventRow.call_id == call_id))
        await self.s.execute(delete(m.RiskAssessmentRow).where(m.RiskAssessmentRow.call_id == call_id))
        await self.s.execute(delete(m.EscalationRow).where(m.EscalationRow.call_id == call_id))
        await self.s.execute(delete(m.CallSummaryRow).where(m.CallSummaryRow.call_id == call_id))
        await self.s.execute(
            delete(m.FeedbackRow).where(m.FeedbackRow.call_id == call_id, m.FeedbackRow.note.is_not(None))
        )
        row.has_content = False
        row.claim = None
        row.purpose = None
        row.summary_text = None
        row.caller_number_enc = None
        row.signal_codes = []
        row.languages = []
        row.context = ConversationContext(state=CallState(row.state), ended_reason="content_deleted").model_dump(
            mode="json"
        )
        await self.s.flush()
        return True

    async def delete_call(self, user_id: str, call_id: str) -> bool:
        await self.delete_idempotent_for_call(user_id, call_id)
        res = await self.s.execute(
            delete(m.CallSessionRow).where(m.CallSessionRow.id == call_id, m.CallSessionRow.user_id == user_id)
        )
        return _rowcount(res) > 0

    async def delete_all_content(self, user_id: str) -> int:
        ids = (
            await self.s.scalars(
                select(m.CallSessionRow.id).where(
                    m.CallSessionRow.user_id == user_id, m.CallSessionRow.has_content.is_(True)
                )
            )
        ).all()
        for call_id in ids:
            await self.delete_call_content(user_id, call_id)
        return len(ids)

    async def content_expiry_candidates(self, user_id: str, cutoff: datetime) -> list[str]:
        stmt = select(m.CallSessionRow.id).where(
            m.CallSessionRow.user_id == user_id,
            m.CallSessionRow.has_content.is_(True),
            m.CallSessionRow.status != CallStatus.ACTIVE.value,
            m.CallSessionRow.ended_at.is_not(None),
            m.CallSessionRow.ended_at < cutoff,
        )
        return list((await self.s.scalars(stmt)).all())

    async def record_expiry_candidates(self, user_id: str, cutoff: datetime) -> list[str]:
        stmt = select(m.CallSessionRow.id).where(
            m.CallSessionRow.user_id == user_id,
            m.CallSessionRow.status != CallStatus.ACTIVE.value,
            m.CallSessionRow.started_at < cutoff,
        )
        return list((await self.s.scalars(stmt)).all())

    async def purge_expired_technical(self, now: datetime, provider_event_age: timedelta) -> None:
        await self.s.execute(delete(m.IdempotencyRow).where(m.IdempotencyRow.expires_at < now))
        await self.s.execute(
            delete(m.ProviderEventRow).where(m.ProviderEventRow.received_at < now - provider_event_age)
        )

    # ================================================================================== audit / idempotency
    async def add_audit(
        self,
        user_id: str,
        action: str,
        target_type: str,
        target_id: str | None,
        detail: dict[str, Any] | None,
        request_id: str | None,
        now: datetime,
    ) -> None:
        self.s.add(
            m.AuditEventRow(
                user_id=user_id,
                at=now,
                action=action[:48],
                target_type=target_type[:32],
                target_id=target_id[:64] if target_id else None,
                detail=detail,
                request_id=request_id,
            )
        )
        await self.s.flush()

    async def list_audit(self, user_id: str, limit: int = 50) -> list[m.AuditEventRow]:
        stmt = (
            select(m.AuditEventRow)
            .where(m.AuditEventRow.user_id == user_id)
            .order_by(m.AuditEventRow.id.desc())
            .limit(min(limit, 200))
        )
        return list((await self.s.scalars(stmt)).all())

    async def get_idempotent(self, user_id: str, route: str, key: str, now: datetime) -> m.IdempotencyRow | None:
        row = await self.s.get(m.IdempotencyRow, (user_id, route, key))
        if row is not None and row.expires_at < now:
            await self.s.delete(row)
            return None
        return row

    async def save_idempotent(
        self,
        user_id: str,
        route: str,
        key: str,
        request_hash: str,
        status_code: int,
        response: Any,
        now: datetime,
        ttl: timedelta,
        call_id: str | None = None,
    ) -> None:
        self.s.add(
            m.IdempotencyRow(
                user_id=user_id,
                route=route,
                key=key,
                request_hash=request_hash,
                status_code=status_code,
                response=response,
                call_id=call_id,
                created_at=now,
                expires_at=now + ttl,
            )
        )
        await self.s.flush()

    # ======================================================================================== scenarios
    async def save_scenario(self, user_id: str, scenario_id: str, data: dict[str, Any], now: datetime) -> None:
        self.s.add(m.ScenarioRow(id=scenario_id, user_id=user_id, data=data, created_at=now))
        await self.s.flush()

    async def list_scenarios(self, user_id: str) -> list[dict[str, Any]]:
        rows = (
            await self.s.scalars(
                select(m.ScenarioRow).where(m.ScenarioRow.user_id == user_id).order_by(m.ScenarioRow.created_at)
            )
        ).all()
        return [{"id": r.id, **(r.data or {})} for r in rows]

    async def get_scenario(self, user_id: str, scenario_id: str) -> dict[str, Any] | None:
        row = await self.s.scalar(
            select(m.ScenarioRow).where(m.ScenarioRow.user_id == user_id, m.ScenarioRow.id == scenario_id)
        )
        return {"id": row.id, **(row.data or {})} if row else None


def _haystack(row: m.CallSessionRow) -> str:
    claim = row.claim or {}
    parts = [
        row.caller_label or "",
        row.caller_display,
        row.purpose or "",
        row.summary_text or "",
        claim.get("name") or "",
        claim.get("organization") or "",
        row.category,
        row.language_profile or "",
    ]
    return " ".join(parts).casefold()


__all__ = ["CallFilter", "Repository", "decode_cursor", "encode_cursor", "list_item_from_row", "utcnow"]
