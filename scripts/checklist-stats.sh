#!/usr/bin/env bash
# Recompute the totals block in docs/CHECKLIST.md from the task lines themselves,
# so the header can never disagree with the list. Fails if the numbering is broken.
# Usage: scripts/checklist-stats.sh [--check]   (--check: fail if the block is stale, change nothing)
set -euo pipefail

file="$(git rev-parse --show-toplevel)/docs/CHECKLIST.md"
tasks="$(grep -E '^- \[[ x]\] T[0-9]{3} `P[012]`' "$file")"

total="$(printf '%s\n' "$tasks" | wc -l | tr -d ' ')"
expected="$(printf 'T%03d\n' $(seq 1 "$total"))"
actual="$(printf '%s\n' "$tasks" | grep -Eo 'T[0-9]{3}')"
if [ "$expected" != "$actual" ]; then
  echo "checklist-stats: task IDs are not a continuous T001..T$(printf '%03d' "$total") sequence" >&2
  diff <(printf '%s\n' "$expected") <(printf '%s\n' "$actual") >&2 || true
  exit 1
fi

count() { printf '%s\n' "$tasks" | grep -c -- "$1" || true; }
done_all="$(count '^- \[x\]')"
line() {
  local p="$1" n d
  n="$(count "\`$p\`")"
  d="$(printf '%s\n' "$tasks" | grep -- "\`$p\`" | grep -c '^- \[x\]' || true)"
  printf '| %s | %s | %s |' "$p" "$n" "$d"
}

block="$(cat <<EOF
<!-- stats:start -->
| Priority | Tasks | Done |
|---|---|---|
$(line P0)
$(line P1)
$(line P2)
| **Total** | **$total** | **$done_all** |

👤 human-owned tasks: $(count '👤')
<!-- stats:end -->
EOF
)"

new="$(awk -v block="$block" '
  /<!-- stats:start -->/ { print block; skip=1; next }
  /<!-- stats:end -->/   { skip=0; next }
  !skip { print }
' "$file")"

if [ "${1:-}" = "--check" ]; then
  [ "$new" = "$(cat "$file")" ] || { echo "checklist-stats: totals block is stale; run scripts/checklist-stats.sh" >&2; exit 1; }
  exit 0
fi
printf '%s\n' "$new" > "$file"
printf 'total=%s done=%s\n' "$total" "$done_all"
