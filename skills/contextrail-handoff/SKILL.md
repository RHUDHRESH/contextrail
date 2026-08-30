---
name: contextrail-handoff
description: Select the specialist agent that owns a needed capability and transfer the full Context Capsule — original request, evidence, applicable policies, prior decisions, action history, and unresolved blockers. Use whenever work moves between agents, teams, or sessions so nothing is re-derived or silently lost.
---

# ContextRail — Handoff

Handoff as a platform primitive rather than a message. The receiving agent gets
everything the sending agent knew, by value.

## When to use

- An action needs a capability the current agent does not own.
- Work crosses a team boundary (HR → IT → Security, Support → Finance).
- A workflow resumes in a new session and must not start from scratch.

## Tool

`handoff_to_specialist(request_id, target_agent?, capability?)`

Name a `target_agent`, or pass a `capability` and let the registry route it.
Routing is capability-based, so adding an agent is a data change, not a code
change.

## What travels

```
original request      → the words the human actually used
evidence[]            → every cited source, with confidence and staleness
constraints[]         → the hard rules, bound to their policy IDs
decisions[]           → everything decided so far, and by whom
assigned_actions[]    → what this agent specifically owns
open_blockers[]       → what is unresolved, so nobody rediscovers it
```

The response includes an explicit `carries` manifest. If you cannot state what
travelled, the handoff did not happen.

## Rules

1. **Never summarise the capsule in transit.** Summarising is how constraints get
   dropped. Pass the object.
2. **Blockers travel too.** An agent that receives a capsule with an unresolved
   blocker must not plan around it silently.
3. **Record the hop.** Every handoff appends to `handoff_chain` and the audit
   ledger.
4. **Unavailable agent is a blocker, not a fallback.** If no agent owns the
   capability, return `CAPABILITY_UNMATCHED` and record it — do not improvise.
