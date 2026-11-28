#!/usr/bin/env bash
# Upgrade entry: verify the fork build. Host extensions have separate installers.
set -euo pipefail
HOST="$(cd "$(dirname "$0")" && pwd)"
if [[ "${1:-}" == --plan || "${1:-}" == --check-only ]]; then
  shift
fi
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$HOST/manage_openclaw_patches.py" verify-fork "$@"
