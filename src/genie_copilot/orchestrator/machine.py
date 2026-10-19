"""State transitions. Every change writes an `incident_event` row in the caller's transaction."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from genie_copilot.db.models import Incident, IncidentEvent
from genie_copilot.db.types import utcnow
from genie_copilot.orchestrator.states import State, can_transition


class IllegalTransition(Exception):
    def __init__(self, from_state: State, to_state: State) -> None:
        super().__init__(f"illegal transition {from_state} -> {to_state}")
        self.from_state = from_state
        self.to_state = to_state


class ConcurrentTransition(Exception):
    """The incident's state changed since it was read."""


def transition(
    session: Session,
    incident: Incident,
    to_state: State,
    reason: str,
    actor: str = "system",
) -> IncidentEvent:
    from_state = State(incident.state)
    if not can_transition(from_state, to_state):
        raise IllegalTransition(from_state, to_state)

    now = utcnow()
    # Compare-and-set on the old state so two processes cannot both move the incident.
    result = session.execute(
        update(Incident)
        .where(Incident.id == incident.id, Incident.state == from_state.value)
        .values(state=to_state.value, updated_at=now)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise ConcurrentTransition(f"incident {incident.id} is no longer {from_state}")

    event = IncidentEvent(
        incident_id=incident.id,
        from_state=from_state.value,
        to_state=to_state.value,
        reason=reason[:512],
        actor=actor,
        at=now,
    )
    session.add(event)
    session.flush()
    return event
