"""FastAPI application (SPEC §9). `make run-api` serves `genie_copilot.api.main:app`."""

from __future__ import annotations

from fastapi import FastAPI

from genie_copilot.api.auth import Authenticator, make_authenticator
from genie_copilot.api.routes import health, help, incidents
from genie_copilot.wiring import Runtime, build_runtime


def create_app(runtime: Runtime | None = None, auth: Authenticator | None = None) -> FastAPI:
    runtime = runtime or build_runtime()
    app = FastAPI(title="Genie Copilot", version="0.1.0")
    app.state.runtime = runtime
    app.state.auth = auth or make_authenticator(runtime.settings)
    app.include_router(health.router)
    app.include_router(incidents.router)
    app.include_router(help.router)
    return app


def __getattr__(name: str) -> FastAPI:
    # Built lazily so importing this module (e.g. in tests) does not read settings.
    if name == "app":
        return create_app()
    raise AttributeError(name)
