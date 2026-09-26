#!/usr/bin/env bash
# One-time per clone: turn on the ContextRail commit gates (CLAUDE.md §24).
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
chmod +x .githooks/* scripts/*.sh 2>/dev/null || true
git config core.hooksPath .githooks
git config commit.template .gitmessage
echo "hooks enabled: $(git config core.hooksPath); template: $(git config commit.template)"
