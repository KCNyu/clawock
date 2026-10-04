#!/usr/bin/env bash
# dispatch_preopen_scans.sh — start the macro and sentiment scans from this host
# shortly before the 08:03 HKT pre-open brief.
#
# Why the host: both scans are GitHub-scheduled for 05:30–05:55 HKT, and GitHub
# has been delivering those schedules 3–10 hours late since 2026-09-29, after the
# brief has read the sidecars. A second cron ten minutes later bought nothing —
# both attempts arrive in the same wave. No schedule on our side can outrun a
# delay of that size while still starting after the US close, so the brief read
# the previous day's VIX/HSI/DXY/10Y for four sessions running (#2516).
# `gh workflow run` is delivered in seconds; it is how brief_watchdog already
# starts the fallback brief. The scheduled runs stay as the host-down fallback.
#
# The scans overwrite their sidecar idempotently and share the `data-write`
# concurrency group, so a scheduled run that did arrive on time costs one no-op
# commit step. The live checkout picks the commit up on its next publisher pull.
#
# System crontab (HKT), Mon–Fri like the brief:
#   20 7 * * 1-5 /bin/bash /root/.openclaw/workspace/ops/host/dispatch_preopen_scans.sh >> /root/.openclaw/workspace/logs/preopen_scans.log 2>&1
set -uo pipefail

# Absolute path: the user crontab's PATH is /usr/bin:/bin.
GH="${GH_BIN:-/usr/bin/gh}"
REPO="${CLAWOCK_REPO:-KCNyu/clawock}"

status=0
for workflow in macro-scan.yml sentiment-scan.yml; do
  if "$GH" workflow run "$workflow" -R "$REPO" --ref master >/dev/null 2>&1; then
    echo "$(date -Is) dispatched $workflow"
  else
    echo "$(date -Is) dispatch FAILED for $workflow — the brief will read whatever the scheduled run left"
    status=1
  fi
done
exit "$status"
