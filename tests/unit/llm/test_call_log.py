from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.db.models import LLMCall
from genie_copilot.db.session import session_scope
from genie_copilot.llm.client import DbCallLog


def test_db_call_log_persists_rows(factory: sessionmaker[Session]) -> None:
    log = DbCallLog(factory)
    log(LLMCall(purpose="diagnose", model="m", input_hash="h" * 64, status="ok"))
    with session_scope(factory) as s:
        [row] = s.scalars(select(LLMCall)).all()
        assert row.status == "ok" and row.at.tzinfo is not None


def test_db_call_log_never_raises(factory: sessionmaker[Session]) -> None:
    DbCallLog(factory)(LLMCall(purpose="x", model="m", input_hash=None, status="ok"))  # type: ignore[arg-type]
