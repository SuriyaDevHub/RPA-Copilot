"""Shared builders for pipeline and API tests (moto S3 + a real database)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from genie_copilot.config import Settings
from genie_copilot.integrations.s3 import S3Store
from genie_copilot.logs.models import RawLog
from genie_copilot.logs.sources.s3_legacy import S3LegacySource
from genie_copilot.wiring import Runtime

BUCKET = "genie-logs"
PREFIX = "logs/"
DOTNET = Path(__file__).resolve().parent / "fixtures" / "dotnet"


class UserTaggingSource(S3LegacySource):
    """The placeholder adapter cannot recover users yet; tests tag them by key."""

    def __init__(self, store: S3Store, prefix: str, users: dict[str, str]) -> None:
        super().__init__(store, prefix)
        self.users = users

    def read(self, key: str) -> RawLog:
        raw = super().read(key)
        return raw.model_copy(update={"user_id": self.users.get(key)})


def make_runtime(
    engine: Engine, s3: Any, users: dict[str, str] | None = None, **overrides: Any
) -> Runtime:
    values: dict[str, Any] = {
        "s3_bucket": BUCKET,
        "s3_log_prefix": PREFIX,
        "watcher_bots": ["bot-a"],
        "in_house_namespaces": ["Genie."],
        "mask_host_patterns": [r"\bVDI-[A-Z]{3}-\d{4}\b"],
        "sse_poll_interval_s": 0.02,
        "sse_timeout_s": 5,
    }
    values.update(overrides)
    settings = Settings(_env_file=None, **values)  # type: ignore[call-arg]
    store = S3Store(BUCKET, s3)
    runtime = Runtime(settings=settings, engine=engine, store_override=store)
    runtime.source = UserTaggingSource(store, PREFIX, users or {})  # type: ignore[misc]
    return runtime


def upload(s3: Any, fixture: str, key: str | None = None) -> str:
    key = key or f"{PREFIX}bot-a/{fixture}"
    s3.put_object(Bucket=BUCKET, Key=key, Body=(DOTNET / fixture).read_bytes())
    return key
