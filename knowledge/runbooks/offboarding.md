---
type: Runbook
title: Offboarding and team transfers
description: What is revoked when someone leaves Northbeam or moves to another team, and how fast.
resource: https://notion.so/northbeam/offboarding
tags: [runbook, offboarding, transfer, revoke, access]
last_verified: 2026-09-21
owner: it-provisioning@northbeam.example
rules: [POL-OFF-001]
claims:
  revocation.deadline: 4 hours
---
# Offboarding and team transfers

## Departures
On the final working day: revoke SSO, transfer document ownership to the manager, reclaim hardware through
Freshservice, remove all repository access, and rotate any shared credentials the person could read. Access revocation must complete within 4 hours of the termination timestamp.

## Transfers
When a person changes team, access granted for the previous team is revoked on the day of the move, and revocation must complete within 4 hours of the transfer timestamp.

Access for the new team is granted first and the previous team's access is revoked the same day, so nobody is left
without the access their new role needs. Example: Anil Kumar (E-1042) moved from risk-analytics to payments on
2026-09-21, so `looker-risk-dashboards` and `slack-risk-analytics` are revoked.

## Contractors
Contractor access ends on the statement-of-work end date with no grace days
([Contractor Onboarding Policy §6](../policies/contractor-onboarding.md)).

# Citations
- Offboarding Runbook (Stage 1 source `ntn_offboarding`, last updated 2026-03-09): the Departures section,
  verbatim.
- Transfers: written for ContextRail from the Departures deadline, as recorded in docs/DECISIONS.md D-011.
