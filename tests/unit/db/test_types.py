from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.db.models import Incident, ParsedErrorRow
from genie_copilot.db.session import session_scope


def test_utc_round_trip(factory: sessionmaker[Session], make_incident) -> None:  # type: ignore[no-untyped-def]
    ist = timezone(timedelta(hours=5, minutes=30))
    created = datetime(2026, 1, 2, 9, 30, 0, 123456, tzinfo=ist)
    incident = make_incident(created_at=created)
    with session_scope(factory) as s:
        loaded = s.get(Incident, incident.id)
        assert loaded is not None
        assert loaded.created_at.tzinfo is UTC
        assert loaded.created_at == created
        assert loaded.created_at.hour == 4


def test_naive_datetime_rejected(factory: sessionmaker[Session], make_incident) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(StatementError, match="naive datetime"):
        make_incident(created_at=datetime(2026, 1, 1))


def test_json_round_trip(factory: sessionmaker[Session], make_incident) -> None:  # type: ignore[no-untyped-def]
    incident = make_incident()
    frames = [{"method": "Bot.Run", "file": None, "line": 12, "in_house": True}]
    with session_scope(factory) as s:
        s.add(
            ParsedErrorRow(
                incident_id=incident.id,
                exception_type="System.IO.IOException",
                message_masked="Ünïcode ✓ message",
                frames=frames,
                log_window_masked="L1 ...",
                line_ids=[1, 2, 3],
                parser="s3_legacy/1",
            )
        )
    with session_scope(factory) as s:
        row = s.get(ParsedErrorRow, incident.id)
        assert row is not None
        assert row.frames == frames
        assert row.line_ids == [1, 2, 3]
        assert row.message_masked == "Ünïcode ✓ message"


def test_uuid_stored_lowercase(factory: sessionmaker[Session], make_incident) -> None:  # type: ignore[no-untyped-def]
    upper = "6F9619FF-8B86-D011-B42D-00C04FC964FF"
    make_incident(id=upper)
    with session_scope(factory) as s:
        assert s.get(Incident, upper.lower()) is not None


def test_invalid_uuid_rejected(make_incident) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(StatementError):
        make_incident(id="not-a-uuid")
