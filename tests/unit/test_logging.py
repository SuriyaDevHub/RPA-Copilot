import asyncio
import json
import logging

import pytest

from genie_copilot.observability.logging import JsonFormatter, current_context, log_context


def _format(msg: str, **extra: object) -> dict[str, object]:
    record = logging.LogRecord("gc.test", logging.INFO, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    out: dict[str, object] = json.loads(JsonFormatter().format(record))
    return out


def test_line_is_json_with_context() -> None:
    with log_context(incident_id="inc-1", run_id="run-9"):
        line = _format("hello")
    assert line["msg"] == "hello"
    assert line["incident_id"] == "inc-1"
    assert line["run_id"] == "run-9"
    assert line["level"] == "INFO"
    assert str(line["ts"]).endswith("+00:00")


def test_context_is_reset_after_block() -> None:
    with log_context(incident_id="inc-1"):
        with log_context(incident_id="inc-2", job_type="parse"):
            assert current_context() == {"incident_id": "inc-2", "job_type": "parse"}
        assert current_context() == {"incident_id": "inc-1"}
    assert current_context() == {}
    assert "incident_id" not in _format("x")


def test_extra_fields_are_emitted() -> None:
    assert _format("x", latency_ms=12)["latency_ms"] == 12


def test_unknown_context_field_rejected() -> None:
    with pytest.raises(ValueError, match="unknown log context"), log_context(user="bob"):
        pass


async def test_context_isolated_between_tasks() -> None:
    async def work(incident: str) -> str | None:
        with log_context(incident_id=incident):
            await asyncio.sleep(0)
            return current_context().get("incident_id")

    assert await asyncio.gather(work("a"), work("b")) == ["a", "b"]
