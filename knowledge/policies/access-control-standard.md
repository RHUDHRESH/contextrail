---
type: Policy
title: Access Control and Least Privilege Standard
description: How every access grant at Northbeam is decided - role baselines, repositories, administrator rights, mirrored access, paid seats and separation of duties.
resource: https://notion.so/northbeam/access-control
tags: [policy, access, security, least-privilege, approval, github, production]
last_verified: 2026-09-20
owner: security@northbeam.example
rules: [POL-ACC-001, POL-ACC-002, POL-ACC-003, POL-ACC-004, POL-ACC-005, POL-SOD-001]
claims:
  contractor.production-credentials: never
  contractor.repository-write-access: never
  repository.production-tagged-approver: security on-call
---
# Access Control and Least Privilege Standard

## §1 Least privilege
All access grants follow least privilege. Every grant must record an owner, a justification, and an expiry.

## §2 Role baselines
Each role has a catalogue baseline of entitlements. A holder of the role receives its baseline entitlements without further approval.

The baselines are listed on the role pages, for example [Payments Engineer](../roles/payments-engineer.md).

## §3 Repository access
Repository access follows least privilege. Contractors receive read-only access to repositories named in their statement of work and nothing else. Any access to a repository tagged 'production' requires approval from the Security on-call before provisioning.

This joins the earlier line "Write access to any repository tagged 'production' requires approval from the Security
on-call before provisioning." with the contractor limits of the
[Contractor Onboarding Policy §3](contractor-onboarding.md) into one rule for everyone. The tagged repositories are
on the [GitHub](../systems/github.md) page.

## §4 Administrator rights
Administrator rights, including production administrator roles, are granted only to senior engineers and above, and only with approval from the Security on-call.

Elevated cloud roles require a named business justification and expire after 90 days.

## §5 Mirrored access
A request to give one person the same access as another is evaluated against the receiving person's own role. Entitlements outside that role's scope are not granted, whatever the peer holds.

## §6 Paid seats
A seat in a paid SaaS tool is a cost to the team's budget and requires approval from the person's manager before it is assigned.

## §7 Separation of duties
No one may approve a request they raised or from which they benefit. An approval given by the requester or the beneficiary is void.

Approval authority cannot be delegated to the requester's own manager when the requester is the beneficiary.

# Citations
- Access Control & Least Privilege Standard (Stage 1 source `ntn_access_control`, last updated 2026-08-01): §1, the
  earlier production-repository line quoted in §3, the elevated-role line in §4 and the delegation line in §7,
  verbatim.
- The clause texts of §2 to §7 were written for ContextRail and are recorded as authored in docs/DECISIONS.md D-011.
