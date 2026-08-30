---
name: contextrail-compile
description: Build an evidence-backed Context Capsule from a raw enterprise request — resolved intent, subject record, cited sources, hard constraints, and a decision ledger. Use whenever a request will cross more than one system, more than one agent, or any approval boundary.
---

# ContextRail — Compile

Turns "Priya joins engineering on Monday, give her everything she needs" into a
structured, portable object that any agent can act on without re-deriving
anything.

## When to use

- The request is a blanket ask that must be decomposed.
- Work will pass between agents, teams, or sessions.
- You need one artefact that carries evidence, constraints, and decisions
  together.

## Tools

`search_enterprise_knowledge` → `compile_context_capsule(request, user_id, tenant_id)`

## What a capsule contains

| field | why it is there |
| --- | --- |
| `intent` + `intent_confidence` | What the request means, and how sure. Below 0.6, clarify instead of acting. |
| `requester` | Who asked, and what authority they hold. |
| `subject` | The worker or account the request is *about* — the attributes policy keys off. |
| `sources[]` | Cited evidence with confidence and staleness. |
| `constraints[]` | Hard rules, each bound to a policy ID and the evidence it came from. |
| `decisions[]` | Append-only ledger. Nothing is ever removed. |
| `handoff_chain[]` | Which agents have held this capsule. |
| `open_blockers[]` | What could not be resolved — travels with every handoff. |

## Rules

1. **Confidence below 0.6 means ask, not act.** Return the ambiguity and the two
   candidate intents.
2. **A missing subject record is a hard stop.** Do not infer employment type,
   tier, or entitlement from a name.
3. **Constraints are derived, never invented.** Every constraint names the policy
   and the evidence item behind it.
4. **The capsule is by-value.** Serialise and hand it on; never pass a pointer to
   state the receiver cannot see.
