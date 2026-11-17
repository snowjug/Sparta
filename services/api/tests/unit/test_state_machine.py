from itertools import pairwise

import pytest

from sparta.domain.enums import ENDING_STATES, TERMINAL_STATES, CallState
from sparta.orchestrator.state_machine import (
    ALLOWED,
    InvalidTransition,
    can_transition,
    is_active,
    transition,
)

S = CallState


def test_every_state_has_a_transition_entry():
    assert set(ALLOWED) == set(CallState)


def test_terminal_states_have_no_outgoing_transitions():
    for state in TERMINAL_STATES:
        assert ALLOWED[state] == frozenset()


def test_every_state_can_reach_completed():
    """No state is a dead end: a call can always be completed (or fail)."""
    for state in CallState:
        if state in TERMINAL_STATES:
            continue
        seen, frontier = {state}, [state]
        while frontier:
            for nxt in ALLOWED[frontier.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        assert S.COMPLETED in seen, state


def test_happy_path_walks_the_documented_states():
    path = [
        S.INITIALIZING,
        S.DISCLOSURE,
        S.IDENTIFY_CALLER,
        S.ASSESSING,
        S.REFUSE_SENSITIVE_REQUEST,
        S.END_SPAM,
        S.COMPLETED,
    ]
    for a, b in pairwise(path):
        assert transition(a, b) == b


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (S.INITIALIZING, S.IDENTIFY_CALLER),  # must disclose first
        (S.END_SPAM, S.IDENTIFY_CALLER),  # a call that is ending cannot resume
        (S.END_SILENCE, S.ESCALATE),
        (S.COMPLETED, S.DISCLOSURE),
        (S.FAILED, S.COMPLETED),
    ],
)
def test_illegal_transitions_raise(a, b):
    assert not can_transition(a, b)
    with pytest.raises(InvalidTransition):
        transition(a, b)


def test_staying_in_the_same_state_is_a_noop():
    assert transition(S.ESCALATE, S.ESCALATE) == S.ESCALATE


def test_ending_states_are_not_active():
    for state in ENDING_STATES | TERMINAL_STATES:
        assert not is_active(state)
    assert is_active(S.ESCALATE) and is_active(S.OWNER_TAKEOVER)
