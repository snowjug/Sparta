"""Chronological, human-readable timeline of a call, derived from persisted rows (never from raw transcripts)."""

from sparta.domain.models import CallDetail, RiskAssessment, TimelineEntry


def build_timeline(detail: CallDetail, risk_history: list[RiskAssessment]) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = [
        TimelineEntry(
            at=detail.started_at,
            kind="system",
            label="Call started",
            detail=("Simulated call" if detail.simulated else f"Provider: {detail.provider.value}"),
        )
    ]
    previous_state = None
    previous_language = None
    for turn in detail.turns:
        if turn.state_after is not None and turn.state_after != previous_state:
            entries.append(TimelineEntry(at=turn.created_at, kind="state", label=f"State: {turn.state_after.value}"))
            previous_state = turn.state_after
        if turn.speaker.value == "caller" and turn.language and turn.language != previous_language:
            profile = f" ({turn.language_profile})" if turn.language_profile else ""
            if previous_language is not None:
                entries.append(
                    TimelineEntry(at=turn.created_at, kind="language", label=f"Language: {turn.language}{profile}")
                )
            previous_language = turn.language
    last_level = None
    for risk in risk_history:
        if risk.risk_level != last_level:
            entries.append(
                TimelineEntry(
                    at=risk.assessed_at,
                    kind="risk",
                    label=f"Risk {risk.risk_level.value} ({round(risk.risk_score * 100)}%)",
                    detail=risk.recommended_action.value,
                )
            )
            last_level = risk.risk_level
    for esc in detail.escalations:
        entries.append(TimelineEntry(at=esc.created_at, kind="escalation", label="Owner alerted", detail=esc.reason))
        if esc.resolved_at is not None:
            entries.append(TimelineEntry(at=esc.resolved_at, kind="escalation", label=f"Escalation {esc.status.value}"))
    for action in detail.owner_actions:
        suffix = " (simulated)" if action.simulated else ""
        entries.append(
            TimelineEntry(
                at=action.created_at,
                kind="owner_action",
                label=f"Owner: {action.action.value}{suffix}",
                detail=action.detail,
            )
        )
    for event in detail.provider_events:
        entries.append(
            TimelineEntry(
                at=event.received_at, kind="provider", label=f"Provider: {event.event_type}", detail=event.detail
            )
        )
    if detail.ended_at is not None:
        entries.append(TimelineEntry(at=detail.ended_at, kind="system", label="Call ended", detail=detail.action_taken))
    entries.sort(key=lambda e: e.at)
    return entries
