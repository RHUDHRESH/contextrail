---
type: Precedent
title: Read-only GitHub access for contractors on production-tagged SOW repositories
description: How requests for read access to a production-tagged repository named in a contractor's statement of work have been decided.
tags: [precedent, github, contractors, production, approval]
last_verified: 2026-09-20
owner: security@northbeam.example
rules: [POL-ACC-004]
claims:
  repository.production-tagged-approver: security on-call
---
# Read-only GitHub access for contractors on production-tagged SOW repositories

## The situation
A contractor's statement of work names a repository tagged `production`, and the contractor needs read access to
it. The [Access Control Standard §3](../policies/access-control-standard.md) (rule POL-ACC-004) allows the grant,
but holds it for the Security on-call because of the tag. The current example is `gh-perception-sdk-read` for
Priya Raghunathan (W-8841), whose SOW names `northbeam/perception-sdk`.

## Reported history
Before ContextRail, these requests were decided in Slack. In #security on 2026-08-18 (message `slk_sec_thread_1`),
Marc Liu (E-0120) wrote: "we approved read-only on northbeam/perception-sdk for the last two contractors within the
same day". In the same message: "Write access to prod-tagged repos has been declined every time so far this year."

This history is reported, not counted. It gives an approver context; it never appears as a count on an approval
card.

## Counts from the audit chain
No decisions have been recorded by ContextRail yet. After each run, the precedent updater recounts approved and
refused decisions for POL-ACC-004 and `gh-perception-sdk-read` from the verified audit chain only, and writes the
updated page to `drafts/` for a person to review. Approval cards show those counts, and only those.

## Related
- [GitHub](../systems/github.md)
- [Contractor Onboarding Policy](../policies/contractor-onboarding.md)
