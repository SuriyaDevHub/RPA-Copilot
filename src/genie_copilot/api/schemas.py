"""API response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class IncidentSummary(BaseModel):
    id: str
    source: str
    bot_name: str
    state: str
    category: str | None
    confidence: float | None
    jira_key: str | None
    created_at: datetime
    updated_at: datetime


class LogLineOut(BaseModel):
    id: int
    text: str


class ParsedErrorOut(BaseModel):
    exception_type: str
    message: str
    chain: list[dict[str, Any]]
    window: list[LogLineOut]
    parser: str


class EventOut(BaseModel):
    id: int
    from_state: str | None
    to_state: str
    reason: str
    actor: str
    at: datetime


class IncidentDetail(IncidentSummary):
    user_id: str | None
    vdi_host: str | None
    run_id: str | None
    step_name: str | None
    error_signature: str | None
    parsed_error: ParsedErrorOut | None
    diagnosis: dict[str, Any] | None
    draft: dict[str, Any] | None
    events: list[EventOut]


class FailedRunOut(BaseModel):
    s3_key_b64: str
    bot_name: str
    last_modified: datetime
    incident_id: str | None


class OpenedIncident(BaseModel):
    incident_id: str
    created: bool
