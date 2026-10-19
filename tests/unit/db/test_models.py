import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.db.models import Job, KBItem
from genie_copilot.db.session import session_scope


def test_dedup_key_unique(make_incident) -> None:  # type: ignore[no-untyped-def]
    make_incident(dedup_key="logs/bot-a/run-1.log")
    with pytest.raises(IntegrityError):
        make_incident(dedup_key="logs/bot-a/run-1.log")


def test_kb_content_hash_unique(factory: sessionmaker[Session]) -> None:
    def add() -> None:
        with session_scope(factory) as s:
            s.add(KBItem(source="jira", title="t", text_masked="x", content_hash="h" * 64))

    add()
    with pytest.raises(IntegrityError):
        add()


def test_foreign_keys_enforced(factory: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError), session_scope(factory) as s:
        s.add(Job(incident_id="00000000-0000-0000-0000-000000000000", type="parse"))


def test_defaults(make_incident) -> None:  # type: ignore[no-untyped-def]
    incident = make_incident()
    assert incident.state == "RECEIVED"
    assert incident.created_at.tzinfo is not None
