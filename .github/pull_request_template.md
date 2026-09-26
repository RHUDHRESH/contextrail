## Section <!-- e.g. B — Repository skeleton and commit discipline -->

**Checklist range:** T___–T___ · **Priority in this PR:** P0 / P1 / P2
**Merge with a merge commit, never squash.** Each commit maps to one task (CLAUDE.md §24).

### Tasks completed
<!-- Paste the ticked lines from docs/CHECKLIST.md for this section. -->
- [x] T___ …

### Tasks deferred (with reason)
<!-- Anything in this section not done yet, and why (e.g. 👤 needs tenant access). -->
- none

### Verification
<!-- Commands actually run and what they printed. No result = say NOT VERIFIED. -->
```text
$ …
```

### Connector modes touched
| Connector / door | Mode |
|---|---|
| | LIVE / FIXTURE / ONE-WAY / n/a |

### Screenshots / recordings
<!-- Slack card, email confirm page, Teams card, sidebar, receipt… -->

### Principles checklist
- [ ] No model output sets a verdict, an approval or `verified` (§0 rule 2)
- [ ] No door decides; doors call `surfaces/door.py` only (§13.0)
- [ ] Every external write carries an idempotency key (§0 rule 5)
- [ ] Nothing labelled LIVE that isn't (§0 rule 4)
- [ ] No secrets in the diff (`pre-commit` hook passed)
- [ ] `docs/BUILDLOG.md` regenerated with `scripts/buildlog.sh`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
