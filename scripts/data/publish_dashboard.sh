#!/usr/bin/env bash
# publish_dashboard.sh — the single scheduled publisher for dashboard.json and
# the Mode 7 heartbeat sidecar (Option 1, 2026-07-04). GH Action scans commit ONLY
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

# Only publish on a SEMANTIC change. build_dashboard bumps wall-clock fields on
# every run — generated_at, and the freshness block's age_hours / days_behind
# tick every few minutes with no real data change — so a byte diff (or even a
# generated_at-only strip) is always non-empty and would spam no-op commits every
# tick. Strip ALL clock fields recursively and compare; meaningful state (stale
# booleans, stale_files, prices, cards) still triggers a publish. If nothing real
# changed, discard the rebuild and stop.
dashboard_semantic_changed=1
if python3 - <<'PY'
import json, subprocess, sys
CLOCK = {'generated_at', 'age_hours', 'days_behind'}
def strip(o):
    if isinstance(o, dict):
        for k in CLOCK: o.pop(k, None)
        for v in o.values(): strip(v)
    elif isinstance(o, list):
        for v in o: strip(v)
    return o
new = strip(json.load(open('assets/data/dashboard.json')))
try:
    old = strip(json.loads(subprocess.check_output(
        ['git', 'show', 'HEAD:assets/data/dashboard.json'])))
except Exception:
    old = None
sys.exit(0 if new == old else 1)   # exit 0 == unchanged
PY
then
  dashboard_semantic_changed=0
  git checkout -- assets/data/dashboard.json
fi

heartbeat_changed=1
if git diff --quiet -- assets/data/cron-heartbeats.json; then
  heartbeat_changed=0
fi

if [ "$dashboard_semantic_changed" -eq 0 ] && [ "$heartbeat_changed" -eq 0 ]; then
  echo "publish_dashboard: no semantic or heartbeat change"
  exit 0
fi

paths=()
if [ "$dashboard_semantic_changed" -eq 1 ]; then
  paths+=(assets/data/dashboard.json)
fi
if [ "$heartbeat_changed" -eq 1 ]; then
  paths+=(assets/data/cron-heartbeats.json)
fi
git add -- "${paths[@]}"
# Scope the commit to dashboard.json with an explicit pathspec: a bare `git commit`
# would also sweep in anything ELSE already staged in the index (e.g. a human mid-edit
# staging files at publish time), mislabeling them "scheduled publish" — happened once.
git "${BOT_ID[@]}" commit -q -m "dashboard: scheduled publish $(date -u +%Y-%m-%dT%H:%MZ)" -- "${paths[@]}"
bash scripts/data/safe_push.sh
