#!/usr/bin/env bash
# gha_commit_push.sh — shared commit+push for GH Action data-scan jobs
# (macro / sentiment / influencer). Stages the job's data file(s), commits as
# the bot, pushes via safe_push.sh — and on a lost push race, retries.
#
# DECOUPLED SIDECARS (2026-07-04): GH Actions NO LONGER rebuild dashboard.json.
# They only commit their own disjoint sidecar (macro.json / sentiment.json /
# influencer_feed.json …), which index.html fetches directly. The host harness
# postflights + flock-guarded publish_dashboard.sh remain the only dashboard.json
# rebuilders, but no rebuild is needed for scan sidecars to reach the page. This
# eliminates the entire class
# of failures that this script used to work around:
#   • sidecar-strip regression — GHA rebuilt dashboard on a fresh checkout with an
#     empty memory/.tmp and published blanked-out narrative cards.
#   • the 2026-06-10 macro-vs-influence race — two runners rebuilt the SAME
#     generated file, safe_push refused the half-merge, and macro.json was lost.
# With dashboard out of the commit, the only files here are per-job disjoint
# sidecars that never content-conflict, so the push path is now trivial.
#
# Usage: gha_commit_push.sh "<commit message>" <data-file> [<data-file>…]
set -euo pipefail

MSG="$1"; shift
DATA_FILES=("$@")

# Bot identity via per-invocation `-c` injection — NEVER persistent `git config`.
# This script normally runs on an ephemeral GHA runner, but if it's ever invoked
# in a real workspace (debugging, a misrouted cron), writing local config would
# clobber kcn's interactive KCNyu identity (see memory feedback-commit-identity-kcnyu).
BOT_ID=(-c "user.name=github-actions[bot]"
        -c "user.email=41898282+github-actions[bot]@users.noreply.github.com")

commit_once() {
  git add -- "${DATA_FILES[@]}"
  if git diff --cached --quiet; then
    echo "no change"
    return 1
  fi
  # NOTE: intentionally does NOT rebuild/stage dashboard.json — see header.
  git "${BOT_ID[@]}" commit -m "$MSG"
}

commit_once || exit 0

if bash ops/publish/safe_push.sh; then
  exit 0
fi

# Sidecars are disjoint per job, so a push rejection here is only GitHub ref-lag,
# never a content conflict. Re-apply this job's data on top of the winner + retry.
echo "push lost a race — re-applying data on top of latest origin/master"
STASH_DIR=$(mktemp -d)
for f in "${DATA_FILES[@]}"; do
  mkdir -p "$STASH_DIR/$(dirname "$f")"
  cp "$f" "$STASH_DIR/$f"
done
git rebase --abort 2>/dev/null || true
git fetch origin master
git reset --hard origin/master
for f in "${DATA_FILES[@]}"; do
  cp "$STASH_DIR/$f" "$f"
done
commit_once || exit 0   # origin already carries identical data → done
bash ops/publish/safe_push.sh
