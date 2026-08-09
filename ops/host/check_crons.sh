#!/usr/bin/env bash
# check_crons.sh — cron visibility across ALL schedulers
# Usage:
#   bash ops/host/check_crons.sh                 # last 20 runs
#   bash ops/host/check_crons.sh --timeline      # merged forward schedule
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "${1:-}" = "--timeline" ]; then
  shift
  exec python3 "$DIR/cron_timeline.py" "$@"
fi
exec python3 "$DIR/cron_runs.py" "$@"
