import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import set_committed_value

from genie_copilot.db.models import Incident, IncidentEvent
from genie_copilot.db.session import session_scope
from genie_copilot.orchestrator.machine import ConcurrentTransition, IllegalTransition, transition
from genie_copilot.orchestrator.states import ALLOWED, State

ALL_EDGES = [(src, dst) for src, targets in ALLOWED.items() for dst in sorted(targets)]


@pytest.mark.parametrize(("src", "dst"), ALL_EDGES, ids=[f"{a}->{b}" for a, b in ALL_EDGES])
def test_every_allowed_transition(
    factory: sessionmaker[Session],
    make_incident,  # type: ignore[no-untyped-def]
    src: State,
    dst: State,
) -> None:
    incident = make_incident(state=src)
    with session_scope(factory) as s:
        inc = s.get(Incident, incident.id)
        assert inc is not None
        transition(s, inc, dst, "test", actor="alice")
        assert inc.state == dst
    with session_scope(factory) as s:
        inc = s.get(Incident, incident.id)
        assert inc is not None and inc.state == dst
        events = s.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id)).all()
        assert [(e.from_state, e.to_state, e.actor) for e in events] == [(src, dst, "alice")]


def test_illegal_transition_raises_and_writes_nothing(
    factory: sessionmaker[Session],
    make_incident,  # type: ignore[no-untyped-def]
) -> None:
    incident = make_incident()
    with pytest.raises(IllegalTransition), session_scope(factory) as s:
        inc = s.get(Incident, incident.id)
        assert inc is not None
        transition(s, inc, State.TICKETED, "skip ahead")
    with session_scope(factory) as s:
        assert s.scalars(select(IncidentEvent)).all() == []
        inc = s.get(Incident, incident.id)
        assert inc is not None and inc.state == State.RECEIVED


def test_stale_state_raises_concurrent_transition(
    factory: sessionmaker[Session],
    make_incident,  # type: ignore[no-untyped-def]
) -> None:
    incident = make_incident()
    with session_scope(factory) as s:
        inc = s.get(Incident, incident.id)
        assert inc is not None
        transition(s, inc, State.LOGS_PARSED, "parsed by worker 1")
    with pytest.raises(ConcurrentTransition), session_scope(factory) as s:
        inc = s.get(Incident, incident.id)
        assert inc is not None
        # Simulate a second worker that read the incident before worker 1 moved it.
        set_committed_value(inc, "state", State.RECEIVED.value)
        transition(s, inc, State.LOGS_PARSED, "parsed by worker 2")
    with session_scope(factory) as s:
        events = s.scalars(select(IncidentEvent)).all()
        assert [e.reason for e in events] == ["parsed by worker 1"]
