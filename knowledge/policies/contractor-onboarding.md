---
type: Policy
title: Contractor Onboarding Policy
description: What contractors and vendors may receive when they join, and who approves it.
resource: https://notion.so/northbeam/contractor-onboarding
tags: [policy, contractors, onboarding, access, security, production]
last_verified: 2026-09-20
owner: security@northbeam.example
rules: [POL-CTR-001, POL-ACC-004]
claims:
  contractor.production-credentials: never
  contractor.repository-write-access: allowed after Security review
---
# Contractor Onboarding Policy

Contractors are onboarded under a restricted access profile.

## §1 Equipment
Contractors receive a loaner laptop from the contractor pool only. Purchase of new hardware for a contractor requires Finance approval.

## §2 Identity
A Slack account is provisioned as a single-channel guest scoped to the engaging team's project channels. Full workspace membership is not granted to contractors.

## §3 Source control
GitHub access is read-only by default and limited to repositories explicitly named in the statement of work. Any write access requires Security review.

Repository access for everyone, contractors included, is also governed by the
[Access Control Standard §3](access-control-standard.md) (rule POL-ACC-004). The repositories and their tags are on
the [GitHub](../systems/github.md) page, and earlier decisions are in the
[precedent](../precedents/github-readonly-contractors.md).

## §4 Production access
Contractors must never receive production credentials, production database access, or customer PII exports.

Rule POL-CTR-001 enforces this as a terminal refusal: there is no approval path and no exception, including during
an incident ([Emergency access](../runbooks/emergency-access.md)). The rule applies to vendors in the same way.

## §5 Paperwork
A signed NDA and countersigned SOW must exist in the HRIS before any access is provisioned.

## §6 Duration
All contractor access carries a hard expiry matching the SOW end date plus zero grace days.

# Citations
- Contractor Onboarding Policy (Stage 1 source `ntn_contractor_onboarding`, last updated 2026-07-14): the text of
  §1 to §6, verbatim.
