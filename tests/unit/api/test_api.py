import json
import threading
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from genie_copilot.api.main import create_app
from genie_copilot.db.models import Incident, Job
from genie_copilot.db.session import session_scope
from genie_copilot.orchestrator.machine import transition
from genie_copilot.orchestrator.states import State
from genie_copilot.watcher.help_runs import encode_key
from genie_copilot.wiring import Runtime
from tests.helpers import PREFIX, make_runtime, upload

JDOE = {"X-Dev-User": "jdoe"}
ASMITH = {"X-Dev-User": "asmith"}
SUPPORT = {"X-Dev-User": "l2-anna", "X-Dev-Roles": "support"}


@pytest.fixture
def runtime(engine, s3) -> Runtime:  # type: ignore[no-untyped-def]
    keys = {
        f"{PREFIX}bot-a/simple_ioexception.log": "jdoe",
        f"{PREFIX}bot-a/inner_chain.log": "asmith",
        f"{PREFIX}bot-a/successful_run.log": "jdoe",
    }
    for key in keys:
        upload(s3, key.rsplit("/", 1)[1])
    return make_runtime(engine, s3, users=keys)


@pytest.fixture
def client(runtime: Runtime) -> Iterator[TestClient]:
    with TestClient(create_app(runtime)) as c:
        yield c


def _pipeline(runtime: Runtime) -> dict[str, str]:
    runtime.watcher().poll_once()
    runtime.worker("w1").drain()
    with session_scope(runtime.factory) as s:
        return {i.user_id or "": i.id for i in s.scalars(select(Incident))}


def test_health_and_ready(client: TestClient) -> None:
    assert client.get("/v1/health").json() == {"status": "ok"}
    assert client.get("/v1/ready").json()["database"] == "ok"


def test_auth_required(client: TestClient) -> None:
    assert client.get("/v1/incidents").status_code == 401
    bad_role = {"X-Dev-User": "x", "X-Dev-Roles": "admin"}
    assert client.get("/v1/incidents", headers=bad_role).status_code == 400


def test_owner_and_support_access(client: TestClient, runtime: Runtime) -> None:
    ids = _pipeline(runtime)
    mine = client.get(f"/v1/incidents/{ids['jdoe']}", headers=JDOE)
    assert mine.status_code == 200
    body = mine.json()
    assert body["state"] == State.FALLBACK_MANUAL
    assert body["parsed_error"]["exception_type"] == "System.IO.IOException"
    assert any(line["id"] == 3 for line in body["parsed_error"]["window"])
    assert [e["to_state"] for e in body["events"]][:2] == ["RECEIVED", "LOGS_PARSED"]

    assert client.get(f"/v1/incidents/{ids['jdoe']}", headers=ASMITH).status_code == 403
    assert client.get(f"/v1/incidents/{ids['jdoe']}", headers=SUPPORT).status_code == 200
    assert client.get("/v1/incidents/does-not-exist", headers=SUPPORT).status_code == 404


def test_list_mine_and_all(client: TestClient, runtime: Runtime) -> None:
    ids = _pipeline(runtime)
    mine = client.get("/v1/incidents", headers=JDOE).json()
    assert [i["id"] for i in mine] == [ids["jdoe"]]
    assert client.get("/v1/incidents?mine=false", headers=JDOE).status_code == 403
    everything = client.get("/v1/incidents?mine=false", headers=SUPPORT).json()
    assert len(everything) == 2


def _read_sse(client: TestClient, url: str, headers: dict[str, str]) -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    events: list[tuple[str, dict]] = []  # type: ignore[type-arg]
    kind = None
    with client.stream("GET", url, headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: ") and kind:
                events.append((kind, json.loads(line[6:])))
    return events


def test_sse_streams_existing_events_in_order_and_ends(
    client: TestClient, runtime: Runtime
) -> None:
    ids = _pipeline(runtime)
    events = _read_sse(client, f"/v1/incidents/{ids['jdoe']}/events", JDOE)
    states = [d["to_state"] for k, d in events if k == "state"]
    assert states == ["RECEIVED", "LOGS_PARSED", "FALLBACK_MANUAL"]
    assert events[-1] == ("end", {"state": "FALLBACK_MANUAL"})
    ids_seen = [d["id"] for k, d in events if k == "state"]
    assert ids_seen == sorted(ids_seen)


def test_sse_resumes_after_last_event_id(client: TestClient, runtime: Runtime) -> None:
    ids = _pipeline(runtime)
    url = f"/v1/incidents/{ids['jdoe']}/events"
    first = [d for k, d in _read_sse(client, url, JDOE) if k == "state"]
    resumed = _read_sse(client, url, {**JDOE, "Last-Event-ID": str(first[0]["id"])})
    assert [d["to_state"] for k, d in resumed if k == "state"] == ["LOGS_PARSED", "FALLBACK_MANUAL"]


def test_sse_delivers_live_transitions(client: TestClient, runtime: Runtime, make_incident) -> None:  # type: ignore[no-untyped-def]
    inc = make_incident(user_id="jdoe")

    def move() -> None:
        for to in (State.LOGS_PARSED, State.DIAGNOSED, State.FALLBACK_MANUAL):
            time.sleep(0.05)
            with session_scope(runtime.factory) as s:
                incident = s.get(Incident, inc.id)
                assert incident is not None
                transition(s, incident, to, "live")

    mover = threading.Thread(target=move)
    mover.start()
    events = _read_sse(client, f"/v1/incidents/{inc.id}/events", JDOE)
    mover.join()
    assert [d["to_state"] for k, d in events if k == "state"] == [
        "LOGS_PARSED",
        "DIAGNOSED",
        "FALLBACK_MANUAL",
    ]


def test_sse_access_checked(client: TestClient, runtime: Runtime) -> None:
    ids = _pipeline(runtime)
    assert client.get(f"/v1/incidents/{ids['jdoe']}/events", headers=ASMITH).status_code == 403


def test_help_lists_only_my_failed_runs(client: TestClient) -> None:
    runs = client.get("/v1/help/runs?days=3", headers=JDOE).json()
    assert [r["s3_key_b64"] for r in runs] == [encode_key(f"{PREFIX}bot-a/simple_ioexception.log")]
    assert runs[0]["incident_id"] is None
    assert client.get("/v1/help/runs?days=30", headers=JDOE).status_code == 422


def test_help_open_incident_idempotent(client: TestClient, runtime: Runtime) -> None:
    token = encode_key(f"{PREFIX}bot-a/simple_ioexception.log")
    first = client.post(f"/v1/help/runs/{token}/incident", headers=JDOE)
    assert first.status_code == 201 and first.json()["created"] is True
    again = client.post(f"/v1/help/runs/{token}/incident", headers=JDOE)
    assert again.status_code == 200 and again.json()["incident_id"] == first.json()["incident_id"]
    with session_scope(runtime.factory) as s:
        incident = s.get(Incident, first.json()["incident_id"])
        assert incident is not None and incident.source == "help_page"
        assert [j.type for j in s.scalars(select(Job))] == ["parse"]
    listed = client.get("/v1/help/runs", headers=JDOE).json()
    assert listed[0]["incident_id"] == first.json()["incident_id"]


def test_help_open_incident_checks(client: TestClient) -> None:
    theirs = encode_key(f"{PREFIX}bot-a/inner_chain.log")
    assert client.post(f"/v1/help/runs/{theirs}/incident", headers=JDOE).status_code == 403
    assert client.post(f"/v1/help/runs/{theirs}/incident", headers=SUPPORT).status_code == 201
    missing = encode_key(f"{PREFIX}bot-a/nope.log")
    assert client.post(f"/v1/help/runs/{missing}/incident", headers=JDOE).status_code == 404
    other_bot = encode_key(f"{PREFIX}bot-z/x.log")
    assert client.post(f"/v1/help/runs/{other_bot}/incident", headers=JDOE).status_code == 404
    assert client.post("/v1/help/runs/%%%/incident", headers=JDOE).status_code == 404
