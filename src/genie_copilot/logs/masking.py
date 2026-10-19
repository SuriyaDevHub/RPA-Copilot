"""Masking applied to every text before it reaches an LLM or an embedding (rule 2).

Values become numbered placeholders such as `<EMAIL_1>`; the same value gets the same
placeholder within one Masker. The reverse map stays in memory and is never sent anywhere.
Masking is idempotent: no rule matches a placeholder.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from genie_copilot.config import Settings

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# The user segment of Windows profile paths: C:\Users\<name>\...
_USER_PATH = re.compile(r"(?i)(?<=\\users\\)[^\\/\s\"'<>]+")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_ISIN = re.compile(r"\b[A-Z]{2}\d[A-Z0-9]{8}\d\b")
_CARD = re.compile(r"(?<![\w-])\d{4}(?:[ -]\d{4}){3}(?![\w-])")
_ACCOUNT = re.compile(r"(?<![\w.-])\d{8,20}(?![\w-])")
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")

PLACEHOLDER = re.compile(r"<([A-Z]+)_\d+>")

_MIN_TERM = 3


@dataclass(frozen=True)
class MaskRules:
    names: tuple[str, ...] = ()
    host_patterns: tuple[str, ...] = ()

    @classmethod
    def from_settings(cls, settings: Settings) -> MaskRules:
        return cls(tuple(settings.mask_names), tuple(settings.mask_host_patterns))


@dataclass
class Masker:
    rules: MaskRules = field(default_factory=MaskRules)
    extra_terms: Iterable[str | None] = ()
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder -> original
    _reverse: dict[tuple[str, str], str] = field(default_factory=dict, repr=False)
    _patterns: list[tuple[str, re.Pattern[str]]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        terms = sorted({t for t in self.extra_terms if t and len(t) >= _MIN_TERM}, key=len)
        self._patterns = [
            ("EMAIL", _EMAIL),
            ("USER", _USER_PATH),
            *(("ID", _term(t)) for t in reversed(terms)),
            *(("NAME", _term(n)) for n in self.rules.names if len(n) >= _MIN_TERM),
            *(("HOST", re.compile(p)) for p in self.rules.host_patterns),
            ("IBAN", _IBAN),
            ("ISIN", _ISIN),
            ("CARD", _CARD),
            ("ACCOUNT", _ACCOUNT),
            ("IP", _IPV4),
        ]

    def mask(self, text: str) -> str:
        for kind, pattern in self._patterns:
            text = pattern.sub(self._replacer(kind), text)
        return text

    def _replacer(self, kind: str) -> Callable[[re.Match[str]], str]:
        return lambda match: self._placeholder(kind, match.group(0))

    def _placeholder(self, kind: str, value: str) -> str:
        if PLACEHOLDER.fullmatch(value):
            return value
        key = (kind, value.lower())
        if key not in self._reverse:
            count = sum(1 for k, _ in self._reverse if k == kind) + 1
            placeholder = f"<{kind}_{count}>"
            self._reverse[key] = placeholder
            self.mapping[placeholder] = value
        return self._reverse[key]


def mask(text: str, rules: MaskRules | None = None, extra_terms: Iterable[str | None] = ()) -> str:
    """One-off masking. Use a shared Masker to keep placeholders consistent across texts."""
    return Masker(rules or MaskRules(), extra_terms).mask(text)


def _term(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?i)(?<![\w.-]){re.escape(term)}(?![\w-])")
