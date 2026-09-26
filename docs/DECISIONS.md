# Decisions

Append-only. Each entry records what we chose, why, and what would change our mind. Where the build context
(CLAUDE.md) and live docs disagree, live docs win, and the difference is logged here.

| ID | Date | Decision | Status |
|---|---|---|---|
| D-001 | 2026-09-26 | Python 3.12 engine; Stage 1 TypeScript app kept as a read-only glass box | Accepted |
| D-002 | 2026-09-26 | No agent frameworks; the rail is the orchestration | Accepted |
| D-003 | 2026-09-26 | Postgres is the only store, including the job queue (`SKIP LOCKED`) | Accepted |
| D-004 | 2026-09-26 | Every connector reports LIVE / FIXTURE / ONE-WAY; LIVE only with credentials and a successful call | Accepted |
| D-005 | 2026-09-26 | Doors never decide: one door contract, one `RunView`, first decision wins | Accepted |
| D-006 | 2026-09-26 | Surfaces: Freshworks base + Slack, Email, Microsoft Teams, Voice; WhatsApp dropped | Accepted |
| D-007 | 2026-09-26 | Email: inbound via the Freshservice mailbox, outbound via Amazon SES; decision links are GET-safe | Accepted |
| D-008 | 2026-09-26 | `mcp` 2.x: use `MCPServer` (brief says `FastMCP`) | Accepted |
| D-009 | 2026-09-26 | Local dev/test database: embedded PostgreSQL 16 (`pgserver`), production: `postgres:16` container | Accepted |
| D-010 | 2026-09-26 | Task-linked, hook-enforced commits; per-section PRs merged without squash | Accepted |
| D-011 | — | Stage 1 policy IDs → the brief's 12 rules | Open (section E) |
| D-012 | — | Teams SDK: Microsoft 365 Agents SDK vs Bot Framework SDK | Open (T240) |

---

## D-001 — Python 3.12 engine; Stage 1 app becomes the glass box
**Context.** Stage 1 is a Next.js/TypeScript Command Center with an in-process engine. Freshworks builds its
agents in Python, the engineer we met prefers Python for agents, and the voice base (`vobiz-ai/Vobiz-Sarvam`)
is Python using `audioop`, which Python 3.13 removed.
**Decision.** New engine in `engine/`, Python 3.12, FastAPI + Pydantic v2. The Stage 1 app stays at the repo
root as an optional read-only view. Its policies, fixtures and adversary cases are ported, not deleted.
**Cost.** Porting is the largest time risk, so the build order puts the fixture-backed 13/2/1 run and the live
Freshservice loop first.
**Revisit if.** The P0 live loop is not working by the end of section I.

## D-002 — No agent frameworks
**Decision.** No LangGraph, CrewAI or AutoGen. Stages are plain async functions called in a fixed order by
`rail/runner.py`.
**Why.** The model must never choose the next stage, decide a verdict, approve or mark anything verified
(CLAUDE.md §0 rule 2). A framework whose value is letting the model route adds exactly the freedom we remove,
and makes "why did this happen" harder to answer from the audit chain.

## D-003 — Postgres only, including the job queue
**Decision.** Runs, actions, approvals, the audit chain, LLM call logs and jobs all live in PostgreSQL 16. Jobs
are claimed with `SELECT … FOR UPDATE SKIP LOCKED`.
**Why.** One store to back up, inspect and reset before a demo; transactional enqueue with the state change
that caused it; no broker to operate on a single EC2 box.
**Revisit if.** Job throughput exceeds hundreds per second, which is not a hackathon problem.

## D-004 — Honest connector modes
**Decision.** Every connector exposes `mode`. LIVE requires configured credentials and a successful call on
that path. Otherwise it is FIXTURE (backed by `fixtures/` with a real `verify()` against fixture state), or
ONE-WAY for the Teams webhook fallback. Every door, card, email, spoken answer and receipt prints the mode.
**Why.** Judges and users must be able to tell a live system of record from a demo fixture. Mislabelling one
destroys trust in everything else.

## D-005 — Doors never decide
**Decision.** Slack, Email, Teams, Voice, the FDK sidebar and MCP call only `surfaces/door.py` (`start_run`,
`get_status`, `answer_query`, `decide`, `pick_candidate`) and render only `presenter.RunView`. The primary key
of `approvals (run_id, action_id)` makes the first decision win. Every other door's message is then updated
from `door_messages`.
**Why.** Five doors that each re-implemented approval logic would eventually disagree about a refusal. One
contract makes "the doors agree" a property that can be tested (`test_doors_agree.py`).

## D-006 — Four doors on top of Freshworks
**Decision.** Freshworks (Freshservice ticket, Workflow Automator, FDK sidebar) is the base. The four doors are
Slack (P0), Email (P0 core), Microsoft Teams (P1) and Voice (P1). WhatsApp is dropped: Business API approval and
template-message rules are a demo risk we cannot control.
**Why.** Freddy AI Agents surface in Slack, Teams, email and the portal. Meeting users there is the product
principle "no UI is the best UI". Voice reaches approvers away from a laptop and non-English speakers.
**Revisit if.** No M365 tenant allows custom apps by section S; Teams then ships as ONE-WAY (webhook card +
signed links), labelled as such.

## D-007 — Email: Freshservice mailbox in, SES out, GET-safe links
**Decision.** Inbound email goes to the Freshservice support mailbox, becomes a ticket (`source=email`) and
triggers the same Workflow Automator webhook as catalog requests. Outbound approval and receipt emails go via
Amazon SES in ap-south-1. Approval links point to `/a/{token}`, an HMAC-signed, expiring token bound to
`run_id|action_id|params_hash|approver|decision`. **GET renders a confirm page only; POST decides.**
**Why.** The mailbox reuses the ticket as the source of truth and needs no inbound mail infrastructure. SES
keeps outbound mail in the same AWS account and region. Corporate mail scanners prefetch every link, so a link
that approved on GET would approve things without a human.
**Alternatives rejected.** SES inbound (more infrastructure, duplicates the ticket); Resend/Postmark (another
vendor outside AWS).

## D-008 — `mcp` 2.x renamed FastMCP to MCPServer
**Found.** Importing `mcp.server.fastmcp` with `mcp==2.2.0` raises: *FastMCP was renamed to MCPServer
(`from mcp.server.mcpserver import MCPServer`)*.
**Decision.** Stay on the current `mcp` 2.x and use `MCPServer`. Where CLAUDE.md §3/§13.4 says "FastMCP", read
"MCPServer". Verify tool, elicitation and Streamable HTTP APIs against the installed 2.x package before T181,
not from memory.

## D-009 — Embedded PostgreSQL for local development and tests
**Context.** Docker Desktop failed to start on the development laptop, and no PostgreSQL is installed.
**Decision.** Dev and test use `pgserver` 0.1.4 (a dev-only dependency) that runs a real PostgreSQL 16.2 in a
temp directory. `SELECT … FOR UPDATE SKIP LOCKED` was confirmed working. Production and compose stay on the
`postgres:16` image.
**Why.** Tests must run against real Postgres semantics (JSONB, `SKIP LOCKED`, unique-constraint races), not a
mock or SQLite.
**Risk.** A minor-version difference from production (16.2 vs latest 16.x) only matters for bug-fix
behaviour.

## D-010 — Commit discipline
**Decision.** Every commit names one checklist task (`[T###]` + `Task:` trailer) and states `Why`, `Verified`
and `Mode`. It is enforced by `.githooks/commit-msg`; `.githooks/pre-commit` blocks secrets. Each checklist
section is one branch and one PR, merged with a merge commit (no squash). `docs/BUILDLOG.md` is generated from
history. Tasks that could not be verified are committed with `Verified: NOT VERIFIED: <reason>` and left
unticked until they are.
**Why.** The judges read the history. A dense, honest, task-linked trail shows how the system was built,
including what failed.
