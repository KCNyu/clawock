#!/usr/bin/env bash
# check_crons.sh — cron visibility across ALL schedulers
# Usage:
#   ./check_crons.sh                 # last 20 runs (auto + manual)  [run HISTORY]
#   ./check_crons.sh 50              # last 50
#   ./check_crons.sh --job 港股       # filter by job name
#   ./check_crons.sh --status error  # only failures
#   ./check_crons.sh --kind cron     # only auto-scheduled
#   ./check_crons.sh --full          # no summary truncation
#   ./check_crons.sh --openclaw-backend sqlite  # read live state without gateway
#   ./check_crons.sh --timeline      # merged forward SCHEDULE (openclaw+GHA+crontab, HKT)
#   ./check_crons.sh --timeline --source gha    # one scheduler only
#   ./check_crons.sh --timeline --openclaw-backend sqlite
DIR="$(dirname "$0")/scripts/data"
if [ "$1" = "--timeline" ]; then
  shift
  exec python3 "$DIR/cron_timeline.py" "$@"
fi
exec python3 "$DIR/cron_runs.py" "$@"
