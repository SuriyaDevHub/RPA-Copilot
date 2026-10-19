import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from genie_copilot.config import Settings, get_settings

MSSQL_URL = "mssql+pyodbc://@host/db?driver=ODBC+Driver+18+for+SQL+Server"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    import os

    for key in list(os.environ):
        if key.startswith("GC_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)  # no stray .env
    get_settings.cache_clear()


def test_defaults_are_valid_for_dev() -> None:
    s = Settings()
    assert s.env == "dev"
    assert s.is_sqlite
    assert s.worker_concurrency == 1
    assert s.confidence_threshold == 0.8


def test_prod_rejects_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GC_ENV", "prod")
    monkeypatch.setenv("GC_AUTH_MODE", "openam")
    monkeypatch.setenv("GC_DATABASE_URL", "sqlite:///x.db")
    with pytest.raises(ValidationError, match="must not be SQLite"):
        Settings()


def test_prod_rejects_dev_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GC_ENV", "prod")
    monkeypatch.setenv("GC_DATABASE_URL", MSSQL_URL)
    with pytest.raises(ValidationError, match="GC_AUTH_MODE=dev is not allowed"):
        Settings()


def test_sqlite_rejects_concurrency_above_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GC_WORKER_CONCURRENCY", "2")
    with pytest.raises(ValidationError, match="GC_WORKER_CONCURRENCY must be 1"):
        Settings()


def test_all_errors_reported_together(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GC_ENV", "prod")
    monkeypatch.setenv("GC_DATABASE_URL", "sqlite:///x.db")
    monkeypatch.setenv("GC_WORKER_CONCURRENCY", "3")
    with pytest.raises(ValidationError) as exc:
        Settings()
    text = str(exc.value)
    assert "must not be SQLite" in text
    assert "GC_AUTH_MODE=dev" in text
    assert "GC_WORKER_CONCURRENCY" in text


def test_valid_prod_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GC_ENV", "prod")
    monkeypatch.setenv("GC_DATABASE_URL", MSSQL_URL)
    monkeypatch.setenv("GC_AUTH_MODE", "openam")
    monkeypatch.setenv("GC_WORKER_CONCURRENCY", "4")
    s = Settings()
    assert not s.is_sqlite
    assert s.worker_concurrency == 4


def test_list_and_json_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GC_WATCHER_BOTS", "bot-a, bot-b,,")
    monkeypatch.setenv("GC_JIRA_FIELD_MAP", '{"summary": "summary", "impact": "customfield_1"}')
    s = Settings()
    assert s.watcher_bots == ["bot-a", "bot-b"]
    assert s.jira_field_map["impact"] == "customfield_1"


def test_secrets_are_not_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GC_TOKEN_CLIENT_SECRET", "s3cret-value")
    monkeypatch.setenv("GC_JIRA_TOKEN", "jira-pat")
    s = Settings()
    assert "s3cret-value" not in repr(s)
    assert "jira-pat" not in repr(s)
    assert s.token_client_secret.get_secret_value() == "s3cret-value"


@pytest.mark.parametrize(
    ("var", "value"),
    [("GC_CONFIDENCE_THRESHOLD", "1.5"), ("GC_ENV", "staging"), ("GC_AUTH_MODE", "basic")],
)
def test_out_of_range_values_rejected(
    monkeypatch: pytest.MonkeyPatch, var: str, value: str
) -> None:
    monkeypatch.setenv(var, value)
    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_cli_prod_sqlite_fails_with_clear_error(tmp_path: object) -> None:
    """The M0 acceptance command."""
    src = Path(__file__).resolve().parents[2] / "src"
    env = {"GC_ENV": "prod", "GC_DATABASE_URL": "sqlite:///x.db", "PYTHONPATH": str(src)}
    result = subprocess.run(
        [sys.executable, "-c", "from genie_copilot.config import get_settings; get_settings()"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "must not be SQLite when GC_ENV=prod" in result.stderr
