"""Authentication. `dev` reads headers (never allowed in prod, see config); `openam`
arrives in M9 behind the same interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from fastapi import HTTPException, Request, status

from genie_copilot.config import Settings

ROLES = frozenset({"user", "support", "l2"})


@dataclass(frozen=True)
class Principal:
    user_id: str
    roles: frozenset[str] = field(default_factory=lambda: frozenset({"user"}))

    @property
    def is_support(self) -> bool:
        return "support" in self.roles


class Authenticator(Protocol):
    def authenticate(self, request: Request) -> Principal: ...


class DevAuth:
    """`X-Dev-User: jdoe` and optional `X-Dev-Roles: support,l2`."""

    def authenticate(self, request: Request) -> Principal:
        user = request.headers.get("X-Dev-User", "").strip()
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Dev-User header required")
        extra = {r.strip() for r in request.headers.get("X-Dev-Roles", "").split(",") if r.strip()}
        unknown = extra - ROLES
        if unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown roles {sorted(unknown)}")
        return Principal(user_id=user, roles=frozenset({"user"} | extra))


class OpenAMAuth:
    def authenticate(self, request: Request) -> Principal:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "openam auth arrives in M9")


def make_authenticator(settings: Settings) -> Authenticator:
    return DevAuth() if settings.auth_mode == "dev" else OpenAMAuth()
