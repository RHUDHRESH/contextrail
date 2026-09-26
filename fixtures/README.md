# fixtures/

FIXTURE data for connectors without a live tenant: HRIS, entitlements, GitHub, the Slack corpus (including the
planted injection message), incidents and payments. Every connector backed by these files reports
`mode: "FIXTURE"`. See CLAUDE.md §12.

`freshservice.json` stands in for the Freshservice tenant (ticket 4412, the identity people as requesters and
agents, the catalog, approvals and notes). It is used when FS_DOMAIN/FS_API_KEY are unset, and as the labelled
fallback when a tenant call fails.
