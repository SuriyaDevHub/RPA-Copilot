"""Incident read endpoints and the live event stream (SPEC §9)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from genie_copilot.api.deps import PrincipalDep, RuntimeDep, SessionDep, readable_incident
from genie_copilot.api.schemas import (
    EventOut,
    IncidentDetail,
    IncidentSummary,
    LogLineOut,
    ParsedErrorOut,
)
from genie_copilot.db.models import (
    DiagnosisRow,
    Incident,
    IncidentEvent,
    ParsedErrorRow,
    SupportDraftRow,
)
from genie_copilot.db.repositories import EventRepo
from genie_copilot.db.session import session_scope
from genie_copilot.orchestrator.states import TERMINAL, State

router = APIRouter(prefix="/v1/incidents", tags=["incidents"])

# The stream ends once automation can no longer move the incident.
_STREAM_ENDS = TERMINAL | {State.FALLBACK_MANUAL}


@router.get("", response_model=list[IncidentSummary])
def list_incidents(
    session: SessionDep,
    principal: PrincipalDep,
    mine: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[Incident]:
    stmt = select(Incident).order_by(Incident.created_at.desc()).limit(limit)
    if mine:
        stmt = stmt.where(Incident.user_id == principal.user_id)
    elif not principal.is_support:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "support role required")
    return list(session.scalars(stmt).all())


@router.get("/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: str, session: SessionDep, principal: PrincipalDep) -> IncidentDetail:
    incident = readable_incident(session, principal, incident_id)
    parsed = session.get(ParsedErrorRow, incident_id)
    diagnosis = session.get(DiagnosisRow, incident_id)
    draft = session.get(SupportDraftRow, incident_id)
    events = EventRepo(session).for_incident(incident_id)
    return IncidentDetail(
        **IncidentSummary.model_validate(incident, from_attributes=True).model_dump(),
        user_id=incident.user_id,
        vdi_host=incident.vdi_host,
        run_id=incident.run_id,
        step_name=incident.step_name,
        error_signature=incident.error_signature,
        parsed_error=_parsed(parsed) if parsed else None,
        diagnosis=_columns(diagnosis) if diagnosis else None,
        draft=_columns(draft) if draft else None,
        events=[EventOut.model_validate(e, from_attributes=True) for e in events],
    )


@router.get("/{incident_id}/events")
async def stream_events(
    incident_id: str,
    principal: PrincipalDep,
    runtime: RuntimeDep,
    last_event_id: Annotated[int | None, Header()] = None,
) -> StreamingResponse:
    # Short session for the access check: the stream itself can last minutes.
    def check() -> None:
        with session_scope(runtime.factory) as s:
            readable_incident(s, principal, incident_id)

    await run_in_threadpool(check)
    settings = runtime.settings
    poll, timeout = settings.sse_poll_interval_s, settings.sse_timeout_s

    def fetch(after: int) -> tuple[list[IncidentEvent], str | None]:
        with session_scope(runtime.factory) as s:
            incident = s.get(Incident, incident_id)
            return list(EventRepo(s).for_incident(incident_id, after)), (
                incident.state if incident else None
            )

    async def stream() -> AsyncIterator[str]:
        after = last_event_id or 0
        deadline = time.monotonic() + timeout
        yield "retry: 3000\n\n"
        while True:
            events, state = await run_in_threadpool(fetch, after)
            for event in events:
                after = event.id
                payload = EventOut.model_validate(event, from_attributes=True).model_dump_json()
                yield f"id: {event.id}\nevent: state\ndata: {payload}\n\n"
            if state is None or State(state) in _STREAM_ENDS or time.monotonic() > deadline:
                yield f"event: end\ndata: {json.dumps({'state': state})}\n\n"
                return
            await asyncio.sleep(poll)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _parsed(row: ParsedErrorRow) -> ParsedErrorOut:
    lines = []
    for raw in row.log_window_masked.splitlines():
        label, _, text = raw.partition(" ")
        if label.startswith("L") and label[1:].isdigit():
            lines.append(LogLineOut(id=int(label[1:]), text=text))
    return ParsedErrorOut(
        exception_type=row.exception_type,
        message=row.message_masked,
        chain=list(row.frames or []),
        window=lines,
        parser=row.parser,
    )


def _columns(row: object) -> dict[str, object]:
    table = row.__table__  # type: ignore[attr-defined]
    return {c.name: getattr(row, c.name) for c in table.columns if c.name != "incident_id"}
