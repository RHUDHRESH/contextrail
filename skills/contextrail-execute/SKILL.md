---
name: contextrail-execute
description: Perform approved actions through MCP integrations under idempotency keys, retry transient failures, and verify each outcome against its post-condition. Use as the final step of a governed workflow, after policy evaluation and human approval.
---

# ContextRail — Execute

Doing the work, and then proving it was done. A write that returned 200 is not
the same as an outcome that actually landed.

## When to use

- An action plan exists, policy has been evaluated, and approvals are decided.
- You need an auditable record of what ran, what was retried, and what was
  refused.

## Tools

`generate_action_plan(request, available_tools?)` → `execute_and_verify(request_id, approvals?)`

## The execution contract

1. **Approval gate.** Any privileged action still pending is refused with
   `APPROVAL_MISSING` and the list of what needs deciding. Unapproved work is
   never deferred into a queue and quietly run later.
2. **Idempotency.** Every action carries a key. A replay returns the original
   result rather than performing the action twice.
3. **Bounded retry.** Transient failures retry under the same key. The attempt
   count is recorded and surfaced, not hidden.
4. **Verification probe.** After each write, a post-condition is checked — the
   ticket exists in the right group, the grant is read-only with the right
   expiry, the guest invite is scoped to one channel. A write that succeeds but
   fails its probe is marked `verified: false`.
5. **Blocked actions are reported, not skipped.** They appear in the execution
   record with `status: "blocked"` and the policy that stopped them.

## Rules

- **Never execute an action whose effect was `deny`.** Not with an override, not
  under a different tool, not "as a test".
- **Report partial completion honestly.** `status: "partial"` with the blocked
  list is the correct outcome for a request that asked for something forbidden.
- **The audit trail is the deliverable.** Every execution appends actor, tool,
  idempotency key, attempts, and verification note.

## Example outcome

> 7 of 8 actions completed and verified. 1 refused: *Issue production database
> credentials* — POL-CTR-001, "Contractors cannot receive production
> credentials" (Notion, Contractor Onboarding Policy). Manager briefed with the
> withheld-item list.
