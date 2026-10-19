"""Engine and session factory.

SQLite: WAL, foreign keys and busy_timeout on every connection, and the pysqlite
transaction fix so `BEGIN IMMEDIATE` (used by the job queue) works.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.config import get_settings

# Execution option read by the "begin" hook; the queue sets it to "BEGIN IMMEDIATE".
SQLITE_BEGIN = "sqlite_begin"


def make_engine(url: str | None = None, **kwargs: Any) -> Engine:
    url = url or get_settings().database_url
    parsed = make_url(url)
    if parsed.get_backend_name() == "mssql":
        kwargs.setdefault("fast_executemany", True)
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        _configure_sqlite(engine)
    return engine


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        # Stop pysqlite from issuing its own BEGIN; the "begin" hook below does it.
        dbapi_conn.isolation_level = None
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Connection) -> None:
        conn.exec_driver_sql(conn.get_execution_options().get(SQLITE_BEGIN, "BEGIN"))


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """One unit of work: commit on success, roll back on error."""
    with factory() as session, session.begin():
        yield session
