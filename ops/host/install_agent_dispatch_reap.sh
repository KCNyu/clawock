#!/usr/bin/env bash
# install_agent_dispatch_reap.sh — install and enable the dead-runner reap timer.
#
#   ops/host/install_agent_dispatch_reap.sh            # install, enable and start the timer
#   ops/host/install_agent_dispatch_reap.sh --check    # exit 1 on file drift or an inactive timer
#   ops/host/install_agent_dispatch_reap.sh --uninstall
#
# The timer runs the installed task_queue_ops.py `reap` every 10 minutes. It only marks a task
# whose unit is not active, whose run.log is quiet and whose result.env is old; it never
# deletes a directory, releases a lock or retries. Merging does not install this timer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_DIR="${AGENT_DISPATCH_UNIT_DIR:-/etc/systemd/system}"
SYSTEMCTL="${AGENT_DISPATCH_SYSTEMCTL:-systemctl}"
UNITS=(agent-dispatch-reap.service agent-dispatch-reap.timer)
TIMER=agent-dispatch-reap.timer

case "${1:-}" in
  --check|--uninstall|"") ;;
  *) sed -n '2,10p' "$0" >&2; exit 2 ;;
esac

if [ "${1:-}" = --uninstall ]; then
  "$SYSTEMCTL" disable --now "$TIMER" 2>/dev/null || true
  for unit in "${UNITS[@]}"; do rm -f "$UNIT_DIR/$unit"; done
  "$SYSTEMCTL" daemon-reload
  echo "removed the reap timer; running tasks and their results were not touched"
  exit 0
fi

bad=0
for unit in "${UNITS[@]}"; do
  if cmp -s "$ROOT/ops/host/$unit" "$UNIT_DIR/$unit"; then
    [ "${1:-}" = --check ] && echo "installed $unit matches this checkout"
  else
    echo "installed $unit differs from $ROOT/ops/host/$unit (or is missing)" >&2
    bad=1
  fi
done
if [ "${1:-}" = --check ]; then
  "$SYSTEMCTL" is-enabled --quiet "$TIMER" || { echo "$TIMER is not enabled" >&2; bad=1; }
  "$SYSTEMCTL" is-active --quiet "$TIMER" || { echo "$TIMER is not active" >&2; bad=1; }
  exit "$bad"
fi

for unit in "${UNITS[@]}"; do
  install -m 0644 "$ROOT/ops/host/$unit" "$UNIT_DIR/$unit"
  cmp "$ROOT/ops/host/$unit" "$UNIT_DIR/$unit"
  echo "installed $UNIT_DIR/$unit"
done
"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" enable --now "$TIMER"
"$SYSTEMCTL" list-timers --no-pager "$TIMER" || true
echo "check: $0 --check"
echo "remove: $0 --uninstall"
