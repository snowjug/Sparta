"""Relational schema.

Content-bearing and personal columns use ``EncryptedText``/``EncryptedJSON``. Everything needed to *list, filter and
cap* calls (risk level, category, timestamps, provider, flags) stays in clear, non-sensitive columns so the product can
work without decrypting history, and so deleting content leaves a useful, privacy-safe shell behind.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from sparta.db.types import EncryptedJSON, EncryptedText, UTCDateTime


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class UserPreferenceRow(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[Any] = mapped_column(EncryptedJSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AssistantProfileRow(Base):
    __tablename__ = "assistant_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class VoiceProfileRow(Base):
    __tablename__ = "voice_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(40))
    consent_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    consent_recorded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    provider_voice_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    speaker_name: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class _CallerListMixin:
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    number_display: Mapped[str] = mapped_column(String(64))
    number_enc: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    source_call_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class TrustedCallerRow(_CallerListMixin, Base):
    __tablename__ = "trusted_callers"
    __table_args__ = (UniqueConstraint("user_id", "fingerprint", name="uq_trusted_user_fp"),)

    label: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)


class BlockedCallerRow(_CallerListMixin, Base):
    __tablename__ = "blocked_callers"
    __table_args__ = (UniqueConstraint("user_id", "fingerprint", name="uq_blocked_user_fp"),)

    reason: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)


class CallSessionRow(Base):
    __tablename__ = "call_sessions"
    __table_args__ = (
        Index("ix_calls_user_started", "user_id", "started_at"),
        UniqueConstraint("user_id", "client_event_id", name="uq_calls_user_client_event"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(24), default="conversational")
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), index=True)
    state: Mapped[str] = mapped_column(String(40))
    language_mode: Mapped[str] = mapped_column(String(16), default="auto")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    caller_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    caller_display: Mapped[str] = mapped_column(String(64), default="Unknown caller")
    caller_number_enc: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    caller_label: Mapped[str | None] = mapped_column(String(80), nullable=True)

    claim: Mapped[Any] = mapped_column(EncryptedJSON, nullable=True)
    purpose: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    summary_text: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)

    category: Mapped[str] = mapped_column(String(48), default="unknown", index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    recommended_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    signal_codes: Mapped[Any] = mapped_column(JSON, default=list)
    languages: Mapped[Any] = mapped_column(JSON, default=list)
    language_profile: Mapped[str | None] = mapped_column(String(24), nullable=True)
    action_taken: Mapped[str | None] = mapped_column(String(64), nullable=True)

    owner_attention: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    has_content: Mapped[bool] = mapped_column(Boolean, default=True)

    context: Mapped[Any] = mapped_column(EncryptedJSON, nullable=True)
    config: Mapped[Any] = mapped_column(JSON, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    versions: Mapped[Any] = mapped_column(JSON, default=dict)
    metrics: Mapped[Any] = mapped_column(JSON, default=dict)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    network_profile: Mapped[str] = mapped_column(String(16), default="ideal")
    event_seq: Mapped[int] = mapped_column(Integer, default=0)
    client_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    turns: Mapped[list["CallTurnRow"]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class CallTurnRow(Base):
    __tablename__ = "call_turns"

    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(12))
    text: Mapped[str] = mapped_column(EncryptedText)
    transliteration: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    translation: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    language_profile: Mapped[str | None] = mapped_column(String(24), nullable=True)
    segments: Mapped[Any] = mapped_column(JSON, default=list)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(24))
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    spoken_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    state_after: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    latency: Mapped[Any] = mapped_column(JSON, nullable=True)
    speech: Mapped[Any] = mapped_column(EncryptedJSON, nullable=True)


class RiskAssessmentRow(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    data: Mapped[Any] = mapped_column(EncryptedJSON)


class EscalationRow(Base):
    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(EncryptedText)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    important_lines: Mapped[Any] = mapped_column(EncryptedJSON, nullable=True)


class OwnerActionRow(Base):
    __tablename__ = "owner_actions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[str] = mapped_column(String(32), default="ok")
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)


class CallSummaryRow(Base):
    __tablename__ = "call_summaries"

    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id", ondelete="CASCADE"), primary_key=True)
    text: Mapped[str] = mapped_column(EncryptedText)
    category: Mapped[str] = mapped_column(String(48))
    risk_level: Mapped[str] = mapped_column(String(16))
    action_taken: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_action_required: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class FeedbackRow(Base):
    """Owner feedback lives apart from the immutable call record and never changes production behaviour on its own."""

    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("call_id", "kind", name="uq_feedback_call_kind"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ProviderEventRow(Base):
    """Inbound provider events. ``(provider, external_id)`` is unique: duplicate webhooks are detected here."""

    __tablename__ = "provider_events"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_provider_event"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(160))
    call_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    detail: Mapped[str | None] = mapped_column(String(200), nullable=True)


class LiveEventRow(Base):
    __tablename__ = "live_events"

    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id", ondelete="CASCADE"), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(40))
    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[Any] = mapped_column(EncryptedJSON, nullable=True)


class AuditEventRow(Base):
    """Audit trail of sensitive actions. Identifiers and short labels only, never call content."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    action: Mapped[str] = mapped_column(String(48))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[Any] = mapped_column(JSON, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class IdempotencyRow(Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    route: Mapped[str] = mapped_column(String(160), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[Any] = mapped_column(EncryptedJSON, nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # the call the response is about
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class ScenarioRow(Base):
    __tablename__ = "simulator_scenarios"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    data: Mapped[Any] = mapped_column(EncryptedJSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
