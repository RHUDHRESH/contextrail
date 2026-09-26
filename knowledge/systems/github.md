---
type: System
title: GitHub (northbeam organisation)
description: Source control; how repository access is granted, which repositories are production-tagged, and how grants are verified.
tags: [github, repositories, access, production, contractors]
last_verified: 2026-09-22
owner: security@northbeam.example
rules: [POL-ACC-004]
---
# GitHub (northbeam organisation)

Northbeam's code lives in the `northbeam` GitHub organisation. Access is granted per repository, as a collaborator
permission, and every grant follows the [Access Control Standard](../policies/access-control-standard.md).

ContextRail reaches GitHub through a FIXTURE connector backed by `fixtures/github.json`: it writes the permission to
fixture state and reads it back to verify. It reports mode FIXTURE until a GitHub App is configured.

## Repositories
| Repository | Tags | Team |
|---|---|---|
| `northbeam/payments-api` | internal | payments |
| `northbeam/ledger-service` | internal | payments |
| `northbeam/payments-web` | none | payments |
| `northbeam/payments-core` | production, pci | payments |
| `northbeam/perception-sdk` | production | perception |
| `northbeam/payments-docs` | none | payments |
| `northbeam/fleet-api` | production, pii | platform |
| `northbeam/infra-terraform` | production | platform |
| `northbeam/platform-tooling` | internal | platform |
| `northbeam/perception-models` | production | perception |
| `northbeam/risk-models` | internal | risk analytics |
| `northbeam/analytics-dbt` | internal | analytics |
| `northbeam/security-policies` | internal | security |
| `northbeam/docs` | none | shared |
| `northbeam/design-system` | internal | design systems |

## Production-tagged repositories
Any access to a repository tagged `production`, read-only included, is held for the Security on-call before it is
provisioned ([Access Control Standard §3](../policies/access-control-standard.md)). In the fixture, those are
`northbeam/payments-core`, `northbeam/perception-sdk`, `northbeam/fleet-api`,
`northbeam/infra-terraform`, and `northbeam/perception-models`.

## Contractors
Contractors get read-only access to the repositories named in their statement of work, and nothing else. Priya
Raghunathan (W-8841) starts on 2026-09-28 with `northbeam/perception-sdk` in her SOW, so she can be granted read
access to it, held for Security because the repository is production-tagged. How earlier requests like hers were
decided is in the [precedent](../precedents/github-readonly-contractors.md).

## Verifying a grant
A grant counts as done only when the collaborator permission is read back from GitHub and matches what was asked
for. A successful API response on its own is not proof.
