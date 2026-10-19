from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.agents.log_parser import LogParserAgent
from genie_copilot.config import Settings
from genie_copilot.db.models import Incident, IncidentEvent, ParsedErrorRow
from genie_copilot.db.session import session_scope
from genie_copilot.logs.models import RawLog
from genie_copilot.orchestrator.states import State

from ..logs.conftest import PLANTED, load


class DictSource:
    name = "test"

    def __init__(self, user_ids: dict[str, str]) -> None:
        self.reads: list[str] = []
        self._user_ids = user_ids

    def read(self, key: str) -> RawLog:
        self.reads.append(key)
        return load(key, user_id=self._user_ids.get(key))


USERS = {
    "simple_ioexception.log": "jdoe",
    "inner_chain.log": "asmith",
    "successful_run.log": "jdoe",
}


def _settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        in_house_namespaces=["Genie."],
        mask_names=["John Doe"],
        mask_host_patterns=[r"\bVDI-[A-Z]{3}-\d{4}\b"],
    )


def _run(factory: sessionmaker[Session], source: DictSource, incident_id: str) -> None:
    with session_scope(factory) as s:
        LogParserAgent(source, _settings()).run(s, incident_id)


def test_parses_masks_stores_and_transitions(factory, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident(s3_log_key="simple_ioexception.log")
    source = DictSource(USERS)
    _run(factory, source, inc.id)
    with session_scope(factory) as s:
        incident = s.get(Incident, inc.id)
        row = s.get(ParsedErrorRow, inc.id)
        assert incident is not None and row is not None
        assert incident.state == State.LOGS_PARSED
        assert incident.user_id == "jdoe"
        assert incident.error_signature and len(incident.error_signature) == 16
        assert row.exception_type == "System.IO.IOException"
        assert row.frames[0]["exception_type"] == "System.IO.IOException"
        assert row.line_ids[0] == 1
        assert "L3 " in row.log_window_masked
        stored = " ".join([row.message_masked, row.log_window_masked, str(row.frames)]).lower()
        for value in PLANTED:
            assert value.lower() not in stored, value
        event = s.scalars(select(IncidentEvent)).one()
        assert event.reason == "System.IO.IOException at L3"


def test_root_cause_of_chain_in_event(factory, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident(s3_log_key="inner_chain.log")
    _run(factory, DictSource(USERS), inc.id)
    with session_scope(factory) as s:
        row = s.get(ParsedErrorRow, inc.id)
        assert row is not None
        assert [e["exception_type"] for e in row.frames][-1] == "System.Net.Sockets.SocketException"


def test_successful_log_falls_back(factory, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident(s3_log_key="successful_run.log")
    _run(factory, DictSource(USERS), inc.id)
    with session_scope(factory) as s:
        incident = s.get(Incident, inc.id)
        assert incident is not None and incident.state == State.FALLBACK_MANUAL
        assert s.get(ParsedErrorRow, inc.id) is None


def test_rerun_is_idempotent(factory, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident(s3_log_key="simple_ioexception.log")
    source = DictSource(USERS)
    _run(factory, source, inc.id)
    _run(factory, source, inc.id)
    assert source.reads == ["simple_ioexception.log"]
    with session_scope(factory) as s:
        assert len(s.scalars(select(IncidentEvent)).all()) == 1
