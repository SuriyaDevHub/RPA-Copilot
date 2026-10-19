import pytest

from genie_copilot.orchestrator.states import ALLOWED, TERMINAL, State, can_transition


def test_every_state_has_an_entry() -> None:
    assert set(ALLOWED) == set(State)


def test_terminal_states_have_no_exits() -> None:
    for state in TERMINAL:
        assert ALLOWED[state] == frozenset()


def test_every_unfinished_state_can_fall_back() -> None:
    for state in State:
        expected = state not in TERMINAL and state is not State.FALLBACK_MANUAL
        assert can_transition(state, State.FALLBACK_MANUAL) is expected


def test_fallback_can_go_to_manual_review() -> None:
    assert ALLOWED[State.FALLBACK_MANUAL] == {State.IN_REVIEW}


def test_every_state_reachable_from_received() -> None:
    seen, todo = {State.RECEIVED}, [State.RECEIVED]
    while todo:
        for nxt in ALLOWED[todo.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    assert seen == set(State)


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (State.RECEIVED, State.DIAGNOSED),
        (State.RECEIVED, State.SUBMITTED),
        (State.ROUTED, State.TICKETED),
        (State.DRAFTED, State.SUBMITTED),
        (State.ACTION_PROPOSED, State.ACTION_SUCCEEDED),
        (State.CLOSED, State.RECEIVED),
        (State.CLOSED, State.FALLBACK_MANUAL),
        (State.KB_UPDATED, State.FALLBACK_MANUAL),
        (State.FALLBACK_MANUAL, State.SUBMITTED),
        (State.TICKETED, State.CLOSED),
    ],
)
def test_illegal_transitions(src: State, dst: State) -> None:
    assert not can_transition(src, dst)
