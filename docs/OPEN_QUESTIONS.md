# Open questions

Claude Code adds to this list whenever it hits a bank-specific value it must not invent. Answer inline and date the answer.

| # | Question | Needed by | Owner | Answer |
| --- | --- | --- | --- | --- |
| 1 | Token endpoint: full FQDN path, grant type, request format, token lifetime. M2 assumes OAuth2 client credentials (form POST, `access_token` + `expires_in` reply) | M2 | GenAI platform | |
| 2 | Header the gateway expects (`Authorization: Bearer` or `AMToken`) | M2 | GenAI platform | |
| 3 | Exact model ids for the GPT model, Qwen and text-embedding-small | M2 | GenAI platform | |
| 4 | Does the gateway enforce `json_schema` strict mode for Qwen? | M2 | GenAI platform | |
| 5 | S3 key naming convention for Genie logs. Placeholder in M4: `<GC_S3_LOG_PREFIX><bot_name>/...`, user/host/run not recovered, so "Get help" lists nothing for users until M3 part 2 | M3 | You / Genie team | |
| 6 | Do current logs contain user id, VDI host, run id, step name? | M3 | You (from samples) | |
| 7 | Rule that marks a run as failed in today's logs. Placeholder in M4: any ERROR/FATAL line or .NET exception header | M3 | Genie team | |
| 8 | In-house .NET namespace prefixes (for marking in-house stack frames). Until set, anything outside `System.`/`Microsoft.` counts as in-house | M3 | Genie team | |
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
| 19 | Can `READ_COMMITTED_SNAPSHOT` be enabled on the copilot database (reduces reader/writer blocking for the job queue)? | P1 | DBA | |
| 20 | tiktoken downloads `cl100k_base` on first use; behind the proxy it fails and we fall back to 4 chars/token. Vendor the file and set `TIKTOKEN_CACHE_DIR`? | M2 | Infra | |
| 21 | Does the gateway expect `max_tokens` or `max_completion_tokens`, and does it accept `temperature`? (M2 sends `max_tokens`, no temperature) | M2 | GenAI platform | |
| 22 | Timezone of timestamps in Genie logs (parser assumes UTC when no offset is written) | M3 | Genie team | |
| 23 | Full list of sensitive identifiers to mask (client ids, internal account formats, Windows `DOMAIN\\user` forms, host naming) | M3 | Security / Genie team | |
