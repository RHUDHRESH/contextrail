# CONTEXTRAIL — MASTER BUILD CONTEXT (for Claude Code)

> This is the project brief for Stage 2. Work through `docs/CHECKLIST.md` (250 tasks, T001–T250) in the order of §20.
> Do not skip acceptance checks. When a fact here conflicts with live docs, the live docs win: note the difference in `docs/DECISIONS.md`.
> **Every commit follows §24.** The judges read the commit history.

---

## 0. RULES FOR THE BUILDER (read first)

1. **Priority is P0 → P1 → P2.** Never start P1 work while a P0 acceptance check fails.
2. **Code decides; the model reads and writes.** The LLM must never decide *who* the subject is, *whether* an action is allowed, *approve* anything, or mark anything *verified*.
3. **Never invent API fields.** For every Freshworks/Slack/Teams/SES/Sarvam/Vobiz/Dodo call, check the official docs or the cloned sample first (`../refs/`, pinned in `../refs/MANIFEST.md`). If unsure, write a fixture adapter and label it `FIXTURE`.
4. **Honest labels.** Every connector exposes `mode: "LIVE" | "FIXTURE"`. UI, cards, emails, voice and receipts print it. A one-way Teams fallback is labelled `ONE-WAY`.
5. **Idempotency everywhere.** Every external write carries an idempotency key derived from `(run_id, action_id)`.
6. **Small, typed, tested.** Pydantic v2 models at every boundary. `pytest` for every rule and every stage.
7. **No agent frameworks** (no LangGraph, CrewAI, AutoGen). The rail *is* the orchestration. Explain in `docs/DECISIONS.md` if asked.
8. **Secrets** come only from environment variables: loaded from AWS SSM/Secrets Manager in production, `.env` locally. Never in the FDK front end, never in logs, never in commits (the `.githooks/pre-commit` scan enforces this).
9. **Commit per task** in the §24 format. Tick the task's box in `docs/CHECKLIST.md` in the same commit.

---

## 1. PRODUCT IN ONE PARAGRAPH

ContextRail is a **business process automation system, powered by AI**. A person (or another AI agent) asks for something in one sentence: *"give Anil the same access as Rahul"*, *"Priya starts Monday, give her everything she needs"*, *"credit the customers hit by last night's outage"*. ContextRail then:

1. fetches the subject **by ID** from the system of record;
2. compiles one **sealed case file**;
3. applies **written policy** to every possible action: allow, hold for a named human, or refuse with the clause quoted;
4. gets approvals where required;
5. executes through the real systems and **reads back** to verify;
6. leaves a **tamper-evident receipt** on the Freshservice ticket.

It lives where users already work. **Freshworks is the base**: the Freshservice ticket is the source of truth. On top of it there are **four doors**: **Slack**, **Email**, **Microsoft Teams** and **Voice** (the phone). It exposes itself to other agents via an **MCP server** and **Agent Skills**, and it keeps its knowledge in an **OKF bundle** maintained with the **LLM-wiki** method.

**Track:** Great Agent Hackathon, Track 2: *Platform Agent Skills & Knowledge* (reusable skills, MCP integrations, Freshworks developer platform).

**Stage 1 → Stage 2.** Stage 1 (commits `052685c`…`c403373`) is the Next.js/TypeScript Command Center at the repo root (`src/`, `mcp/`, `skills/`). Stage 2 adds the Python engine in `engine/` and the real doors. The Stage 1 app stays as an optional read-only **glass box**. Its policies, fixtures and adversary cases are ported, not deleted.

### Use cases (what the demo proves)
1. **Access requests**: "Same access as Rahul" → 13 granted and verified, 2 held for named approvers, 1 refused with the clause cited, old-team access revoked.
2. **Onboarding**: "Priya starts Monday": contractor identified from the HR record, SOW repo read-only with Security approval, production credentials refused under Contractor Onboarding Policy §4.
3. **Refunds / service credits**: outage credits within limits issued, large ones held for Finance, the duplicate declined, and every refund read back from the payment system.

### Non-negotiable principles (these are the product)
| # | Principle | Enforced where |
|---|---|---|
| P1 | **Relevance is not identity**: subjects are fetched by ID, never chosen by search | `rail/discover.py` |
| P2 | **Rules decide, not the model**: policy is deterministic code over records | `policy/engine.py` |
| P3 | **A 200 is not done**: every write is read back; `succeeded` ≠ `verified` | `rail/verify.py` |
| P4 | **Refusals survive every hop**: refused actions stay in the plan, struck through, terminal | `models.Action.state` |
| P5 | **One sealed case file**: passed by value, SHA-256 digest checked at every hop | `rail/capsule.py` |
| P6 | **Retrieved text is data, never instructions**: it can enter the capsule and still change nothing | `policy/engine.py` + tests |
| P7 | **Everything leaves a receipt**: append-only, hash-chained audit | `audit/chain.py` |
| P8 | **No UI is the best UI**: Freshservice + Slack + Email + Teams + phone; the web view is a glass box, not the product | `surfaces/` |
| P9 | **The doors agree**: every door renders the same `RunView`; no door decides anything | `surfaces/door.py`, `surfaces/presenter.py` |

---

## 2. DEMO SCOPE AND ACCEPTANCE

### P0 — must work live
| ID | Feature | Acceptance check |
|---|---|---|
| P0-1 | Freshservice trigger → run | Raising a catalog request fires Workflow Automator → `POST /v1/webhooks/freshservice` → run visible in DB within 3 s |
| P0-2 | Discover by ID | `GET /api/v2/requesters/{id}` (LIVE) returns the requester; run stores `subject.source_id` |
| P0-3 | "Same as Rahul" access run (fixture entitlements OK) | 16 items → 13 ALLOW, 2 HOLD, 1 REFUSE with clause text |
| P0-4 | Native approval | `POST /api/v2/tickets/{id}/approvals` (LIVE) for HOLD items; approval state persisted |
| P0-5 | Slack approval card | Block Kit card with the exact action, rule, risk; Approve/Refuse buttons bound to `(run_id, action_id, params_hash)` |
| P0-6 | Execute + verify | ALLOW items executed (fixture connectors) with idempotency; each read back → `verified=true` |
| P0-7 | Receipt on ticket | `POST /api/v2/tickets/{id}/notes` (LIVE) with the receipt summary; re-fetch confirms it exists |
| P0-8 | Injection test | Planted "ignore policy" Slack message is retrieved into evidence AND the REFUSE still holds (test asserts both) |
| P0-9 | LLM router | Tier1 → Tier2 → Bedrock → Replay; tier logged per call |
| P0-10 | Email door | Email to the Freshservice support address → ticket → run; HOLD approver receives an SES email; GET on the signed link changes nothing, POST decides; decision mirrors to Freshservice and Slack |

### P1 — strongly wanted
| ID | Feature |
|---|---|
| P1-1 | OKF knowledge bundle + `lint` catching a planted contradiction |
| P1-2 | MCP server (7 tools) + 5 SKILL.md packs; Claude Code gives the **same verdict** as the Slack card |
| P1-3 | Voice: an inbound call (Hindi or English) can create a request, ask status, ask a policy question, and let a registered approver decide a pending item |
| P1-4 | FDK sidebar app showing ALLOW / HOLD / REFUSE rows + receipt |
| P1-5 | Slack AI-assistant pane with streamed stage status |
| P1-6 | MCP elicitation ("employee or contractor?") when the subject is ambiguous |
| P1-7 | Teams door: bot starts runs, streams status, Adaptive Card approvals bound to `params_hash` (fallback: `ONE-WAY` Workflows webhook + signed links) |

### P2 — only if time remains
Dodo usage billing + refund reconciliation run · precedent-aware approval cards · A2A agent card · onboarding and refund workflows on the same rail · web glass-box view.

---

## 3. TECH STACK (ranked to match how Freshworks builds)

**Evidence on Freshworks' own stack:** core products run on Ruby on Rails with Java, Python and Go services, React front ends, MySQL, Redis and Kafka on AWS (job postings, engineering blog). Marketplace apps run on **FDK (Node)**. The official agentic toolkit targets **Platform 3.0, FDK 10.x, Node 24.x, Crayons 4.x**. Freddy AI Agents surface in **Slack, Microsoft Teams, email and the portal**, which is why those are our doors. The engineer we met prefers **Python for agents**.

| Rank | Layer | Choice (pin these) | Why |
|---|---|---|---|
| 1 | Agent engine | **Python 3.12**, FastAPI, Pydantic v2, httpx, tenacity, structlog | Freshworks' AI/agent preference; typed boundaries. **3.12, not 3.13**: the voice clone uses `audioop` (removed in 3.13). Local interpreter: `D:\AIWorkspace\Python\cpython-3.12-windows-x86_64-none\python.exe` via `uv` |
| 2 | Freshworks app | **FDK 10.x, Node 24.x, Platform 3.0, Crayons 4.x**, `service_ticket` module | Mandatory for in-product apps; matches `fw-dev-tools` |
| 3 | Models | `anthropic` Python SDK (`Anthropic` + `AnthropicBedrock`): **Claude Haiku 4.5 only** (D-013) | Same Messages API across direct and Bedrock tiers; one key, $20 Bedrock cap |
| 4 | MCP | `mcp` Python SDK (`FastMCP`) as server; `mcp` client for Freshservice MCP | Track 2 "MCP integrations" |
| 5 | Chat doors | `slack_bolt` (Python), Socket Mode for dev, HTTP mode in prod · Teams via the Microsoft 365 Agents SDK or Bot Framework SDK for Python (**verify which is current before coding**; record in DECISIONS.md) | "Meet users where they live" |
| 6 | Email door | Inbound: Freshservice support mailbox → ticket. Outbound: **Amazon SES** (`boto3`, ap-south-1) | Same AWS account/region; SES is supported in ap-south-1 |
| 7 | Voice | Clone of `vobiz-ai/Vobiz-Sarvam` (FastAPI + WebSocket), Sarvam Saaras v3 STT + Bulbul v3 TTS | Official Vobiz × Sarvam pattern |
| 8 | Database | **PostgreSQL 16** (runs, actions, audit, jobs); JSONB for capsules | One store; `SELECT … FOR UPDATE SKIP LOCKED` job queue, no extra broker |
| 9 | Hosting | **AWS ap-south-1**: one EC2 (t3.large) with Docker Compose + Caddy (HTTPS) | No cold starts on stage |
| 10 | Observability | OpenTelemetry (GenAI semantic conventions) → console/CloudWatch; structlog JSON | Glass-box traces |
| 11 | Payments | Dodo Payments Python SDK (`dodopayments`; verify the package name) | Usage billing + reconciliation |
| 12 | Knowledge | OKF v0.1 bundle in `knowledge/` (Markdown + YAML frontmatter) | Google Cloud open format for agent knowledge |
| 13 | Optional web glass box | Stage 1 Next.js Command Center at repo root, reading the Python API (read-only) | Keep only if already working |

---

## 4. REPOSITORY LAYOUT

```
contextrail/
├─ CLAUDE.md                     # this file
├─ .githooks/ commit-msg pre-commit   # §24 enforcement (enable: scripts/setup-hooks.sh)
├─ .gitmessage                   # commit template
├─ .github/pull_request_template.md
├─ docker-compose.yml  Caddyfile  Makefile  .env.example
├─ docs/
│  ├─ CHECKLIST.md               # the 250 tasks — ticked in the commit that does them
│  ├─ BUILDLOG.md                # generated by scripts/buildlog.sh from git log
│  ├─ DECISIONS.md  DEMO.md  API.md
├─ scripts/  setup-hooks.sh  buildlog.sh  checklist-stats.sh
├─ src/ mcp/ public/             # Stage 1 Next.js glass box (read-only view of the engine)
├─ engine/                       # Python 3.12 service  (port 8000)
│  ├─ pyproject.toml
│  ├─ contextrail/migrations/0001_core.sql 0002_audit_jobs_llm.sql 0003_doors.sql  # shipped inside the package
│  ├─ contextrail/
│  │  ├─ main.py  settings.py  models.py  db.py  jobs.py  telemetry.py
│  │  ├─ rail/        runner discover compile govern plan handoff approve execute verify capsule
│  │  ├─ policy/      engine.py  rules/*.yaml
│  │  ├─ knowledge/   OKF reader, ingest, query, lint (§10)
│  │  ├─ llm/         router.py  prompts/*.md  schemas.py
│  │  ├─ connectors/  base freshservice freshservice_mcp freshdesk ses slack github hris entitlements dodo
│  │  ├─ surfaces/
│  │  │  ├─ door.py              # the door contract every surface calls (§13.0)
│  │  │  ├─ presenter.py         # RunView — the one view every door renders
│  │  │  ├─ slack_app.py  email.py  teams.py  mcp_server.py  webhooks.py  decision_page.py
│  │  └─ audit/chain.py
│  └─ tests/
├─ voice/                        # Python 3.12 service (port 8100), clone of Vobiz-Sarvam
├─ teams/                        # Teams app manifest + icons
├─ fdk-app/                      # FDK 10 / Node 24 / Platform 3.0 app
├─ skills/                       # Agent Skills packs (SKILL.md)
├─ knowledge/                    # OKF bundle (§10)
└─ fixtures/                     # HRIS, entitlements, Slack corpus, GitHub, incident data
```

---

## 5. ARCHITECTURE

```
 USERS & AGENTS (no new UI)
 ┌────────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────┐
 │Freshservice│ │ Slack    │ │ Email        │ │ Teams    │ │ Phone     │ │ Other agents │
 │ catalog,   │ │ /cmd,    │ │ support@ →   │ │ bot +    │ │ Vobiz no. │ │ Claude Code, │
 │ ticket,    │ │ assistant│ │ FS ticket;   │ │ Adaptive │ │ → voice   │ │ Freddy, any  │
 │ FDK sidebar│ │ cards    │ │ SES approvals│ │ Cards    │ │ (Sarvam)  │ │ MCP client   │
 └─────┬──────┘ └────┬─────┘ └──────┬───────┘ └────┬─────┘ └─────┬─────┘ └──────┬───────┘
       │ Workflow    │ Bolt          │ (via FS)      │ Bot msgs    │ HTTPS        │ MCP
       ▼ Automator   ▼               ▼               ▼             ▼              ▼
 ┌──────────────────────────────────────────────────────────────────────────────────────┐
 │ ENGINE (FastAPI, Python 3.12)       surfaces/door.py  ←  every door calls only this  │
 │  webhooks ─▶ jobs (Postgres SKIP LOCKED) ─▶ rail runner                              │
 │   Discover → Compile → Govern → Plan → Handoff → Approve → Execute → Verify          │
 │  LLM router (T1/T2/Bedrock/Replay) · Policy engine (YAML) · OKF knowledge            │
 │  Connectors (LIVE/FIXTURE): Freshservice REST+MCP, SES, Slack, GitHub, HRIS, Dodo    │
 │  presenter.RunView → Block Kit | Adaptive Card | email HTML | voice script | sidebar │
 │  audit chain + receipts · OpenTelemetry                                              │
 └──────────────────────────────────────────────────────────────────────────────────────┘
       │ notes, approvals, replies, custom-object receipts       │ usage events, refunds
       ▼                                                          ▼
  Freshservice ticket (source of truth)                      Dodo Payments
```

**Boundaries**
- The voice service, Slack app, Teams bot and email handlers **never decide**. They call `door.py`.
- The FDK app **never holds secrets**. It calls the engine through FDK request templates.
- The engine is the **only** writer to external systems.

---

## 6. DATA MODEL (PostgreSQL)

```sql
create table runs (
  id uuid primary key,
  source text not null,              -- 'freshservice'|'slack'|'email'|'teams'|'voice'|'mcp'
  source_ref text,                   -- ticket id, slack ts, teams conversation id, call id
  request_text text not null,
  intent text,                       -- 'access.same_as_peer' | 'onboarding' | 'refund.outage' | 'query' | ...
  subject_id text,                   -- system-of-record ID (never a name)
  status text not null,              -- 'running'|'needs_input'|'awaiting_approval'|'partial'|'done'|'failed'
  capsule jsonb, capsule_digest text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);
create table actions (
  id text not null, run_id uuid references runs(id),
  kind text not null,                -- 'grant'|'revoke'|'assign_asset'|'refund'|...
  target jsonb not null, params_hash text not null,
  verdict text not null,             -- 'ALLOW'|'HOLD'|'REFUSE'
  rule_id text, clause text, approver text,
  state text not null,               -- 'planned'|'awaiting'|'approved'|'refused'|'executed'|'verified'|'failed'|'unknown'
  idempotency_key text unique, evidence jsonb, verified_at timestamptz,
  primary key (run_id, id)
);
create table approvals (             -- PK means first decision wins across all doors
  run_id uuid, action_id text, params_hash text,
  approver text, decision text, reason text,
  channel text,                      -- 'slack'|'teams'|'email'|'voice'|'freshservice'
  decided_at timestamptz, primary key (run_id, action_id)
);
create table audit (seq bigserial primary key, run_id uuid, event text, payload jsonb,
  prev_hash text, hash text not null, at timestamptz default now());
create table jobs (id bigserial primary key, kind text, payload jsonb, run_at timestamptz default now(),
  attempts int default 0, locked_until timestamptz, done boolean default false);
create table llm_calls (id bigserial primary key, run_id uuid, stage text, model text, tier text,
  input_tokens int, output_tokens int, cost_usd numeric(10,6), latency_ms int, at timestamptz default now());
create table webhook_dedupe (source text, external_id text, received_at timestamptz default now(),
  primary key (source, external_id));
create table identity_map (person_id text primary key, display_name text, email text unique,
  slack_user_id text unique, teams_aad_id text unique, phone text unique,
  fs_agent_id text, fs_requester_id text, preferred_door text);
create table receipts (run_id uuid primary key, fs_note_id text, fs_record_id text, summary text, body jsonb);
create table door_messages (          -- where each card/email/message lives, so decisions update every door
  run_id uuid, action_id text, channel text, ref jsonb, primary key (run_id, action_id, channel));
```

**Audit hash:** `hash = sha256(prev_hash || canonical_json(event, payload, at))`. The first row has `prev_hash = "GENESIS"`.

---

## 7. DOMAIN MODELS (Pydantic v2 — `models.py`)

```python
class Subject(BaseModel):
    source: Literal["freshservice","hris","freshdesk"]
    source_id: str                 # REQUIRED; never derived from search
    display_name: str
    employment_type: Literal["employee","contractor","vendor","customer"]
    role: str | None; team: str | None; manager_id: str | None
    start_date: date | None; end_date: date | None
    sow_repos: list[str] = []

class Evidence(BaseModel):
    id: str; kind: Literal["record","policy","document","message","precedent"]
    source: str; uri: str; excerpt: str
    retrieved_at: datetime; last_verified: date | None
    stale: bool = False
    trust: Literal["record","curated","untrusted"]   # messages/documents are 'untrusted'

class Action(BaseModel):
    id: str; kind: str; target: dict; params_hash: str
    verdict: Literal["ALLOW","HOLD","REFUSE"] | None = None
    rule_id: str | None = None; clause: str | None = None; approver: str | None = None
    state: str = "planned"; expires_at: datetime | None = None

class CaseFile(BaseModel):          # the sealed capsule
    run_id: UUID; request_text: str; intent: str
    subject: Subject; peer: Subject | None = None
    evidence: list[Evidence]; constraints: list[str]
    actions: list[Action]; decisions: list[dict]; open_blockers: list[str]
    digest: str | None = None
```

---

## 8. THE RAIL — STAGE CONTRACTS

| Stage | Input → Output | AI does | Code does | Failure behaviour |
|---|---|---|---|---|
| **Discover** | request → `Subject`(+peer) | Haiku: intent + *mentions* (names/IDs/dates) as JSON; also classifies request / query / approval-reply for email and voice | Resolve mentions to IDs via Freshservice/HRIS **exact** lookup; if ambiguous → **elicit** (P1-6) or ask in the originating door | No ID → run status `needs_input`; never guess |
| **Compile** | Subject → CaseFile | Haiku: extract constraints from contracts/policies with cited spans | Fetch records in parallel (`asyncio.gather`), load OKF concepts, mark `stale`, seal digest | Missing policy → blocker, not assumption |
| **Govern** | CaseFile → verdicts | Nothing (Haiku may *explain* after) | `policy/engine.py` evaluates each action against rules using **Subject fields only**; untrusted evidence is never read by rules | Unknown action kind → REFUSE (default deny for access) |
| **Plan** | verdicts → ordered plan | Haiku: 1-line explanation per HOLD/REFUSE | Dependency order; REFUSE kept visible | — |
| **Handoff** | plan → per-team views | Haiku: team brief from capsule | Pass capsule **by value**; receiving stage re-computes digest and rejects mismatch | Digest mismatch → halt + audit event |
| **Approve** | HOLD actions → decisions | Haiku: approval card text (cites capsule fields only) | Freshservice approval + card/email in the approver's preferred door (+ Slack); bind to `params_hash`; deadline job; separation of duties | Changed params → approval void |
| **Execute** | ALLOW/approved → results | Nothing | Connector call with idempotency key; backoff on 429/5xx; `unknown` on timeout → reconcile before retry | Never blind-retry an unknown outcome |
| **Verify** | results → verified | Nothing (Haiku may explain mismatch) | Read back target state; compare to intended; set `verified_at` | Mismatch → `failed`, alert |

**Runner:** stages are plain async functions called in fixed order by `rail/runner.py`. The model never chooses the next stage. Each stage writes an audit event and emits a `StageEvent` to SSE (`/v1/runs/{id}/events`) and to the originating door (Slack status, Teams card update, and so on).

---

## 9. POLICY ENGINE

### YAML rule format (`policy/rules/*.yaml`)
```yaml
id: POL-CTR-001
title: Contractors never receive production credentials
source: {okf: knowledge/policies/contractor-onboarding.md, clause: "§4"}
clause_text: "Contractors and vendors must not be issued production credentials or production administrator rights."
applies_to: {employment_type: [contractor, vendor]}
match: {kind: grant, target.resource_class: [production_credential, production_admin]}
verdict: REFUSE
terminal: true
```
```yaml
id: POL-ACC-004
title: Repository access for contractors limited to SOW repos, read-only, Security approval if production-tagged
applies_to: {employment_type: [contractor]}
match: {kind: grant, target.system: github}
conditions:
  - target.repo in subject.sow_repos
  - target.permission == "read"
verdict_if_all: {verdict: HOLD, approver: "security-oncall", when: "target.repo_tags contains production"}
else_verdict: REFUSE
```

### Evaluation semantics
1. Collect all rules whose `applies_to` matches the **Subject record** and whose `match` matches the action.
2. Any `REFUSE` with `terminal: true` → REFUSE (cannot be approved, cannot be overridden).
3. Else any HOLD → HOLD with the most senior named approver.
4. Else ALLOW **only if at least one rule explicitly allows**. Access actions with no matching rule → REFUSE (default deny).
5. The verdict records `rule_id` and `clause_text` verbatim.

### Required rules (12). Port the Stage 1 TypeScript ones in `src/lib/contextrail/policy.ts`; these are the minimum shapes.
POL-CTR-001 contractor prod creds (REFUSE) · POL-ACC-001 role baseline allow · POL-ACC-002 "same as peer" filtered by the **requester's** role, not the peer's · POL-ACC-003 admin rights require senior role · POL-ACC-004 contractor repos (above) · POL-ACC-005 manager approval for paid SaaS seats · POL-DAT-001 raw customer PII only for analytics team; offer masked view · POL-EMG-001 incident access read-only, time-boxed 4 h, incident commander approval · POL-OFF-001 old-team access revoked on transfer · POL-SOD-001 requester cannot approve own request · POL-REF-001 refund ≤ limit auto, > limit finance approval · POL-REF-002 one outage credit per customer per quarter.

Stage 1 uses additional IDs (POL-CTR-002…005, POL-ACC-010, POL-ONB-020, POL-REF-003, POL-FIN-004). Reconcile them into the 12 above, or keep them as extras, and record the mapping in `docs/DECISIONS.md`.

---

## 10. KNOWLEDGE LAYER — OKF + LLM WIKI (Track 2 core)

**Standard:** Open Knowledge Format v0.1 (Google Cloud, June 2026). It is a directory of Markdown files with YAML frontmatter, one concept per file, and only `type` is required. `index.md` (lists a directory) and `log.md` (dated change history) are reserved names, and relationships are standard Markdown links. **Method:** Karpathy's LLM wiki: immutable `raw/`, model-maintained pages, a schema file, and three operations: **ingest, query, lint**.

### Bundle layout and example
```
knowledge/
  SCHEMA.md  index.md  log.md
  raw/                 # immutable copies of source docs (Freshservice Solutions articles, SOWs, Slack exports)
  policies/contractor-onboarding.md
  roles/payments-engineer.md
  systems/github.md
  precedents/github-readonly-contractors.md
  runbooks/emergency-access.md
```
```markdown
---
type: Policy
title: Contractor Onboarding Policy
description: What contractors and vendors may receive, and who approves.
resource: freshservice://solutions/articles/50001234
tags: [access, contractors, security]
last_verified: 2026-09-20
owner: security@acme.example
rules: [POL-CTR-001, POL-ACC-004]
---
## §4 Production access
Contractors and vendors must not be issued production credentials ...
See [GitHub](../systems/github.md) and [precedent](../precedents/github-readonly-contractors.md).
```

### Operations (`contextrail/knowledge/`)
| Op | Trigger | What it does | Guardrail |
|---|---|---|---|
| **ingest** | Freshservice Solutions article created/updated (poll or webhook) | Copy to `raw/`; Haiku drafts/updates only the affected concept pages; append `log.md` | Writes go to `drafts/`; a human (or a CI check) promotes |
| **query** | Compile stage; door queries | Load concepts by `rules:`/`tags:` links (no vector DB at this size); attach as `Evidence(kind="policy", trust="curated")` | Only curated pages feed rule references |
| **lint** | Nightly + on demand | Contradictions, stale `last_verified`, broken links, orphan pages, rules without source clauses | **Never overwrites**: records both claims with dates, flags for review |
| **precedent** | After every run | Update `precedents/*.md` counts (approved/refused), link to receipts | Counts only from the audit chain |
| **publish-back** | When lint/precedent finds something new | Draft a **Freshservice Solutions article** for human approval | Draft only |

---

## 11. LLM LAYER

### Router (`llm/router.py`)
| Tier | Client | Models |
|---|---|---|
| T1 | `Anthropic(api_key=ANTHROPIC_KEY_A)` | `claude-haiku-4-5-20251001` (the only model, D-013) |
| T2 | `Anthropic(api_key=ANTHROPIC_KEY_B)` | same (skipped while no key B exists) |
| T3 | `AnthropicBedrock(aws_region="ap-south-1")` | `global.anthropic.claude-haiku-4-5-20251001-v1:0` only |
| T4 | Replay | Recorded outputs for the demo script only; response carries `replay=true` and every door shows it |

- **Fail over** on 429 (after one retry-after wait), 529, 5xx, timeouts, and credit-exhausted errors. **Do not** fail over on other 400s.
- **Circuit breaker:** skip a failed tier for 180 s.
- **Budgets:** per-run cap (default $0.50); Bedrock cap **$20** in code; AWS Budgets alerts at 40/70/90% of $50, credits excluded (D-013).
- **Log** every call to `llm_calls` with tier, tokens, cost and latency.

### Call discipline
- **Structured output via tool use** with a Pydantic-generated JSON schema; keep `max_tokens` small (≤ 800 for Haiku calls).
- **Prompt caching** on the system prompt + OKF policy text (`cache_control: {"type": "ephemeral"}`).
- **Temperature:** 0 for extraction, 0.3 for card prose.
- **Untrusted text** (messages, documents, inbound email bodies, voice transcripts) is wrapped in `<untrusted source="...">…</untrusted>`, and the system prompt states it is data only. Rules never read it.

### Prompts (`llm/prompts/`)
`intent.md` (intent + mentions + request/query/approval-reply) · `extract_constraints.md` · `explain_verdict.md` · `approval_card.md` · `team_brief.md` · `mismatch_explain.md` · `audit_answer.md` (answers only from receipts, cites seq numbers).

---

## 12. CONNECTORS

`base.py`:
```python
class Connector(Protocol):
    mode: Literal["LIVE","FIXTURE"]
    async def read(self, ref: dict) -> dict: ...
    async def write(self, action: Action, idem_key: str) -> dict: ...
    async def verify(self, action: Action) -> tuple[bool, dict]: ...
```

### Freshservice REST v2 (LIVE). Verify each path at api.freshservice.com before use.
| Purpose | Call |
|---|---|
| Ticket | `GET /api/v2/tickets/{id}` (`source` field distinguishes email-created tickets) |
| Requester by ID | `GET /api/v2/requesters/{id}` |
| Agent by ID | `GET /api/v2/agents/{id}` |
| Create approval | `POST /api/v2/tickets/{id}/approvals` (`approver_id`, `approval_type`, optional `email_content`) |
| Approval status | `GET /api/v2/tickets/{id}/approvals` or `GET /api/v2/tickets/{id}/activities` |
| Private note (receipt) | `POST /api/v2/tickets/{id}/notes` |
| Reply to requester (email door) | `POST /api/v2/tickets/{id}/reply` (verify) |
| Assets | `GET/PUT /api/v2/assets/{display_id}` |
| Catalog | `GET /api/v2/service_catalog/items`, `POST /api/v2/service_catalog/items/{id}/place_request` |
| Solutions (policies) | `GET /api/v2/solutions/articles/{id}` |
| Custom object receipts | `POST /api/v2/objects/{object_id}/records` |

Auth is Basic (API key as username, `X` as password) over the plain `*.freshservice.com` domain. **Rate limits are account-wide** (100–500/min by plan): use a token bucket (default 80/min) and cache reads within a run.

### Freshservice MCP (read/explore): `https://{domain}.freshservice.com/mcp`
It uses OAuth 2.0 with dynamic client registration, or an API key. Use it for Claude-driven exploration. **Writes that must not fail stay on REST.** MCP inherits the connecting account's permissions and adds no authorization layer, so use a least-privilege service account.

### Amazon SES (LIVE, outbound only)
`boto3` `sesv2.send_email` in `ap-south-1` from a verified domain identity. While the account is in the SES sandbox, recipients must be verified identities (the demo approvers). Every send is idempotent on `(run_id, action_id, "email")` via `door_messages`. Bounces and complaints arrive via SNS → `/v1/webhooks/ses`.

### Fixture connectors (clearly labelled)
`hris.py` (W-8841 Priya contractor; Anil; Rahul; a second Rahul), `entitlements.py` (Rahul's 16 items with `resource_class`, `repo_tags`), `github.py`, `slack.py` (corpus incl. the planted injection message), `incidents.py`, `payments.py`. Each implements `verify()` against its fixture state, so read-back is real within the fixture.

---

## 13. SURFACES (the doors)

### 13.0 The door contract — `surfaces/door.py` + `surfaces/presenter.py`
Every door is thin. It may only call:

| Function | Purpose |
|---|---|
| `start_run(text, actor, channel, source_ref)` | New request → rail |
| `get_status(ref)` | Status by run id, ticket id or actor |
| `answer_query(question, actor)` | Answers **only** from receipts + curated OKF, citing audit seq numbers |
| `decide(run_id, action_id, params_hash, actor, decision, reason, channel)` | Approval decision |
| `pick_candidate(run_id, mention, source_id)` | Resolve `needs_input` |

Each door renders one `RunView` (from `presenter.py`): the lamps ✅ ALLOW / 🟠 HOLD / ⛔ REFUSE, the clause, the approver, the deadline, precedent counts, the connector modes (LIVE/FIXTURE/ONE-WAY) and the replay flag.

`decide()`:
1. Resolves the actor through `identity_map`.
2. Applies POL-SOD-001.
3. Checks that `params_hash` still matches.
4. Inserts into `approvals`. The primary key means the first decision wins.
5. Mirrors the decision to the Freshservice approval.
6. Updates every door message in `door_messages` ("Decided by Anil in Teams at 14:02").

### 13.1 Slack — `surfaces/slack_app.py`
- **Slash command** `/contextrail <request>` → `start_run(channel="slack")`.
- **AI assistant pane** (Bolt `Assistant` middleware): stream stage status with `set_status("Compiling case file…")`; post the final summary; offer suggested prompts ("Same access as…", "Onboard…", "Why was this refused?").
- **Approval card** (Block Kit), posted to the approver's DM:
```json
{"blocks":[
 {"type":"header","text":{"type":"plain_text","text":"Approval needed · GitHub read-only"}},
 {"type":"section","text":{"type":"mrkdwn","text":"*Anil Kumar* (employee, payments) · requested via *same as Rahul*\n*Action:* read access to `northbeam/perception-sdk`\n*Rule:* POL-ACC-004 — production-tagged repo requires Security approval\n*Precedent:* approved 12× before, refused 0×\n*Deadline:* today 17:00 IST"}},
 {"type":"context","elements":[{"type":"mrkdwn","text":"Run RUN-24081 · case digest 9f3a…e1 · connectors: GitHub FIXTURE"}]},
 {"type":"actions","elements":[
   {"type":"button","style":"primary","text":{"type":"plain_text","text":"Approve"},"action_id":"approve","value":"<run_id>|<action_id>|<params_hash>"},
   {"type":"button","style":"danger","text":{"type":"plain_text","text":"Refuse"},"action_id":"refuse","value":"<run_id>|<action_id>|<params_hash>"}]}]}
```
Handler → `door.decide(...)`.

### 13.2 Freshservice (the base)
- **Workflow Automator:** Event *Ticket is Raised* → Condition *Category/Item = Access Request* **or** *Source = Email and mailbox = support* → **Web Request** `POST https://<host>/v1/webhooks/freshservice` with `{ "ticket_id": {{ticket.id_numeric}} }`, header `X-ContextRail-Signature` (shared secret). The engine responds 202 immediately and dedupes by ticket id (webhooks retry up to 4×).
- **FDK app** (`fdk-app/`; scaffold with `npx @freshworks/fw-dev-tools install`, then `/fw-app-dev`):
  - `manifest.json`: `platform-version: "3.0"`, module `service_ticket`, location `ticket_sidebar`, events `onTicketCreate` (backup trigger), request templates in `modules.common.requests`.
  - `config/requests.json`: `getRun` → `GET https://<host>/v1/runs/by-ticket/<%= context.ticket_id %>` with header `Authorization: Bearer <%= iparam.engine_token %>`; `startRun` → `POST /v1/runs`.
  - Sidebar (Crayons): rows for `ALLOW` (green, "verified" tick), `HOLD` (amber, approver + deadline) and `REFUSE` (red, struck through, clause quoted), plus a "View receipt" link.
  - Validate with `fdk validate`; review with `/fw-review`.
- **Receipt:** a private note (short) + a custom object record (full JSON) + the audit seq range.

### 13.3 Voice — `voice/` (clone of `vobiz-ai/Vobiz-Sarvam`)
The clone is a FastAPI app with endpoints `/answer`, `/ws`, `/stream-status`, `/hangup` and `/health`. It runs Saaras v3 STT → **LLM** → Bulbul v3 TTS, mu-law 8 kHz, with the language set by `AGENT_LANGUAGE` (`hi-IN`, `en-IN`, `ta-IN`, …). It uses `audioop` (Python 3.12) and currently calls OpenAI (`agent.py:24`, `:188`).

**Inbound conversational agent.** You call the number and talk to it:
1. Replace the OpenAI call with the engine's router (Claude Haiku) for **conversation only**.
2. `engine_client.py` wraps the door contract: `start_run`, `get_status`, `answer_query`, `decide`.
3. **Intent routing:** *new request* ("give Anil the same access as Rahul") · *status* ("what happened to my request?") · *policy question* ("can contractors get production access?") · *approve* (for registered approvers).
4. **Caller ID** → `identity_map.phone`; registered numbers only. Unknown callers can ask general policy questions only.
5. **Request flow:** read the request back, confirm, start the run, then speak the ticket number.
6. **Query flow:** speak only verified receipt facts and curated OKF answers, never model guesses.
7. **Approver flow:** list pending items, confirm by speech, then capture **DTMF 1 = approve / 2 = refuse**. High-risk items (terminal-adjacent, production-tagged) also need a tap in Slack or Teams.
8. The first sentence always discloses AI, in every language (`hi-IN` default, `en-IN`, `ta-IN`, `kn-IN`). There is a transfer-to-human fallback.

### 13.4 MCP server — `surfaces/mcp_server.py` (FastMCP, Streamable HTTP at `/mcp`)
| Tool | Input | Output |
|---|---|---|
| `search_enterprise_knowledge` | query, tags | OKF concepts (curated) + evidence refs |
| `compile_context_capsule` | request_text, subject_id? | `capsule_handle` = `{run_id, digest}` |
| `check_policy_and_permissions` | capsule_handle | verdict table (ALLOW/HOLD/REFUSE + clauses) |
| `generate_action_plan` | capsule_handle | ordered plan |
| `handoff_to_specialist` | capsule_handle, team | team brief (capsule by value, digest) |
| `execute_and_verify` | capsule_handle, action_ids | results with `verified` flags (requires approvals) |
| `list_runs` | filters | runs |

**Capsule handle:** tools are stateless; state is carried by an explicit handle (`run_id` + `digest`), and every tool re-checks the digest.
**Elicitation (X-factor):** if Discover finds two matching people, the tool asks the calling client to choose (MCP elicitation) instead of guessing. If the client doesn't support elicitation, it returns `needs_input` with candidates.

### 13.5 Skills — `skills/*/SKILL.md` (Agent Skills format; mirror the `fw-dev-tools/skills/*` layout)
```markdown
---
name: contextrail-govern
description: Check whether each proposed action for a subject is allowed, needs a named approver, or is refused, with the policy clause quoted. Use before granting access, issuing refunds or changing entitlements.
---
# Govern with ContextRail
1. Call `compile_context_capsule` with the user's request (never pass a name as the subject; pass an ID or let the tool resolve it).
2. Call `check_policy_and_permissions` with the returned handle.
3. Report ALLOW / HOLD (with approver) / REFUSE (with clause) exactly as returned. Never reinterpret a REFUSE.
4. Do not execute anything; hand off to `contextrail-execute` only after approvals exist.
```
There are five packs: discover, compile, govern, handoff, execute. Each has `references/` (tool schemas) and `examples/` (the "same as Rahul" transcript). Stage 1 already has the five SKILL.md files; update them to the Python MCP tools.

### 13.6 Email — `surfaces/email.py`, `surfaces/decision_page.py`, `connectors/ses.py`
- **Inbound** uses the **Freshservice support mailbox**: an email becomes a ticket with `source=email`. The same Workflow Automator Web Request fires, and Discover classifies the email as *request*, *query* ("status of my access request?") or *approval-reply*. The email body is **untrusted** text.
- **Requester acknowledgement:** a Freshservice ticket **reply**, so the thread stays in their inbox and on the ticket.
- **Approval email** (SES) is rendered from `RunView` (HTML + plain text) with the LIVE/FIXTURE label and two buttons linking to `/a/{token}`.
  - **Token** = base64url(payload) + HMAC-SHA256 over `run_id|action_id|params_hash|approver|decision|exp`, using the `DECISION_LINK_SECRET` key. It expires at the action deadline.
  - **GET `/a/{token}` only renders a confirm page.** **POST** calls `door.decide(channel="email")`. Corporate link scanners prefetch every URL, so a GET that decided would auto-approve.
  - A tampered token, an expired token, a changed `params_hash` or an actor mismatch is rejected and audited.
- **Receipt email** goes to the requester on finalize (P1). **Status/query replies** come only from receipts (P1).

### 13.7 Microsoft Teams — `surfaces/teams.py`, `teams/manifest.json`
- **Setup:** an Entra app registration, an Azure Bot resource (F0) with the Teams channel, and a Teams app manifest sideloaded into an M365 tenant that allows custom app upload.
- **SDK:** check whether the **Microsoft 365 Agents SDK for Python** or the Bot Framework SDK is current and supported **before coding**, and record the choice in DECISIONS.md.
- **Messaging endpoint:** `/api/teams/messages`, which validates the Bot Framework JWT.
- **Message** → `start_run(channel="teams")`. There is one proactive status card per run, updated in place per stage.
- **Approval** is an Adaptive Card rendered from `RunView`. `Action.Execute` data = `{run_id, action_id, params_hash, decision}`. The handler resolves the AAD object id through `identity_map` and calls `door.decide`, and the card refreshes to show the outcome.
- `needs_input` becomes a candidate-picker card. Queries ("why was X refused?") go to `answer_query`.
- **Fallback** (no tenant or bot): a Teams **Workflows incoming webhook** posts the card one-way, with signed `/a/{token}` links for decisions, labelled `ONE-WAY`.

---

## 14. DODO PAYMENTS — BILLING AND RECONCILIATION (P2)

1. **Usage billing:** after each completed run, send a usage event (`event_name: "contextrail.governed_run"`, `idempotency: run_id`, metadata: action count). The pilot checkout link runs in **test mode**.
2. **Refund reconciliation workflow** (same rail, finance domain), intent `refund.reconcile`:
   - Discover: customers by account ID.
   - Compile: Freshdesk tickets promising credits + Dodo payment records.
   - Govern: POL-REF-001/002.
   - Execute: issue the refund via the Dodo API (test mode).
   - **Verify: read the refund status back from Dodo.**
   - Receipt: a Freshdesk note.
   - Mismatches (promised but not paid, paid twice) become blockers.

Verify the SDK package name and the refund/usage endpoints in Dodo's docs before coding.

---

## 15. AGENTIC X-FACTOR (state-of-the-art features to show)

| # | Feature | What judges see | Build |
|---|---|---|---|
| X1 | **Ask-back instead of guessing (MCP elicitation)** | "Two people named Rahul — which one?" appears in Claude Code/Slack/Teams; run continues after the answer | §13.4 |
| X2 | **Stateless tools, stateful capsule** | Same capsule handle flows Claude Code → MCP → Slack → Freshservice; digest verified at each hop | §13.4 |
| X3 | **Slack AI assistant pane with live stage status** | Request typed in Slack's side panel; status streams "Discovering… Govern: 1 refused…" | §13.1 |
| X4 | **Self-improving knowledge, human-gated** | After a run, a precedent page updates; lint flags a contradiction; a draft Solutions article appears for approval | §10 |
| X5 | **Precedent-aware approvals** | Card shows "approved 12×, refused 0×"; Policy Studio suggests an auto-approve rule for a human to accept | §10 + §13.1 |
| X6 | **Five doors agree** | Slack = Email = Teams = Voice = MCP = FDK sidebar verdict (integration test); a decision in one door updates the others | §13.0 |
| X7 | **Glass-box trace** | OpenTelemetry GenAI spans: stage → model call (tier, tokens, cost) → connector call → verify | §17 |
| X8 | **Adversary console** | Five live attacks (forged approval, stripped constraint, promoted subject, replayed write, "ignore policy") all held | §18 |
| X9 | **Multilingual voice with the same rail** | Hindi call → request / status / approval → same verdicts | §13.3 |
| X10 (opt.) | **A2A agent card** | `/.well-known/agent.json` describing ContextRail's skills | P2 |

---

## 16. SECURITY

- **Webhooks:** HMAC signature header; reject replays (timestamp ± 5 min, nonce table).
- **Slack:** verify the signing secret. **Teams:** validate the Bot Framework JWT. **Email links:** HMAC tokens, GET-safe, expiring. **Voice:** registered caller IDs only; high-risk approvals also need a tap in a chat door.
- Map every door identity through `identity_map` before accepting a decision.
- **Separation of duties:** requester ≠ approver.
- Least-privilege Freshservice service account. API keys in SSM; rotate after the event.
- **PII:** capsule field allow-lists per team (Security never sees salary); redact phone numbers and email addresses in logs.
- **Retrieved text** (messages, inbound email bodies, voice transcripts) is `trust="untrusted"`, never read by rules, and always wrapped as data in prompts.

---

## 17. OBSERVABILITY

- `structlog` JSON logs with `run_id`, `stage`, `action_id`, `channel`.
- OpenTelemetry spans per stage, per LLM call (GenAI attributes: model, tokens) and per connector call.
- `GET /v1/runs/{id}/events` (SSE) for the glass-box view.
- `GET /v1/metrics`: runs, verdict counts, median time-to-access, LLM cost by tier, and decisions per door.

---

## 18. TESTS AND EVALS (pytest)

| Test | Asserts |
|---|---|
| `test_policy_rules.py` | Each of the 12 rules: allow/hold/refuse cases, clause text present |
| `test_same_as_peer.py` | Rahul's 16 items → 13/2/1 for Anil |
| `test_injection_both_halves.py` | Planted message **is** in capsule evidence **and** REFUSE holds |
| `test_paraphrase_identity.py` | "new contract engineer starting next week" → `needs_input` or correct ID, never a wrong subject |
| `test_idempotency.py` | Replayed webhook/Slack/Teams/email action → exactly one write |
| `test_approval_binding.py` | Changing target params voids approval |
| `test_decision_link.py` | GET changes nothing; tampered/expired token rejected; POST decides once |
| `test_verify_not_success.py` | Connector returns 200 but state absent → `failed`, not `verified` |
| `test_capsule_digest.py` | Tampered capsule rejected at handoff |
| `test_doors_agree.py` | MCP == REST == Slack blocks == Teams card == email HTML == voice script data |
| `test_router_failover.py` | T1 429 → T2; T2 credit error → T3; non-credit 400 → no failover |
| `test_audit_chain.py` | Editing one audit row breaks all later hashes |
| `test_knowledge_lint.py` | Planted contradiction flagged, both claims preserved |
| `evals/requests.yaml` | ≥ 30 labelled requests → intent/subject accuracy report (print the real number) |

---

## 19. DEPLOYMENT

`docker-compose.yml` services: `postgres:16`, `engine` (8000), `voice` (8100), `caddy` (443). Caddy routes engine `/`, `/mcp`, `/slack/*`, `/api/teams/*`, `/a/*`; voice `/voice/*`. The host is one EC2 t3.large, Ubuntu, ap-south-1, with an Elastic IP and a DNS A record; Caddy obtains TLS automatically.

`.env.example`:
```
DATABASE_URL=postgresql://cr:cr@postgres:5432/cr
PUBLIC_URL=https://contextrail.example.com
ENGINE_TOKEN=change-me
DECISION_LINK_SECRET=change-me
FS_DOMAIN=yourtenant.freshservice.com
FS_API_KEY=
FS_WEBHOOK_SECRET=
FD_DOMAIN=yourtenant.freshdesk.com
FD_API_KEY=
ANTHROPIC_KEY_A=
ANTHROPIC_KEY_B=
AWS_REGION=ap-south-1
BEDROCK_HAIKU_ID=global.anthropic.claude-haiku-4-5-20251001-v1:0
BEDROCK_SONNET_ID=
BEDROCK_BUDGET_USD=20
SES_FROM_ADDRESS=contextrail@yourdomain.example
SES_CONFIGURATION_SET=
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
SLACK_APP_TOKEN=            # socket mode (dev)
TEAMS_APP_ID=
TEAMS_APP_PASSWORD=
TEAMS_TENANT_ID=
TEAMS_WORKFLOW_WEBHOOK_URL= # ONE-WAY fallback
SARVAM_API_KEY=
AGENT_LANGUAGE=hi-IN
TTS_SPEAKER=anand
VOBIZ_AUTH_ID=
VOBIZ_AUTH_TOKEN=
DODO_API_KEY=               # test mode
RUN_BUDGET_USD=0.50
```

---

## 20. BUILD ORDER (with checkpoints)

Follow `docs/CHECKLIST.md`. **Every P0 in every section comes before any P1.**

1. **B: Skeleton + commit discipline.** Hooks and templates come first, so every later commit is checked. ✔ `docker compose up` green; bad commit messages rejected.
2. **C → D → E → F → G → H** (fixture-backed). ✔ `test_policy_rules`, `test_same_as_peer` and the injection test pass; the same-as-Rahul run completes 13/2/1 end to end; `test_router_failover` passes; `llm_calls` is populated.
3. **I: Freshservice LIVE loop.** Workflow Automator → webhook → `GET requester` → create approval → note → re-fetch. ✔ P0-1/2/4/7 on the trial tenant.
4. **J: Slack P0.** Slash command + approval card + resume. ✔ P0-5; `test_approval_binding`.
5. **R: Email P0.** ✔ P0-10; `test_decision_link`.
6. **P: Audit chain + receipts.** ✔ `test_audit_chain`.
7. **Q: Deploy to EC2** and re-run steps 3–5 against the public URL.
8. **P1:** S Teams → N Voice → K FDK sidebar → L OKF + lint → M MCP server + skills (`test_doors_agree`) → assistant pane → elicitation.
9. **P2:** O Dodo usage + reconciliation → precedent cards → A2A card.
10. **Freeze:** record the backup video of the full demo, tag the release, write the README (problem, 10-second line, architecture, sponsors, the five doors, the LIVE vs FIXTURE table, how to run, and how to read the commit trail).

---

## 21. DEMO SCRIPT (3 minutes) + FALLBACKS

1. Slack assistant pane: *"Give Anil the same access as Rahul."* Status streams through the stages.
2. Result: 13 granted (verified), 2 held (manager/Security), 1 refused (production admin, clause quoted).
3. The manager approves one HOLD **from the email** (confirm page → POST); the Security approver taps **Approve** in **Teams**; the Slack card updates itself to show who decided where.
4. Freshservice ticket: sidebar rows + receipt note.
5. Attack: the planted "ignore policy" message is retrieved and still refused.
6. Phone: a Hindi call asks "what happened to Anil's request?" and hears only the verified receipt.
7. Claude Code with our skill: same question → same verdict (the doors agree).
8. Close: *"Right action. Right person. Proven."*

**Fallbacks:** replay tier (labelled), recorded video, hotspot, pre-seeded tickets, Teams `ONE-WAY` mode.

---

## 22. CLONE LIST

All of these are cloned (shallow) in `../refs/` with pinned commits in `../refs/MANIFEST.md`. Copy patterns; don't merge them wholesale.

- **Most used:** `freshworks-developers/fw-dev-tools` (Agent Skills + Developer MCP; Platform 3.0, FDK 10.x, Node 24.x, Crayons 4.x) · `vobiz-ai/Vobiz-Sarvam` (voice base) · `matthewlboyd/freshservice-mcp` · `slack-samples/deno-request-time-off` (approval-card pattern) · `freshworks-developers/say-hello`, `superstack`, `serverless-app-samples`, `request-method-samples` · `sarvamai/sarvam-ai-cookbook` · `agentskills/agentskills`, `anthropics/skills` (SKILL.md format).
- **Stale (2022), for patterns only:** `freshworks-oss/fresh-samples`, `freshworks/freshworks-api-sdk`.
- The TypeScript SDK clones (`bolt-js`, `anthropic-sdk-typescript`, `dodopayments-typescript`, MCP `typescript-sdk`) are references for API shapes; the engine uses the Python equivalents.

---

## 23. DO NOT

- Port the rail into LangGraph/CrewAI, or let a model choose the next stage.
- Let any model output set a verdict, an approval or `verified`.
- Let any door decide anything: doors call `door.py` only.
- Approve on an HTTP GET.
- Label anything LIVE that isn't.
- Claim a "time saved" number or accuracy you didn't measure.
- Build an ElevenLabs stack, a second web dashboard, a WhatsApp door, or a Journeys-style phase designer.
- Use Lambda for the demo path.
- Squash, rebase-rewrite or force-push shared history.

---

## 24. COMMIT RULES (judges read the history)

**One checklist task gives one or more commits. Never bundle two tasks. Never go more than about 45 minutes without a commit. Commit at every green step.**

```
<type>(<scope>): <imperative summary> [T063]

Why: the problem or principle (cite CLAUDE.md §)
What:
- concrete change
Verified: exact command + observed result  (or "NOT VERIFIED: <reason>")
Mode: LIVE | FIXTURE | n/a

Task: T063
Priority: P0
Refs: CLAUDE.md §9, docs/CHECKLIST.md
```

- **types:** `feat fix refactor docs chore build ci perf test`.
- **scopes:** `repo engine policy rail db models fixtures llm fs slack email teams voice fdk mcp skills okf audit deploy dodo`.
- `.githooks/commit-msg` enforces the header, the matching `Task:` trailer, `Priority:`, `Why:`, `Verified:` and `Mode:`. `.githooks/pre-commit` blocks `.env` files and credential shapes. Run `scripts/setup-hooks.sh` once per clone.
- **Tick the task** (`- [ ]` → `- [x]`) in `docs/CHECKLIST.md` in the same commit.
- **Branch per section** (`sec/B-skeleton`, `sec/E-policy`, `sec/R-email`, …). At the end of the section: push, then open a PR using `.github/pull_request_template.md` (ticked tasks, verification output, screenshots). **Merge with a merge commit, never squash.**
- **Milestone tags:** `stage2-p0-skeleton`, `stage2-p0-rail`, `stage2-p0-live-loop`, `stage2-p0-doors`, `stage2-p1-complete`, `stage2-demo-freeze`.
- `scripts/buildlog.sh` regenerates `docs/BUILDLOG.md` (task → commits → date) from `git log`. Never hand-edit it.
- **Honesty:** a commit never claims LIVE or verified for something that was not observed.

---

## 25. AGENTIC CORE — MEMORY, RAG, TOOLS, CAPABILITIES (section T, D-014)

| Pillar | What it is here | Guardrail |
|---|---|---|
| **Memory** | *Working*: the sealed case file per run. *Episodic*: precedents computed from the audit chain (approved/refused counts per rule + entitlement), shown on approval cards (X5). *Semantic*: the OKF bundle. *Conversational*: bounded per-door thread memory so "why was that refused?" resolves to the right run | Memory is evidence, never instruction; conversational memory is PII-redacted and expires; counts come only from the audit chain |
| **RAG** | OKF pages and receipts chunked and indexed in Postgres full-text search; hybrid retrieval (lexical rank + `rules:`/`tags:` links); Haiku writes answers only from retrieved chunks, citing chunk ids and audit seq numbers | No supporting chunk → "not in the knowledge base"; untrusted text is fenced; retrieval never feeds policy |
| **Tools** | A bounded read-only tool-use loop (Haiku) for questions: search_knowledge, run_status, my_runs, precedent; the same capabilities exposed to other agents as MCP tools (§13.4) | Step limit + per-question cost cap; tools are read-only, and approve/execute stay behind door.decide and the rail |
| **Capabilities** | Skills (§13.5), MCP tools, doors and connector modes, published at `GET /v1/capabilities` and `/.well-known/agent.json`, generated from code | The manifest is built from the registry and rules, so it cannot claim what is not built |
