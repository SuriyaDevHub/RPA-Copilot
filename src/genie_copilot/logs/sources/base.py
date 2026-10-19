"""Where logs come from. PoC: the legacy S3 adapter; production: the structured adapter."""

from __future__ import annotations

from typing import Protocol

from genie_copilot.logs.models import RawLog


class LogSource(Protocol):
    name: str

    def read(self, key: str) -> RawLog:
        """Load one run's log. Fields the format does not carry are left None."""
        ...
