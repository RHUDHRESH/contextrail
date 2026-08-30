---
name: contextrail-govern
description: Evaluate policies, role permissions, and approval thresholds against a specific subject, returning allow, deny, or require_approval with the clause each verdict came from. Use before any action that writes to a system, grants access, moves money, or touches a privileged resource.
---

# ContextRail — Govern

The difference between an assistant and infrastructure. Answers not "what does
the policy say" but "does this policy apply to *this* person, for *this* action,
right now — and who owns the decision."

## When to use

- Before executing any write, grant, purchase, or credential issuance.
- When a request sounds reasonable and you need to check whether it is permitted.
- When an approval threshold might apply based on amount, tier, or risk.

## Tool

`check_policy_and_permissions(action, context_capsule)`

Returns `effect`, `approver`, `policy_id`, `reason`, and a `citation`
(`{ system, title, excerpt }`).

## The three effects

| effect | meaning | escalatable |
| --- | --- | --- |
| `allow` | No policy restricts this action for this subject. | — |
| `require_approval` | Permitted, but a named human owns the decision. | Yes — route to `approver`. |
| `deny` | Forbidden. | **No.** An approval cannot override a deny. |

## Rules

1. **Deny is terminal.** Never route a denied action to an approver, and never
   re-attempt it under a different framing. Report it as prevented, with the
   policy ID.
2. **Every verdict quotes its clause.** A verdict without a citation is an
   opinion and must not be returned.
3. **Policy applicability is subject-specific.** The same action can be `allow`
   for an employee and `deny` for a contractor. Always evaluate against the
   capsule's `subject`, never against the request's wording.
4. **Stale governing document downgrades the effect.** If the policy source is
   past its freshness budget, return `require_approval` with
   `POLICY_STALE`, never `allow`.
5. **Blocked actions stay visible.** They are reported to the user, not dropped
   from the plan.
