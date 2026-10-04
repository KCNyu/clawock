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
# The scans overwrite their sidecar idempotently, so a scheduled run that did
# arrive on time costs one no-op commit step. The live checkout picks the commit
# up on its next publisher pull.
#
# Both share the `data-write` concurrency group, which holds one running and one
# waiting run: a run that is still waiting when another member of the group
# queues is cancelled, not delayed. Dispatching the two together left the second
# one waiting, and it was cancelled the first time this ran (2026-10-04). So each
# scan is dispatched on its own, given time to finish, and dispatched once more
# if it was cancelled.
#
# A dispatch that GitHub accepted is not a scan that ran (#2549): the retry can be
# cancelled too, and a scan can fail. So the run each dispatch produced is read
# back, and anything other than `success` — no new run, still running when the
# wait is spent, cancelled twice, failure — is a FAILED line and exit 1.
#
# System crontab (HKT), Mon–Fri like the brief:
#   20 7 * * 1-5 /bin/bash /root/.openclaw/workspace/ops/host/dispatch_preopen_scans.sh >> /root/.openclaw/workspace/logs/preopen_scans.log 2>&1
set -uo pipefail

# Absolute path: the user crontab's PATH is /usr/bin:/bin.
GH="${GH_BIN:-/usr/bin/gh}"
REPO="${CLAWOCK_REPO:-KCNyu/clawock}"

SETTLE_SECONDS="${PREOPEN_SCAN_SETTLE_SECONDS:-150}"
# A scan takes about a minute; one still running after the settle is polled
# for this much longer before it is reported as not finished.
WAIT_SECONDS="${PREOPEN_SCAN_WAIT_SECONDS:-300}"
POLL_SECONDS="${PREOPEN_SCAN_POLL_SECONDS:-20}"

dispatch() {
  "$GH" workflow run "$1" -R "$REPO" --ref master >/dev/null 2>&1
}

# "<run id> <conclusion>" of the newest host-dispatched run of a workflow; the
# conclusion is empty while it runs, the whole line is empty when there is none.
newest() {
  "$GH" run list -R "$REPO" --workflow "$1" --event workflow_dispatch --limit 1 \
    --json databaseId,conclusion \
    --jq 'map("\(.databaseId) \(.conclusion // "")") | first // ""' 2>/dev/null
}

run_id() {
  local line
  line="$(newest "$1")"
  echo "${line%% *}"
}

# How the run dispatched after run id $2 ended: its conclusion, `missing` when
# no newer run showed up, `running` when it has not concluded in time.
outcome() {
  local workflow="$1" before="$2" waited=0 line id result
  sleep "$SETTLE_SECONDS"
  while :; do
    line="$(newest "$workflow")"
    id="${line%% *}"
    result="${line#* }"
    [ "$line" = "$id" ] && result=""
    if [ -z "$id" ] || [ "$id" = "$before" ]; then
      result="missing"
    elif [ -z "$result" ]; then
      result="running"
    else
      break
    fi
    [ "$waited" -ge "$WAIT_SECONDS" ] && break
    sleep "$POLL_SECONDS"
    waited=$((waited + POLL_SECONDS))
  done
  echo "$result"
}

status=0
for workflow in macro-scan.yml sentiment-scan.yml; do
  before="$(run_id "$workflow")"
  if ! dispatch "$workflow"; then
    echo "$(date -Is) dispatch FAILED for $workflow — the brief will read whatever the scheduled run left"
    status=1
    continue
  fi
  echo "$(date -Is) dispatched $workflow"
  result="$(outcome "$workflow" "$before")"
  if [ "$result" = "cancelled" ]; then
    before="$(run_id "$workflow")"
    if ! dispatch "$workflow"; then
      echo "$(date -Is) $workflow was cancelled in the queue and the retry FAILED"
      status=1
      continue
    fi
    echo "$(date -Is) $workflow was cancelled in the queue — dispatched again"
    result="$(outcome "$workflow" "$before")"
  fi
  if [ "$result" = "success" ]; then
    echo "$(date -Is) $workflow finished: success"
  else
    echo "$(date -Is) $workflow FAILED: run ended $result — the brief will read whatever the previous scan left"
    status=1
  fi
done
exit "$status"
