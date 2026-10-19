"""Tell users an incident was opened for them. SMTP arrives in M8; until then we log."""

from __future__ import annotations

import logging
from typing import Protocol

from genie_copilot.db.models import Incident

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def incident_opened(self, incident: Incident, review_url: str) -> None: ...


class LoggingNotifier:
    def incident_opened(self, incident: Incident, review_url: str) -> None:
        if incident.user_email:
            log.info("would email user about new incident", extra={"review_url": review_url})


def review_url(ui_base_url: str, incident_id: str) -> str:
    return f"{ui_base_url.rstrip('/')}/incidents/{incident_id}"
