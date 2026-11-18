"""Explicit conversation state machine.

Sparta is not a free-form chatbot: every step is a named state and every move is checked against ``ALLOWED``.
An illegal transition is a bug and raises ``InvalidTransition`` instead of silently drifting.
"""

from sparta.domain.enums import ENDING_STATES, TERMINAL_STATES, CallState

S = CallState

_ACTIVE_ANYTIME = {
    S.ASSESSING,
    S.REFUSE_SENSITIVE_REQUEST,
    S.END_SPAM,
    S.END_SILENCE,
    S.ESCALATE,
    S.OWNER_TAKEOVER,
    S.COMPLETED,
    S.FAILED,
}

ALLOWED: dict[CallState, frozenset[CallState]] = {
    S.INITIALIZING: frozenset({S.DISCLOSURE, S.FAILED, S.COMPLETED}),
    S.DISCLOSURE: frozenset({S.IDENTIFY_CALLER, *_ACTIVE_ANYTIME}),
    S.IDENTIFY_CALLER: frozenset({S.IDENTIFY_PURPOSE, S.CLARIFY, S.SAFE_CONTINUE, *_ACTIVE_ANYTIME}),
    S.IDENTIFY_PURPOSE: frozenset({S.IDENTIFY_CALLER, S.CLARIFY, S.SAFE_CONTINUE, *_ACTIVE_ANYTIME}),
    S.CLARIFY: frozenset({S.IDENTIFY_CALLER, S.IDENTIFY_PURPOSE, S.SAFE_CONTINUE, *_ACTIVE_ANYTIME}),
    S.ASSESSING: frozenset(
        {S.IDENTIFY_CALLER, S.IDENTIFY_PURPOSE, S.CLARIFY, S.SAFE_CONTINUE, *_ACTIVE_ANYTIME - {S.ASSESSING}}
    ),
    S.SAFE_CONTINUE: frozenset({S.IDENTIFY_PURPOSE, S.CLARIFY, *_ACTIVE_ANYTIME}),
    S.ESCALATE: frozenset({S.SAFE_CONTINUE, S.IDENTIFY_PURPOSE, S.CLARIFY, *_ACTIVE_ANYTIME - {S.ESCALATE}}),
    S.REFUSE_SENSITIVE_REQUEST: frozenset(
        {S.SAFE_CONTINUE, S.IDENTIFY_PURPOSE, *_ACTIVE_ANYTIME - {S.REFUSE_SENSITIVE_REQUEST}}
    ),
    S.END_SPAM: frozenset({S.COMPLETED, S.FAILED}),
    S.END_SILENCE: frozenset({S.COMPLETED, S.FAILED}),
    S.OWNER_TAKEOVER: frozenset({S.COMPLETED, S.FAILED, S.SAFE_CONTINUE}),
    S.COMPLETED: frozenset(),
    S.FAILED: frozenset(),
}


class InvalidTransition(RuntimeError):
    def __init__(self, source: CallState, target: CallState) -> None:
        super().__init__(f"illegal call-state transition {source.value} -> {target.value}")
        self.source = source
        self.target = target


def can_transition(source: CallState, target: CallState) -> bool:
    return target in ALLOWED[source]


def transition(source: CallState, target: CallState) -> CallState:
    if source == target:
        return target
    if not can_transition(source, target):
        raise InvalidTransition(source, target)
    return target


def is_terminal(state: CallState) -> bool:
    return state in TERMINAL_STATES


def is_ending(state: CallState) -> bool:
    return state in ENDING_STATES or state in TERMINAL_STATES


def is_active(state: CallState) -> bool:
    return not is_ending(state)
