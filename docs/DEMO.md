# ContextRail — 1:50 video walkthrough

Stage 1 asks for a 1–2 minute walkthrough. This is the shot list. Record at 1512×950 in a clean browser window with deliberate pointer movement.

**Before you record:** stop any existing server, clear the demo store (`Remove-Item .data -Recurse -Force` in PowerShell or `rm -rf .data` in a Unix shell), then run `npm run build && npm start` and open `http://localhost:3100`. Leave the store empty — the first run should assemble live on camera.

---

### 0:00 – 0:12 · The claim

*Screen: Command Center, empty state.*

> "Enterprise agents can find records and call tools. The risk is what gets lost between those steps: evidence, policy, ownership, and proof of outcome."

Point at the header line — *Other agents retrieve information. ContextRail turns enterprise knowledge into governed action.*

---

### 0:12 – 0:22 · One sentence in

*Click **Contractor onboarding** → the composer opens pre-filled. Click **Assemble capsule**.*

> "One sentence from a manager. 'Priya joins engineering on Monday. Give her everything she needs to start.'"

---

### 0:22 – 0:40 · The rail runs

*Let the eight-stage rail run live. Do not narrate the stages — let the lamps do it.*

> "ContextRail sweeps eight connected systems, builds a Context Capsule, applies seven policies against *this specific* contractor, and generates an eight-step plan."

Land on the **Capsule** tab as it fills.

---

### 0:40 – 0:55 · The capsule

*Scroll the capsule slowly. Hit the `{ }` toggle for one second to show the raw JSON, then toggle back.*

> "This is the wedge. Intent, subject record, eleven cited sources, seven hard constraints — each bound to the policy it came from. It's a portable object. Serialise it and hand it to any agent."

---

### 0:55 – 1:10 · The refusal

*Click **Plan**. Scroll to `ACT-06` — `vault.issue_credential`, struck through, red, `POL-CTR-001`.*

> "'Everything she needs' implicitly asked for production credentials. Policy forbids that for non-employees, so it's refused — with the clause quoted. And a deny is terminal. No approval can override it."

*Click **Policy** for two seconds — show that every verdict carries its own citation.*

---

### 1:10 – 1:25 · The handoff

*Click **Handoff**.*

> "The capsule routes HR to IT to Security by capability. Each hop carries eleven evidence items, seven constraints, every prior decision, and the open blockers. Nobody starts from scratch."

---

### 1:25 – 1:40 · Approve and execute

*Click **Approvals**. Type a reason. Click **Approve**. Click **Execute approved actions**.*

> "The one privileged action stops for a named human. Approve it, and the plan executes — with idempotency keys, retries, and a verification probe on every outcome."

*Land on **Execution**. Point at the `ACT-05` GitHub row: `2 attempts`, `verified`.*

---

### 1:40 – 1:50 · It is infrastructure

*Jump to Command Center, click **Refund after an outage**, let it assemble for three seconds. Then cut to **Skills & Tools**.*

> "Same rail, completely different domain — support to finance, tier-based eligibility, an approval threshold. Because it isn't an onboarding app. It's six MCP tools and five skills that any agent can call, including Freddy AI Agent Studio."

---

## What must be on screen at least once

- [ ] The eight-stage rail with a **red** stage
- [ ] The raw Context Capsule JSON
- [ ] A struck-through action with its policy ID
- [ ] A policy card with its quoted clause and source
- [ ] The handoff graph with the carry manifest
- [ ] An approval being granted with a typed reason
- [ ] `2 attempts` on the retried execution row
- [ ] The second scenario assembling
- [ ] The MCP tool catalogue

## Lines to avoid

Don't say "AI-powered", "seamlessly", or "leverages". Don't explain what MCP is — the judges know. Don't apologise for mocked connectors; say "eight-system fixture" and move on.
