#!/usr/bin/env bash
# safe_push.sh — THE one hardened push path. Every committer (GH Actions, harness
# postflights, system-crontab backstops, manual sessions) should push through this so
# behaviour is identical everywhere. Rebase-retry on divergence; abort (don't loop) on
# a real content conflict.
#
# rebase.autoStash=true is the key resilience knob: a writer's working tree is often
# dirty with OTHER in-flight files (host openclaw rebuilding dashboard.json, dreaming
# appending MEMORY.md, …). Plain `git pull --rebase` REFUSES on a dirty tree ("cannot
# pull with rebase: you have unstaged changes") — the exact failure that stranded
# commits before 2026-05-30. autoStash auto-stashes those files, rebases, restores them.
set -e

MAX_RETRIES=3
REMOTE="${1:-origin}"
BRANCH="${2:-master}"

# ── Conflict-marker guard (2026-06-03) ───────────────────────────────────────
# A "merge fix" once committed dashboard.json WITH unresolved <<<<<<< / ======= /
# >>>>>>> markers and pushed it → JSON invalid → Pages dashboard went fully blank.
# Refuse to push if ANY tracked file in this commit carries conflict markers. This
# is the source-of-truth gate: no committer (cron / harness / manual) can publish a
# half-merged file again. We match only the OPEN/CLOSE markers (7 brackets + space +
# label) — unambiguous and always present in a real conflict — so a legit `=======`
# markdown h1 underline never false-trips this. `git grep` scans HEAD's committed tree.
if git grep -nE '^(<<<<<<< |>>>>>>> )' HEAD -- 2>/dev/null | grep -q .; then
  echo "✗ REFUSING TO PUSH — unresolved git conflict markers in committed files:"
  git grep -nE '^(<<<<<<< |>>>>>>> )' HEAD -- 2>/dev/null | head -20
  echo "  Resolve the conflict (or rebuild the generated file) and re-commit before pushing."
  exit 3
fi

for i in $(seq 1 $MAX_RETRIES); do
  if git push "$REMOTE" "$BRANCH"; then
    echo "✓ pushed on attempt $i"
    exit 0
  fi
  echo "push failed attempt $i, trying rebase (autostash)…"

  # -c rebase.autoStash=true → tolerate a dirty working tree during the rebase.
  if git -c rebase.autoStash=true pull --rebase "$REMOTE" "$BRANCH"; then
    echo "  rebase clean, will retry push"
    sleep $((i * 3))
  else
    # real content conflict (same lines changed both sides) — abort + don't retry.
    echo "  ✗ rebase conflict — abort, leaving commit local"
    git rebase --abort 2>/dev/null || true
    echo "  Manual resolution needed: git pull --rebase + resolve + git push"
    exit 2
  fi
done

echo "✗ push failed after $MAX_RETRIES retries"
exit 1
