from datetime import timedelta

from freezegun import freeze_time
from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.db.models import Incident
from genie_copilot.db.repositories import IncidentRepo, OutboxRepo
from genie_copilot.db.session import session_scope
from genie_copilot.db.types import utcnow
from genie_copilot.orchestrator.machine import transition
from genie_copilot.orchestrator.states import State


def _escalate(factory: sessionmaker[Session], incident: Incident) -> None:
    with session_scope(factory) as s:
        inc = s.get(Incident, incident.id)
        assert inc is not None
        transition(s, inc, State.DRAFTED, "escalated")


def test_count_escalations_within_window(factory, make_incident) -> None:  # type: ignore[no-untyped-def]
    with freeze_time("2026-10-18 08:00:00+00:00"):
        _escalate(factory, make_incident(state=State.ROUTED, error_signature="abc"))
    with freeze_time("2026-10-19 09:00:00+00:00"):
        _escalate(factory, make_incident(state=State.ROUTED, error_signature="abc"))
        _escalate(factory, make_incident(state=State.ROUTED, error_signature="abc"))
        _escalate(factory, make_incident(state=State.ROUTED, error_signature="other"))
        with session_scope(factory) as s:
            repo = IncidentRepo(s)
            assert repo.count_escalations("abc", utcnow() - timedelta(hours=24)) == 2
            assert repo.count_escalations("abc", utcnow() - timedelta(days=3)) == 3


def test_get_by_dedup_key_and_list_for_user(factory, make_incident) -> None:  # type: ignore[no-untyped-def]
    a = make_incident(dedup_key="k1", user_id="u1")
    make_incident(dedup_key="k2", user_id="u2")
    with session_scope(factory) as s:
        repo = IncidentRepo(s)
        found = repo.get_by_dedup_key("k1")
        assert found is not None and found.id == a.id
        assert [i.id for i in repo.list_for_user("u1")] == [a.id]


def test_outbox_due(factory, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident()
    with freeze_time("2026-10-19 12:00:00+00:00"), session_scope(factory) as s:
        repo = OutboxRepo(s)
        now_row = repo.add(inc.id, "jira_create", {"summary": "x"})
        later = repo.add(inc.id, "email", {"to": "support"})
        later.next_attempt_at = utcnow() + timedelta(minutes=1)
        s.flush()
        assert [r.id for r in repo.due()] == [now_row.id]
