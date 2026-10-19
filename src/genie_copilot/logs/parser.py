"""Log parser (SPEC §5.2). Pure functions; the output is always masked.

Format-independent: finds the first error line, parses the .NET exception text near it
(`Exception.ToString()` layout, including `--->` inner exceptions, the
`--- End of inner exception stack trace ---` separators and async frames) and cuts a window
of lines around it. Format-specific knowledge (timestamps, the failed step) belongs in the
LogSource adapter.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import pairwise

from genie_copilot.logs import signature
from genie_copilot.logs.masking import Masker
from genie_copilot.logs.models import ExceptionInfo, Frame, LogLine, ParsedError, RawLog

PARSER_VERSION = "1"
WINDOW_RADIUS = 200
HEADER_LOOKAHEAD = 20  # lines after the error line to search for the exception header
MAX_MESSAGE_LINES = 20

_TS = re.compile(
    r"^\s*\[?(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?"
)
_LEVEL = re.compile(r"\b(TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL)\b", re.IGNORECASE)
_ERROR_LEVELS = {"ERROR", "FATAL", "CRITICAL"}
_LEVEL_SCAN = 80  # levels are looked for near the start of the line only

# A namespaced type ending in Exception/Error, optionally followed by ": message".
_TYPE = r"(?:[A-Za-z_][\w`]*\.)+[A-Za-z_][\w`]*(?:Exception|Error)\b"
_HEADER = re.compile(rf"(?P<type>{_TYPE})(?::\s?(?P<msg>.*))?$")
_CHAIN_PART = re.compile(
    rf"^\s*(?:\(Inner Exception #\d+\)\s*)?(?P<type>{_TYPE})(?::\s?(?P<msg>.*))?$"
)
_FRAME = re.compile(
    r"^\s*at (?P<method>[^(]+?)\s*\((?P<args>.*?)\)(?: in (?P<file>.+?):line (?P<line>\d+))?\s*$"
)
_END_INNER = re.compile(r"^\s*--- End of inner exception stack trace ---\s*$")
_END_ASYNC = re.compile(r"^\s*--- End of stack trace from previous location")
_ASYNC_METHOD = re.compile(r"\.<(?P<name>[\w`]+)>d__\d+\.MoveNext$")

_DEFAULT_EXTERNAL = ("System.", "Microsoft.")


def find_first_error(lines: Sequence[str]) -> int | None:
    """Index of the first line logged at ERROR/FATAL or carrying a .NET exception header."""
    for i, line in enumerate(lines):
        if _level(line) in _ERROR_LEVELS or _HEADER.search(line):
            return i
    return None


def build_window(
    lines: Sequence[str], center: int, masker: Masker, radius: int = WINDOW_RADIUS
) -> list[LogLine]:
    start, end = max(0, center - radius), min(len(lines), center + radius + 1)
    return [
        LogLine(
            id=i + 1, ts=_timestamp(lines[i]), level=_level(lines[i]), text=masker.mask(lines[i])
        )
        for i in range(start, end)
    ]


def parse_exception(
    lines: Sequence[str], start: int, in_house: Sequence[str] = ()
) -> ExceptionInfo | None:
    """Parse the exception whose header appears within HEADER_LOOKAHEAD lines of `start`."""
    for h in range(start, min(len(lines), start + HEADER_LOOKAHEAD + 1)):
        match = _HEADER.search(lines[h])
        if match:
            return _parse_from(lines, h, match.start(), in_house)
    return None


def parse(
    raw: RawLog, masker: Masker, in_house: Sequence[str] = (), failed_step: str | None = None
) -> ParsedError | None:
    """Parse a run's log. None when no error is found (a successful run)."""
    index = find_first_error(raw.lines)
    if index is None:
        return None
    exc = parse_exception(raw.lines, index, in_house) or ExceptionInfo(
        exception_type="Unknown", message=_strip_prefix(raw.lines[index])
    )
    masked = _mask_exception(exc, masker)
    return ParsedError(
        **masked.model_dump(),
        window=build_window(raw.lines, index, masker),
        error_line_id=index + 1,
        error_signature=signature.compute(masked),
        failed_step=masker.mask(failed_step) if failed_step else None,
    )


def is_in_house(method: str, prefixes: Sequence[str]) -> bool:
    if prefixes:
        return method.startswith(tuple(prefixes))
    return not method.startswith(_DEFAULT_EXTERNAL)


# -- internals --------------------------------------------------------------


def _parse_from(
    lines: Sequence[str], header: int, column: int, in_house: Sequence[str]
) -> ExceptionInfo:
    header_text = lines[header][column:]
    i = header + 1
    # Messages can span lines; continue until the first frame, marker or new log entry.
    extra: list[str] = []
    while (
        i < len(lines)
        and len(extra) < MAX_MESSAGE_LINES
        and not _FRAME.match(lines[i])
        and not _END_INNER.match(lines[i])
        and not _TS.match(lines[i])
        and lines[i].strip()
    ):
        extra.append(lines[i].strip())
        i += 1
    chain = _split_chain(header_text)
    if extra:
        chain[-1] = (chain[-1][0], "\n".join([chain[-1][1], *extra]).strip())

    sections: list[list[Frame]] = [[]]
    while i < len(lines):
        line = lines[i]
        frame = _FRAME.match(line)
        if frame:
            sections[-1].append(_frame(frame, in_house))
        elif _END_INNER.match(line):
            sections.append([])
        elif not _END_ASYNC.match(line):
            break
        i += 1

    # ToString() prints the innermost exception's frames first, then each outer one.
    infos = [ExceptionInfo(exception_type=t, message=m) for t, m in chain]
    for exc, frames in zip(reversed(infos), sections, strict=False):
        exc.frames = frames
    if len(sections) == 1 and len(infos) > 1 and not infos[-1].frames:
        infos[-1].frames = sections[0]  # truncated trace without separators
    for outer, inner in pairwise(infos):
        outer.inner = [inner]
    return infos[0]


def _split_chain(text: str) -> list[tuple[str, str]]:
    parts = text.split(" ---> ")
    chain: list[tuple[str, str]] = []
    for part in parts:
        match = _CHAIN_PART.match(part)
        if match:
            chain.append((match["type"], (match["msg"] or "").strip()))
        elif chain:  # "--->" inside a message
            chain[-1] = (chain[-1][0], f"{chain[-1][1]} ---> {part}".strip())
    return chain


def _frame(match: re.Match[str], in_house: Sequence[str]) -> Frame:
    method = _ASYNC_METHOD.sub(lambda m: f".{m['name']}", match["method"].strip())
    return Frame(
        method=method,
        file=match["file"],
        line=int(match["line"]) if match["line"] else None,
        in_house=is_in_house(method, in_house),
    )


def _mask_exception(exc: ExceptionInfo, masker: Masker) -> ExceptionInfo:
    return ExceptionInfo(
        exception_type=exc.exception_type,
        message=masker.mask(exc.message),
        frames=[
            f.model_copy(update={"file": masker.mask(f.file) if f.file else None})
            for f in exc.frames
        ],
        inner=[_mask_exception(i, masker) for i in exc.inner],
    )


def _level(line: str) -> str | None:
    match = _LEVEL.search(line[:_LEVEL_SCAN])
    if not match:
        return None
    level = match.group(1).upper()
    return "WARN" if level == "WARNING" else level


def _timestamp(line: str) -> datetime | None:
    match = _TS.match(line)
    if not match:
        return None
    try:
        ts = datetime.fromisoformat(match["ts"].replace(",", "."))
    except ValueError:
        return None
    # Naive timestamps are assumed UTC until the log timezone is known (OPEN_QUESTIONS #22).
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def _strip_prefix(line: str) -> str:
    text = _TS.sub("", line)
    match = _LEVEL.search(text[:_LEVEL_SCAN])
    return (text[match.end() :] if match else text).strip(" :-[]\t")
