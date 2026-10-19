"""Rule 7: no dialect-specific SQL outside the database portability layer."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "genie_copilot"
ALLOWED = {
    SRC / "db" / "queue.py",
    SRC / "db" / "session.py",
    SRC / "db" / "types.py",
    SRC / "config.py",  # inspects the URL scheme for startup rules; issues no SQL
}
PATTERN = re.compile(r"\btext\(|exec_driver_sql|PRAGMA|['\"](sqlite|mssql)['\"]|dialects\.")


def test_no_dialect_specific_sql_outside_db_layer() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{n}: {line.strip()}"
        for path in SRC.rglob("*.py")
        if path not in ALLOWED
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if PATTERN.search(line)
    ]
    assert offenders == []
