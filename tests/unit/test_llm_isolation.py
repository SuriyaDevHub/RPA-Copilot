"""Rule 3: only llm/client.py may import openai."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "genie_copilot"
IMPORT = re.compile(r"^\s*(import openai|from openai\b)", re.MULTILINE)


def test_only_llm_client_imports_openai() -> None:
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if p != SRC / "llm" / "client.py" and IMPORT.search(p.read_text())
    ]
    assert offenders == []
