# ContextRail — Stage 2 build checklist (250 tasks)

Build, integration, UI/UX and connectors only. Tests are required by CLAUDE.md §18 but are not counted here.
Tags: `P0` must work live · `P1` strongly wanted · `P2` only if time remains · 👤 needs a human (accounts, keys, tenants, recordings).
**Finish every P0 across all sections before starting any P1.** Each task is ticked in the commit that completes it (CLAUDE.md §24);
`scripts/buildlog.sh` maps every ticked task to its commits in `docs/BUILDLOG.md`.

<!-- stats:start -->
| Priority | Tasks | Done |
|---|---|---|
| P0 | 148 | 46 |
| P1 | 92 | 0 |
| P2 | 10 | 0 |
| **Total** | **250** | **46** |

👤 human-owned tasks: 24
<!-- stats:end -->

## A. Accounts, keys and local setup (17)

- [x] T001 `P0` 👤 Public GitHub repo `contextrail` (MIT, `main`). Done in Stage 1.
- [ ] T002 `P0` 👤 Freshservice trial tenant; note the domain; least-privilege service agent; copy its API key.
- [ ] T003 `P2` 👤 Freshdesk trial tenant for the refund/reconciliation workflow; copy its API key.
- [ ] T004 `P0` 👤 Enable Freshservice MCP (Admin → MCP → MCP Details); record the `/mcp` URL.
- [ ] T005 `P0` 👤 Slack app from the repo manifest; Socket Mode; scopes `commands`, `chat:write`, `im:write`, `users:read`, `users:read.email`, `assistant:write`.
- [ ] T006 `P0` 👤 Anthropic API keys for member A and member B, each with a spend limit.
- [ ] T007 `P0` 👤 AWS IAM role/user with Bedrock invoke in ap-south-1; model access for Claude Haiku 4.5 and Sonnet 5.
- [ ] T008 `P0` 👤 AWS Budgets alert at $25.
- [ ] T009 `P1` 👤 Sarvam API key.
- [ ] T010 `P1` 👤 Vobiz account; one Indian number; Auth ID + Auth Token.
- [ ] T011 `P2` 👤 Dodo Payments test mode: API key; product "ContextRail governed run" with usage-based price.
- [ ] T012 `P0` 👤 Freshworks Developer Portal API key (Developer MCP / `fw-publish`).
- [ ] T013 `P0` `npx @freshworks/fw-dev-tools install`, then `/fw-setup-install` (FDK 10.x, Node 24.x).
- [ ] T014 `P0` Python 3.12 via uv (not 3.13), Docker and Docker Compose locally.
- [ ] T015 `P0` 👤 Reserve a subdomain (e.g. `cr.<yourdomain>`) for the engine.
- [ ] T016 `P0` 👤 SES in ap-south-1: verify the sender domain (DKIM) and the demo approvers' addresses (sandbox); configuration set for bounces.
- [ ] T017 `P1` 👤 Teams: M365 tenant that allows custom app upload; Entra app registration; Azure Bot (F0) with the Teams channel.

## B. Repository skeleton and commit discipline (19)

- [x] T018 `P0` Folders: `engine/`, `voice/`, `teams/`, `fdk-app/`, `knowledge/`, `fixtures/` (each with a README stating its purpose).
- [x] T019 `P0` `CLAUDE.md` (the build context) at the repo root.
- [x] T020 `P0` `docs/CHECKLIST.md` (this file) with computed totals (`scripts/checklist-stats.sh`).
- [x] T021 `P0` `.githooks/commit-msg`: enforce `<type>(<scope>): … [T###]`, matching `Task:`, `Priority:`, `Why:`, `Verified:`, `Mode:`.
- [x] T022 `P0` `.githooks/pre-commit`: block `.env` files and credential shapes.
- [x] T023 `P0` `.gitmessage` template + `scripts/setup-hooks.sh` (sets `core.hooksPath` and `commit.template`).
- [x] T024 `P0` `.github/pull_request_template.md` for per-section PRs.
- [x] T025 `P0` `scripts/buildlog.sh` generating `docs/BUILDLOG.md` from `git log`.
- [x] T026 `P0` `engine/pyproject.toml` with pinned deps: fastapi, uvicorn, pydantic v2, pydantic-settings, httpx, tenacity, structlog, psycopg[pool], anthropic[bedrock], mcp, slack_bolt, boto3, pyyaml, opentelemetry-sdk.
- [x] T027 `P0` `settings.py` (pydantic-settings) reading every variable in `.env.example`.
- [x] T028 `P0` `main.py`: FastAPI app, `/health`, `/v1` router mount.
- [ ] T029 `P0` Dockerfiles for engine and voice (`python:3.12-slim`).
- [ ] T030 `P0` `docker-compose.yml`: postgres:16, engine, voice, caddy.
- [ ] T031 `P0` `Caddyfile`: engine `/`, `/mcp`, `/slack/*`, `/api/teams/*`, `/a/*`; voice `/voice/*`; automatic TLS.
- [x] T032 `P0` `.env.example` with every key from CLAUDE.md §19.
- [ ] T033 `P0` Makefile targets: `up`, `down`, `migrate`, `seed`, `reset`, `logs`, `fmt`.
- [x] T034 `P0` structlog JSON logging with `run_id`/`channel` context + problem+json error middleware with a request id.
- [ ] T035 `P1` CORS / allowed-origin config for the FDK app origin.
- [x] T036 `P0` `docs/DECISIONS.md`: Python engine, no LangGraph, Postgres job queue, fixtures labelled, doors never decide, Stage 1 kept as glass box.

## C. Database (6)

- [x] T037 `P0` Plain-SQL migration runner (`engine/contextrail/migrations/*.sql`, applied in order, recorded in `schema_migrations`).
- [x] T038 `P0` `0001_core.sql`: `runs`, `actions` (unique `idempotency_key`), `approvals` (PK `(run_id, action_id)`, channel incl. teams/email/voice).
- [x] T039 `P0` `0002_audit_jobs_llm.sql`: `audit` (hash chain), `jobs` (run_at, attempts, locked_until), `llm_calls`.
- [x] T040 `P0` `0003_doors.sql`: `webhook_dedupe`, `identity_map` (slack/teams/email/phone/Freshservice ids, preferred door), `receipts`, `door_messages`.
- [x] T041 `P0` `db.py`: pooled connections + transaction helper.
- [x] T042 `P0` Repository functions: create_run, set_stage, upsert_action, record_approval, append_audit, enqueue_job, claim_job (SKIP LOCKED), upsert_door_message.

## D. Domain models and the sealed case file (10)

- [x] T043 `P0` `Subject` model (source, required source_id, employment_type, role, team, manager, dates, sow_repos).
- [x] T044 `P0` `Evidence` model with `trust`: record / curated / untrusted.
- [x] T045 `P0` `Action` model and state enum.
- [x] T046 `P0` `Verdict` model (ALLOW / HOLD / REFUSE, rule_id, clause_text, approver).
- [x] T047 `P0` `CaseFile` model.
- [x] T048 `P0` Canonical JSON serializer (sorted keys, no whitespace, UTC) + `params_hash(action)`.
- [x] T049 `P0` Capsule seal: compute and store the digest.
- [x] T050 `P0` Capsule verify at every handoff; raise `DigestMismatch`.
- [x] T051 `P0` Idempotency key = sha256(run_id + action_id + params_hash).
- [x] T052 `P0` Run status and stage enums with an allowed-transitions table + `StageEvent` model for SSE and doors.

## E. Policy engine and the 12 rules (20)

- [x] T053 `P0` Rule schema (pydantic): id, title, source, clause_text, applies_to, match, conditions, verdict, approver, terminal, expires_after.
- [x] T054 `P0` Rule loader for `policy/rules/*.yaml` with schema validation at startup.
- [x] T055 `P0` `applies_to` matcher over Subject fields only.
- [x] T056 `P0` `match` matcher over action kind and target (dot paths, list membership).
- [x] T057 `P0` Safe condition evaluator (`in`, `==`, `contains`, `>`, `<`); no `eval`.
- [x] T058 `P0` Precedence: terminal REFUSE > HOLD > explicit ALLOW; default deny for access actions.
- [x] T059 `P0` Approver resolution: role/group → named person (fixture first, Freshservice group later).
- [ ] T060 `P0` Verdict carries `rule_id` and the clause verbatim (clauses ported from `src/lib/contextrail/policy.ts`).
- [x] T061 `P0` POL-CTR-001: contractors never get production credentials (REFUSE, terminal).
- [x] T062 `P0` POL-ACC-001: role baseline entitlements ALLOW.
- [x] T063 `P0` POL-ACC-002: "same as peer" filtered by the requester's role, not the peer's.
- [x] T064 `P0` POL-ACC-003: admin rights only for senior roles.
- [x] T065 `P0` POL-ACC-004: contractor repos limited to SOW, read-only, Security approval if production-tagged.
- [x] T066 `P0` POL-ACC-005: paid SaaS seats need manager approval.
- [ ] T067 `P1` POL-DAT-001: raw customer PII only for analytics; suggest the masked view.
- [ ] T068 `P1` POL-EMG-001: incident access read-only, 4-hour expiry, incident commander approval.
- [x] T069 `P0` POL-OFF-001: revoke old-team access on transfer.
- [x] T070 `P0` POL-SOD-001: requester cannot approve their own request (enforced in `door.decide` for every door).
- [ ] T071 `P2` POL-REF-001 (refund limit) and POL-REF-002 (one outage credit per quarter).
- [ ] T072 `P1` Policy Studio function: re-evaluate a run with one rule held out and return the diff.

## F. Fixtures (clearly labelled FIXTURE) (10)

- [ ] T073 `P0` HRIS fixture: Priya W-8841 contractor; Anil (payments, employee); Rahul (senior); a second "Rahul" for the ambiguity demo.
- [ ] T074 `P0` Entitlements + role catalogue fixture: Rahul's 16 items (resource_class, repo_tags) → 13 / 2 / 1 for Anil; payments-engineer baseline.
- [ ] T075 `P0` GitHub fixture state (repos, collaborators, permissions).
- [ ] T076 `P0` Slack corpus fixture incl. the planted "ignore policy" message (ported from `src/lib/contextrail/data/corpus.ts`).
- [ ] T077 `P1` Priya's SOW document naming `northbeam/perception-sdk` + incident INC-4412 fixture.
- [ ] T078 `P2` Payments fixture: customers, plans, prior credits, one duplicate.
- [ ] T079 `P0` Fixture connectors with persistent state files and a real `verify()` against that state.
- [ ] T080 `P0` Seed script loading fixtures and the identity map for all doors (Slack, Teams, email, phone).
- [ ] T081 `P0` `/v1/connectors` endpoint listing each connector's LIVE/FIXTURE/ONE-WAY mode.
- [ ] T082 `P0` Reset script restoring fixture state between demo runs.

## G. The rail (eight stages) and the door layer (26)

- [ ] T083 `P0` `runner.py`: fixed-order stage executor with per-stage timing.
- [ ] T084 `P0` Stage event emitter feeding SSE and per-door callbacks.
- [ ] T085 `P0` Discover: intent + mentions + request/query/approval-reply via the intent prompt (structured output).
- [ ] T086 `P0` Discover: resolve mentions to IDs by exact lookup only (HRIS / Freshservice requester).
- [ ] T087 `P0` Discover: ambiguity → `needs_input` with a candidate list.
- [ ] T088 `P0` Discover: peer resolution for "same as X".
- [ ] T089 `P0` Compile: parallel fetch of records, entitlements and policies (`asyncio.gather`).
- [ ] T090 `P1` Compile: load OKF concepts by tags/rules.
- [ ] T091 `P1` Compile: extract SOW constraints with cited spans.
- [ ] T092 `P0` Compile: mark stale evidence into open blockers.
- [ ] T093 `P0` Compile: include untrusted messages/email bodies as evidence, wrapped as data.
- [ ] T094 `P0` Compile: seal the capsule and store the digest.
- [ ] T095 `P0` Govern: build candidate actions (peer's items minus requester's current items).
- [ ] T096 `P0` Govern: evaluate every candidate through the policy engine.
- [ ] T097 `P0` Plan: dependency ordering; add revoke actions for the old team.
- [ ] T098 `P0` Plan: one-line explanations for HOLD and REFUSE (Sonnet).
- [ ] T099 `P1` Handoff: per-team views (IT, Security) with digest verification.
- [ ] T100 `P0` Approve: create approval records; dispatch to Freshservice and the approver's doors.
- [ ] T101 `P1` Approve: deadline and chase jobs (chase in the approver's preferred door).
- [ ] T102 `P0` Approve: resume the run when a decision arrives from any door.
- [ ] T103 `P0` Execute: connector dispatch with idempotency key and backoff on 429/5xx.
- [ ] T104 `P0` Execute: unknown outcome → reconcile before any retry.
- [ ] T105 `P0` Verify: read back each action; set verified or failed.
- [ ] T106 `P0` Finalize: status partial/done; trigger receipt generation.
- [ ] T107 `P0` `surfaces/door.py`: start_run, get_status, answer_query, decide (identity map, SoD, params_hash, first-wins, mirror to Freshservice), pick_candidate.
- [ ] T108 `P0` `surfaces/presenter.py`: `RunView` (lamps, clause, approver, deadline, precedent, modes, replay flag) + cross-door message update.

## H. LLM router and prompts (13)

- [ ] T109 `P0` Router config from env (tiers, model IDs, budgets).
- [ ] T110 `P0` Tier 1 and Tier 2 `Anthropic` clients.
- [ ] T111 `P0` Tier 3 `AnthropicBedrock` client (ap-south-1, global inference IDs).
- [ ] T112 `P0` Tier 4 replay store: record and replay modes keyed by prompt hash; responses flagged `replay=true`.
- [ ] T113 `P0` Failover classifier: 429, 529, 5xx, timeout, credit-exhausted (no failover on other 400s).
- [ ] T114 `P0` Per-tier circuit breaker (180 s).
- [ ] T115 `P0` Cost calculator per model; write every call to `llm_calls`.
- [ ] T116 `P0` Per-run budget enforcement.
- [ ] T117 `P0` Structured-output helper: pydantic model → tool schema → validated object.
- [ ] T118 `P1` Prompt caching on the system prompt and policy text.
- [ ] T119 `P0` Prompts `intent.md`, `explain_verdict.md`, `approval_card.md` (cites capsule fields only).
- [ ] T120 `P1` Prompt `extract_constraints.md`.
- [ ] T121 `P1` Prompts `team_brief.md`, `mismatch_explain.md`, `audit_answer.md` (receipts only, cites audit seq numbers).

## I. Freshservice (the base) and Workflow Automator (17)

- [ ] T122 `P0` REST client: basic auth, base URL, timeouts, keep-alive.
- [ ] T123 `P0` Token-bucket rate limiter (default 80 calls/min).
- [ ] T124 `P0` GET ticket (incl. `source`), GET requester by ID, GET agent by ID and by email.
- [ ] T125 `P0` List service catalog items; store the Access Request item ID.
- [ ] T126 `P0` POST approval on a ticket + read approval state (approvals list or activities).
- [ ] T127 `P0` POST private note (receipt).
- [ ] T128 `P1` Receipts custom object in admin; POST receipt records.
- [ ] T129 `P1` GET Solutions article (policy source for OKF ingest).
- [ ] T130 `P2` GET/PUT asset (laptop assignment for onboarding).
- [ ] T131 `P1` Catalog place_request (tickets for Slack/Teams/voice-originated requests).
- [ ] T132 `P0` `/v1/webhooks/freshservice` with HMAC signature check.
- [ ] T133 `P0` Webhook dedupe by ticket ID; respond 202 immediately.
- [ ] T134 `P0` 👤 Catalog item "Access request (ContextRail)" with fields: request text, requested-for.
- [ ] T135 `P0` 👤 Workflow Automator: ticket raised → item is Access request → Web Request to the engine.
- [ ] T136 `P0` Check Workflow Automator execution logs; fix the `{{ticket.id_numeric}}` payload.
- [ ] T137 `P1` Freshservice MCP client for exploratory reads, wrapped as a read-only tool.
- [ ] T138 `P0` LIVE flag per call path; labelled fixture fallback if a tenant call fails.

## J. Slack door (18)

- [ ] T139 `P0` Slack app manifest YAML in the repo (scopes, slash command, interactivity, assistant).
- [ ] T140 `P0` Bolt app init (Socket Mode in dev, HTTP in prod).
- [ ] T141 `P0` `/contextrail <request>` → `door.start_run`; ephemeral acknowledgement.
- [ ] T142 `P0` Run status message updated in place per stage (`chat.update`).
- [ ] T143 `P1` Assistant pane: thread started → suggested prompts.
- [ ] T144 `P1` Assistant pane: user message → start run; `set_status` per stage.
- [ ] T145 `P1` Assistant pane: final summary blocks (granted / held / refused) with receipt link.
- [ ] T146 `P0` Approval card Block Kit renderer from `RunView` (action, rule, risk, precedent, deadline, LIVE/FIXTURE).
- [ ] T147 `P0` Deliver the card to the approver's DM (`users.lookupByEmail`); record in `door_messages`.
- [ ] T148 `P0` Approve / Refuse handlers parsing `run_id|action_id|params_hash` → `door.decide`.
- [ ] T149 `P0` On click: params_hash still matches and approver identity via the identity map.
- [ ] T150 `P0` Update the card after a decision, including decisions made in another door.
- [ ] T151 `P1` "Why refused?" button → explanation with clause.
- [ ] T152 `P1` Refuse-with-reason modal (`views.open`).
- [ ] T153 `P0` Seed identity map for demo Slack users.
- [ ] T154 `P0` Friendly `needs_input` message with candidate buttons.
- [ ] T155 `P0` Candidate picker handler resumes the run with the chosen ID.
- [ ] T156 `P1` Copy and design pass: consistent verbs, lamps (✅ 🟠 ⛔), short sentences.

## K. Freshworks FDK app (ticket sidebar) (13)

- [ ] T157 `P1` Scaffold with `/fw-app-dev`: Platform 3.0, `service_ticket`, `ticket_sidebar`.
- [ ] T158 `P1` `manifest.json`: modules, location, engines (Node 24, FDK 10), request templates registered.
- [ ] T159 `P1` `iparams.json`: engine_url, engine_token (secure).
- [ ] T160 `P1` `config/requests.json`: getRunByTicket, startRun, getReceipt.
- [ ] T161 `P1` `app.js` client init (`client.data.get('ticket')`) + Crayons layout: header, run status pill, LIVE/FIXTURE badge.
- [ ] T162 `P1` Rows: ALLOW (verified tick), HOLD (approver + deadline), REFUSE (struck through + clause).
- [ ] T163 `P1` Empty state with "Run ContextRail on this ticket" button.
- [ ] T164 `P1` Poll every 3 s while running; stop on final state.
- [ ] T165 `P1` Receipt modal via interface method + error and timeout states.
- [ ] T166 `P1` `server/server.js`: `onTicketCreate` backup trigger calling startRun.
- [ ] T167 `P1` `fdk validate` clean (`/fdk-fix`) + `/fw-review` blocking findings fixed.
- [ ] T168 `P1` 👤 `fdk pack`; install as a custom app on the trial tenant.
- [ ] T169 `P1` Visual polish using Crayons tokens; spacing and dark mode.

## L. Knowledge layer (OKF + LLM wiki) (11)

- [ ] T170 `P1` `knowledge/SCHEMA.md`: frontmatter conventions and ingest/lint rules.
- [ ] T171 `P1` Root and per-folder `index.md`.
- [ ] T172 `P1` `log.md` with ISO-dated entries.
- [ ] T173 `P1` `policies/contractor-onboarding.md` + `policies/access-control-standard.md`, linked to their rules.
- [ ] T174 `P1` `roles/payments-engineer.md` + `systems/github.md` + `systems/freshservice.md`.
- [ ] T175 `P1` `precedents/github-readonly-contractors.md` + `runbooks/emergency-access.md`.
- [ ] T176 `P1` OKF loader: frontmatter parser + link graph.
- [ ] T177 `P1` Query by tags/rules for Compile and `door.answer_query`.
- [ ] T178 `P2` Ingest: Solutions article → `raw/` copy → drafted page update in `drafts/`.
- [ ] T179 `P1` Lint: contradictions, stale pages, broken links, orphans; report without overwriting.
- [ ] T180 `P2` Precedent updater after each run + draft Solutions article for publish-back.

## M. MCP server and Agent Skills (13)

- [ ] T181 `P1` FastMCP server mounted at `/mcp` (Streamable HTTP) with bearer auth.
- [ ] T182 `P1` Tool `search_enterprise_knowledge`.
- [ ] T183 `P1` Tool `compile_context_capsule` returning a capsule handle (run_id + digest).
- [ ] T184 `P1` Tool `check_policy_and_permissions`.
- [ ] T185 `P1` Tool `generate_action_plan`.
- [ ] T186 `P1` Tool `handoff_to_specialist`.
- [ ] T187 `P1` Tool `execute_and_verify` (refuses without approvals).
- [ ] T188 `P1` Tool `list_runs`.
- [ ] T189 `P1` Elicitation for an ambiguous subject, with `needs_input` fallback.
- [ ] T190 `P1` Tool descriptions and annotations (read-only vs destructive hints).
- [ ] T191 `P1` `skills/contextrail-discover` and `-compile` SKILL.md + references + examples.
- [ ] T192 `P1` `skills/contextrail-govern`, `-handoff`, `-execute` SKILL.md + references + examples.
- [ ] T193 `P1` Claude Code `.mcp.json` snippet + install steps in the README; package skills (zip) and check frontmatter against the Agent Skills format.

## N. Voice door (Vobiz × Sarvam, inbound conversational) (12)

- [ ] T194 `P1` Copy `vobiz-ai/Vobiz-Sarvam` into `voice/` with attribution (pinned commit from `refs/MANIFEST.md`).
- [ ] T195 `P1` Replace the OpenAI call with the engine router (Haiku) for conversation only.
- [ ] T196 `P1` `engine_client.py` wrapping the door contract (start_run, get_status, answer_query, decide).
- [ ] T197 `P1` Intent routing: new request / status / policy question / approve.
- [ ] T198 `P1` AI-disclosure opening line in each supported language.
- [ ] T199 `P1` Language config (`hi-IN` default; `en-IN`, `ta-IN`, `kn-IN`) with a speaker per language.
- [ ] T200 `P1` Caller ID → `identity_map.phone` (registered numbers only; unknown callers get policy Q&A only).
- [ ] T201 `P1` Request flow: listen → read the request back → start the run → speak the ticket number.
- [ ] T202 `P1` Query flow: speak only verified receipt facts and curated OKF answers.
- [ ] T203 `P1` Approver flow: list pending items → spoken confirm → DTMF 1/2; high-risk items also need a Slack/Teams tap.
- [ ] T204 `P1` Transfer-to-human fallback.
- [ ] T205 `P1` 👤 Vobiz application: Answer URL → `https://<host>/voice/answer`; attach the number; record a backup call.

## O. Dodo Payments (3)

- [ ] T206 `P2` Dodo client in test mode + usage event per completed run (idempotent by run_id) + pilot checkout link.
- [ ] T207 `P2` Refund reconciliation intent + fixtures; refund via the Dodo test API with read-back; payment webhook with signature check.
- [ ] T208 `P2` Reconciliation receipt note + finance approver card in Slack.

## P. Audit, receipts and glass box (8)

- [ ] T209 `P0` Audit append with hash chaining.
- [ ] T210 `P0` Receipt builder: short summary + full JSON.
- [ ] T211 `P0` Write the receipt to Freshservice (note; custom object when ready).
- [ ] T212 `P0` SSE endpoint `/v1/runs/{id}/events`.
- [ ] T213 `P1` OpenTelemetry spans for stages, LLM calls and connector calls.
- [ ] T214 `P1` `/v1/metrics` (runs, verdict counts, time-to-access, LLM cost by tier, decisions per door).
- [ ] T215 `P1` Read-only receipt page `/r/{run_id}` (printable).
- [ ] T216 `P1` Adversary console endpoints: forged approval, stripped constraint, promoted subject, replayed write, "ignore policy".

## Q. Deployment, polish and submission (10)

- [ ] T217 `P0` 👤 EC2 t3.large in ap-south-1; security group 443 open, 22 restricted; Elastic IP.
- [ ] T218 `P0` Install Docker; deploy compose; load env from SSM Parameter Store.
- [ ] T219 `P0` 👤 DNS A record; confirm Caddy TLS.
- [ ] T220 `P0` Point Workflow Automator, Slack request URLs, the Teams messaging endpoint, the Vobiz Answer URL, FDK iparams and SES links at the public host.
- [ ] T221 `P0` Warm-up script: seed, reset fixtures, record replay outputs for the demo script.
- [ ] T222 `P0` README: 10-second line, architecture, sponsors, the five doors, LIVE vs FIXTURE table, run steps, how to read the commit trail.
- [ ] T223 `P0` Devpost description incl. the Stage 1 → Stage 2 evolution and the doors.
- [ ] T224 `P0` Slide assets: Slack card, email confirm page, Teams card, ticket sidebar, receipt, MCP verdict in Claude Code.
- [ ] T225 `P0` 👤 Backup demo video (60–90 s).
- [ ] T226 `P0` Final label audit: every door shows LIVE/FIXTURE/ONE-WAY correctly; remove "98 min" and "four workflows".

## R. Email door (Freshservice mailbox in, SES out) (12)

- [ ] T227 `P0` 👤 Freshservice support mailbox configured (forwarding from the demo address).
- [ ] T228 `P0` Workflow Automator condition for email-sourced tickets → same Web Request; webhook reads ticket `source`.
- [ ] T229 `P0` Discover classifies email as request / query / approval-reply; body wrapped as untrusted.
- [ ] T230 `P0` SES connector (boto3 sesv2, ap-south-1); idempotent send keyed by (run_id, action_id, "email").
- [ ] T231 `P0` Approval email (HTML + plain text) rendered from `RunView` with the LIVE/FIXTURE label.
- [ ] T232 `P0` Signed decision links: HMAC token; `GET /a/{token}` renders a confirm page only; `POST` decides.
- [ ] T233 `P0` Email decisions go through `door.decide` → mirrored to Freshservice and every other door.
- [ ] T234 `P0` Requester acknowledgement via Freshservice ticket reply (verify the endpoint).
- [ ] T235 `P1` Receipt email to the requester on finalize.
- [ ] T236 `P1` Status/query emails answered only from receipts, citing audit seq numbers.
- [ ] T237 `P1` SES bounce/complaint SNS handler (`/v1/webhooks/ses`, signature verified).
- [ ] T238 `P1` Copy pass: same verbs and lamps as Slack; plain-text version readable on phones.

## S. Microsoft Teams door (12)

- [ ] T239 `P1` Teams app manifest + icons in `teams/`.
- [ ] T240 `P1` Choose the SDK (Microsoft 365 Agents SDK vs Bot Framework) from current docs; record it in DECISIONS.md.
- [ ] T241 `P1` `/api/teams/messages` endpoint with Bot Framework JWT validation.
- [ ] T242 `P1` Message → `door.start_run(channel="teams")`.
- [ ] T243 `P1` Proactive status card per run, updated in place per stage.
- [ ] T244 `P1` Adaptive Card approval rendered from `RunView`.
- [ ] T245 `P1` `Action.Execute` handler: params_hash + AAD identity via identity map → `door.decide`.
- [ ] T246 `P1` Refresh the card after a decision, including decisions from other doors.
- [ ] T247 `P1` `needs_input` candidate-picker card.
- [ ] T248 `P1` Query answering in Teams ("why was X refused?") via `door.answer_query`.
- [ ] T249 `P1` `ONE-WAY` fallback: Workflows incoming webhook card + signed decision links.
- [ ] T250 `P1` 👤 Sideload the app into the tenant; set the Azure Bot messaging endpoint to the public host.
