"""Thin repositories over a Session. They flush but never commit; callers own the transaction."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from genie_copilot.db.models import (
    Incident,
    IncidentEvent,
    Job,
    KBItem,
    LLMCall,
    Outbox,
    OutboxStatus,
)
from genie_copilot.db.types import utcnow
from genie_copilot.orchestrator.states import State


class IncidentRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(self, **fields: Any) -> Incident:
        incident = Incident(**fields)
        self.s.add(incident)
        self.s.flush()
        return incident

    def get(self, incident_id: str) -> Incident | None:
        return self.s.get(Incident, incident_id)

    def get_by_dedup_key(self, dedup_key: str) -> Incident | None:
        return self.s.scalars(select(Incident).where(Incident.dedup_key == dedup_key)).first()

    def list_for_user(self, user_id: str, limit: int = 20) -> Sequence[Incident]:
        return self.s.scalars(
            select(Incident)
            .where(Incident.user_id == user_id)
            .order_by(Incident.created_at.desc())
            .limit(limit)
        ).all()

    def count_escalations(self, error_signature: str, since: datetime) -> int:
        """Incidents with this signature that reached DRAFTED since `since` (router rule 1)."""
        stmt = (
            select(func.count(func.distinct(IncidentEvent.incident_id)))
            .join(Incident, Incident.id == IncidentEvent.incident_id)
            .where(
                Incident.error_signature == error_signature,
                IncidentEvent.to_state == State.DRAFTED.value,
                IncidentEvent.at >= since,
            )
        )
        return int(self.s.scalar(stmt) or 0)


class EventRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def for_incident(self, incident_id: str, after_id: int = 0) -> Sequence[IncidentEvent]:
        return self.s.scalars(
            select(IncidentEvent)
            .where(IncidentEvent.incident_id == incident_id, IncidentEvent.id > after_id)
            .order_by(IncidentEvent.id)
        ).all()


class JobRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def for_incident(self, incident_id: str) -> Sequence[Job]:
        return self.s.scalars(
            select(Job).where(Job.incident_id == incident_id).order_by(Job.id)
        ).all()


class OutboxRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def add(self, incident_id: str, kind: str, payload: Any) -> Outbox:
        row = Outbox(incident_id=incident_id, kind=kind, payload=payload)
        self.s.add(row)
        self.s.flush()
        return row

    def due(self, limit: int = 20) -> Sequence[Outbox]:
        now = utcnow()
        return self.s.scalars(
            select(Outbox)
            .where(
                Outbox.status == OutboxStatus.PENDING,
                (Outbox.next_attempt_at.is_(None)) | (Outbox.next_attempt_at <= now),
            )
            .order_by(Outbox.id)
            .limit(limit)
        ).all()

    def for_incident(self, incident_id: str) -> Sequence[Outbox]:
        return self.s.scalars(
            select(Outbox).where(Outbox.incident_id == incident_id).order_by(Outbox.id)
        ).all()


class KBRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def get_by_hash(self, content_hash: str) -> KBItem | None:
        return self.s.scalars(select(KBItem).where(KBItem.content_hash == content_hash)).first()

    def add(self, item: KBItem) -> KBItem:
        self.s.add(item)
        self.s.flush()
        return item

    def verified(self) -> Sequence[KBItem]:
        return self.s.scalars(select(KBItem).where(KBItem.verified.is_(True))).all()


class LLMCallRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def add(self, call: LLMCall) -> LLMCall:
        self.s.add(call)
        self.s.flush()
        return call
