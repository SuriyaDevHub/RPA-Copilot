"""Job queue (SPEC §4). The only module besides Alembic allowed dialect-specific SQL.

`claim` and `reclaim_stale` run their own transactions; `enqueue`, `complete` and `fail`
join the caller's session so job changes commit together with the work they record.
`attempts` counts claims: a job gets MAX_ATTEMPTS tries, then its incident falls back.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import Engine, bindparam, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from genie_copilot.db.models import Incident, Job, JobStatus
from genie_copilot.db.session import SQLITE_BEGIN
from genie_copilot.db.types import UTCDateTime, utcnow
from genie_copilot.orchestrator.machine import transition
from genie_copilot.orchestrator.states import State, can_transition

MAX_ATTEMPTS = 4
BACKOFF: tuple[timedelta, ...] = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
)
_ERROR_MAX = 2000


class JobQueue(Protocol):
    def enqueue(
        self, session: Session, incident_id: str, type: str, run_after: datetime | None = None
    ) -> Job: ...

    def claim(self, worker_id: str) -> Job | None: ...

    def complete(self, session: Session, job: Job) -> None: ...

    def fail(
        self, session: Session, job: Job, error: str, retry_in: timedelta | None = None
    ) -> bool: ...

    def reclaim_stale(self, timeout_s: float) -> int: ...


class _BaseQueue:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def enqueue(
        self, session: Session, incident_id: str, type: str, run_after: datetime | None = None
    ) -> Job:
        """Idempotent on (incident_id, type): returns the existing job if there is one."""
        existing = self._find(session, incident_id, type)
        if existing is not None:
            return existing
        job = Job(incident_id=incident_id, type=type, run_after=run_after)
        try:
            with session.begin_nested():
                session.add(job)
        except IntegrityError:
            found = self._find(session, incident_id, type)
            if found is None:
                raise
            return found
        return job

    def claim(self, worker_id: str) -> Job | None:
        raise NotImplementedError

    def complete(self, session: Session, job: Job) -> None:
        row = self._load(session, job)
        row.status = JobStatus.DONE
        row.locked_at = None
        row.locked_by = None
        session.flush()

    def fail(
        self, session: Session, job: Job, error: str, retry_in: timedelta | None = None
    ) -> bool:
        """Requeue with backoff and return True, or give up and move the incident to
        FALLBACK_MANUAL and return False."""
        row = self._load(session, job)
        row.last_error = error[:_ERROR_MAX]
        row.locked_at = None
        row.locked_by = None
        if row.attempts >= MAX_ATTEMPTS:
            row.status = JobStatus.FAILED
            incident = session.get(Incident, row.incident_id)
            if incident is not None and can_transition(
                State(incident.state), State.FALLBACK_MANUAL
            ):
                transition(
                    session,
                    incident,
                    State.FALLBACK_MANUAL,
                    f"job {row.type} failed after {row.attempts} attempts: {error}",
                )
            session.flush()
            return False
        delay = (
            retry_in
            if retry_in is not None
            else BACKOFF[min(max(row.attempts, 1), len(BACKOFF)) - 1]
        )
        row.status = JobStatus.QUEUED
        row.run_after = utcnow() + delay
        session.flush()
        return True

    def reclaim_stale(self, timeout_s: float) -> int:
        """Treat jobs locked longer than timeout_s as failed attempts (worker crashed)."""
        cutoff = utcnow() - timedelta(seconds=timeout_s)
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            stale = session.scalars(
                select(Job).where(Job.status == JobStatus.RUNNING, Job.locked_at < cutoff)
            ).all()
            for job in stale:
                self.fail(session, job, f"stale lock held by {job.locked_by} reclaimed")
            return len(stale)

    @staticmethod
    def _find(session: Session, incident_id: str, type: str) -> Job | None:
        return session.scalars(
            select(Job).where(Job.incident_id == incident_id, Job.type == type)
        ).first()

    @staticmethod
    def _load(session: Session, job: Job) -> Job:
        row = session.get(Job, job.id)
        if row is None:
            raise LookupError(f"job {job.id} not found")
        return row


class SqliteJobQueue(_BaseQueue):
    """Single worker. BEGIN IMMEDIATE takes the write lock before reading."""

    def claim(self, worker_id: str) -> Job | None:
        now = utcnow()
        with (
            self._engine.connect().execution_options(**{SQLITE_BEGIN: "BEGIN IMMEDIATE"}) as conn,
            Session(bind=conn, expire_on_commit=False) as session,
            session.begin(),
        ):
            job = session.scalars(
                select(Job)
                .where(
                    Job.status == JobStatus.QUEUED,
                    or_(Job.run_after.is_(None), Job.run_after <= now),
                )
                .order_by(Job.id)
                .limit(1)
            ).first()
            if job is None:
                return None
            job.status = JobStatus.RUNNING
            job.locked_at = now
            job.locked_by = worker_id
            job.attempts += 1
        return job


_MSSQL_CLAIM = text(
    """
    WITH next AS (
        SELECT TOP (1) * FROM job WITH (UPDLOCK, READPAST, ROWLOCK)
        WHERE status = 'queued' AND (run_after IS NULL OR run_after <= :now)
        ORDER BY id
    )
    UPDATE next
    SET status = 'running', locked_at = :now, locked_by = :worker, attempts = attempts + 1
    OUTPUT inserted.id;
    """
).bindparams(bindparam("now", type_=UTCDateTime()))


class MssqlJobQueue(_BaseQueue):
    """Many workers. READPAST skips rows other workers have locked."""

    def claim(self, worker_id: str) -> Job | None:
        now = utcnow()
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            job_id = session.execute(_MSSQL_CLAIM, {"now": now, "worker": worker_id}).scalar()
            if job_id is None:
                return None
            return session.get(Job, job_id)


def make_queue(engine: Engine) -> JobQueue:
    if engine.dialect.name == "sqlite":
        return SqliteJobQueue(engine)
    if engine.dialect.name == "mssql":
        return MssqlJobQueue(engine)
    raise ValueError(f"unsupported database dialect: {engine.dialect.name}")
