"""Job worker (SPEC §4, M4): claim, dispatch to the job type's handler, complete or fail.

A handler's work and the job's completion commit together. On an exception the work is
rolled back and the job is failed in a fresh transaction (backoff, then FALLBACK_MANUAL).
Stale locks from crashed workers are reclaimed on start and periodically.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time

from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.db.models import Incident, Job
from genie_copilot.db.queue import JobQueue
from genie_copilot.db.session import session_scope
from genie_copilot.observability.logging import log_context
from genie_copilot.orchestrator.handlers import Handler
from genie_copilot.orchestrator.states import TERMINAL, State

log = logging.getLogger(__name__)

RECLAIM_EVERY_S = 60.0
# Automation stops here; leftover jobs for these incidents are completed without work.
_NO_AUTOMATION = TERMINAL | {State.FALLBACK_MANUAL}


class UnknownJobType(Exception):
    pass


def default_worker_id(index: int = 0) -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{index}"


class Worker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        queue: JobQueue,
        handlers: dict[str, Handler],
        worker_id: str | None = None,
        poll_interval_s: float = 1.0,
        stale_lock_s: float = 600,
    ) -> None:
        self._factory = factory
        self._queue = queue
        self._handlers = handlers
        self.worker_id = worker_id or default_worker_id()
        self._poll = poll_interval_s
        self._stale = stale_lock_s
        self._last_reclaim = 0.0

    def run_once(self) -> bool:
        """Process one job. Returns False when nothing was due."""
        job = self._queue.claim(self.worker_id)
        if job is None:
            return False
        self._process(job)
        return True

    def drain(self, max_jobs: int = 1000) -> int:
        count = 0
        while count < max_jobs and self.run_once():
            count += 1
        return count

    def reclaim(self) -> int:
        self._last_reclaim = time.monotonic()
        count = self._queue.reclaim_stale(self._stale)
        if count:
            log.warning("reclaimed stale jobs", extra={"count": count})
        return count

    def run(self, stop: threading.Event) -> None:
        log.info("worker started", extra={"worker_id": self.worker_id})
        self.reclaim()
        while not stop.is_set():
            if time.monotonic() - self._last_reclaim > RECLAIM_EVERY_S:
                self.reclaim()
            try:
                busy = self.run_once()
            except Exception:
                log.exception("worker loop error")
                busy = False
            if not busy:
                stop.wait(self._poll)
        log.info("worker stopped", extra={"worker_id": self.worker_id})

    def _process(self, job: Job) -> None:
        with log_context(incident_id=job.incident_id, job_type=job.type):
            try:
                with session_scope(self._factory) as s:
                    incident = s.get(Incident, job.incident_id)
                    if incident is not None and State(incident.state) not in _NO_AUTOMATION:
                        handler = self._handlers.get(job.type)
                        if handler is None:
                            raise UnknownJobType(job.type)
                        with log_context(state=incident.state):
                            handler(s, incident, self._queue)
                    self._queue.complete(s, job)
                log.info("job done")
            except Exception as exc:
                log.exception("job failed")
                with session_scope(self._factory) as s:
                    retry = self._queue.fail(s, job, f"{type(exc).__name__}: {exc}")
                log.warning("job will retry" if retry else "job gave up")


def run_workers(workers: list[Worker], stop: threading.Event) -> None:
    threads = [threading.Thread(target=w.run, args=(stop,), name=w.worker_id) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def main() -> None:
    from genie_copilot.wiring import build_runtime, install_signal_handlers

    runtime = build_runtime()
    stop = install_signal_handlers()
    count = runtime.settings.worker_concurrency
    run_workers([runtime.worker(default_worker_id(i)) for i in range(count)], stop)


if __name__ == "__main__":
    main()
