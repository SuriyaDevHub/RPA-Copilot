"""Stage 2 "Get help": pick one of my recent failed runs and open an incident for it."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from genie_copilot.api.deps import PrincipalDep, RuntimeDep, SessionDep
from genie_copilot.api.schemas import FailedRunOut, OpenedIncident
from genie_copilot.watcher.help_runs import NotYourRun, RunNotFound, decode_key

router = APIRouter(prefix="/v1/help", tags=["help"])


@router.get("/runs", response_model=list[FailedRunOut])
def my_failed_runs(
    session: SessionDep,
    principal: PrincipalDep,
    runtime: RuntimeDep,
    days: Annotated[int, Query(ge=1, le=14)] = 3,
) -> list[FailedRunOut]:
    runs = runtime.help_service().recent_failed_runs(session, principal.user_id, days)
    return [
        FailedRunOut(
            s3_key_b64=r.s3_key_b64,
            bot_name=r.bot_name,
            last_modified=r.last_modified,
            incident_id=r.incident_id,
        )
        for r in runs
    ]


@router.post("/runs/{s3_key_b64}/incident", response_model=OpenedIncident)
def open_incident_for_run(
    s3_key_b64: str,
    response: Response,
    session: SessionDep,
    principal: PrincipalDep,
    runtime: RuntimeDep,
) -> OpenedIncident:
    try:
        key = decode_key(s3_key_b64)
        incident, created = runtime.help_service().open_incident(
            session, runtime.queue, key, principal.user_id, any_user=principal.is_support
        )
    except RunNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found") from exc
    except NotYourRun as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your run") from exc
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return OpenedIncident(incident_id=incident.id, created=created)
