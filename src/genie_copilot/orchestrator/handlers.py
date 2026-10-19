"""Job handlers: one per job type. A handler does the step's work inside the job's
transaction and enqueues the next step. Agents not built yet move the incident to
FALLBACK_MANUAL so the pipeline is runnable end to end.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from genie_copilot.agents.log_parser import LogParserAgent
from genie_copilot.db.models import Incident, JobType
from genie_copilot.db.queue import JobQueue
from genie_copilot.orchestrator.machine import transition
from genie_copilot.orchestrator.states import State

Handler = Callable[[Session, Incident, JobQueue], None]


def parse_handler(agent: LogParserAgent) -> Handler:
    def handle(session: Session, incident: Incident, queue: JobQueue) -> None:
        agent.run(session, incident.id)
        if incident.state == State.LOGS_PARSED:
            queue.enqueue(session, incident.id, JobType.DIAGNOSE)

    return handle


def not_built(job_type: str, milestone: str) -> Handler:
    def handle(session: Session, incident: Incident, queue: JobQueue) -> None:
        transition(
            session,
            incident,
            State.FALLBACK_MANUAL,
            f"{job_type} agent not built yet ({milestone}); manual template",
        )

    return handle


def default_handlers(parser: LogParserAgent) -> dict[str, Handler]:
    return {
        JobType.PARSE: parse_handler(parser),
        JobType.DIAGNOSE: not_built(JobType.DIAGNOSE, "M6"),
        JobType.ROUTE: not_built(JobType.ROUTE, "M6"),
        JobType.DRAFT: not_built(JobType.DRAFT, "M7"),
        JobType.INTEGRATE: not_built(JobType.INTEGRATE, "M8"),
        JobType.LEARN: not_built(JobType.LEARN, "M10"),
    }
