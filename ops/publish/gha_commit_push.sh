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

# Resolve the sibling publisher by this script's own location, not by CWD. The
# runner happens to start at the repo root, so `bash ops/publish/safe_push.sh`
# worked there and nowhere else — including from a test that wants to drive the
# real script against a real repository.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAFE_PUSH="$HERE/safe_push.sh"

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

if bash "$SAFE_PUSH"; then
  exit 0
fi

# Sidecars are disjoint per job, so a push rejection here is only GitHub ref-lag,
# never a content conflict. Re-apply this job's data on top of the winner + retry.
#
# A data path may be a DIRECTORY (2026-08-31): the factor-snapshot slices are
# passed as `assets/data/factor-snapshots/{sentiment,macro}`, whole trees of
# dated rows. `git add` takes a directory happily, so the first-try path always
# worked and this recovery — the one that only runs on a lost race — died on
# `cp` without -a, under `set -e`, ~10ms in. Every lost race therefore became a
# red run with the scan's data dropped, in the branch written to save it
# (sentiment-scan 2026-08-28 and 2026-08-30).
echo "push lost a race — re-applying data on top of latest origin/master"
STASH_DIR=$(mktemp -d)
for f in "${DATA_FILES[@]}"; do
  [ -e "$f" ] || continue
  mkdir -p "$STASH_DIR/$(dirname "$f")"
  cp -a "$f" "$STASH_DIR/$(dirname "$f")/"
done
git rebase --abort 2>/dev/null || true
git fetch origin master
git reset --hard origin/master
for f in "${DATA_FILES[@]}"; do
  [ -e "$STASH_DIR/$f" ] || continue
  if [ -d "$STASH_DIR/$f" ]; then
    # Overlay our rows onto the winner's tree rather than replacing it: the
    # snapshot directories are one dated file per writer per day, so the run we
    # lost to may have added a row of its own that must survive.
    mkdir -p "$f"
    cp -a "$STASH_DIR/$f/." "$f/"
  else
    mkdir -p "$(dirname "$f")"
    cp -a "$STASH_DIR/$f" "$f"
  fi
done
commit_once || exit 0   # origin already carries identical data → done
bash "$SAFE_PUSH"
