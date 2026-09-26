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
| D-011 | 2026-09-26 | Stage 1 policy IDs → the brief's 12 rules; rule-format refinements | Accepted |
| D-012 | — | Teams SDK: Microsoft 365 Agents SDK vs Bot Framework SDK | Open (T240) |
| D-015 | 2026-09-26 | Freshservice approvals: the API cannot approve or reject, so decisions are mirrored as ticket notes | Accepted |
| D-016 | — | Freshservice webhook: Workflow Automator cannot sign an HMAC; a signing hop or a weaker scheme | Open |
| D-017 | 2026-09-26 | Freshservice assets: classic `/assets/{display_id}` built; newer (ITAM) tenants document no user assignment | Accepted |

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

## D-011 — Reconciling the Stage 1 policies with the brief's 12 rules
**Context.** Stage 1 (`src/lib/contextrail/policy.ts`) had 12 TypeScript policies with different ids and
scopes from the 12 rules the brief requires (CLAUDE.md §9).

**Rule format refinements** (the brief gives "minimum shapes"):
- `escalate: {when, verdict, approver}` raises a rule's ALLOW to HOLD, for example when the repository is tagged
  production. `else_verdict` fires when a condition fails. Conditions can nest `{any: [...]}` and
  `{all: [...]}`. This replaces the brief's `verdict_if_all` sketch with an equivalent that is testable.
- Precedence: **any** REFUSE wins, with terminal refusals chosen first. The brief left non-terminal refusals
  unspecified; treating them as weaker than a HOLD would let an approval override a written refusal, which
  contradicts P4. `terminal` records "no approval path exists" and blocks Policy Studio exceptions.
- Nothing fires → `DEFAULT-DENY` for every action, not only access actions. Stage 1 had the same stance:
  "nothing in the rail executes without a matching allow".

**Mapping.**
| Stage 1 | Stage 2 | Note |
|---|---|---|
| POL-CTR-001 | POL-CTR-001 | Clause verbatim (§4); `applies_to` also covers vendors |
| POL-CTR-002 (contractor repos) | POL-ACC-004 | Merged with the Access Control Standard's production-repository line, for everyone. The brief's approval card shows ACC-004 applied to an employee (Anil), while its YAML sketch is contractor-only. One rule covers both |
| POL-OFF-001 (offboarding, 4 h) | POL-OFF-001 (transfer revocation) | The brief's rule is about team transfers; the 4-hour window is kept |
| POL-FIN-004, POL-REF-001…003 | POL-REF-001/002 (P2) | $2,000 / $10,000 thresholds carried into the refund work |
| POL-CTR-003/004/005, POL-ACC-010, POL-ONB-020 | not yet ported | Onboarding-workflow rules (pool hardware, Slack guest, paperwork, expiry, training); they return with the onboarding workflow (P1/P2) |

**Authored clauses.** ACC-001, ACC-002, ACC-003, ACC-004 (combined), ACC-005, OFF-001 (transfer) and
SOD-001 carry clause text written for Stage 2, marked in each YAML file. When the OKF bundle lands (T173), each
clause must appear verbatim in its `source.okf` page, and a test will enforce it.

## D-015 — Freshservice approvals: what the API allows, and how decisions are mirrored
**Found** (api.freshservice.com, Tickets > Approvals, read 2026-09-26):
- `POST /api/v2/tickets/[ticket_id]/approvals` takes `approver_id`, `approval_type` (1 everyone, 2 anyone,
  3 majority, 4 first responder) and an optional `email_content`. It is "planned for deprecation" for accounts
  with Parallel Approvals, which should use approval groups instead.
- The approval status (0 requested, 1 approved, 2 rejected, 3 cancelled) can be set through the API **only to
  cancelled**: "Any other status change will be done based on the approver's action."
- No endpoint takes an idempotency key.
- `GET /api/v2/service_catalog/items` allows at most 30 per page (the reference MCP client sends 100).

**Conflict with the brief.** CLAUDE.md §13.0 step 5 says `decide()` "mirrors the decision to the Freshservice
approval". An approval decided in Slack, email, Teams or voice cannot be written onto the Freshservice approval
as approved or rejected.

**Decision.**
- One Freshservice approval per held action's approver (`approval_type` everyone), created by
  reading the ticket's approvals first. A retried job reuses a live approval for the same approver instead of
  asking twice.
- The mirror of a decision made in another door is a **private note** on the ticket (who, what, where, when,
  params hash, connector mode). The note is found by a marker before posting and re-fetched after, and the
  Freshservice approval's own state is read back and reported alongside it.
- We do **not** cancel the superseded Freshservice approval automatically. Cancelling is the only write the
  API allows, but it would show "cancelled" for an item that was approved, and it changes the ticket's approval
  state on a live tenant. Left open for the lead or product.

**Revisit if.** The trial tenant has Parallel Approvals enabled (switch to approval groups), or we decide that
cancelling superseded approvals is the clearer signal for Freshservice agents.

## D-016 — Signing the Freshservice webhook (open)
**Built.** `/v1/webhooks/freshservice` accepts only `X-ContextRail-Signature: sha256=HMAC-SHA256(FS_WEBHOOK_SECRET,
"<timestamp>.<body>")` with `X-ContextRail-Timestamp` within ±300 s, as CLAUDE.md §16 asks. The comparison is
constant-time, it fails closed without a secret, and replays inside the window are absorbed by the ticket-id
dedupe (T133).
**Found.** Workflow Automator's Web Request node offers Basic auth, API key or no auth, and nothing that computes
a signature (support.freshservice.com, "Web Request Node", read 2026-09-26). §13.2's direct Workflow Automator →
engine call therefore cannot pass this check as it stands.
**Options.**
1. A signing hop. The FDK app's `onTicketCreate` event (§13.2 already names it the backup trigger) signs with
   the secret stored as a secure iparam and forwards the delivery. The HMAC scheme stays as built.
2. Accept a static shared secret in the header for Workflow Automator only. This is weaker: the header is
   replayable for as long as the secret lives. The exposure is bounded, because the payload is only a ticket id
   that the engine re-reads from Freshservice by ID (P1) and a replay is a 202 no-op after dedupe. It still
   lowers the bar the brief set, so it needs an explicit yes.
**Not done.** Option 2 was not implemented unasked: it is a security trade-off for the lead or security to make.
Until then, T135/T136 (Workflow Automator setup, human tasks) cannot pass end to end without option 1.

## D-017 — Freshservice assets: two API generations
**Found** (api.freshservice.com, read 2026-09-26). `GET/PUT /api/v2/assets/[display_id]` (the brief's §12 row) "is
valid for Freshservice signups before March 31, 2026". Newer signups use the Freshservice ITAM API:
`GET /api/v2/itam/assets/{id}` (no envelope) and `PUT /api/v2/itam/assets/` with `asset_id` in the body. Its
update attributes (type, service_level, state, building, serial_no, ...) include **no user or "Used By"
field**.
**Decision.** T130 implements the classic endpoints (`user_id` = "Used By"), with read-first reconciliation and
read-back verification, and the FIXTURE tenant. A trial tenant created now is likely an ITAM tenant. There, the
classic call is expected to fail and the result is the labelled FIXTURE fallback, never a LIVE claim.
**Revisit if.** The trial tenant turns out to be a classic tenant (then T130 is LIVE as built), or Freshservice
documents user assignment on ITAM assets.
