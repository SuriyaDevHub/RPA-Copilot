"""Service-account token auth for the GenAI gateway (SPEC §6).

The token request is standard OAuth2 client credentials (form POST, `access_token` and
`expires_in` in the JSON reply). The exact format is OPEN_QUESTIONS #1.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Generator

import httpx
from pydantic import SecretStr

from genie_copilot.llm.base import LLMError

REFRESH_MARGIN_S = 60.0
DEFAULT_LIFETIME_S = 300.0


class TokenError(LLMError):
    """The token endpoint did not return a usable token."""


class ServiceAccountAuth(httpx.Auth):
    def __init__(
        self,
        token_url: str,
        client_id: SecretStr,
        client_secret: SecretStr,
        header: str = "Authorization",
        scheme: str = "Bearer",
        scope: str = "",
        http: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._header = header
        self._scheme = scheme
        self._scope = scope
        self._http = http or httpx.Client(timeout=10)
        self._clock = clock
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0

    def get_token(self, stale: str | None = None) -> str:
        """Return a valid token. If `stale` is the current token, fetch a new one."""
        with self._lock:
            expiring = self._expires_at - self._clock() < REFRESH_MARGIN_S
            if self._token is None or expiring or (stale is not None and stale == self._token):
                self._token, self._expires_at = self._fetch()
            return self._token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        token = self.get_token()
        self._apply(request, token)
        response = yield request
        if response.status_code == 401:
            # Token revoked or rotated early: refresh once and retry.
            self._apply(request, self.get_token(stale=token))
            yield request

    def _apply(self, request: httpx.Request, token: str) -> None:
        request.headers[self._header] = f"{self._scheme} {token}" if self._scheme else token

    def _fetch(self) -> tuple[str, float]:
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id.get_secret_value(),
            "client_secret": self._client_secret.get_secret_value(),
        }
        if self._scope:
            data["scope"] = self._scope
        try:
            response = self._http.post(self._token_url, data=data)
        except httpx.HTTPError as exc:
            raise TokenError(f"token endpoint unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            # Never include the body: some endpoints echo the request.
            raise TokenError(f"token endpoint returned HTTP {response.status_code}")
        try:
            body = response.json()
            token = str(body["access_token"])
            lifetime = float(body.get("expires_in", DEFAULT_LIFETIME_S))
        except (ValueError, KeyError, TypeError) as exc:
            raise TokenError("token endpoint returned an unexpected body") from exc
        return token, self._clock() + lifetime
