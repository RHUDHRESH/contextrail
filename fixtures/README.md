# fixtures/

FIXTURE data for connectors without a live tenant: HRIS, entitlements, GitHub, the Slack corpus (including the
planted injection message), incidents and payments. Every connector backed by these files reports
`mode: "FIXTURE"`. See CLAUDE.md §12.

`documents.json` (statements of work) and `incidents.json` are seed data with no connector yet: nothing in the
rail reads them today. `engine/tests/test_org_fixtures.py` checks that every file agrees with every other.
