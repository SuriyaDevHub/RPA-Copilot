import json
from pathlib import Path
from typing import Any

from genie_copilot.logs.masking import MaskRules
from genie_copilot.logs.models import RawLog

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "dotnet"
IN_HOUSE = ("Genie.",)
RULES = MaskRules(names=("John Doe",), host_patterns=(r"\bVDI-[A-Z]{3}-\d{4}\b",))

# Sensitive values planted in the fixtures; none may survive masking.
PLANTED = [
    "jdoe",
    "asmith",
    "bwong",
    "john.doe@example-bank.com",
    "12345678901",
    "GB29NWBK60161331926819",
    "US0378331005",
    "10.20.30.40",
    "VDI-LON-0042",
    "VDI-NYC-0007",
]


def load(name: str, user_id: str | None = None) -> RawLog:
    lines = (FIXTURES / name).read_text().splitlines()
    return RawLog(source_key=name, bot_name="bot-a", user_id=user_id, lines=lines, adapter="test")


def expected() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / "expected.json").read_text())
    return data


def log_names() -> list[str]:
    return sorted(p.name for p in FIXTURES.glob("*.log"))
