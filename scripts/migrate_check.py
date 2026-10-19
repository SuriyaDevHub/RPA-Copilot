"""Check migrations on a fresh SQLite file, and on MSSQL_TEST_URL when set.

For each database: upgrade head, verify models and migrations match, downgrade base,
upgrade head again.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


def check(url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["configure_logger"] = False
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    command.check(cfg)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        check(f"sqlite:///{Path(tmp) / 'migrate_check.db'}")
        print("migrate-check: sqlite ok")
    mssql_url = os.environ.get("MSSQL_TEST_URL")
    if mssql_url:
        check(mssql_url)
        print("migrate-check: mssql ok")
    else:
        print("migrate-check: MSSQL_TEST_URL not set, skipped SQL Server")
    return 0


if __name__ == "__main__":
    sys.exit(main())
