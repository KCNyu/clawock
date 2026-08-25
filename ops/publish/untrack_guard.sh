# untrack_guard.sh — the one guarded autostash pull, shared by every pull site.
#
# Sourced (never executed) by ops/host/refresh_live.sh and ops/publish/safe_push.sh.
#
# Why this exists (#1038): master stops tracking the daily notes
# `memory/YYYY-MM-DD.md`. On the live box those files are written all day by
# openclaw sessions and committed by several autonomous writers, so a pull
# carrying their deletion can meet a locally-dirty tracked copy. Under
# `rebase.autoStash=true` that turns into a modify/delete stash-pop conflict —
# an aborted postflight push at best, a re-staged diary or a lost day of notes
# at worst. Before the pull, `pull_guard_backup` copies every dirty tracked
# bare-dated daily note the incoming range deletes to
# `memory/.tmp/pre-untrack-backup/`; after the pull (either outcome),
# `pull_guard_restore` puts back any copy the rebase removed and cleans up.
#
# Scope is exactly `^memory/YYYY-MM-DD\.md$` — the untracking commit's surface.
# Deletions of any other path are not guarded, so behaviour for them is
# unchanged from the raw autostash pull this file wraps. Everything here is
# best-effort: a guard failure degrades to today's behaviour (the plain
# autostash pull), never blocks it.
#
# Removal condition: once the untracking commit has been on origin/master long
# enough that no live checkout can be pulling it for the first time (a few
# weeks of refreshes), no backup target can exist; delete this file together
# with its two call sites. Deleting it earlier reopens the window.

_pull_guard_root() {
  git rev-parse --show-toplevel 2>/dev/null || true
}

pull_guard_backup() {
  # $1 = remote, $2 = branch. Records dirty tracked dailies the incoming range
  # deletes. Fetches first because callers reach here without a fresh
  # remote-tracking ref (safe_push only fetches for its money check).
  local root deleted f dest
  root="$(_pull_guard_root)"
  [ -n "$root" ] || return 0
  git fetch -q "$1" "$2" >/dev/null 2>&1 || true
  deleted="$(git diff --name-only "HEAD..$1/$2" -- memory/ 2>/dev/null \
    | grep -E '^memory/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$' || true)"
  [ -n "$deleted" ] || return 0
  dest="$root/memory/.tmp/pre-untrack-backup"
  mkdir -p "$dest" 2>/dev/null || return 0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    # Only a locally-modified tracked copy has something a stash pop can lose;
    # a clean file just gets deleted, which is exactly what master wants.
    if git diff --quiet HEAD -- "$f" 2>/dev/null; then
      continue
    fi
    if [ ! -f "$root/$f" ]; then
      continue  # already deleted locally — nothing to preserve
    fi
    mkdir -p "$dest/$(dirname "$f")" 2>/dev/null || continue
    cp -p "$root/$f" "$dest/$f" 2>/dev/null &&
      echo "pull-guard: backed up dirty $f before pull" >&2
  done <<EOF
$deleted
EOF
}

pull_guard_restore() {
  # Puts back any backup whose path the rebase removed, then clears the
  # backup dir. Restored files are untracked (master no longer carries them);
  # once the .gitignore rule from the same migration lands they are also
  # ignored, so the tree ends quiet either way.
  local root dest f rel
  root="$(_pull_guard_root)"
  [ -n "$root" ] || return 0
  dest="$root/memory/.tmp/pre-untrack-backup"
  [ -d "$dest" ] || return 0
  find "$dest" -type f 2>/dev/null | while IFS= read -r f; do
    rel="${f#"$dest"/}"
    if [ ! -e "$root/$rel" ]; then
      mkdir -p "$root/$(dirname "$rel")" 2>/dev/null || true
      cp -p "$f" "$root/$rel" 2>/dev/null &&
        echo "pull-guard: restored $rel after pull" >&2
    fi
    rm -f "$f" 2>/dev/null || true
  done
  # Remove the emptied tree bottom-up (the backup mirrors memory/… paths), so
  # only the transient pre-untrack-backup directory ever disappears.
  find "$dest" -depth -type d -empty -exec rmdir {} \; 2>/dev/null || true
  rmdir "$dest" 2>/dev/null || true
}

pull_guarded() {
  # Usage: pull_guarded REMOTE BRANCH [extra git-pull options…]
  # The wrapped pull both host-side call sites use. Returns git-pull's exit
  # code; the restore runs on failure too (a conflicted stash pop is exactly
  # when the backup matters).
  local remote="$1" branch="$2"
  shift 2
  local rc=0
  pull_guard_backup "$remote" "$branch"
  git -c rebase.autoStash=true pull --rebase "$remote" "$branch" "$@" || rc=$?
  pull_guard_restore
  return "$rc"
}
