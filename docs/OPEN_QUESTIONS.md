# Open questions

Claude Code adds to this list whenever it hits a bank-specific value it must not invent. Answer inline and date the answer.

| # | Question | Needed by | Owner | Answer |
| --- | --- | --- | --- | --- |
| 1 | Token endpoint: full FQDN path, grant type, request format, token lifetime | M2 | GenAI platform | |
| 2 | Header the gateway expects (`Authorization: Bearer` or `AMToken`) | M2 | GenAI platform | |
| 3 | Exact model ids for the GPT model, Qwen and text-embedding-small | M2 | GenAI platform | |
| 4 | Does the gateway enforce `json_schema` strict mode for Qwen? | M2 | GenAI platform | |
| 5 | S3 key naming convention for Genie logs | M3 | You / Genie team | |
| 6 | Do current logs contain user id, VDI host, run id, step name? | M3 | You (from samples) | |
| 7 | Rule that marks a run as failed in today's logs | M3 | Genie team | |
| 8 | In-house .NET namespace prefixes (for marking in-house stack frames) | M3 | Genie team | |
| 9 | Mapping from Windows user id to email (directory lookup?) | M4 | Infra | |
| 10 | Jira: project key, issue type, required custom field ids, resolution statuses | M7–M8 | You | |
| 11 | Genie support template: exact fields and allowed values | M7 | Genie team | |
| 12 | SMTP relay host, port, auth, sender address | M8 | Infra | |
| 13 | How internal web apps authenticate users (OpenAM cookie or JWT, JWKS URL, group names for roles) | M9 | Security | |
| 14 | Where the pilot runs (container platform or VM) and how it is reached by users | M12 | Infra | |
| 15 | Data retention for logs, incidents and LLM call records | M12 | Compliance | |
| 16 | SQL Server version, database name, auth mode (SQL login or integrated), backup policy | P1 | DBA | |
| 17 | Genie Bot target .NET framework and step-runner structure | P2 | Genie team | |
| 18 | New structured log format spec and release date | P3 | Genie team | |
