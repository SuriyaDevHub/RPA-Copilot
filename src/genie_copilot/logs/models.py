"""Log contracts (SPEC §5.1-5.2)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RawLog(BaseModel):
    source_key: str
    bot_name: str
    user_id: str | None = None
    vdi_host: str | None = None
    run_id: str | None = None
    started_at: datetime | None = None
    lines: list[str]
    adapter: str


class Frame(BaseModel):
    method: str
    file: str | None = None
    line: int | None = None
    in_house: bool = False


class LogLine(BaseModel):
    id: int  # 1-based line number in the source log; cited as "L<id>"
    ts: datetime | None = None
    level: str | None = None
    text: str


class ExceptionInfo(BaseModel):
    exception_type: str
    message: str
    frames: list[Frame] = []
    inner: list[ExceptionInfo] = []

    def chain(self) -> list[ExceptionInfo]:
        """Outermost first, innermost (usually the root cause) last."""
        out: list[ExceptionInfo] = [self]
        while out[-1].inner:
            out.append(out[-1].inner[0])
        return out

    @property
    def root(self) -> ExceptionInfo:
        return self.chain()[-1]


class ParsedError(ExceptionInfo):
    """All text in here is already masked."""

    window: list[LogLine]
    error_line_id: int
    error_signature: str
    failed_step: str | None = None
