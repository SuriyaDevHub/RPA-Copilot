"""Application settings (SPEC §1).

Every value comes from a `GC_`-prefixed environment variable (or `.env` in DEV).
Bank-specific values have no defaults or obvious placeholders; see docs/OPEN_QUESTIONS.md.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Env = Literal["dev", "uat", "prod"]
AuthMode = Literal["dev", "openam"]

# Placeholder marker for values that must be supplied per environment.
PLACEHOLDER = "CHANGE-ME"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GC_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    env: Env = "dev"

    # Storage
    database_url: str = "sqlite:///./data/copilot.db"
    data_dir: Path = Path("./data")

    # GenAI gateway auth (OPEN_QUESTIONS #1, #2)
    token_url: str = f"https://{PLACEHOLDER}/token"
    token_client_id: SecretStr = SecretStr("")
    token_client_secret: SecretStr = SecretStr("")
    token_header: str = "Authorization"  # noqa: S105 (header name, not a secret)
    token_scheme: str = "Bearer"  # noqa: S105

    # LLM (OPEN_QUESTIONS #3, #4)
    llm_base_url: str = f"https://{PLACEHOLDER}/v1"
    llm_primary_model: str = PLACEHOLDER
    llm_fallback_model: str = ""
    embed_model: str = "text-embedding-small"
    llm_timeout_s: float = Field(default=30, gt=0)
    embed_timeout_s: float = Field(default=10, gt=0)
    llm_max_input_tokens: int = Field(default=6000, gt=0)
    llm_max_output_tokens: int = Field(default=1000, gt=0)

    # S3 (OPEN_QUESTIONS #5)
    s3_bucket: str = ""
    s3_log_prefix: str = ""
    s3_evidence_prefix: str = ""
    watcher_interval_s: int = Field(default=90, gt=0)
    watcher_bots: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Jira (OPEN_QUESTIONS #10)
    jira_base_url: str = ""
    jira_token: SecretStr = SecretStr("")
    jira_project: str = ""
    jira_issue_type: str = ""
    jira_field_map: dict[str, str] = Field(default_factory=dict)

    # Mail (OPEN_QUESTIONS #12)
    smtp_host: str = ""
    smtp_port: int = Field(default=25, gt=0, le=65535)
    mail_from: str = ""
    support_mailbox: str = ""

    # UI and auth (OPEN_QUESTIONS #13)
    ui_base_url: str = "http://localhost:8000"
    auth_mode: AuthMode = "dev"

    # Routing and runtime
    confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    feature_self_heal: bool = False
    worker_concurrency: int = Field(default=1, ge=1)

    @field_validator("watcher_bots", mode="before")
    @classmethod
    def _split_bots(cls, value: object) -> object:
        if isinstance(value, str):
            return [b.strip() for b in value.split(",") if b.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @model_validator(mode="after")
    def _startup_rules(self) -> Self:
        errors: list[str] = []
        if self.env == "prod" and self.is_sqlite:
            errors.append("GC_DATABASE_URL must not be SQLite when GC_ENV=prod (use SQL Server)")
        if self.env == "prod" and self.auth_mode == "dev":
            errors.append("GC_AUTH_MODE=dev is not allowed when GC_ENV=prod")
        if self.is_sqlite and self.worker_concurrency > 1:
            errors.append("GC_WORKER_CONCURRENCY must be 1 when the database is SQLite")
        if errors:
            raise ValueError("invalid configuration: " + "; ".join(errors))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
