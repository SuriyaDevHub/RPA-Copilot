"""FastAPI dependencies: database session, current principal, authorization checks."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from genie_copilot.api.auth import Principal
from genie_copilot.db.models import Incident
from genie_copilot.db.session import session_scope
from genie_copilot.watcher.help_runs import same_user
from genie_copilot.wiring import Runtime


def get_runtime(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


def get_session(runtime: Annotated[Runtime, Depends(get_runtime)]) -> Iterator[Session]:
    with session_scope(runtime.factory) as session:
        yield session


def get_principal(request: Request) -> Principal:
    principal: Principal = request.app.state.auth.authenticate(request)
    return principal


SessionDep = Annotated[Session, Depends(get_session)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]
RuntimeDep = Annotated[Runtime, Depends(get_runtime)]


def can_read(principal: Principal, incident: Incident) -> bool:
    return principal.is_support or same_user(incident.user_id, principal.user_id)


def readable_incident(session: Session, principal: Principal, incident_id: str) -> Incident:
    try:
        uuid.UUID(incident_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found") from None
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
    if not can_read(principal, incident):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your incident")
    return incident
