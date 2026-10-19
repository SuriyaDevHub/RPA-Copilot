"""ORM models (SPEC §3). Portable across SQLite and SQL Server.

Identifiers and codes use String (VARCHAR); human or LLM text uses Unicode/UnicodeText
(NVARCHAR). Status-like columns are plain strings validated by the enums below.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Unicode,
    UnicodeText,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from genie_copilot.db.types import JSONText, StrUUID, UTCDateTime, new_id, utcnow
from genie_copilot.orchestrator.states import State

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class IncidentSource(StrEnum):
    S3_WATCHER = "s3_watcher"
    HELP_PAGE = "help_page"
    CLIENT = "client"


class JobType(StrEnum):
    PARSE = "parse"
    DIAGNOSE = "diagnose"
    ROUTE = "route"
    DRAFT = "draft"
    INTEGRATE = "integrate"
    LEARN = "learn"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class OutboxKind(StrEnum):
    JIRA_CREATE = "jira_create"
    EMAIL = "email"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class KBSource(StrEnum):
    JIRA = "jira"
    EMAIL = "email"
    SOP = "sop"
    KNOWN_ERROR = "known_error"
    RELEASE_NOTE = "release_note"
    LEARNED = "learned"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _incident_fk() -> ForeignKey:
    return ForeignKey("incident.id", ondelete="CASCADE")


class Incident(Base):
    __tablename__ = "incident"
    __table_args__ = (
        Index(None, "user_id", "created_at"),
        Index(None, "error_signature", "created_at"),
    )

    id: Mapped[str] = mapped_column(StrUUID, primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(16))
    dedup_key: Mapped[str] = mapped_column(String(1024), unique=True)
    bot_name: Mapped[str] = mapped_column(String(128))
    bot_version: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(String(128))
    user_email: Mapped[str | None] = mapped_column(String(256))
    vdi_host: Mapped[str | None] = mapped_column(String(128))
    run_id: Mapped[str | None] = mapped_column(String(128))
    step_name: Mapped[str | None] = mapped_column(Unicode(256))
    s3_log_key: Mapped[str | None] = mapped_column(String(1024))
    evidence_key: Mapped[str | None] = mapped_column(String(1024))
    error_signature: Mapped[str | None] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(32), default=State.RECEIVED, index=True)
    category: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    jira_key: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class IncidentEvent(Base):
    __tablename__ = "incident_event"
    __table_args__ = (Index(None, "incident_id", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(StrUUID, _incident_fk())
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Unicode(512))
    actor: Mapped[str] = mapped_column(String(128), default="system")
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ParsedErrorRow(Base):
    __tablename__ = "parsed_error"

    incident_id: Mapped[str] = mapped_column(StrUUID, _incident_fk(), primary_key=True)
    exception_type: Mapped[str] = mapped_column(String(256))
    message_masked: Mapped[str] = mapped_column(UnicodeText)
    frames: Mapped[Any] = mapped_column(JSONText)
    log_window_masked: Mapped[str] = mapped_column(UnicodeText)
    line_ids: Mapped[Any] = mapped_column(JSONText)
    parser: Mapped[str] = mapped_column(String(64))


class DiagnosisRow(Base):
    __tablename__ = "diagnosis"

    incident_id: Mapped[str] = mapped_column(StrUUID, _incident_fk(), primary_key=True)
    category: Mapped[str] = mapped_column(String(32))
    root_cause: Mapped[str] = mapped_column(Unicode(1000))
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[Any] = mapped_column(JSONText)
    user_fix_steps: Mapped[Any] = mapped_column(JSONText)
    recommended_action: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))


class SupportDraftRow(Base):
    __tablename__ = "support_draft"

    incident_id: Mapped[str] = mapped_column(StrUUID, _incident_fk(), primary_key=True)
    fields_ai: Mapped[Any] = mapped_column(JSONText)
    fields_final: Mapped[Any | None] = mapped_column(JSONText)
    duplicate_of: Mapped[str | None] = mapped_column(String(32))
    edit_distance: Mapped[float | None] = mapped_column(Float)
    submitted_by: Mapped[str | None] = mapped_column(String(128))
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class LLMCall(Base):
    __tablename__ = "llm_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str | None] = mapped_column(StrUUID, _incident_fk(), index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    prompt_name: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(32))
    input_hash: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Unicode(2000))
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        UniqueConstraint("incident_id", "type"),
        Index(None, "status", "run_after"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(StrUUID, _incident_fk())
    type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime | None] = mapped_column(UTCDateTime)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    last_error: Mapped[str | None] = mapped_column(Unicode(2000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (Index(None, "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(StrUUID, _incident_fk())
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[Any] = mapped_column(JSONText)
    status: Mapped[str] = mapped_column(String(16), default=OutboxStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    external_id: Mapped[str | None] = mapped_column(String(128))
    last_error: Mapped[str | None] = mapped_column(Unicode(2000))


class KBItem(Base):
    __tablename__ = "kb_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16))
    source_ref: Mapped[str | None] = mapped_column(String(256))
    bot_name: Mapped[str | None] = mapped_column(String(128), index=True)
    error_signature: Mapped[str | None] = mapped_column(String(16), index=True)
    category: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Unicode(500))
    text_masked: Mapped[str] = mapped_column(UnicodeText)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    vector_id: Mapped[int | None] = mapped_column(Integer)
    embed_model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class KnownError(Base):
    __tablename__ = "known_error"

    error_signature: Mapped[str] = mapped_column(String(16), primary_key=True)
    bot_name: Mapped[str | None] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(32))
    root_cause: Mapped[str] = mapped_column(Unicode(1000))
    user_fix_steps: Mapped[Any] = mapped_column(JSONText)
    recommended_action: Mapped[str] = mapped_column(String(32))
    kb_item_id: Mapped[int | None] = mapped_column(ForeignKey("kb_item.id"))
    approved_by: Mapped[str | None] = mapped_column(String(128))


class WatcherState(Base):
    __tablename__ = "watcher_state"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    watermark: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(StrUUID, _incident_fk(), index=True)
    user_id: Mapped[str] = mapped_column(String(128))
    helpful: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Unicode(1000))
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class IndexVersion(Base):
    __tablename__ = "index_version"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    built_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
