#!/usr/bin/env bash
# gha_commit_push.sh — shared commit+push for GH Action data-scan jobs
# (macro / sentiment / influencer). Stages the job's data file(s), rebuilds
# dashboard.json so its embedded block doesn't go stale, commits as the bot,
# pushes via safe_push.sh — and on a lost push race, retries deterministically.
#
# WHY the retry (2026-06-10 macro-scan failure): the `data-write` concurrency
# group serializes runs, but GitHub's ref replication can lag a few seconds —
# macro checked out master at 23:04:25, missing influence's 23:04:19 push.
# Its push was rejected, the rebase then CONFLICTED on dashboard.json (both
# runners rebuilt the generated file), safe_push correctly refused to publish
# a half-merge… and the day's macro.json was lost with it. A generated file
# must never be hand-merged: stash the data files aside, hard-reset to the
# winner, re-apply data, REBUILD dashboard on top, recommit, push again.
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
  python3 scripts/data/build_dashboard.py
  git add assets/data/dashboard.json
  git "${BOT_ID[@]}" commit -m "$MSG"
}

commit_once || exit 0

if bash scripts/data/safe_push.sh; then
  exit 0
fi

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
bash scripts/data/safe_push.sh
