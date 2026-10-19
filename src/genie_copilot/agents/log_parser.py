"""Log Parser agent (SPEC §8): incident -> masked ParsedError stored, state LOGS_PARSED.

No LLM. A log with no error moves the incident to FALLBACK_MANUAL. Idempotent: a second
run for the same incident reuses the stored parse.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from genie_copilot.config import Settings
from genie_copilot.db.models import Incident, ParsedErrorRow
from genie_copilot.logs.masking import Masker, MaskRules
from genie_copilot.logs.models import ParsedError
from genie_copilot.logs.parser import PARSER_VERSION, parse
from genie_copilot.logs.sources.base import LogSource
from genie_copilot.orchestrator.machine import transition
from genie_copilot.orchestrator.states import State

log = logging.getLogger(__name__)


class LogParserAgent:
    def __init__(self, source: LogSource, settings: Settings) -> None:
        self._source = source
        self._rules = MaskRules.from_settings(settings)
        self._in_house = tuple(settings.in_house_namespaces)

    def run(self, session: Session, incident_id: str) -> ParsedError | None:
        incident = session.get(Incident, incident_id)
        if incident is None:
            raise LookupError(f"incident {incident_id} not found")
        if session.get(ParsedErrorRow, incident_id) is not None:
            if incident.state == State.RECEIVED:
                transition(session, incident, State.LOGS_PARSED, "parse already stored")
            return None

        raw = self._source.read(incident.s3_log_key or incident.dedup_key)
        incident.user_id = incident.user_id or raw.user_id
        incident.vdi_host = incident.vdi_host or raw.vdi_host
        incident.run_id = incident.run_id or raw.run_id

        masker = Masker(
            self._rules,
            extra_terms=[incident.user_id, incident.vdi_host, raw.user_id, raw.vdi_host],
        )
        parsed = parse(raw, masker, self._in_house)
        if parsed is None:
            transition(session, incident, State.FALLBACK_MANUAL, "no error found in the log")
            return None

        session.add(
            ParsedErrorRow(
                incident_id=incident.id,
                exception_type=parsed.exception_type,
                message_masked=parsed.message,
                # The whole chain, outermost first: [{exception_type, message, frames}, ...]
                frames=[
                    e.model_dump(include={"exception_type", "message", "frames"})
                    for e in parsed.chain()
                ],
                log_window_masked="\n".join(f"L{line.id} {line.text}" for line in parsed.window),
                line_ids=[line.id for line in parsed.window],
                parser=f"{raw.adapter}/parser-v{PARSER_VERSION}",
            )
        )
        incident.error_signature = parsed.error_signature
        if parsed.failed_step:
            incident.step_name = parsed.failed_step
        transition(
            session,
            incident,
            State.LOGS_PARSED,
            f"{parsed.root.exception_type} at L{parsed.error_line_id}",
        )
        log.info("parsed incident", extra={"signature": parsed.error_signature})
        return parsed
