from datetime import timedelta

import pytest
from freezegun import freeze_time
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.db.models import Incident, Job, JobStatus
from genie_copilot.db.queue import BACKOFF, MAX_ATTEMPTS, JobQueue, make_queue
from genie_copilot.db.repositories import EventRepo
from genie_copilot.db.session import session_scope
from genie_copilot.db.types import utcnow
from genie_copilot.orchestrator.states import State

T0 = "2026-10-19 12:00:00+00:00"


@pytest.fixture
def queue(engine: Engine) -> JobQueue:
    return make_queue(engine)


def _enqueue(
    factory: sessionmaker[Session],
    queue: JobQueue,
    incident_id: str,
    type: str = "parse",
    **kw: object,
) -> Job:
    with session_scope(factory) as s:
        return queue.enqueue(s, incident_id, type, **kw)  # type: ignore[arg-type]


def _get(factory: sessionmaker[Session], job: Job) -> Job:
    with session_scope(factory) as s:
        row = s.get(Job, job.id)
        assert row is not None
        return row


def test_enqueue_claim_complete(factory, queue, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident()
    job = _enqueue(factory, queue, inc.id)
    claimed = queue.claim("w1")
    assert claimed is not None and claimed.id == job.id
    assert claimed.status == JobStatus.RUNNING
    assert claimed.locked_by == "w1" and claimed.attempts == 1
    assert queue.claim("w2") is None
    with session_scope(factory) as s:
        queue.complete(s, claimed)
    done = _get(factory, job)
    assert done.status == JobStatus.DONE and done.locked_by is None


def test_enqueue_is_idempotent(factory, queue, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident()
    first = _enqueue(factory, queue, inc.id)
    second = _enqueue(factory, queue, inc.id)
    assert first.id == second.id
    other = _enqueue(factory, queue, inc.id, "diagnose")
    assert other.id != first.id


def test_enqueue_joins_caller_transaction(factory, queue, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident()
    with pytest.raises(RuntimeError), session_scope(factory) as s:
        queue.enqueue(s, inc.id, "parse")
        raise RuntimeError("rollback")
    assert queue.claim("w1") is None


def test_claims_oldest_first(factory, queue, make_incident) -> None:  # type: ignore[no-untyped-def]
    jobs = [_enqueue(factory, queue, make_incident().id) for _ in range(3)]
    claimed = [queue.claim("w1") for _ in range(3)]
    assert [j.id for j in claimed if j] == [j.id for j in jobs]


def test_job_not_due_is_not_claimed(factory, queue, make_incident) -> None:  # type: ignore[no-untyped-def]
    with freeze_time(T0):
        _enqueue(factory, queue, make_incident().id, run_after=utcnow() + timedelta(minutes=5))
        assert queue.claim("w1") is None
    with freeze_time("2026-10-19 12:05:01+00:00"):
        assert queue.claim("w1") is not None


def test_fail_backs_off_then_falls_back(factory, queue, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident(state=State.LOGS_PARSED)
    job = _enqueue(factory, queue, inc.id, "diagnose")
    now = utcnow()
    with freeze_time(now) as clock:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            claimed = queue.claim("w1")
            assert claimed is not None, f"attempt {attempt} not claimable"
            assert claimed.attempts == attempt
            with session_scope(factory) as s:
                retry = queue.fail(s, claimed, f"boom {attempt}")
            row = _get(factory, job)
            if attempt < MAX_ATTEMPTS:
                assert retry is True
                assert row.status == JobStatus.QUEUED
                delay = BACKOFF[attempt - 1]
                assert row.run_after == utcnow() + delay
                assert queue.claim("w1") is None  # not due yet
                clock.tick(delay)
            else:
                assert retry is False
                assert row.status == JobStatus.FAILED
                assert row.last_error == f"boom {attempt}"

    with session_scope(factory) as s:
        incident = s.get(Incident, inc.id)
        assert incident is not None and incident.state == State.FALLBACK_MANUAL
        events = EventRepo(s).for_incident(inc.id)
        assert events[-1].to_state == State.FALLBACK_MANUAL
        assert "after 4 attempts" in events[-1].reason


def test_retry_in_overrides_backoff(factory, queue, make_incident) -> None:  # type: ignore[no-untyped-def]
    job = _enqueue(factory, queue, make_incident().id)
    with freeze_time(T0):
        claimed = queue.claim("w1")
        assert claimed is not None
        with session_scope(factory) as s:
            queue.fail(s, claimed, "429", retry_in=timedelta(seconds=5))
        assert _get(factory, job).run_after == utcnow() + timedelta(seconds=5)


def test_final_failure_on_finished_incident_leaves_state(factory, queue, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident(state=State.CLOSED)
    _enqueue(factory, queue, inc.id, "learn")
    with freeze_time(T0) as clock:
        for _ in range(MAX_ATTEMPTS):
            claimed = queue.claim("w1")
            assert claimed is not None
            with session_scope(factory) as s:
                queue.fail(s, claimed, "boom")
            clock.tick(timedelta(hours=1))
    with session_scope(factory) as s:
        incident = s.get(Incident, inc.id)
        assert incident is not None and incident.state == State.CLOSED


def test_reclaim_stale(factory, queue, make_incident) -> None:  # type: ignore[no-untyped-def]
    job = _enqueue(factory, queue, make_incident().id)
    with freeze_time(T0) as clock:
        assert queue.claim("crashed-worker") is not None
        clock.tick(timedelta(seconds=60))
        assert queue.reclaim_stale(timeout_s=300) == 0
        clock.tick(timedelta(seconds=300))
        assert queue.reclaim_stale(timeout_s=300) == 1
        row = _get(factory, job)
        assert row.status == JobStatus.QUEUED
        assert row.locked_by is None
        assert "crashed-worker" in (row.last_error or "")
        clock.tick(BACKOFF[0])
        again = queue.claim("w2")
        assert again is not None and again.attempts == 2
