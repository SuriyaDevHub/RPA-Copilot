"""Gateway LLM client (SPEC §6). The only module that imports `openai`.

complete_json: budget check -> primary model (strict json_schema) with transient retries
and one repair retry on invalid output -> fallback model -> LLMUnavailable.
Every API attempt writes one `llm_call` row through the injected call log.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from collections.abc import Callable, Mapping
from typing import Any, TypeVar, cast

import httpx
import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from genie_copilot.config import Settings
from genie_copilot.db.models import LLMCall
from genie_copilot.db.session import session_scope
from genie_copilot.llm.auth import ServiceAccountAuth, TokenError
from genie_copilot.llm.base import LLMError, LLMInputTooLarge, LLMUnavailable
from genie_copilot.llm.prompts import Prompt, PromptStore
from genie_copilot.llm.schemas import response_format, strict_json_schema
from genie_copilot.llm.tokens import TokenCounter, default_token_counter, fit_variables

M = TypeVar("M", bound=BaseModel)
R = TypeVar("R")

CallLog = Callable[[LLMCall], None]

EMBED_BATCH = 64
_ERROR_MAX = 2000
_RETRYABLE = (
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    TokenError,  # raised from inside the httpx auth flow, not wrapped by the SDK
)

log = logging.getLogger(__name__)


class DbCallLog:
    """Writes each llm_call row in its own transaction, so it survives agent rollbacks."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def __call__(self, call: LLMCall) -> None:
        try:
            with session_scope(self._factory) as session:
                session.add(call)
        except Exception:
            log.exception("failed to record llm_call")


class _ModelFailed(Exception):
    pass


class _InvalidOutput(Exception):
    def __init__(self, content: str, error: ValidationError) -> None:
        super().__init__(str(error))
        self.content = content
        self.error = error


class GatewayLLMClient:
    def __init__(
        self,
        settings: Settings,
        *,
        call_log: CallLog,
        prompts: PromptStore | None = None,
        count_tokens: TokenCounter | None = None,
        sleep: Callable[[float], None] = time.sleep,
        auth: httpx.Auth | None = None,
    ) -> None:
        self._s = settings
        self._call_log = call_log
        self._prompts = prompts or PromptStore()
        self._count = count_tokens or default_token_counter()
        self._sleep = sleep
        auth = auth or ServiceAccountAuth(
            token_url=settings.token_url,
            client_id=settings.token_client_id,
            client_secret=settings.token_client_secret,
            header=settings.token_header,
            scheme=settings.token_scheme,
            scope=settings.token_scope,
        )
        self._http = httpx.Client(auth=auth, timeout=settings.llm_timeout_s)
        # Retries are ours (they need llm_call rows and the fallback model).
        # openai>=3 types this as httpx2.Client but accepts a plain httpx.Client at runtime.
        self._openai = OpenAI(
            base_url=settings.llm_base_url,
            api_key="unused",
            http_client=self._http,  # type: ignore[arg-type,unused-ignore]
            max_retries=0,
        )

    def close(self) -> None:
        self._http.close()

    # -- chat ---------------------------------------------------------------

    def complete_json(
        self,
        *,
        purpose: str,
        prompt_name: str,
        variables: Mapping[str, str],
        schema: type[M],
        incident_id: str | None = None,
    ) -> M:
        prompt = self._prompts.load(prompt_name)
        models = [(self._s.llm_primary_model, True)]
        if self._s.llm_fallback_model:
            models.append((self._s.llm_fallback_model, self._s.llm_fallback_json_schema))
        schema_note = _schema_instructions(schema)
        reserve = 0 if all(strict for _, strict in models) else self._count(schema_note)

        def total(values: Mapping[str, str]) -> int:
            system, user = prompt.render(values)
            return self._count(system) + self._count(user)

        fitted = fit_variables(
            variables, prompt.truncatable, total, self._s.llm_max_input_tokens - reserve
        )
        if fitted is None:
            raise LLMInputTooLarge(f"prompt {prompt.name} exceeds the input budget")
        system, user = prompt.render(fitted)

        last: Exception | None = None
        for model, strict in models:
            messages = [
                {"role": "system", "content": system if strict else f"{system}\n\n{schema_note}"},
                {"role": "user", "content": user},
            ]
            fmt = response_format(schema) if strict else {"type": "json_object"}
            try:
                return self._complete_with_repair(
                    model, messages, fmt, schema, prompt, purpose, incident_id
                )
            except _ModelFailed as exc:
                log.warning("model %s failed for %s: %s", model, prompt.name, exc)
                last = exc
        raise LLMUnavailable(f"all models failed for {prompt.name}: {last}") from last

    def _complete_with_repair(
        self,
        model: str,
        messages: list[dict[str, str]],
        fmt: dict[str, Any],
        schema: type[M],
        prompt: Prompt,
        purpose: str,
        incident_id: str | None,
    ) -> M:
        try:
            return self._chat(model, messages, fmt, schema, prompt, purpose, incident_id)
        except _InvalidOutput as exc:
            repair = [
                *messages,
                {"role": "assistant", "content": exc.content},
                {
                    "role": "user",
                    "content": "Your previous reply did not match the required JSON schema. "
                    f"Validation errors:\n{_errors(exc.error)}\n"
                    "Reply again with only the corrected JSON.",
                },
            ]
            try:
                return self._chat(model, repair, fmt, schema, prompt, purpose, incident_id)
            except _InvalidOutput as again:
                raise _ModelFailed(
                    f"invalid output after repair: {_errors(again.error)}"
                ) from again

    def _chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        fmt: dict[str, Any],
        schema: type[M],
        prompt: Prompt,
        purpose: str,
        incident_id: str | None,
    ) -> M:
        record = {
            "incident_id": incident_id,
            "purpose": purpose,
            "model": model,
            "prompt_name": prompt.name,
            "prompt_version": prompt.version,
            "input_hash": _hash(messages),
        }

        def call() -> Any:
            return self._openai.chat.completions.create(
                model=model,
                messages=cast(Any, messages),
                response_format=cast(Any, fmt),
                max_tokens=self._s.llm_max_output_tokens,
                timeout=self._s.llm_timeout_s,
            )

        response, latency_ms = self._with_retries(call, record)
        usage = response.usage
        content = (response.choices[0].message.content or "") if response.choices else ""
        done = {
            **record,
            "input_tokens": usage.prompt_tokens if usage else None,
            "output_tokens": usage.completion_tokens if usage else None,
            "latency_ms": latency_ms,
            "cost_usd": self._cost(model, usage),
        }
        try:
            parsed = schema.model_validate_json(content)
        except ValidationError as exc:
            self._log(done, "invalid_output", _errors(exc))
            raise _InvalidOutput(content, exc) from exc
        self._log(done, "ok")
        return parsed

    # -- embeddings ---------------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start : start + EMBED_BATCH]
            record = {
                "incident_id": None,
                "purpose": "embed",
                "model": self._s.embed_model,
                "prompt_name": None,
                "prompt_version": None,
                "input_hash": _hash(batch),
            }

            def call(batch: list[str] = batch) -> Any:
                return self._openai.embeddings.create(
                    model=self._s.embed_model, input=batch, timeout=self._s.embed_timeout_s
                )

            try:
                response, latency_ms = self._with_retries(call, record)
            except _ModelFailed as exc:
                raise LLMUnavailable(f"embedding failed: {exc}") from exc
            usage = response.usage
            self._log(
                {
                    **record,
                    "input_tokens": usage.prompt_tokens if usage else None,
                    "latency_ms": latency_ms,
                    "cost_usd": self._cost(self._s.embed_model, usage),
                },
                "ok",
            )
            vectors.extend(d.embedding for d in sorted(response.data, key=lambda d: d.index))
        return vectors

    # -- shared -------------------------------------------------------------

    def _with_retries(self, call: Callable[[], R], record: dict[str, Any]) -> tuple[R, int]:
        attempts = self._s.llm_max_retries + 1
        for attempt in range(attempts):
            started = time.monotonic()
            try:
                result = call()
            except _RETRYABLE as exc:
                self._log({**record, "latency_ms": _ms(started)}, "retryable_error", _describe(exc))
                if attempt + 1 < attempts:
                    self._sleep(_backoff(attempt))
                    continue
                raise _ModelFailed(_describe(exc)) from exc
            except (openai.APIError, LLMError) as exc:
                self._log({**record, "latency_ms": _ms(started)}, "error", _describe(exc))
                raise _ModelFailed(_describe(exc)) from exc
            return result, _ms(started)
        raise AssertionError("unreachable")

    def _log(self, fields: dict[str, Any], status: str, error: str | None = None) -> None:
        self._call_log(
            LLMCall(**fields, status=status, error=error[:_ERROR_MAX] if error else None)
        )

    def _cost(self, model: str, usage: Any) -> float | None:
        price = self._s.llm_price_table.get(model)
        if price is None or usage is None:
            return None
        output = int(getattr(usage, "completion_tokens", 0) or 0)
        return float(int(usage.prompt_tokens) * price.input + output * price.output) / 1000


def build_client(settings: Settings, factory: sessionmaker[Session]) -> GatewayLLMClient:
    return GatewayLLMClient(settings, call_log=DbCallLog(factory))


def _schema_instructions(schema: type[BaseModel]) -> str:
    return "Respond with a single JSON object that conforms to this JSON Schema:\n" + json.dumps(
        strict_json_schema(schema), separators=(",", ":")
    )


def _errors(exc: ValidationError) -> str:
    return "\n".join(
        f"- {'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in exc.errors()
    )


def _describe(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    return f"{type(exc).__name__}{f' (HTTP {status})' if status else ''}: {exc}"


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _backoff(attempt: int) -> float:
    return float(min(8.0, 0.5 * 2**attempt) + random.uniform(0, 0.25))  # noqa: S311


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
