#!/usr/bin/env bash
# publish_dashboard.sh — the single scheduled publisher for dashboard-generated
# JSON and the Mode 7 heartbeat sidecar (Option 1, 2026-07-04). GH Action scans commit ONLY
# their sidecar files (macro/sentiment/influencer/…); index.html fetches those
# directly, so this publisher does not embed them. This crontab-run publisher
# rebuilds portfolio-derived dashboard data and publishes the whole generation —
# four payloads plus the heartbeat and workflow-outcome sidecars — to the orphan
# data branch. It no longer commits anything to `master` (#325).
#
# Concurrency: holds /tmp/dashboard_publish.lock (the same lock the host harness
# rebuild takes, see _harness_common.DASHBOARD_PUBLISH_LOCK) for the WHOLE
# build→commit→push critical section, so a host cron and this publisher can never
# race on the generated file. `flock -n` → if a build is already in flight, skip
# this tick rather than pile up.
#
# The bot identity now lives with the only thing that still writes a commit —
# `publish_data_branch.py` injects it per invocation into `commit-tree`, never
# into git config (see feedback-commit-identity-kcnyu).
set -euo pipefail

WS="/root/.openclaw/workspace"
LOCK="/tmp/dashboard_publish.lock"
# Where the last published generation is materialised for this tick. Gitignored,
# rewritten every run, and read by two steps that must agree on what "previously
# published" means.
PREVIOUS_DIR="$WS/.data-plane.cache"
cd "$WS"


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

# The last published generation, materialised out of the data branch. Two things
# need it and both used to get it from this repository: the recovery source for
# `--previous`, and the baseline the semantic diff compares against. Neither is a
# git question any more — the outputs are not tracked (#314) — and the worktree
# copy would answer both with "whatever this host built last time", which is the
# wrong answer on any checkout that did not build the previous one.
#
# NOT fatal, deliberately. `set -e` is on, so a bare invocation here would turn
# a transient network failure into "this tick publishes nothing at all" — the
# publisher would be strictly less resilient than before the migration, and
# detection is not allowed to degrade into not-publishing. What a failed fetch
# actually costs is bounded and self-correcting:
#   • --previous does not resolve → the build is workspace-only and says so (#315);
#   • the baseline is absent or one generation stale → the semantic diff falls
#     back to "everything changed", so the tick republishes and redeploys. Noisy
#     for one tick, correct, and repaired by the next fetch.
# A stale $PREVIOUS_DIR is not a problem either: it still holds the last
# generation this host saw published, which is exactly what the baseline means.
if ! python3 ops/pages/fetch_data_plane.py --into "$PREVIOUS_DIR"; then
  echo "⚠ publish_dashboard: could not read the published generation — this tick" >&2
  echo "  builds workspace-only and may republish without a real change" >&2
fi

# --previous: this build is published, so it opts in to restoring cards whose
# memory/.tmp sidecar is missing (#262 slice 2 made workspace-only the default).
# On this host the sidecars are present, so it is a no-op — it is here so a
# degraded run publishes the last good cards instead of blanking them.
python3 scripts/data/build_dashboard.py --previous "$PREVIOUS_DIR/assets/data/dashboard.json"
python3 scripts/data/cron_heartbeat.py --publish
python3 scripts/data/workflow_outcomes.py --publish

# build_dashboard writes four public files. The shared ownership helper compares
# all four against the last published generation, strips build-clock metadata,
# and restores clock-only rewrites — so a rebuild that changed nothing but
# `generated_at` is not republished, and does not trigger a site deploy for a
# generation the site already serves.
#
# The comparison target is the data branch, not HEAD: these files left the
# repository's history in #314, so `git show HEAD:…` has nothing to answer with
# and every output would read as changed on every tick. The return value is no
# longer a commit pathspec — nothing commits these any more — so it is discarded;
# the restore is the part that matters.
python3 scripts/data/dashboard_outputs.py --baseline-dir "$PREVIOUS_DIR" > /dev/null

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
# There is no longer a master publish to order against — this script's only
# destination is the data branch (#325).
data_plane_failed=0
publish_data_plane() {
  # One entry point, shared with the harness postflights (#328) — identity
  # selection and the publish itself must not drift between the two callers.
  if ! bash scripts/data/publish_generation.sh; then
    echo "✗ publish_dashboard: data plane not published or not deployed" >&2
    return 1
  fi
}

# Nothing to commit any more. The scheduled publisher's entire commit pathspec
# was `cron-heartbeats.json` + `workflow-outcomes.json`, and both went to the
# data branch with the four payloads (#325) — so this publisher stops writing to
# `master` altogether.
#
# The `git diff --quiet` checks that used to gate the commit are gone with it:
# git cannot answer "did this change" for an untracked file, and the store
# already answers it better by comparing against what the branch actually holds.
#
# Side effect worth naming: `master` no longer receives a push from this script,
# so the tick no longer triggers a Pages deploy by pushing AND by dispatching.
# That double trigger is what produced the `cancelled` runs in #321.


publish_data_plane || data_plane_failed=1
exit "$data_plane_failed"
