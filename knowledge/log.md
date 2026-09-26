# Change log

Newest first. Each entry says what changed. The day a person last confirmed a page is its `last_verified`.

## 2026-09-26
- **Review** Open contradiction, left for the policy owner to settle: the [Contractor Onboarding Policy §3](policies/contractor-onboarding.md) says contractor write access needs Security review, while the [Access Control Standard §3](policies/access-control-standard.md) says contractors get read-only access to their SOW repositories and nothing else. ContextRail enforces the Standard (POL-ACC-004 refuses write access). Both texts stay as written; the lint reports the disagreement until a person resolves it.
- **Creation** [Access Control and Least Privilege Standard](policies/access-control-standard.md) and [Contractor Onboarding Policy](policies/contractor-onboarding.md), ported from the Stage 1 policy documents. Every shipped rule's clause text is verbatim under its clause heading.
- **Creation** [Payments Engineer](roles/payments-engineer.md), matching the role catalogue in fixtures/roles.json.
- **Creation** [GitHub](systems/github.md) and [Freshservice](systems/freshservice.md).
- **Creation** [Read-only GitHub access for contractors](precedents/github-readonly-contractors.md), with the reported Slack history and no audit-chain counts yet.
- **Creation** [Offboarding and team transfers](runbooks/offboarding.md) (cited by POL-OFF-001) and [Emergency access during an incident](runbooks/emergency-access.md).
- **Creation** [Schema](SCHEMA.md), [Read me](README.md), the root and folder indexes, and this log.
