#!/usr/bin/env bash
# publish_dashboard.sh — the single scheduled publisher for dashboard-generated
# JSON and the Mode 7 heartbeat sidecar (Option 1, 2026-07-04). GH Action scans commit ONLY
# their sidecar files (macro/sentiment/influencer/…); index.html fetches those
# directly, so this publisher does not embed them. This crontab-run publisher
# rebuilds portfolio-derived dashboard data, publishes the heartbeat sidecar, and
# pushes any semantic change.
#
# Concurrency: holds /tmp/dashboard_publish.lock (the same lock the host harness
# rebuild takes, see _harness_common.DASHBOARD_PUBLISH_LOCK) for the WHOLE
# build→commit→push critical section, so a host cron and this publisher can never
# race on the generated file. `flock -n` → if a build is already in flight, skip
# this tick rather than pile up.
#
# Commits as the bot via per-invocation `-c` (never persistent git config, which
# would clobber kcn's interactive KCNyu identity — see feedback-commit-identity-kcnyu).
set -euo pipefail

WS="/root/.openclaw/workspace"
LOCK="/tmp/dashboard_publish.lock"
cd "$WS"

BOT_ID=(-c "user.name=github-actions[bot]"
        -c "user.email=41898282+github-actions[bot]@users.noreply.github.com")

# Take the lock on fd 9 for the whole critical section (released on exit). -n:
# if the host harness is mid-rebuild, skip this tick rather than pile up.
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "publish_dashboard: another build holds the lock — skipping this tick"
  exit 0
fi

# Fetch first so we build on top of the latest sidecars other writers pushed.
git fetch -q origin master || true
git merge -q --ff-only origin/master 2>/dev/null || true

python3 scripts/data/build_dashboard.py
python3 scripts/data/cron_heartbeat.py --publish
python3 scripts/data/workflow_outcomes.py --publish

# build_dashboard writes four public files. The shared ownership helper compares
# all four against HEAD, strips only build-clock metadata, restores clock-only
# rewrites, and prints the exact semantic publication pathspec.
dashboard_paths_output="$(python3 scripts/data/dashboard_outputs.py)"
dashboard_paths=()
if [ -n "$dashboard_paths_output" ]; then
  mapfile -t dashboard_paths <<< "$dashboard_paths_output"
fi

heartbeat_changed=1
if git diff --quiet -- assets/data/cron-heartbeats.json; then
  heartbeat_changed=0
fi
outcomes_changed=1
if git diff --quiet -- assets/data/workflow-outcomes.json; then
  outcomes_changed=0
fi

if [ "${#dashboard_paths[@]}" -eq 0 ] && [ "$heartbeat_changed" -eq 0 ] && [ "$outcomes_changed" -eq 0 ]; then
  echo "publish_dashboard: no semantic or heartbeat change"
  exit 0
fi

paths=("${dashboard_paths[@]}")
if [ "$heartbeat_changed" -eq 1 ]; then
  paths+=(assets/data/cron-heartbeats.json)
fi
if [ "$outcomes_changed" -eq 1 ]; then
  paths+=(assets/data/workflow-outcomes.json)
fi
git add -- "${paths[@]}"
# Scope the commit to generated outputs with an explicit pathspec: a bare `git commit`
# would also sweep in anything ELSE already staged in the index (e.g. a human mid-edit
# staging files at publish time), mislabeling them "scheduled publish" — happened once.
git "${BOT_ID[@]}" commit -q -m "dashboard: scheduled publish $(date -u +%Y-%m-%dT%H:%MZ)" -- "${paths[@]}"
bash scripts/data/safe_push.sh
