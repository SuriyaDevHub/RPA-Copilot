import json
from collections.abc import Callable

import httpx
import pytest
import respx

from genie_copilot.db.models import LLMCall
from genie_copilot.llm.base import LLMInputTooLarge, LLMUnavailable
from genie_copilot.llm.client import GatewayLLMClient
from genie_copilot.llm.tokens import TRUNCATION_MARKER

from .conftest import GATEWAY, TOKEN_URL, Answer, body, chat_response, token_response

CHAT = f"{GATEWAY}/chat/completions"
EMBED = f"{GATEWAY}/embeddings"
GOOD = json.dumps({"category": "TRANSIENT", "confidence": 0.9})
VARS = {"bot": "bot-a", "log": "L1 started\nL2 System.TimeoutException"}

MakeClient = Callable[..., GatewayLLMClient]


@pytest.fixture(autouse=True)
def gateway():  # type: ignore[no-untyped-def]
    with respx.mock(assert_all_called=False) as mock:
        mock.post(TOKEN_URL).mock(return_value=token_response())
        yield mock


def run(client: GatewayLLMClient) -> Answer:
    return client.complete_json(
        purpose="diagnose", prompt_name="diag", variables=VARS, schema=Answer, incident_id=None
    )


def test_happy_path(gateway, make_client: MakeClient, calls: list[LLMCall]) -> None:  # type: ignore[no-untyped-def]
    route = gateway.post(CHAT).mock(return_value=chat_response(GOOD))
    assert run(make_client()) == Answer(category="TRANSIENT", confidence=0.9)

    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer tok-1"
    sent = body(request)
    assert sent["model"] == "gpt-primary"
    assert sent["max_tokens"] == 1000
    fmt = sent["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert "Bot: bot-a" in sent["messages"][1]["content"]

    [call] = calls
    assert (call.status, call.model, call.prompt_name, call.prompt_version) == (
        "ok",
        "gpt-primary",
        "diag",
        "2",
    )
    assert (call.input_tokens, call.output_tokens) == (100, 20)
    assert call.cost_usd == pytest.approx((100 * 1.0 + 20 * 2.0) / 1000)
    assert len(call.input_hash) == 64


def test_429_retries_then_succeeds(gateway, make_client, calls, sleeps) -> None:  # type: ignore[no-untyped-def]
    gateway.post(CHAT).mock(side_effect=[httpx.Response(429), chat_response(GOOD)])
    assert run(make_client()).category == "TRANSIENT"
    assert [c.status for c in calls] == ["retryable_error", "ok"]
    assert "HTTP 429" in (calls[0].error or "")
    assert len(sleeps) == 1


def test_429_exhausted_falls_back(gateway, make_client, calls) -> None:  # type: ignore[no-untyped-def]
    def by_model(request: httpx.Request) -> httpx.Response:
        if body(request)["model"] == "gpt-primary":
            return httpx.Response(429)
        return chat_response(GOOD, model="qwen-fallback")

    route = gateway.post(CHAT).mock(side_effect=by_model)
    assert run(make_client()).confidence == 0.9
    models = [body(c.request)["model"] for c in route.calls]
    assert models == ["gpt-primary"] * 3 + ["qwen-fallback"]
    fallback = body(route.calls[-1].request)
    assert fallback["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in fallback["messages"][0]["content"]
    assert [c.status for c in calls] == ["retryable_error"] * 3 + ["ok"]


def test_fallback_uses_strict_schema_when_supported(gateway, make_client) -> None:  # type: ignore[no-untyped-def]
    route = gateway.post(CHAT).mock(side_effect=[httpx.Response(503)] * 3 + [chat_response(GOOD)])
    run(make_client(llm_fallback_json_schema=True))
    assert body(route.calls[-1].request)["response_format"]["type"] == "json_schema"


def test_both_models_fail(gateway, make_client) -> None:  # type: ignore[no-untyped-def]
    gateway.post(CHAT).mock(return_value=httpx.Response(500))
    with pytest.raises(LLMUnavailable, match="all models failed"):
        run(make_client())


def test_no_fallback_configured(gateway, make_client) -> None:  # type: ignore[no-untyped-def]
    route = gateway.post(CHAT).mock(return_value=httpx.Response(500))
    with pytest.raises(LLMUnavailable):
        run(make_client(llm_fallback_model=""))
    assert route.call_count == 3


def test_timeout_is_retryable(gateway, make_client, calls) -> None:  # type: ignore[no-untyped-def]
    gateway.post(CHAT).mock(side_effect=[httpx.ReadTimeout("slow"), chat_response(GOOD)])
    run(make_client())
    assert [c.status for c in calls] == ["retryable_error", "ok"]


def test_client_error_skips_retries(gateway, make_client, calls) -> None:  # type: ignore[no-untyped-def]
    def by_model(request: httpx.Request) -> httpx.Response:
        if body(request)["model"] == "gpt-primary":
            return httpx.Response(400, json={"error": {"message": "bad response_format"}})
        return chat_response(GOOD)

    route = gateway.post(CHAT).mock(side_effect=by_model)
    run(make_client())
    assert [body(c.request)["model"] for c in route.calls] == ["gpt-primary", "qwen-fallback"]
    assert calls[0].status == "error"


def test_invalid_json_gets_one_repair(gateway, make_client, calls) -> None:  # type: ignore[no-untyped-def]
    bad = json.dumps({"category": "TRANSIENT"})  # confidence missing
    route = gateway.post(CHAT).mock(side_effect=[chat_response(bad), chat_response(GOOD)])
    assert run(make_client()).confidence == 0.9
    repair = body(route.calls[1].request)["messages"]
    assert repair[-2] == {"role": "assistant", "content": bad}
    assert "confidence: Field required" in repair[-1]["content"]
    assert [c.status for c in calls] == ["invalid_output", "ok"]


def test_invalid_after_repair_moves_to_fallback(gateway, make_client, calls) -> None:  # type: ignore[no-untyped-def]
    def by_model(request: httpx.Request) -> httpx.Response:
        if body(request)["model"] == "gpt-primary":
            return chat_response("not json at all")
        return chat_response(GOOD)

    gateway.post(CHAT).mock(side_effect=by_model)
    assert run(make_client()).category == "TRANSIENT"
    assert [c.status for c in calls] == ["invalid_output", "invalid_output", "ok"]
    assert [c.model for c in calls][-1] == "qwen-fallback"


def test_long_log_is_truncated_not_instructions(gateway, make_client) -> None:  # type: ignore[no-untyped-def]
    route = gateway.post(CHAT).mock(return_value=chat_response(GOOD))
    log = "\n".join(f"L{i} " + "x" * 76 for i in range(1000))  # ~20k tokens at 4 chars/token
    client = make_client(llm_max_input_tokens=1000, llm_fallback_model="")
    client.complete_json(
        purpose="diagnose",
        prompt_name="diag",
        variables={"bot": "bot-a", "log": log},
        schema=Answer,
    )
    sent = body(route.calls[0].request)["messages"]
    assert sent[0]["content"].startswith("Classify the error.")
    user = sent[1]["content"]
    assert user.startswith("Bot: bot-a") and user.rstrip().endswith("</log>")
    assert user.count(TRUNCATION_MARKER) == 2
    assert "L500 " in user  # middle of the window kept
    assert "L0 " not in user and "L999 " not in user
    assert (len(sent[0]["content"]) + len(user)) / 4 <= 1000


def test_instructions_over_budget_raise_without_calling(gateway, make_client) -> None:  # type: ignore[no-untyped-def]
    route = gateway.post(CHAT).mock(return_value=chat_response(GOOD))
    with pytest.raises(LLMInputTooLarge):
        make_client(llm_max_input_tokens=5).complete_json(
            purpose="diagnose", prompt_name="diag", variables=VARS, schema=Answer
        )
    assert route.call_count == 0


def test_embed_batches_of_64_in_order(gateway, make_client, calls) -> None:  # type: ignore[no-untyped-def]
    def respond(request: httpx.Request) -> httpx.Response:
        texts = body(request)["input"]
        data = [
            {"object": "embedding", "index": i, "embedding": [float(t.split("-")[1]), 0.0]}
            for i, t in reversed(list(enumerate(texts)))
        ]
        usage = {"prompt_tokens": len(texts), "total_tokens": len(texts)}
        return httpx.Response(
            200, json={"object": "list", "data": data, "model": "emb", "usage": usage}
        )

    route = gateway.post(EMBED).mock(side_effect=respond)
    texts = [f"t-{i}" for i in range(130)]
    vectors = make_client().embed(texts)
    assert [len(body(c.request)["input"]) for c in route.calls] == [64, 64, 2]
    assert [v[0] for v in vectors] == [float(i) for i in range(130)]
    assert body(route.calls[0].request)["model"] == "text-embedding-small"
    assert [c.purpose for c in calls] == ["embed"] * 3


def test_embed_failure_raises_unavailable(gateway, make_client) -> None:  # type: ignore[no-untyped-def]
    gateway.post(EMBED).mock(return_value=httpx.Response(503))
    with pytest.raises(LLMUnavailable, match="embedding failed"):
        make_client().embed(["a"])


def test_token_endpoint_down_is_retried_then_unavailable(gateway, make_client, calls) -> None:  # type: ignore[no-untyped-def]
    gateway.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("no route"))
    chat = gateway.post(CHAT).mock(return_value=chat_response(GOOD))
    with pytest.raises(LLMUnavailable):
        run(make_client())
    assert chat.call_count == 0
    assert {c.status for c in calls} == {"retryable_error"}
    assert "TokenError" in (calls[0].error or "")
