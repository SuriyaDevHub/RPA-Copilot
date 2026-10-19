"""S3 watcher (SPEC §2, M4): poll each pilot bot's log prefix, open an incident per failed run.

dedup_key = S3 key, so re-listing the same object never creates a second incident.
Watermarks are kept per bot in `watcher_state`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.db.models import IncidentSource, JobType, WatcherState
from genie_copilot.db.queue import JobQueue
from genie_copilot.db.repositories import IncidentRepo
from genie_copilot.db.session import session_scope
from genie_copilot.db.types import utcnow
from genie_copilot.integrations.notify import Notifier, review_url
from genie_copilot.integrations.s3 import S3Store
from genie_copilot.logs.sources.s3_legacy import FailureRule, S3LegacySource
from genie_copilot.observability.logging import log_context
from genie_copilot.orchestrator.machine import open_incident

log = logging.getLogger(__name__)


@dataclass
class PollResult:
    seen: int = 0
    created: int = 0
    skipped_ok: int = 0


class S3Watcher:
    def __init__(
        self,
        factory: sessionmaker[Session],
        queue: JobQueue,
        store: S3Store,
        source: S3LegacySource,
        bots: list[str],
        is_failed: FailureRule,
        notifier: Notifier,
        ui_base_url: str,
    ) -> None:
        self._factory = factory
        self._queue = queue
        self._store = store
        self._source = source
        self._bots = bots
        self._is_failed = is_failed
        self._notifier = notifier
        self._ui = ui_base_url

    def poll_once(self) -> PollResult:
        result = PollResult()
        for bot in self._bots:
            self._poll_bot(bot, result)
        return result

    def _poll_bot(self, bot: str, result: PollResult) -> None:
        name = f"s3:{bot}"
        with session_scope(self._factory) as s:
            state = s.get(WatcherState, name)
            watermark = state.watermark if state else None
        objects = self._store.list_since(self._source.bot_prefix(bot), watermark)
        for obj in objects:
            result.seen += 1
            with session_scope(self._factory) as s:
                if IncidentRepo(s).get_by_dedup_key(obj.key) is not None:
                    continue
            raw = self._source.read(obj.key)
            if not self._is_failed(raw):
                result.skipped_ok += 1
                continue
            with session_scope(self._factory) as s:
                incident, created = open_incident(
                    s,
                    source=IncidentSource.S3_WATCHER,
                    dedup_key=obj.key,
                    bot_name=bot,
                    user_id=raw.user_id,
                    vdi_host=raw.vdi_host,
                    run_id=raw.run_id,
                    s3_log_key=obj.key,
                )
                if created:
                    self._queue.enqueue(s, incident.id, JobType.PARSE)
            if created:
                result.created += 1
                with log_context(incident_id=incident.id, run_id=incident.run_id):
                    log.info("incident opened from S3", extra={"bot": bot})
                    self._notifier.incident_opened(incident, review_url(self._ui, incident.id))
        if objects:
            with session_scope(self._factory) as s:
                state = s.get(WatcherState, name) or WatcherState(name=name)
                state.watermark = max(o.last_modified for o in objects)
                state.updated_at = utcnow()
                s.add(state)

    def run(self, interval_s: float, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                result = self.poll_once()
                log.info("watcher poll", extra={"seen": result.seen, "created": result.created})
            except Exception:
                log.exception("watcher poll failed")
            stop.wait(interval_s)


def main() -> None:
    from genie_copilot.wiring import build_runtime, install_signal_handlers

    runtime = build_runtime()
    stop = install_signal_handlers()
    runtime.watcher().run(runtime.settings.watcher_interval_s, stop)


if __name__ == "__main__":
    main()
