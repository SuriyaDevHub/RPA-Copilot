"""Incident states and allowed transitions (SPEC §2)."""

from __future__ import annotations

from enum import StrEnum


class State(StrEnum):
    RECEIVED = "RECEIVED"
    LOGS_PARSED = "LOGS_PARSED"
    DIAGNOSED = "DIAGNOSED"
    ROUTED = "ROUTED"
    USER_FIX_SHOWN = "USER_FIX_SHOWN"
    RERUN_ADVISED = "RERUN_ADVISED"
    ACTION_PROPOSED = "ACTION_PROPOSED"
    ACTION_CONFIRMED = "ACTION_CONFIRMED"
    ACTION_SUCCEEDED = "ACTION_SUCCEEDED"
    ACTION_FAILED = "ACTION_FAILED"
    DRAFTED = "DRAFTED"
    IN_REVIEW = "IN_REVIEW"
    SUBMITTED = "SUBMITTED"
    TICKETED = "TICKETED"
    RESOLVED_L2 = "RESOLVED_L2"
    KB_PENDING = "KB_PENDING"
    KB_UPDATED = "KB_UPDATED"
    CLOSED = "CLOSED"
    FALLBACK_MANUAL = "FALLBACK_MANUAL"


S = State

# Finished: nothing, not even FALLBACK_MANUAL, follows these.
TERMINAL: frozenset[State] = frozenset({S.CLOSED, S.KB_UPDATED})

_FORWARD: dict[State, frozenset[State]] = {
    S.RECEIVED: frozenset({S.LOGS_PARSED}),
    S.LOGS_PARSED: frozenset({S.DIAGNOSED}),
    S.DIAGNOSED: frozenset({S.ROUTED}),
    S.ROUTED: frozenset({S.USER_FIX_SHOWN, S.RERUN_ADVISED, S.ACTION_PROPOSED, S.DRAFTED}),
    S.USER_FIX_SHOWN: frozenset({S.CLOSED, S.DRAFTED}),
    S.RERUN_ADVISED: frozenset({S.CLOSED, S.DRAFTED}),
    S.ACTION_PROPOSED: frozenset({S.ACTION_CONFIRMED}),
    S.ACTION_CONFIRMED: frozenset({S.ACTION_SUCCEEDED, S.ACTION_FAILED}),
    S.ACTION_SUCCEEDED: frozenset({S.CLOSED}),
    S.ACTION_FAILED: frozenset({S.DRAFTED}),
    S.DRAFTED: frozenset({S.IN_REVIEW}),
    S.IN_REVIEW: frozenset({S.SUBMITTED}),
    S.SUBMITTED: frozenset({S.TICKETED}),
    S.TICKETED: frozenset({S.RESOLVED_L2}),
    S.RESOLVED_L2: frozenset({S.KB_PENDING}),
    S.KB_PENDING: frozenset({S.KB_UPDATED}),
    # The user can still review and submit the manual template.
    S.FALLBACK_MANUAL: frozenset({S.IN_REVIEW}),
    S.CLOSED: frozenset(),
    S.KB_UPDATED: frozenset(),
}

# Any unfinished state may fall back to manual handling.
ALLOWED: dict[State, frozenset[State]] = {
    state: targets | {S.FALLBACK_MANUAL}
    if state not in TERMINAL and state is not S.FALLBACK_MANUAL
    else targets
    for state, targets in _FORWARD.items()
}


def can_transition(from_state: State, to_state: State) -> bool:
    return to_state in ALLOWED[from_state]
