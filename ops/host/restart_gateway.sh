#!/usr/bin/env bash
# restart_gateway.sh — restart OpenClaw's gateway from a dispatched task, with the task's
# machine-readable mandate checked first.
#
# kcn 2026-11-01: making a task's change effective may restart the gateway without asking.
# The default mandate allows it; a task dispatched with --no-restart says
# `gateway.restart: deny`, and this wrapper refuses and appends the denial to
# <task dir>/mandate-violations.jsonl. Use this instead of `openclaw gateway restart` so the
# authorization and the restart record exist. `--check` only decides; it starts nothing.
#
#   ops/host/restart_gateway.sh          # check the mandate, record the restart, restart
#   ops/host/restart_gateway.sh --check  # check only
#
# A task from before mandates (or an interactive shell) has no mandate: it proceeds and says so.
set -euo pipefail

check_only=0
if [ "${1:-}" = "--check" ]; then check_only=1; shift; fi
[ "$#" -eq 0 ] || { echo "usage: $0 [--check]" >&2; exit 2; }

source_dir=$(dirname "$(readlink -f "$0")")
MANDATE_FILE="${AGENT_DISPATCH_MANDATE:-}"
TASK_ID="${AGENT_DISPATCH_TASK_ID:-}"
if [ -z "$MANDATE_FILE" ] && [ -n "$TASK_ID" ]; then
  candidate="/root/logs/agent-dispatch/$TASK_ID/mandate.json"
  [ ! -r "$candidate" ] || MANDATE_FILE="$candidate"
fi
if [ -n "$MANDATE_FILE" ]; then
  helper="$source_dir/agent-dispatch/mandate.py"
  [ -r "$helper" ] || helper="/root/tools/agent-dispatch/mandate.py"
  [ -r "$helper" ] || { echo "refused: no mandate checker at $helper; install the runner first" >&2; exit 3; }
  if ! python3 "$helper" check --file "$MANDATE_FILE" --action gateway.restart \
      --source restart_gateway.sh --task-dir "$(dirname "$MANDATE_FILE")" >/dev/null; then
    echo "refused: this task's mandate does not allow gateway.restart; the denial is recorded in $(dirname "$MANDATE_FILE")/mandate-violations.jsonl" >&2
    exit 3
  fi
else
  echo "restart_gateway: no task mandate (interactive or legacy task); proceeding" >&2
fi

if [ "$check_only" = 1 ]; then
  echo "restart_gateway: mandate allows gateway.restart"
  exit 0
fi

if [ -n "$TASK_ID" ]; then
  printf '%s action=gateway.restart task=%s source=restart_gateway.sh\n' "$(date '+%F %T')" "$TASK_ID" \
    >>"/root/logs/agent-dispatch/$TASK_ID/restarts.log" 2>/dev/null || true
fi
exec openclaw gateway restart