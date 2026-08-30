# Figma — what is wrong, and the rewrite

File: [ContextRail prototype](https://www.figma.com/design/LIWk2Se8ol7tEuJQ2xTE5L)

Stage 1 accepts a Figma prototype *or* a working demo. We have a working demo. Figma still matters: many Stage 1 reviewers will never clone the repo. They will open one link. That link has to explain the product in ten seconds.

## What is wrong with the current file

The file is real (frames, not flattened screenshots). That is not the problem.

The problem is narrative. The first frame is a catalogue: many screens, many tokens, no question. A judge cannot answer:

1. What was asked?
2. What was refused, and why?
3. What was proven to have happened?

Until those three are the opening, more frames make it worse.

Figma MCP writes are blocked on the Starter plan. The automation browser currently hits Figma’s cookie wall, not the canvas. Until quota resets, **`/storyboard.html` is the narrative prototype.** Recreate the beats below in Figma as soon as the file is writable. Do not add screens. Cut.

## The file should be six frames, not a product dump

Use the same tokens as `DESIGN.md` / `src/app/globals.css`:

| Token | Hex | Meaning |
|---|---|---|
| ink | `#07090e` | Page |
| panel | `#0d111a` | Surface |
| line | `#1c2434` | Rules |
| text | `#e9edf6` | Body |
| muted | `#8b95aa` | Secondary |
| rail | `#6e8cff` | In motion |
| clear | `#3ddc97` | Verified |
| caution | `#f5a623` | Held |
| stop | `#ff5a5f` | Denied |

Type: Archivo (display) + Inter (body) + JetBrains Mono (ids, clauses).

## Frame 01 — Cover (the only frame that matters if they bounce)

Full ink field. No screenshot collage.

Left, large:

```
ContextRail
The evidence contract between enterprise agents.
```

Centre, one spoken request:

```
“Priya starts Monday. Give her everything.”
```

Right, three lamps in a column, each with a one-line outcome:

```
CLEAR     7 actions verified
CAUTION   GitHub read-only held for Security
STOP      Production credentials refused
          POL-CTR-001 · terminal · not an approval
```

Footer, one sentence:

```
MCP moves verbs. ContextRail moves the case.
Track 1 · TGPF 2026 · Freshworks
```

If a judge reads only this frame, they already understand the product.

## Frame 02 — The request becomes a subject

Do not show a dashboard. Show identity beating search.

- Utterance: “Priya starts Monday. Give her everything.”
- Anchor lookup (not search): `W-8841 · Priya Raghunathan · contractor · start 2026-09-01`
- Search is for documents. The subject of a workflow is fetched by identity.
- Caption: *This is the defect the eval harness caught. A paraphrase used to skip the contractor policy family and grant production credentials. Lookup by identity closed it.*

## Frame 03 — The capsule, not a chat log

One object, labelled **Context Capsule**, with seven fields only:

```
request     Priya starts Monday. Give her everything.
intent      contractor_onboarding
subject     W-8841 · contractor
sources     8 systems · cited · freshness flagged
constraints POL-CTR-001 · no production credentials
handoff     HR → IT · IT → Security
blockers    POL-CTR-001 production credentials
audit       partial
```

Caption: *This object is what hops. It is not summarised. A specialist agent that cannot see the blocker is a defective agent.*

## Frame 04 — Refusal is the product

Plan table. Seven rows complete or held. One row struck through:

```
grant_production_credentials
STOP  POL-CTR-001
“Contractors cannot receive production credentials.”
§4 Contractor Onboarding Policy
Terminal. No approval path.
```

Beside it, the approval that *does* exist:

```
GitHub read-only on SOW repos
CAUTION  Security on-call
Typed reason required
```

Caption: *A deny is not a queue. An approval is not a deny with extra steps.*

## Frame 05 — Handoff + verify

Left: HR → IT → Security. Each hop lists what was carried (subject, citations, constraints, blockers). Nothing is re-derived.

Right: execute timeline.

```
NDA + countersigned SOW check      verified
Freshservice ticket SR-4401        verified
Contractor-pool laptop NB-CTR-0114 verified
Slack single-channel guest         verified
Onboarding checklist               verified
GitHub read-only                   2 attempts · then verified
Calendar 30-day review             verified
Production credentials             not executed
```

Caption: *“The API returned 200” is not the finish line. A post-condition probe is.*

## Frame 06 — Track 1 and Track 2 on one board

Left, Track 1: the contractor story above, on Agent Studio + MCP + specialist agents.

Right, Track 2: six tools, five skills, one engine.

```
search_enterprise_knowledge
compile_context_capsule
check_policy_and_permissions
generate_action_plan
handoff_to_specialist
execute_and_verify
```

Footer: *The UI, the MCP server, and the skills call the same runtime. A deny in one place is a deny in all three.*

## What not to put in Figma

- A screen dump of every tab.
- Token palettes as the opening.
- “AI-powered”, robot marks, constellation graphs.
- A 28-tool boast.
- Any “made with” or vendor-assistant mark.

## Until Figma is writable

Open `public/storyboard.html` (served as `/storyboard.html`). That is the Stage 1 narrative prototype. Paste its six beats into Figma when the file accepts writes. Then set the file to “anyone with the link can view.”
