"""Portable column types (SPEC §3).

These, `db/session.py` and `db/queue.py` are the only modules that may know about dialects.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, UnicodeText
from sqlalchemy.dialects import mssql
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator, TypeEngine


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC in Python, naive UTC in the database (DATETIME2 on SQL Server)."""

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "mssql":
            return dialect.type_descriptor(mssql.DATETIME2(precision=6))  # type: ignore[no-untyped-call]
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; use timezone-aware UTC")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class JSONText(TypeDecorator[Any]):
    """JSON serialised to UnicodeText (NVARCHAR(MAX) on SQL Server).

    Changes are detected only on reassignment, not on in-place mutation.
    """

    impl = UnicodeText
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value: str | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        return json.loads(value)


class StrUUID(TypeDecorator[str]):
    """UUID stored as a lowercase 36-character string."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: str | uuid.UUID | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return str(uuid.UUID(str(value)))

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return value


def new_id() -> str:
    return str(uuid.uuid4())
