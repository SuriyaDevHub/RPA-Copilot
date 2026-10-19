"""Adapter for today's Genie logs in S3. PLACEHOLDER until real samples arrive.

Assumed key layout: `<GC_S3_LOG_PREFIX><bot_name>/<anything>`. User, host and run id are
not recovered yet (OPEN_QUESTIONS #5-#7); M3 part 2 replaces this with the real format.
"""

from __future__ import annotations

from collections.abc import Callable

from genie_copilot.integrations.s3 import S3Store
from genie_copilot.logs.models import RawLog
from genie_copilot.logs.parser import find_first_error

ADAPTER = "s3_legacy-placeholder"

# Decides whether a run failed. Placeholder: any ERROR/FATAL line or exception header.
FailureRule = Callable[[RawLog], bool]


def has_error_line(raw: RawLog) -> bool:
    return find_first_error(raw.lines) is not None


class S3LegacySource:
    name = ADAPTER

    def __init__(self, store: S3Store, prefix: str) -> None:
        self._store = store
        self._prefix = prefix

    def bot_for_key(self, key: str) -> str | None:
        if not key.startswith(self._prefix):
            return None
        bot, sep, _ = key[len(self._prefix) :].lstrip("/").partition("/")
        return bot if sep and bot else None

    def bot_prefix(self, bot: str) -> str:
        return f"{self._prefix.rstrip('/')}/{bot}/" if self._prefix else f"{bot}/"

    def read(self, key: str) -> RawLog:
        text = self._store.get_text(key)
        return RawLog(
            source_key=key,
            bot_name=self.bot_for_key(key) or "unknown",
            lines=text.splitlines(),
            adapter=ADAPTER,
        )
