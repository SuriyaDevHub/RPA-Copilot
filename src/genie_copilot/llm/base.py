"""What agents depend on. No `openai` import here: agents and tests use this module only."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


class LLMError(Exception):
    """Base for every LLM failure an agent should turn into FALLBACK_MANUAL."""


class LLMUnavailable(LLMError):
    """Primary and fallback models failed (errors, timeouts or invalid output)."""


class LLMInputTooLarge(LLMError):
    """The prompt's fixed instructions alone exceed the input token budget."""


class LLMClient(Protocol):
    def complete_json(
        self,
        *,
        purpose: str,
        prompt_name: str,
        variables: Mapping[str, str],
        schema: type[M],
        incident_id: str | None = None,
    ) -> M: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...
