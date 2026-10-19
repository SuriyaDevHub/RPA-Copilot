"""Token counting and budget truncation.

Uses tiktoken `cl100k_base` as an approximation. tiktoken downloads the encoding file on
first use; where that is blocked, vendor it via TIKTOKEN_CACHE_DIR (OPEN_QUESTIONS #20).
Until then we fall back to ~4 characters per token, which overestimates for logs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

TokenCounter = Callable[[str], int]

TRUNCATION_MARKER = "[... truncated to fit the token budget ...]"

log = logging.getLogger(__name__)


def approx_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def default_token_counter() -> TokenCounter:
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception as exc:  # network blocked, cache missing, ...
        log.warning("tiktoken unavailable (%s); using 4 chars/token", type(exc).__name__)
        return approx_tokens
    return lambda text: len(encoding.encode(text, disallowed_special=()))


def keep_middle(text: str, keep: int) -> str:
    """Keep the `keep` central lines. Log windows are centred on the error."""
    lines = text.splitlines()
    if keep >= len(lines):
        return text
    start = (len(lines) - keep) // 2
    return "\n".join([TRUNCATION_MARKER, *lines[start : start + keep], TRUNCATION_MARKER])


def fit_variables(
    variables: Mapping[str, str],
    truncatable: frozenset[str],
    total_tokens: Callable[[Mapping[str, str]], int],
    budget: int,
) -> dict[str, str] | None:
    """Shrink truncatable variables, in order, until `total_tokens` fits the budget.

    Returns None when even empty truncatable variables do not fit.
    """
    current = dict(variables)
    if total_tokens(current) <= budget:
        return current
    for name in sorted(truncatable & set(current)):
        lines = current[name].splitlines()
        lo, hi = 0, len(lines)  # binary search for the most lines that still fit
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if total_tokens({**current, name: keep_middle(current[name], mid)}) <= budget:
                lo = mid
            else:
                hi = mid - 1
        current[name] = keep_middle(current[name], lo)
        if total_tokens(current) <= budget:
            return current
    return None
