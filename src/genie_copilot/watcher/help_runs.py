"""Stage 2 "Get help": a user's recent failed runs, and opening an incident for one."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from genie_copilot.db.models import Incident, IncidentSource, JobType
from genie_copilot.db.queue import JobQueue
from genie_copilot.db.repositories import IncidentRepo
from genie_copilot.db.types import utcnow
from genie_copilot.integrations.s3 import S3Store
from genie_copilot.logs.models import RawLog
from genie_copilot.logs.sources.s3_legacy import FailureRule, S3LegacySource
from genie_copilot.orchestrator.machine import open_incident


class RunNotFound(Exception):
    pass


class NotYourRun(Exception):
    pass


@dataclass(frozen=True)
class FailedRun:
    s3_key: str
    bot_name: str
    last_modified: datetime
    incident_id: str | None

    @property
    def s3_key_b64(self) -> str:
        return encode_key(self.s3_key)


def encode_key(key: str) -> str:
    return base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")


def decode_key(token: str) -> str:
    try:
        return base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise RunNotFound("malformed run id") from exc


def same_user(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a.casefold() == b.casefold()


class HelpService:
    def __init__(
        self,
        store: S3Store,
        source: S3LegacySource,
        bots: list[str],
        is_failed: FailureRule,
        max_runs: int = 200,
    ) -> None:
        self._store = store
        self._source = source
        self._bots = bots
        self._is_failed = is_failed
        self._max_runs = max_runs
        self._cache: dict[tuple[str, datetime], RawLog] = {}

    def recent_failed_runs(
        self, session: Session, user_id: str, days: int, any_user: bool = False
    ) -> list[FailedRun]:
        since = utcnow() - timedelta(days=days)
        objects = [
            o
            for bot in self._bots
            for o in self._store.list_since(self._source.bot_prefix(bot), since)
        ]
        objects = sorted(objects, key=lambda o: o.last_modified, reverse=True)[: self._max_runs]
        repo = IncidentRepo(session)
        runs: list[FailedRun] = []
        for obj in objects:
            raw = self._read(obj.key, obj.last_modified)
            if not (any_user or same_user(raw.user_id, user_id)) or not self._is_failed(raw):
                continue
            incident = repo.get_by_dedup_key(obj.key)
            runs.append(
                FailedRun(
                    obj.key, raw.bot_name, obj.last_modified, incident.id if incident else None
                )
            )
        return runs

    def open_incident(
        self, session: Session, queue: JobQueue, key: str, user_id: str, any_user: bool = False
    ) -> tuple[Incident, bool]:
        bot = self._source.bot_for_key(key)
        if bot is None or bot not in self._bots:
            raise RunNotFound(key)
        try:
            raw = self._source.read(key)
        except Exception as exc:
            raise RunNotFound(key) from exc
        if not (any_user or same_user(raw.user_id, user_id)):
            raise NotYourRun(key)
        incident, created = open_incident(
            session,
            actor=user_id,
            source=IncidentSource.HELP_PAGE,
            dedup_key=key,
            bot_name=bot,
            user_id=raw.user_id or user_id,
            vdi_host=raw.vdi_host,
            run_id=raw.run_id,
            s3_log_key=key,
        )
        if created:
            queue.enqueue(session, incident.id, JobType.PARSE)
        return incident, created

    def _read(self, key: str, modified: datetime) -> RawLog:
        cache_key = (key, modified)
        if cache_key not in self._cache:
            if len(self._cache) > 4 * self._max_runs:
                self._cache.clear()
            self._cache[cache_key] = self._source.read(key)
        return self._cache[cache_key]
