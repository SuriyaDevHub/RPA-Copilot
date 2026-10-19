"""Error signature (SPEC §5.2): the same failure on different runs, users and days hashes
to the same 16 hex characters.

Computed on the root-cause (innermost) exception after masking: its type, its normalised
message and its first three in-house frame methods (searching outward if it has none).
"""

from __future__ import annotations

import hashlib
import re

from genie_copilot.logs.masking import PLACEHOLDER
from genie_copilot.logs.models import ExceptionInfo

_STRIP = [
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),  # emails
    re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b"),  # GUIDs
    re.compile(
        r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"
    ),  # ISO timestamps
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}(?: \d{1,2}:\d{2}(?::\d{2})?(?: ?[AP]M)?)?"),  # dates
    re.compile(r"[A-Za-z]:\\[^\s'\"]*|\\\\[^\s'\"]+"),  # Windows and UNC paths
    re.compile(r"(?<![\w.])/(?:[\w.-]+/)+[\w.-]*"),  # unix-style paths
    re.compile("'[^']*'|\"[^\"]*\"|\u2018[^\u2019]*\u2019|\u201c[^\u201d]*\u201d"),  # quoted
    re.compile(r"\d{4,}"),  # long numbers
]
_SPACES = re.compile(r"\s+")


def normalise(message: str) -> str:
    text = PLACEHOLDER.sub(r"<\1>", message)
    for pattern in _STRIP:
        text = pattern.sub("_", text)
    return _SPACES.sub(" ", text).strip()


def signature_methods(error: ExceptionInfo, count: int = 3) -> list[str]:
    for exc in reversed(error.chain()):
        methods = [f.method for f in exc.frames if f.in_house][:count]
        if methods:
            return methods
    return []


def compute(error: ExceptionInfo) -> str:
    root = error.root
    parts = [root.exception_type, normalise(root.message), *signature_methods(error)]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
