"""Structured JSON logging (SPEC §12).

Context such as `incident_id` and `run_id` is held in contextvars and added to every
line emitted inside `log_context(...)`, including from nested calls and asyncio tasks.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

CONTEXT_FIELDS = ("incident_id", "run_id", "job_type", "state")

_context: dict[str, ContextVar[str | None]] = {
    name: ContextVar(name, default=None) for name in CONTEXT_FIELDS
}

# Attributes every LogRecord has; anything else passed via `extra=` is emitted.
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}


@contextmanager
def log_context(**fields: str | None) -> Iterator[None]:
    unknown = set(fields) - set(CONTEXT_FIELDS)
    if unknown:
        raise ValueError(f"unknown log context fields: {sorted(unknown)}")
    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = [
        (_context[name], _context[name].set(value)) for name, value in fields.items()
    ]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def current_context() -> dict[str, str]:
    return {name: value for name, var in _context.items() if (value := var.get()) is not None}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **current_context(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str | int = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
