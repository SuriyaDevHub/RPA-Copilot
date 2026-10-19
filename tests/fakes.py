"""Test doubles. Agents get these instead of the gateway client."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from genie_copilot.llm.base import LLMUnavailable

M = TypeVar("M", bound=BaseModel)

Canned = dict[str, Any] | Callable[[Mapping[str, str]], dict[str, Any]] | Exception


@dataclass
class RecordedCall:
    purpose: str
    prompt_name: str
    variables: dict[str, str]
    incident_id: str | None


@dataclass
class FakeLLMClient:
    """Returns canned JSON per prompt name and records every call.

    A canned value may be a dict, a function of the variables, or an exception to raise.
    Prompts with no canned answer raise LLMUnavailable, like a gateway outage.
    """

    responses: dict[str, Canned] = field(default_factory=dict)
    dim: int = 32
    calls: list[RecordedCall] = field(default_factory=list)
    embedded: list[str] = field(default_factory=list)

    def complete_json(
        self,
        *,
        purpose: str,
        prompt_name: str,
        variables: Mapping[str, str],
        schema: type[M],
        incident_id: str | None = None,
    ) -> M:
        self.calls.append(RecordedCall(purpose, prompt_name, dict(variables), incident_id))
        canned = self.responses.get(prompt_name)
        if canned is None:
            raise LLMUnavailable(f"no canned response for {prompt_name}")
        if isinstance(canned, Exception):
            raise canned
        data = canned(variables) if callable(canned) else canned
        return schema.model_validate(data)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Deterministic unit vectors from a hash, so retrieval tests are repeatable."""
        self.embedded.extend(texts)
        return [_vector(t, self.dim) for t in texts]


def _vector(text: str, dim: int) -> list[float]:
    raw = hashlib.sha256(text.encode()).digest() * (dim // 32 + 1)
    values = [b / 255 - 0.5 for b in raw[:dim]]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]
