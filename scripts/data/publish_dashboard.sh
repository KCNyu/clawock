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

# --previous: this build is published, so it opts in to restoring cards whose
# memory/.tmp sidecar is missing (#262 slice 2 made workspace-only the default).
# On this host the sidecars are present, so it is a no-op — it is here so a
# degraded run publishes the last good cards instead of blanking them.
python3 scripts/data/build_dashboard.py --previous assets/data/dashboard.json
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

# ── Data plane (#314) ────────────────────────────────────────────────────────
# The same generation, also published to the orphan data branch, and the site
# deploy asked for explicitly. Dual write while the migration is in flight:
# `master` stays the served source until the outputs stop being tracked, which
# makes this verifiable the only way that matters — the branch's four files must
# be byte-identical to the ones this tick commits to `master`.
#
# Runs on EVERY path, deliberately NOT gated on the local semantic diff. The
# store compares against what the branch actually holds and no-ops when it
# matches, so a gate could only ever suppress a publish the store was going to
# skip anyway — while costing the one thing that matters: a tick that failed to
# reach the branch is repaired by the next one with no new information. Gated on
# "nothing changed locally", a failed publish would sit stale until the next
# genuine change, which on a quiet day is indefinitely. It also covers the first
# tick, where there is no branch yet.
#
# AFTER the master publish, not before. Both destinations trigger a Pages run
# during the dual write, and `concurrency: pages` cancels the older one — going
# second is what leaves the dispatched run to finish, so the path that has to
# work after the cut is the one actually exercised now. Ordering is otherwise
# free precisely because the store is self-healing.
data_plane_failed=0
publish_data_plane() {
  # Sourced for GIT_SSH_COMMAND/PUBLISH_REMOTE — the same deploy-key identity
  # safe_push.sh uses, selected in one place rather than restated per publisher.
  # shellcheck source=scripts/data/publish_identity.sh
  . scripts/data/publish_identity.sh
  if ! python3 scripts/data/publish_data_branch.py \
       --deploy --remote "${PUBLISH_REMOTE:-origin}"; then
    echo "✗ publish_dashboard: data plane not published or not deployed" >&2
    return 1
  fi
}

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
  # Nothing to commit, but the data plane still gets checked: a quiet tick is
  # exactly when nothing else would force a retry of a publish that never
  # arrived, so this is the branch a stale data plane would exit through.
  publish_data_plane || data_plane_failed=1
  exit "$data_plane_failed"
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

publish_data_plane || data_plane_failed=1
# A tick that reached only one of its two destinations is degraded, and the cron
# health check is where that belongs. Non-zero only after `master` was published,
# so the failing half cannot take the working half down with it.
exit "$data_plane_failed"
