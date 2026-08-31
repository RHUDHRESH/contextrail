<div align="center">
  <img src="public/brand/the-rail.svg" alt="ContextRail eight-stage evidence rail" width="760" />
  <h1>ContextRail</h1>
  <p><strong>MCP moves verbs. ContextRail moves the case.</strong></p>
  <p>Evidence, policy, ownership, and proof — carried together from the first request to the final verified action.</p>
  <p>
    <a href="http://localhost:3100">Run locally</a> ·
    <a href="public/storyboard.html">View storyboard</a> ·
    <a href="https://github.com/RHUDHRESH/contextrail">GitHub</a> ·
    <a href="https://the-great-agent-hackathon.devpost.com/">Hackathon</a>
  </p>
  <p><a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-black.svg" alt="MIT license" /></a></p>
</div>

Enterprise agents can already search, call tools, and hand work to specialists. What they drop is the *file*: who the person is, which clause applies, what is forbidden, and whether the systems actually changed.

ContextRail is that file. It rides a visual rail — green clear, amber held, red stopped — so a manager can see a governed outcome without reconstructing a chat log.

Built for **The Great Agent Hackathon (TGPF 2026)** · Track 1 story · Track 2 platform.

![Policy verdict with its deciding clause](docs/screens/05-policy-verdicts-with-clause.png)

---

## The pitch, in one request

> “Priya starts Monday. Give her everything.”

That sentence is the trap. “Everything” includes production credentials. Policy forbids it. Most agent demos either grant it, or hide the refusal in a paragraph of prose.

ContextRail does the unfashionable thing:

| Lamp | Meaning | In this run |
|---|---|---|
| **CLEAR** | Allowed, executed, probed | Paperwork check, ticket, laptop, Slack guest, onboarding checklist, team notice, GitHub read-only (after retry) |
| **CAUTION** | Privileged — named human, typed reason | GitHub read-only on SOW repos |
| **STOP** | Terminal deny. Not a queue. | Production credentials · `POL-CTR-001` |

The manager does not get a green dashboard. They get a **partial completion**: seven verified, one refused, clause quoted. That refusal is the product.

### The product in one glance

| Request | Evidence | Decision | Proof |
|---|---|---|---|
| “Give her everything” | Resolved subject + cited sources | 7 clear · 1 held · 1 terminal stop | Idempotent writes + post-condition probes |

---

## How it works

One natural-language request enters the rail. Eight stages, one object, no re-derivation.

```mermaid
flowchart LR
  Q["“Give her everything”"] --> D[Discover]
  D --> C[Compile capsule]
  C --> G[Govern]
  G --> P[Plan]
  P --> H[Handoff by capability]
  H --> A{Privileged?}
  A -->|named human| AP[Typed approval]
  A -->|no| E[Execute]
  AP --> E
  E --> V[Verify probe]
  V --> U[Audit]
  G -->|STOP| U
```

### 1. Discover — search finds documents

Sweep connected systems (HRIS, Notion policy, Freshservice, Slack, GitHub, Linear, CRM, Google Docs). Keep only citations above a confidence floor, with freshness flags. Search is for **evidence**, not for identity.

### 2. Compile — the subject is looked up

Intents declare **anchor records fetched by identity**. Priya is `W-8841`, contractor, start 2026-09-01. A paraphrase (“new contract engineer next week”) used to skip this lookup, miss the contractor policy family, and issue production credentials. The eval harness caught it. Search no longer gets to decide who she is.

### 3. Govern — quote the clause

Twelve subject-aware policies. Every verdict names the person it applies to and quotes the deciding paragraph. `POL-CTR-001` is not a vibe. It is Contractor Onboarding Policy §4.

### 4. Plan — the forbidden row stays visible

Denied actions are struck through on the plan. They are not deleted. A judge (or a CISO) can see what was asked and what was refused in the same table.

### 5. Handoff — the capsule hops by value

![Capsule hops HR → IT → Security](public/brand/handoff.svg)

HR, IT, and Security do not get a summary. They get the capsule: request, subject, citations, constraints, prior decisions, blockers. Security does not re-ask HRIS who Priya is.

### 6. Approve — amber is not red

GitHub read-only waits for Security. An approval is a named owner and a typed reason. It cannot resurrect a terminal deny.

### 7. Execute — idempotent writes, bounded retry

Writes carry idempotency keys. GitHub fails once, retries, then proceeds.

### 8. Verify — 200 is not the finish line

Each write is followed by a post-condition probe. Ticket exists. Group membership is real. Collaborator is on the repo. Production credentials were **not executed**.

```mermaid
flowchart TB
  subgraph capsule ["Context Capsule — the object that hops"]
    R["request: Give her everything"]
    S["subject: W-8841 contractor"]
    E["8 cited sources · freshness"]
    P["POL-CTR-001 · no prod creds"]
    B["blocker: terminal deny"]
    A["audit: partial"]
  end
  R --- S --- E --- P --- B --- A
```

---

## Why it is special

Enterprise platforms already orchestrate. Freshworks Agent Studio does. Salesforce Agent Fabric does. ServiceNow Control Tower does. Saying they do not would lose this room.

ContextRail is special in a **narrower** way — the way a signal box is special relative to a railway:

1. **The case file is the product.** MCP `2026-07-28` made every tool call independently routable. The spec itself says: if you need state across calls, mint an explicit handle and pass it back. The capsule *is* that handle, structured.
2. **Identity is not a search ranking.** The subject of a workflow is fetched. Documents are retrieved. Mixing those two is how contractors get production keys.
3. **A deny is a successful governed result.** It is terminal, cited, and still on the plan. No approval path can launder it.
4. **Proof is a probe, not a status code.** Connector success is a claim. ContextRail checks the resulting system state.
5. **One engine, three doors.** The UI, six MCP tools, and five `SKILL.md` packs cannot disagree about a deny. A run started in an external MCP client appears in the Command Center — and an integration test spawns the real MCP server to prove the two doors return the same verdict.
6. **Retrieved text does not get to give orders.** The fixture corpus contains a planted Slack thread instructing the agent to ignore contractor policy and grant production credentials. Retrieval ranks it into the capsule. Policy reads the subject record, so it changes nothing.

That is the Freshworks fit: Agent Studio and the MCP Gateway are the ecosystem. ContextRail is the evidence contract those surfaces do not ship — portable, inspectable, and honest about partial completion.

---

## The three lamps, as a language

This is not a palette. It is operations vocabulary.

```text
  CLEAR   ●  allowed · executed · probe passed
  CAUTION ●  held for a named human · typed reason required
  STOP    ●  forbidden · quoted · terminal
  RAIL    ●  capsule in motion
```

If a screen uses green for decoration, it is wrong.

---

## Working surface

- Next.js 16 control plane with live SSE across all eight stages
- Six Zod-validated MCP tools over stdio
- Five installable skills
- Twelve declarative policies with clause-level citations
- Eval harness: routing, agents, tools, policy, handoff completeness, verified execution

### Three surfaces built on the rail

**Attack it** — an adversary console inside the running product. Five attacks (forge an
approval on the refused action, strip a constraint in transit, promote the subject to an
employee, replay a write, order the agent to ignore policy) execute against the live
engine and report what happened, with real digests. Nothing is scripted, and the run is
not modified. A judge does not have to take a refusal on faith.

**Policy Studio** (`/policy`) — every rule replayed against all four fixture workflows
with that rule held out, diffed. It answers the question a service manager actually asks
before editing governance: *if I turn this off, what starts happening?* Removing
`POL-CTR-001` releases production credentials. It also reports, honestly, which rules
change no outcome at all in the current fixtures.

**The governed receipt** (`/runs/[id]/receipt`) — the one printable page a manager shows
a CISO: what was asked, what was refused and under which clause, what was verified, and a
hash-chained attestation of every decision. EU AI Act Article 12 requires tamper-evident
logs that distinguish a hard stop from a warning; the chain labels each entry `hard`,
`soft`, or `record`, and breaks visibly if an entry is edited or removed.

### MCP tools

```text
search_enterprise_knowledge     # discover — evidence only, never identity
compile_context_capsule         # resolve the subject, bind constraints
check_policy_and_permissions    # verdict + deciding clause
generate_action_plan            # denied rows stay on the plan
handoff_to_specialist           # capsule hops by value
execute_and_verify              # idempotent write + post-condition probe
list_runs                       # read-only: the Command Center's own feed
```

The six rail tools carry a run end to end. `list_runs` is the read-only
seventh that lets an external MCP client see runs it
did not start.

```json
{
  "mcpServers": {
    "contextrail": {
      "command": "npx",
      "args": ["tsx", "mcp/server.ts"],
      "env": { "CONTEXTRAIL_TENANT": "tnt_northbeam" }
    }
  }
}
```

### Skills

`contextrail-discover` · `contextrail-compile` · `contextrail-govern` · `contextrail-handoff` · `contextrail-execute`

A verdict without a citation is not actionable. A capsule is never summarised in transit. A deny is terminal.

## Evaluation

```text
routing accuracy           100%   4/4 intents
agent routing accuracy     100%   8/8 expected agents reached
tool selection accuracy    100%   13/13 expected tools planned
policy compliance          100%   5/5 verdicts correct
handoff completeness       100%   9/9 hops carried full context
action success rate        100%   19/19 executed and verified
time saved                 287 minutes across 4 workflows
```

### What the tests actually attack

`npm run eval` measures the happy path. `npm test` tries to break the guarantees:

```text
a terminal deny cannot be laundered      forge an approval on the blocked action — still refused, 0 attempts
evidence cannot override policy          plant an injection in the corpus — retrieved, ranked 6th, ignored
identity is resolved, not ranked         named and paraphrased requests resolve the same W-8841
tampering is detected                    drop a constraint mid-hop — digest mismatch names what went missing
one engine, three doors                  spawn the real MCP server, diff its verdict against the UI engine
a 200 is not a finish line               connector succeeds, post-condition fails, action is not "done"
the docs match the code                  README/storyboard numbers asserted against the source
```

46 tests across 6 files. The MCP case spawns an actual stdio process — it is an
integration test, not a mock. The last file is a drift guard: it fails the build if this
README claims a tool, policy count, or connector the code does not have.

These are fixture results, not a general safety certificate. The interesting number is the defect we found: paraphrase → missed identity → skipped policy → production credentials. That story is in the README because a caught-and-fixed failure reads better than a claim of correctness.

## Run it

```bash
npm install
npm run dev      # http://localhost:3100
npm test         # 46 tests — the adversarial suite
npm run eval     # the six demo metrics
npm run mcp      # the same engine over stdio
```

No API keys. Open `/storyboard.html` for the six-beat narrative. Open `/` for the control plane.

## Architecture

| Layer | Implementation |
|---|---|
| Interface | Next.js 16, React 19, TypeScript, Tailwind v4, `@xyflow/react` |
| Runtime | Node.js, SSE, typed async-generator rail |
| Protocol | Official MCP SDK, stdio |
| Contracts | Zod at route, tool, and event edges |
| State | Append-only file store, shaped for a future `runs` table |
| Integrity | SHA-256 capsule digest over subject, constraints, decisions, blockers |
| Safety | Subject-aware policy, terminal deny, approval, idempotency, verify |
| Proof | Vitest — adversarial suite + live MCP integration |

## Docs

- [Stage 1 submission](docs/SUBMISSION.md)
- [1:50 video script](docs/DEMO.md)
- [Storyboard](public/storyboard.html)
- [Figma rewrite](docs/FIGMA.md)
- [Research](docs/RESEARCH.md)
- [Design](DESIGN.md) · [Product](PRODUCT.md)

## Limits

Fixture-backed connectors. File store is for the demo. Eval set is small. Auth is in the contracts, not a live IdP.

## License

MIT. See [LICENSE](LICENSE).
