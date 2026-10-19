import threading

import httpx
import pytest
import respx
from pydantic import SecretStr

from genie_copilot.llm.auth import ServiceAccountAuth, TokenError

from .conftest import TOKEN_URL, token_response

API = "https://gateway.test/v1/ping"


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def make_auth(clock: Clock | None = None, **kw: str) -> ServiceAccountAuth:
    return ServiceAccountAuth(
        token_url=TOKEN_URL,
        client_id=SecretStr("svc-id"),
        client_secret=SecretStr("svc-secret"),
        clock=clock or Clock(),
        **kw,  # type: ignore[arg-type]
    )


@respx.mock
def test_token_cached_across_calls() -> None:
    token = respx.post(TOKEN_URL).mock(return_value=token_response())
    api = respx.get(API).mock(return_value=httpx.Response(200))
    with httpx.Client(auth=make_auth()) as client:
        client.get(API)
        client.get(API)
    assert token.call_count == 1
    assert api.calls[1].request.headers["Authorization"] == "Bearer tok-1"
    sent = token.calls[0].request.content.decode()
    assert "grant_type=client_credentials" in sent and "client_secret=svc-secret" in sent


@respx.mock
def test_refreshed_60s_before_expiry() -> None:
    clock = Clock()
    token = respx.post(TOKEN_URL).mock(
        side_effect=[token_response("tok-1", 300), token_response("tok-2", 300)]
    )
    auth = make_auth(clock)
    assert auth.get_token() == "tok-1"
    clock.now += 239  # 61 s left
    assert auth.get_token() == "tok-1"
    clock.now += 2  # 59 s left
    assert auth.get_token() == "tok-2"
    assert token.call_count == 2


@respx.mock
def test_401_refreshes_once_and_retries() -> None:
    respx.post(TOKEN_URL).mock(side_effect=[token_response("old"), token_response("new")])
    api = respx.get(API).mock(side_effect=[httpx.Response(401), httpx.Response(200)])
    with httpx.Client(auth=make_auth()) as client:
        assert client.get(API).status_code == 200
    assert [c.request.headers["Authorization"] for c in api.calls] == ["Bearer old", "Bearer new"]


@respx.mock
def test_second_401_is_returned_not_looped() -> None:
    respx.post(TOKEN_URL).mock(side_effect=[token_response("a"), token_response("b")])
    api = respx.get(API).mock(return_value=httpx.Response(401))
    with httpx.Client(auth=make_auth()) as client:
        assert client.get(API).status_code == 401
    assert api.call_count == 2


@respx.mock
def test_custom_header_without_scheme() -> None:
    respx.post(TOKEN_URL).mock(return_value=token_response("am-token"))
    api = respx.get(API).mock(return_value=httpx.Response(200))
    with httpx.Client(auth=make_auth(header="AMToken", scheme="")) as client:
        client.get(API)
    assert api.calls[0].request.headers["AMToken"] == "am-token"
    assert "Authorization" not in api.calls[0].request.headers


@respx.mock
def test_token_endpoint_error_does_not_leak_secret() -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(500, text="svc-secret echoed"))
    with pytest.raises(TokenError) as exc:
        make_auth().get_token()
    assert "HTTP 500" in str(exc.value)
    assert "svc-secret" not in str(exc.value)


@respx.mock
def test_malformed_token_body() -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"token": "x"}))
    with pytest.raises(TokenError, match="unexpected body"):
        make_auth().get_token()


@respx.mock
def test_concurrent_callers_fetch_once() -> None:
    token = respx.post(TOKEN_URL).mock(return_value=token_response())
    auth = make_auth()
    results: list[str] = []
    threads = [threading.Thread(target=lambda: results.append(auth.get_token())) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == ["tok-1"] * 10
    assert token.call_count == 1
