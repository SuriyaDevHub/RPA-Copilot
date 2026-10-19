import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.db.models import Base, Incident, IncidentSource
from genie_copilot.db.session import make_engine, make_session_factory, session_scope
from genie_copilot.db.types import new_id

MSSQL_TEST_URL = os.environ.get("MSSQL_TEST_URL")


@pytest.fixture(
    params=["sqlite", pytest.param("mssql", marks=pytest.mark.mssql)],
)
def engine(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Engine]:
    """Fresh schema per test, on SQLite always and on SQL Server when MSSQL_TEST_URL is set."""
    if request.param == "mssql":
        if not MSSQL_TEST_URL:
            pytest.skip("MSSQL_TEST_URL not set")
        eng = make_engine(MSSQL_TEST_URL)
        Base.metadata.drop_all(eng)
    else:
        if request.node.get_closest_marker("mssql_only"):
            pytest.skip("SQL Server only")
        eng = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(eng)
    yield eng
    if request.param == "mssql":
        Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture
def make_incident(factory: sessionmaker[Session]):  # type: ignore[no-untyped-def]
    def _make(**fields: object) -> Incident:
        values: dict[str, object] = {
            "source": IncidentSource.S3_WATCHER,
            "dedup_key": f"logs/bot-a/{new_id()}.log",
            "bot_name": "bot-a",
        }
        values.update(fields)
        with session_scope(factory) as s:
            incident = Incident(**values)
            s.add(incident)
        return incident

    return _make
