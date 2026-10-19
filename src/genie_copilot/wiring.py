"""Composition root: builds the long-lived objects each process needs from settings."""

from __future__ import annotations

import signal
import threading
from dataclasses import dataclass, field
from functools import cached_property

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.agents.log_parser import LogParserAgent
from genie_copilot.config import Settings, get_settings
from genie_copilot.db.queue import JobQueue, make_queue
from genie_copilot.db.session import make_engine, make_session_factory
from genie_copilot.integrations.notify import LoggingNotifier, Notifier
from genie_copilot.integrations.s3 import S3Store
from genie_copilot.logs.sources.s3_legacy import FailureRule, S3LegacySource, has_error_line
from genie_copilot.observability.logging import configure_logging
from genie_copilot.orchestrator.handlers import default_handlers
from genie_copilot.orchestrator.worker import Worker
from genie_copilot.watcher.help_runs import HelpService
from genie_copilot.watcher.s3_watcher import S3Watcher


@dataclass
class Runtime:
    settings: Settings
    engine: Engine
    store_override: S3Store | None = None
    notifier: Notifier = field(default_factory=LoggingNotifier)
    is_failed: FailureRule = has_error_line

    @cached_property
    def factory(self) -> sessionmaker[Session]:
        return make_session_factory(self.engine)

    @cached_property
    def queue(self) -> JobQueue:
        return make_queue(self.engine)

    @cached_property
    def store(self) -> S3Store:
        if self.store_override is not None:
            return self.store_override
        if not self.settings.s3_bucket:
            raise RuntimeError("GC_S3_BUCKET is not set")
        return S3Store(self.settings.s3_bucket)

    @cached_property
    def source(self) -> S3LegacySource:
        return S3LegacySource(self.store, self.settings.s3_log_prefix)

    def worker(self, worker_id: str | None = None) -> Worker:
        parser = LogParserAgent(self.source, self.settings)
        return Worker(
            self.factory,
            self.queue,
            default_handlers(parser),
            worker_id=worker_id,
            poll_interval_s=self.settings.worker_poll_interval_s,
            stale_lock_s=self.settings.worker_stale_lock_s,
        )

    def watcher(self) -> S3Watcher:
        return S3Watcher(
            self.factory,
            self.queue,
            self.store,
            self.source,
            self.settings.watcher_bots,
            self.is_failed,
            self.notifier,
            self.settings.ui_base_url,
        )

    def help_service(self) -> HelpService:
        return HelpService(
            self.store,
            self.source,
            self.settings.watcher_bots,
            self.is_failed,
            self.settings.help_max_runs,
        )


def build_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or get_settings()
    configure_logging()
    return Runtime(settings=settings, engine=make_engine(settings.database_url))


def install_signal_handlers() -> threading.Event:
    """SIGINT/SIGTERM finish the current job, then stop."""
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    return stop
