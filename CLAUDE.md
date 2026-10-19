# Genie Copilot — project context for Claude Code

Read this file, `docs/SPEC.md` and the current milestone in `docs/DEVELOPMENT_PLAN.md` before writing code.
Build one milestone at a time. Do not start the next milestone until the current one's acceptance tests pass.

## What we are building

An agentic AI support copilot for **Genie Bot**, a C#/.NET RPA tool that end users run as a `.exe` on their VDIs.
When a bot run fails, the copilot:

1. detects the failure (PoC: from execution logs in S3; production: from a C# client inside the .exe),
2. parses and masks the log (**Log Parser Agent**, no LLM),
3. diagnoses the root cause with cited evidence (**Diagnostic Agent**, LLM + retrieval),
4. routes it: user fix / rerun / escalate (plain code, never the LLM),
5. pre-fills the Genie support template and checks for duplicate Jira tickets (**Template Generator Agent**, LLM),
6. waits for the user to review, edit and submit (**human-in-the-loop**, mandatory),
7. creates the Jira L2 ticket and emails the Genie Support Mailbox (**Integration Agent**, no LLM),
8. learns from the L2 resolution into the knowledge base (**Learner**, LLM + L2 approval).

## Stack (fixed — do not substitute)

- Python 3.11, FastAPI, Uvicorn, Pydantic v2, pydantic-settings
- SQLAlchemy 2.0 (typed ORM) + Alembic. **SQLite for PoC/pilot, SQL Server for production. Same code, different `DATABASE_URL`.**
- OpenAI Python SDK (`openai>=1.x`) pointed at the internal GenAI gateway via `base_url`; token from an FQDN token endpoint using a service account
- Models: a GPT chat model (primary), Qwen (fallback), `text-embedding-small` (embeddings). Model names come from config only.
- FAISS (`faiss-cpu`) for vectors, `rank_bm25` for keyword search
- boto3 for S3, httpx for Jira and the token endpoint, smtplib for email
- React 18 + Vite + TypeScript for the Review UI, built to static files served by FastAPI
- pytest, pytest-asyncio, moto (S3), respx (HTTP mocks), freezegun
- ruff (lint + format), mypy (strict on `src/`)
- Production only: a C#/.NET client library `GenieCopilot` (in `client-dotnet/`)

## Repository layout

```
src/genie_copilot/
  config.py            settings (pydantic-settings, env vars, .env)
  db/                  models.py, session.py, repositories.py, queue.py, types.py
  llm/                 auth.py (httpx.Auth token provider), client.py (LLMClient), schemas.py
  logs/                sources/ (base.py, s3_legacy.py, structured.py), parser.py, masking.py, signature.py
  kb/                  ingest.py, chunking.py, vector_store.py, bm25.py, retriever.py, sources/
  agents/              log_parser.py, diagnostic.py, router.py, template_generator.py, integration.py, learner.py
  orchestrator/        states.py, machine.py, worker.py
  integrations/        s3.py, jira.py, mailer.py, outbox.py
  watcher/             s3_watcher.py
  api/                 main.py, deps.py, auth.py, routes/ (incidents.py, help.py, kb.py, stats.py, health.py, actions.py)
  prompts/             diagnose.v1.md, draft.v1.md, kb_entry.v1.md
  observability/       logging.py, tracing.py, metrics.py
ui/                    React review UI (Vite)
eval/                  golden_set/, run_eval.py, metrics.py, judge.py
tests/                 unit/, integration/, fixtures/ (sample logs, Jira payloads)
alembic/               migrations (must run on SQLite AND SQL Server)
client-dotnet/         production C# client (milestone P2)
docs/                  SPEC.md, DEVELOPMENT_PLAN.md, runbooks/
```

## Non-negotiable rules

1. **The LLM never acts.** It returns JSON that code validates. Routing, reruns, Jira and email are code paths gated by a human click.
2. **Mask before every LLM or embedding call.** All text goes through `logs.masking.mask()` first. There is a unit test that fails if any agent calls `LLMClient` with unmasked fixtures.
3. **Agents never import `openai`.** Only `llm/client.py` does. Agents depend on the `LLMClient` protocol in `llm/base.py` so tests can inject `tests/fakes.py` `FakeLLMClient`.
4. **Evidence or UNKNOWN.** Diagnoses must cite log line ids and KB ids that exist; otherwise category = `UNKNOWN`. Validation is code, not prompt.
5. **Every step is idempotent** and keyed on `incident_id + step`. Every state change writes an `incident_event` row.
6. **Graceful degradation.** Any agent failure moves the incident to `FALLBACK_MANUAL` with whatever was produced, never to a dead end.
7. **Database portability.** No SQLite-only or SQL Server-only SQL outside `db/queue.py` and Alembic. Use the portable types in `db/types.py` (UTC datetimes, JSON-as-text, string UUIDs). Test migrations on both dialects.
8. **No secrets in code or logs.** Config from env; tokens and passwords are `SecretStr`.
9. **Prompts are versioned files** in `prompts/`; every LLM call logs prompt name + version.
10. **No business data leaves the VDI** (production client): evidence bundles use an extension allowlist and a 5 MB cap.

## Conventions

- Type hints everywhere; `mypy --strict src/` must pass.
- Pydantic models for every boundary (API, agent input/output, LLM output).
- Structured JSON logging with `incident_id` and `run_id` on every line (`observability/logging.py`).
- Time is always UTC (`datetime.now(timezone.utc)`).
- Tests: every module gets unit tests; every milestone adds at least one integration test. No real network in tests.
- Commands: `make lint`, `make test`, `make eval`, `make run-api`, `make run-worker`, `make run-watcher`, `make ui`.
- Keep functions small; prefer pure functions for parsing, masking, signatures and routing.

## Commands Claude Code should run before saying a milestone is done

```
make lint      # ruff + mypy
make test      # pytest -q
make migrate-check   # alembic upgrade head on a fresh SQLite file (and SQL Server when MSSQL_TEST_URL is set)
```

## When information is missing

Do not invent bank-specific values (Jira field ids, S3 bucket names, token endpoint paths, header names).
Put them in `config.py` with a clear placeholder and add them to `docs/OPEN_QUESTIONS.md`.
