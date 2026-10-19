"""Liveness and readiness."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from genie_copilot.api.deps import SessionDep

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(session: SessionDep) -> dict[str, str]:
    # Index readiness joins this check in M5.
    session.execute(select(1))
    return {"status": "ready", "database": "ok"}
