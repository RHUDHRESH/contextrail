#!/usr/bin/env bash
# Fetch the complete production dotenv from one SSM SecureString parameter.
# Example: ./scripts/ssm-env.sh /contextrail/prod/dotenv
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  printf 'usage: %s SSM_SECURESTRING_PARAMETER\n' "$0" >&2
  exit 2
fi

command -v aws >/dev/null || { printf 'aws CLI is required\n' >&2; exit 2; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
destination="$repo_root/.env"
umask 077
temporary="$(mktemp "$repo_root/.env.tmp.XXXXXXXX")"
trap 'rm -f "$temporary"' EXIT

aws ssm get-parameter --name "$1" --with-decryption \
  --query 'Parameter.Value' --output text > "$temporary"

if [ ! -s "$temporary" ] || ! grep -q '^ENGINE_TOKEN=' "$temporary"; then
  printf 'SSM parameter is empty or lacks ENGINE_TOKEN; existing .env was kept\n' >&2
  exit 1
fi

chmod 600 "$temporary"
mv -f "$temporary" "$destination"
trap - EXIT
printf 'Loaded production environment into %s (mode 600)\n' "$destination"
