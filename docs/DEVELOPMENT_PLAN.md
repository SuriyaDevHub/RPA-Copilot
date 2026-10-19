# Genie Copilot — development plan (PoC → pilot → production)

Built with Claude Code, one milestone per session (or a few sessions). Each milestone lists what to build, how it is accepted, what humans must supply, and a prompt to paste into Claude Code.

- **PoC + pilot (M0–M12):** SQLite, logs already in S3, no change to the Genie Bot .exe.
- **Production (P1–P7):** SQL Server, embedded C# client, structured logs, self-healing, fleet onboarding.

---

## How to run each milestone in Claude Code

1. Start a fresh session in the repo root. `CLAUDE.md` loads automatically.
2. Paste the milestone prompt. For milestones marked **(plan first)**, ask Claude Code to use plan mode and approve the plan before it writes code.
3. Let it build, then run `make lint && make test` (it should do this itself).
4. Review the diff yourself. Check the acceptance list below, not just green tests.
5. Commit with the milestone id in the message (`M3: legacy S3 log adapter and parser`).
6. Note any new unknowns in `docs/OPEN_QUESTIONS.md`.

Keep sessions focused: if a milestone grows past a day of work, split it at the sub-headings.

---

## Before M0: inputs to collect

| Input | Needed by | Owner |
| --- | --- | --- |
| S3 bucket + prefix + read-only credentials (you have access) | M3 | You |
| 20–30 failed + 5 successful logs per pilot bot, copied to `tests/fixtures/logs/<bot>/` | M3 | You (from S3) |
| Jira base URL, L2 project key, issue type, required fields, service-account token (you have access) | M8 | You |
| Export of resolved Genie Jira tickets (last 12–24 months) as JSON/CSV | M5 | You |
| Genie support template (blank + 10 filled examples) | M7 | Genie Bot team |
| Support mailbox emails export (optional, improves KB) | M5 | Genie Bot team |
| SOPs, runbooks, known-error list | M5 | Genie Bot team |
| Token endpoint FQDN, auth flow (client credentials?), token lifetime, header name | M2 | GenAI platform team |
| Exact model names on the gateway; whether Qwen supports `json_schema` | M2 | GenAI platform team |
| SMTP relay host/port and sender address | M8 | Infra |
| How users authenticate to internal web apps (OpenAM details) | M9 | Infra / security |
| 150–200 labelled golden cases (category, action, root cause) | M11 | L2 SME (start labelling in week 1) |

---

## Phase map

| Phase (weeks) | Milestones | Gate |
| --- | --- | --- |
| 0 · Foundations (1–2) | M0, M1, M2 | Can call the LLM through the gateway from code; DB migrates |
| 1 · Deterministic core (3–6) | M3, M4, M8 (Jira/email only) | S3 failure → incident → Jira ticket end to end in UAT, no LLM |
| 2 · AI triage (7–10) | M5, M6, M7, M11 | Offline eval passes gates |
| 3 · Human loop + hardening (11–13) | M9, M10, M12 | Security + AI governance sign-off |
| 4 · Pilot (14–16) | Run, measure, tune | Go / no-go for production |
| Production (≈ 8–12 weeks after go) | P1–P7 | Per-step gates below |

M8 is built in Phase 1 against a stub draft so the plumbing is proven before the LLM arrives.

---

# PoC and pilot milestones

## M0 · Repository scaffold and tooling

**Build**
- `pyproject.toml` (deps from CLAUDE.md, optional `[mssql]` extra with `pyodbc`), `Makefile`, `.env.example`, `ruff.toml`, `mypy.ini`, `pytest.ini`
- package skeleton per CLAUDE.md layout with empty modules and `__init__.py`
- `observability/logging.py` (JSON logger with contextvars for `incident_id`, `run_id`)
- `config.py` with every setting from SPEC §1, including startup validation rules
- `docs/OPEN_QUESTIONS.md` seeded from the inputs table
- CI config (GitHub Actions or the bank's CI) running lint + test

**Accept**
- `make lint` and `make test` pass on the empty skeleton
- `GC_ENV=prod GC_DATABASE_URL=sqlite:///x.db python -c "from genie_copilot.config import get_settings; get_settings()"` fails with a clear error

**Prompt**
> Read CLAUDE.md and docs/SPEC.md. Implement milestone M0 from docs/DEVELOPMENT_PLAN.md: scaffold the repository exactly as in the CLAUDE.md layout, with pyproject, Makefile targets (lint, test, eval, migrate-check, run-api, run-worker, run-watcher, ui), config.py implementing every setting and startup rule in SPEC §1, and the JSON logger. Add tests for the config validation rules. Run make lint and make test until green.

---

## M1 · Database layer, migrations and job queue (plan first)

**Build**
- `db/types.py` (UTCDateTime, JSONText, StrUUID), `db/models.py` (all tables in SPEC §3 except `bot_registry`), `db/session.py` (engine factory; SQLite pragmas WAL, foreign_keys, busy_timeout)
- Alembic setup with an initial migration; `make migrate-check` runs `alembic upgrade head` on a temp SQLite file and on `MSSQL_TEST_URL` when set
- `db/repositories.py`: IncidentRepo, EventRepo, JobRepo, OutboxRepo, KBRepo, LLMCallRepo
- `db/queue.py`: SQLite and SQL Server implementations (SPEC §4), chosen by dialect
- `orchestrator/states.py`: states, allowed transitions; `orchestrator/machine.py`: `transition()` writing events

**Accept**
- unit tests for every allowed and a sample of illegal transitions
- queue tests: enqueue/claim/complete/fail/backoff/reclaim on SQLite; the SQL Server variant has a test marked `mssql` that runs when `MSSQL_TEST_URL` is set
- `incident.dedup_key` uniqueness enforced

**Prompt**
> Implement milestone M1. Use plan mode first and show me the model and migration plan. Follow SPEC §2–§4 exactly. Code must be portable between SQLite and SQL Server: only db/queue.py and Alembic may contain dialect-specific SQL. Write the tests listed under M1 Accept.

---

## M2 · LLM client and token auth

**Build**
- `llm/auth.py` `ServiceAccountAuth` (SPEC §6) with locking and 401 refresh-retry
- `llm/client.py` `LLMClient`: `complete_json`, `embed`, token budget, retries, fallback, `llm_call` rows, cost estimate from a per-model price table in config
- `llm/schemas.py`: JSON-schema export from Pydantic models (strict-mode compatible: no defaults, `additionalProperties: false`)
- `prompts/` loader with front matter and `{{var}}` rendering; missing variable = error
- `scripts/llm_smoke.py`: one chat call + one embedding against the real gateway, prints model, latency, tokens
- `tests/fakes.py`: `FakeLLMClient`

**Accept**
- respx tests: token cached across calls; refreshed 60 s before expiry; 401 → one refresh → retry; 429 → retry → fallback model; both fail → `LLMUnavailable`
- invalid JSON from the model → one repair retry with validation errors appended
- `scripts/llm_smoke.py` succeeds in DEV against the gateway (manual check)

**Prompt**
> Implement milestone M2 per SPEC §6. Use the OpenAI Python SDK with base_url from config and a custom httpx.Auth for the service-account token; the header name and scheme come from config. Agents must never import openai. Add the FakeLLMClient and the respx tests listed under M2 Accept, plus scripts/llm_smoke.py.

---

## M3 · S3 access, legacy log adapter, parser, masking, signature (plan first)

**Build**
- `integrations/s3.py` (list with watermark, get object, presigned link for the UI)
- `logs/sources/base.py` `LogSource` protocol; `logs/sources/s3_legacy.py` parsing today's log format into `RawLog` (derive bot/user/host/run from key path or content; record what is missing)
- `logs/parser.py`: find first error, window ±200 lines with line ids, parse .NET stack traces (incl. inner exceptions, `--- End of inner exception stack trace ---`, async frames), mark in-house frames by namespace prefix list from config
- `logs/masking.py`: names from a configurable list, emails, account/ISIN-like tokens, Windows user paths, IPs, hostnames (configurable); reversible map kept out of the LLM input
- `logs/signature.py` per SPEC §5.2
- `agents/log_parser.py` wiring it together and storing `parsed_error`

**Accept**
- golden tests over every fixture in `tests/fixtures/logs/`: each failed log yields a `ParsedError` with the expected exception type (write `expected.json` per fixture); successful logs yield none
- same error with different GUIDs/timestamps → same signature; different exception → different signature
- masking tests: no email/account pattern survives; masking is idempotent
- a test that fails if any agent passes unmasked fixture text to `FakeLLMClient`

**Prompt**
> Implement milestone M3. First read 5 failed and 2 successful fixtures in tests/fixtures/logs/ and describe the log format back to me in plan mode, including which fields (user, host, run id, step) can be recovered and from where. After I approve, implement the S3 integration, the LogSource protocol, the legacy adapter, parser, masking and signature per SPEC §5.1–5.2, and the Log Parser agent. Create expected.json per fixture and the tests under M3 Accept. List anything you could not recover in docs/OPEN_QUESTIONS.md.

---

## M4 · S3 watcher, intake API, orchestrator worker

**Build**
- `watcher/s3_watcher.py`: poll `GC_S3_LOG_PREFIX` for pilot bots since watermark; classify failed runs (rule from M3 findings); create incident with `dedup_key = s3 key`; enqueue `parse`; notify user by email with the review link (if user email known)
- `orchestrator/worker.py`: loop claiming jobs, dispatching to agents, transitions, retries, fallback; graceful shutdown; concurrency from config
- `api/main.py`, `api/routes/health.py`, `api/routes/incidents.py` (read endpoints + SSE), `api/routes/help.py` (Stage 2: list my failed runs, open incident)
- `api/auth.py`: `dev` mode only for now, behind the interface the OpenAM mode will implement in M9

**Accept**
- moto-based integration test: drop 3 logs (2 failed, 1 ok) into a fake bucket → watcher creates 2 incidents → worker parses both → states `LOGS_PARSED`; rerunning the watcher creates no duplicates
- killing the worker mid-job and restarting resumes correctly (stale reclaim)
- SSE endpoint streams state changes in order

**Prompt**
> Implement milestone M4: the S3 watcher, the job worker and the first API routes per SPEC §2, §4 and §9. Agents not yet built should be registered as stubs that move the incident to FALLBACK_MANUAL so the pipeline is runnable end to end. Write the moto integration test and the resume-after-crash test under M4 Accept.

---

## M5 · Knowledge base ingestion and retrieval (plan first)

**Build**
- `kb/sources/jira_export.py`, `kb/sources/emails.py`, `kb/sources/docs.py` (Markdown, DOCX, PDF text), `kb/sources/known_errors.py` (CSV/YAML)
- `kb/chunking.py`, cleaning (signatures, disclaimers, quoted replies), masking, dedup per SPEC §7
- `kb/vector_store.py` (FAISS, versioned save/load, reload on version change), `kb/bm25.py`, `kb/retriever.py` (hybrid + RRF + bot filter + verified boost)
- CLI: `python -m genie_copilot.kb ingest --source jira --path export.json`, `... rebuild-index`, `... search "text" --bot X`
- `known_error` lookup by signature

**Accept**
- ingest of the fixture export is idempotent (second run adds 0 items)
- `rebuild-index` from `kb_item` reproduces the same search results
- retrieval recall@5 on a 20-case mini set in `tests/fixtures/kb_eval.jsonl` ≥ 0.8 with the fake embedder seeded for determinism; real number recorded in M11
- the index file can be deleted and rebuilt with no data loss

**Prompt**
> Implement milestone M5 per SPEC §7. Start in plan mode: inspect tests/fixtures/jira_export sample and propose the cleaning and document shape for tickets. Then build the sources, chunking, dedup, FAISS store, BM25, hybrid retriever and the kb CLI. Only the indexer writes the FAISS file; API and worker reload on index_version change.

---

## M6 · Diagnostic agent and router

**Build**
- `prompts/diagnose.v1.md`
- `agents/diagnostic.py`: known-error short-circuit → retrieval → `complete_json` with `Diagnosis` schema → post-validation (SPEC §5.3) → store
- `agents/router.py`: pure function per SPEC §8 rules; PoC maps RETRY actions to `RERUN_ADVISED`
- user-facing fix steps and manual rerun steps stored with the diagnosis

**Accept**
- table-driven router tests covering every rule and threshold edge (0.79 / 0.80)
- diagnostic tests with `FakeLLMClient`: valid answer; answer citing a non-existent line → repaired or UNKNOWN; LLM down → `FALLBACK_MANUAL` path still produces a deterministic draft later
- known-error hit makes zero LLM calls

**Prompt**
> Implement milestone M6: the diagnose prompt, the Diagnostic agent and the Router per SPEC §5.3 and §8. Validation of evidence references is code, not prompt. Write the tests under M6 Accept, including the 0.79/0.80 threshold edges.

---

## M7 · Template Generator and duplicate check

**Build**
- `prompts/draft.v1.md` with 3 few-shot examples taken from real filled templates (masked)
- `agents/template_generator.py`: deterministic fields + LLM fields → `SupportDraft`; duplicate candidates = open Jira tickets with the same signature label, plus similarity search over open tickets (cosine ≥ 0.85) — limit 3
- Jira search helper in `integrations/jira.py` (JQL by label and status)

**Accept**
- deterministic fields always filled even when the LLM fails
- summary ≤ 300 chars enforced; empty LLM fields flagged for the user, not invented
- duplicate test with respx Jira mock returns the right candidate

**Prompt**
> Implement milestone M7 per SPEC §5.4 and §8. Field names must match docs/templates/support_template.md (create it from the sample I added in tests/fixtures/templates/). Build the duplicate check against Jira with labels and similarity. Tests per M7 Accept.

---

## M8 · Integration agent: Jira and mailbox via outbox

**Build**
- `integrations/jira.py`: create issue (field map from config), add label `gc-<incident_id>` and `sig-<signature>`, attach log window file, add comment (for link-duplicate)
- `integrations/mailer.py`: SMTP with HTML + text bodies rendered from the final template
- `integrations/outbox.py`: writer + dispatcher loop (in the worker) with backoff; idempotency by searching the `gc-<incident_id>` label before create
- `agents/integration.py`: on submit, write both outbox rows in one transaction; mark `TICKETED` when Jira succeeds

**Accept**
- Jira 500 then 201 → exactly one ticket; crash between create and DB update → re-run finds the label and does not create a second ticket
- email failure does not block the Jira ticket; both statuses visible on the incident
- UAT manual check: one real ticket created in the sandbox project

**Prompt**
> Implement milestone M8: Jira and SMTP integrations through a transactional outbox per SPEC §8. Idempotency uses the gc-<incident_id> Jira label. Write the failure-and-retry tests under M8 Accept with respx and an SMTP stub.

---

## M9 · Review UI and authentication (plan first)

**Build**
- `ui/` React + Vite + TS: pages per SPEC §11, SSE progress, evidence highlighting, draft form with AI-filled markers and diff on submit, low-confidence comment requirement, feedback
- `api/auth.py` `openam` mode (validate token/cookie per the details in OPEN_QUESTIONS; roles from groups) — keep `dev` mode for local work
- write endpoints: draft save, submit, resolve, escalate, link-duplicate, feedback
- build pipeline copying `ui/dist` into `api/static`

**Accept**
- a user cannot read another user's incident (403); support role can
- Playwright (or Vitest + Testing Library) tests for: open incident → see diagnosis → edit → submit
- page usable at 1280 px and 400 px widths

**Prompt**
> Implement milestone M9. In plan mode, propose the UI component tree and the auth approach for openam mode based on docs/OPEN_QUESTIONS.md. Then build the React UI per SPEC §11 and the write endpoints per SPEC §9 with role checks. Keep styling simple, accessible and consistent; no UI framework needed.

---

## M10 · Learning loop

**Build**
- poll Jira for `gc-*` tickets moved to Resolved/Closed; fetch resolution and comments
- `prompts/kb_entry.v1.md`, `agents/learner.py` → pending KB entry
- L2 approval endpoints + UI page; on approve: embed, add to index (via indexer job), `verified=true`; promote to `known_error` when the same signature has ≥ 3 approved resolutions

**Accept**
- unapproved entries never appear in retrieval
- approval adds the item to FAISS and BM25 within one indexer cycle
- promotion rule tested

**Prompt**
> Implement milestone M10: the resolution poller, the Learner agent, L2 approval endpoints and UI page, and known-error promotion, per SPEC §7–§9. Tests per M10 Accept.

---

## M11 · Evaluation harness and CI gate

**Build**
- `eval/golden_set/` loader, `eval/run_eval.py`, `eval/metrics.py`, `eval/judge.py` (unsupported-claim check prompt)
- report JSON + a short Markdown summary; `make eval` exits non-zero on gate failure
- adversarial cases: instructions embedded in logs, truncated traces, unseen exceptions
- CI job running eval (fake LLM in PR checks, real LLM nightly in DEV)

**Accept**
- with the real model on the labelled golden set: category accuracy ≥ 0.80, unsafe action rate 0, schema-valid ≥ 0.98, recall@5 ≥ 0.85
- report lists every failed case with the model output for review

**Prompt**
> Implement milestone M11 per SPEC §13. Build the eval runner, metrics, judge and gates, plus the adversarial cases. Then run it against the real gateway and summarise failures by category so we can tune prompts.

---

## M12 · Observability, hardening and pilot packaging

**Build**
- OpenTelemetry tracing, `/v1/metrics`, structured logs complete
- rate limiting per user on write endpoints; request size limits; security headers
- `scripts/backup_sqlite.py` (online backup API) + FAISS snapshot to S3, scheduled daily
- deployment: Dockerfile (if containers allowed) **and** a Windows/Linux service option (three processes: api, worker, watcher; plus indexer on schedule); `docs/runbooks/pilot.md` (start/stop, backup/restore, rotate token, kill switch, common failures)
- feature flag to disable the copilot per bot

**Accept**
- chaos checks: LLM down, Jira down, SMTP down, S3 throttled — each degrades as specified, nothing lost
- restore from backup reproduces incidents and search results
- dependency and SAST scans clean or waived

**Prompt**
> Implement milestone M12: tracing, metrics, rate limits, backups, packaging and the pilot runbook. Then write and run the failure-injection tests listed under M12 Accept and report results.

---

## Pilot (weeks 14–16): run and measure

- 1–2 bots, 15–25 users; watcher + Get help enabled; self-heal off (PoC has no rerun hook).
- Weekly review with L2: failed diagnoses, threshold tuning, prompt v2 if needed (every change through `make eval`).
- Exit criteria: error-to-ticket < 5 min median; ≥ 25 % resolved at L1; L2 agreement ≥ 80 %; ≥ 75 % drafts submitted with minor edits; fallback < 10 %; user satisfaction ≥ 4/5.

---

# Production milestones

## P1 · Move to SQL Server

**Build**
- install `[mssql]` extra; confirm `ODBC Driver 18`; connection via SQL login or integrated auth (config)
- run Alembic migrations on the dedicated database; fix any portability issue found
- `scripts/migrate_sqlite_to_mssql.py`: copy all tables in FK order with row-count and checksum verification, dry-run mode
- switch queue implementation (automatic by dialect); raise `GC_WORKER_CONCURRENCY` to 2–4
- SQL Server backups and retention per DBA standard; remove SQLite backup job

**Accept**
- full test suite passes with `GC_DATABASE_URL` pointing at a SQL Server test DB (`pytest -m "not sqlite_only"`)
- 4 concurrent workers process 500 synthetic jobs with zero duplicates and zero lost jobs
- pilot data migrated with matching counts and checksums

**Prompt**
> Implement milestone P1. Run the whole test suite against MSSQL_TEST_URL and fix portability issues without adding dialect checks outside db/queue.py. Write the migration script with dry-run and verification, and a concurrency test with 4 workers and 500 jobs.

## P2 · Embedded C# client (`client-dotnet/GenieCopilot`) (plan first)

**Build**
- .NET library (target the Genie Bot's framework version) with: failure capture hooks, envelope builder (SPEC §5.5), evidence bundle (allowlist, 5 MB cap), S3 upload of the bundle, HTTP client with Polly retries + 10 s timeout, auth, kill switch from central config, non-modal dialog that opens the review page
- `POST /v1/incidents` server side: idempotent on `run_id`, validates schema version
- contract test: C# serialises a sample envelope → Python validates it (shared JSON Schema file in `docs/contracts/envelope.schema.json`)

**Accept**
- unit tests in C# (xUnit) for envelope, bundle limits, offline fallback
- the .exe still behaves exactly as today when the copilot is off or unreachable
- released to the pilot group through the existing .exe distribution, behind a per-bot flag

**Prompt**
> Implement milestone P2 in client-dotnet/. In plan mode, ask me for the Genie Bot target framework and how the step runner is structured, then propose the integration points. Build the GenieCopilot library, the shared envelope JSON Schema, the server intake endpoint and contract tests on both sides.

## P3 · Structured log adapter

**Build** `logs/sources/structured.py` for the Genie Bot team's new JSON log format (lookup by `run_id`); adapter selection by bot version; add new-format samples to the golden set.
**Accept** parser golden tests pass for both formats; eval gates still pass.
**Prompt**
> Implement milestone P3: the structured log adapter for the format in docs/contracts/genie_log_format.md, adapter selection by bot version, and golden tests for both formats.

## P4 · Self-healing (controlled rerun)

**Build**
- `bot_registry` table and admin CLI; per-bot `self_heal_actions`, step idempotency flags supplied by the client
- router change: `ACTION_PROPOSED` when enabled; action endpoints (SPEC §9); global and per-bot kill switch
- client side: poll action, confirm dialog showing exactly what will happen, run from checkpoint, report result
- guardrails: one rerun per run, input fingerprint must match, never on non-idempotent steps

**Accept**
- tests for every guardrail; rerun failure escalates automatically
- two weeks of `RETRY_STEP` only, for `TRANSIENT`, with zero bad reruns before adding other actions

**Prompt**
> Implement milestone P4 per section 6 of the approach doc and SPEC §2, §8, §9: bot registry, action proposal, confirm, result, guardrails and kill switches on the server, and the matching rerun hook in the C# client. Every guardrail gets a test.

## P5 · Platform hardening

**Build** at least 2 API replicas and 2–4 workers; singleton indexer with leader lock (a row lock in SQL Server); secrets from the bank vault; TLS; Always On / HA if available; RPO/RTO documented; DR runbook tested; load test at 10× expected volume.
**Accept** failover drill passes; p95 diagnosis < 60 s under load; no single point of failure except the documented indexer recovery.
**Prompt**
> Implement milestone P5: indexer leader lock in SQL Server, multi-replica readiness, vault-backed secrets loader, load test script at 10x volume, and the DR runbook. Report the load-test results.

## P6 · Fleet onboarding and stats

**Build** onboarding CLI (`gc bots onboard <bot>`: checks samples, golden cases, KB items, L2 owner, eval pass); stats endpoints + read-only SQL views (for a dashboard later); monthly quality and cost report job.
**Accept** onboarding a new bot is a checklist run, not code; report generated monthly.
**Prompt**
> Implement milestone P6: the bot onboarding CLI with its checks, the stats endpoints and read-only SQL Server views listed in SPEC §9, and the monthly report job.

## P7 · Operate

Not a build milestone: production support runbook, on-call owner, SLAs, monthly prompt/model review, quarterly golden-set refresh, change control for model/prompt/threshold changes through `make eval`. When Genie Bot Orchestration replaces VDI-local scheduling, add an intake from the orchestrator and move reruns server-side.

---

## Definition of done (every milestone)

- [ ] Acceptance items above all checked
- [ ] `make lint`, `make test`, `make migrate-check` green
- [ ] `make eval` green when prompts, agents, kb or llm changed
- [ ] No new secrets, no unmasked text reaching the LLM, no dialect-specific SQL outside `db/queue.py`
- [ ] SPEC.md and OPEN_QUESTIONS.md updated if anything changed
