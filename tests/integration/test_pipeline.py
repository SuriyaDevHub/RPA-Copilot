"""M4 acceptance: S3 -> watcher -> incidents -> worker -> parsed, with crash recovery."""

from datetime import timedelta

from freezegun import freeze_time
from sqlalchemy import select
from sqlalchemy.orm import Session

from genie_copilot.db.models import Incident, IncidentEvent, Job, JobStatus, WatcherState
from genie_copilot.db.queue import MAX_ATTEMPTS
from genie_copilot.db.session import session_scope
from genie_copilot.orchestrator.handlers import Handler
from genie_copilot.orchestrator.states import State
from genie_copilot.orchestrator.worker import Worker
from tests.helpers import make_runtime, upload

T0 = "2026-10-19 12:00:00+00:00"


def _incidents(s: Session) -> list[Incident]:
    return list(s.scalars(select(Incident).order_by(Incident.created_at, Incident.dedup_key)))


def test_watcher_to_parsed_without_duplicates(engine, s3) -> None:  # type: ignore[no-untyped-def]
    failed = [upload(s3, "simple_ioexception.log"), upload(s3, "inner_chain.log")]
    upload(s3, "successful_run.log")
    runtime = make_runtime(engine, s3)

    result = runtime.watcher().poll_once()
    assert (result.seen, result.created, result.skipped_ok) == (3, 2, 1)
    with session_scope(runtime.factory) as s:
        incidents = _incidents(s)
        assert sorted(i.dedup_key for i in incidents) == sorted(failed)
        assert {i.state for i in incidents} == {State.RECEIVED}
        assert s.get(WatcherState, "s3:bot-a") is not None

    worker = runtime.worker("w1")
    assert worker.run_once() and worker.run_once()  # the two parse jobs
    with session_scope(runtime.factory) as s:
        assert {i.state for i in _incidents(s)} == {State.LOGS_PARSED}
        assert all(i.error_signature for i in _incidents(s))

    assert runtime.watcher().poll_once().created == 0  # rerun: no duplicates

    worker.drain()  # diagnose is a stub until M6
    with session_scope(runtime.factory) as s:
        assert {i.state for i in _incidents(s)} == {State.FALLBACK_MANUAL}
        reasons = s.scalars(
            select(IncidentEvent.reason).where(IncidentEvent.to_state == State.FALLBACK_MANUAL)
        ).all()
        assert all("not built yet (M6)" in r for r in reasons)
        assert {j.status for j in s.scalars(select(Job))} == {JobStatus.DONE}


def test_new_objects_after_watermark_are_picked_up(engine, s3) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(engine, s3)
    with freeze_time(T0) as clock:
        upload(s3, "simple_ioexception.log")
        assert runtime.watcher().poll_once().created == 1
        clock.tick(timedelta(minutes=5))
        upload(s3, "inner_chain.log")
        result = runtime.watcher().poll_once()
    assert result.created == 1


def test_worker_crash_mid_job_resumes(engine, s3) -> None:  # type: ignore[no-untyped-def]
    upload(s3, "simple_ioexception.log")
    runtime = make_runtime(engine, s3)
    with freeze_time(T0) as clock:
        runtime.watcher().poll_once()
        crashed = runtime.queue.claim("crashed-worker")  # claimed, never finished
        assert crashed is not None

        survivor = runtime.worker("w2")
        assert survivor.run_once() is False  # the job is still locked
        clock.tick(timedelta(seconds=runtime.settings.worker_stale_lock_s + 1))
        assert survivor.reclaim() == 1
        clock.tick(timedelta(seconds=31))  # first backoff
        assert survivor.run_once() is True

    with session_scope(runtime.factory) as s:
        [incident] = _incidents(s)
        assert incident.state == State.LOGS_PARSED
        job = s.scalars(select(Job).where(Job.type == "parse")).one()
        assert job.status == JobStatus.DONE and job.attempts == 2


def test_failing_handler_retries_then_falls_back(engine, s3, make_incident) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(engine, s3)
    inc = make_incident()
    calls: list[str] = []

    def boom(session, incident, queue) -> None:  # type: ignore[no-untyped-def]
        calls.append(incident.id)
        raise RuntimeError("agent exploded")

    handlers: dict[str, Handler] = {"parse": boom}
    worker = Worker(runtime.factory, runtime.queue, handlers, "w1")
    with session_scope(runtime.factory) as s:
        runtime.queue.enqueue(s, inc.id, "parse")
    with freeze_time(T0) as clock:
        for _ in range(MAX_ATTEMPTS):
            assert worker.run_once()
            clock.tick(timedelta(minutes=11))
    assert len(calls) == MAX_ATTEMPTS
    with session_scope(runtime.factory) as s:
        incident = s.get(Incident, inc.id)
        assert incident is not None and incident.state == State.FALLBACK_MANUAL
        job = s.scalars(select(Job)).one()
        assert job.status == JobStatus.FAILED and "agent exploded" in (job.last_error or "")


def test_handler_work_rolls_back_on_failure(engine, s3, make_incident) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(engine, s3)
    inc = make_incident()

    def half_done(session, incident, queue) -> None:  # type: ignore[no-untyped-def]
        incident.category = "SHOULD_NOT_STICK"
        raise RuntimeError("boom")

    worker = Worker(runtime.factory, runtime.queue, {"parse": half_done}, "w1")
    with session_scope(runtime.factory) as s:
        runtime.queue.enqueue(s, inc.id, "parse")
    worker.run_once()
    with session_scope(runtime.factory) as s:
        incident = s.get(Incident, inc.id)
        assert incident is not None and incident.category is None


def test_unknown_job_type_fails_the_job(engine, s3, make_incident) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(engine, s3)
    inc = make_incident()
    with session_scope(runtime.factory) as s:
        runtime.queue.enqueue(s, inc.id, "mystery")
    Worker(runtime.factory, runtime.queue, {}, "w1").run_once()
    with session_scope(runtime.factory) as s:
        job = s.scalars(select(Job)).one()
        assert job.status == JobStatus.QUEUED and "UnknownJobType" in (job.last_error or "")


def test_jobs_for_finished_incidents_complete_without_work(engine, s3, make_incident) -> None:  # type: ignore[no-untyped-def]
    runtime = make_runtime(engine, s3)
    inc = make_incident(state=State.CLOSED)
    with session_scope(runtime.factory) as s:
        runtime.queue.enqueue(s, inc.id, "parse")
    assert runtime.worker("w1").run_once()
    with session_scope(runtime.factory) as s:
        assert s.scalars(select(Job)).one().status == JobStatus.DONE
