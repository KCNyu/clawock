# untrack_guard.sh — the one guarded autostash pull, shared by every pull site.
#
# Sourced (never executed) by ops/host/refresh_live.sh and ops/publish/safe_push.sh.
#
# Why this exists (#1038): master stops tracking the daily notes
# `memory/YYYY-MM-DD.md`. They stay workspace continuity — AGENTS.md reads
# today+yesterday from disk, the openclaw memory index rglobs the tree — so
# the untracking must remove them from the INDEX without removing them from
# any DISK. Three merge paths reach a working tree:
#   • ops/publish/safe_push.sh retry loop — autostash pull;
#   • ops/host/refresh_live.sh — autostash pull;
#   • ops/publish/publish_dashboard.sh — plain --ff-only merge (refuses on
#     dirty files, so a dirty diary only ever delays it — but it SILENTLY
#     DELETES clean ones, which is precisely what must not happen).
# Before the merge, `pull_guard_backup` copies every locally-present daily
# note the incoming range deletes (clean or dirty — clean ones are the ff
# path's victim, dirty ones the stash-pop hazard) to
# `memory/.tmp/pre-untrack-backup/`; afterwards `pull_guard_restore` puts
# back whatever the merge removed and cleans up. Restored files are
# untracked, and ignored once the matching .gitignore rule arrives.
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
  # $1 = remote, $2 = branch. Records every locally-present daily note the
  # incoming range deletes — clean or dirty. Callers must have fetched the
  # remote recently enough that "$1/$2" answers "what a merge would bring":
  # pull_guarded fetches itself, publish_dashboard reuses the fetch its
  # ff-merge already needed.
  local root deleted f dest
  root="$(_pull_guard_root)"
  [ -n "$root" ] || return 0
  deleted="$(git diff --name-only "HEAD..$1/$2" -- memory/ 2>/dev/null \
    | grep -E '^memory/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$' || true)"
  [ -n "$deleted" ] || return 0
  dest="$root/memory/.tmp/pre-untrack-backup"
  mkdir -p "$dest" 2>/dev/null || return 0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    # Present on disk is the only criterion: a clean copy is what the ff
    # merge deletes outright, a dirty one what a stash pop can mangle.
    if [ ! -f "$root/$f" ]; then
      continue
    fi
    mkdir -p "$dest/$(dirname "$f")" 2>/dev/null || continue
    cp -p "$root/$f" "$dest/$f" 2>/dev/null &&
      echo "pull-guard: backed up $f before merge" >&2
  done <<EOF
$deleted
EOF
}

pull_guard_restore() {
  # Puts back any backup whose path the merge removed, then clears the
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
  git fetch -q "$remote" "$branch" >/dev/null 2>&1 || true
  pull_guard_backup "$remote" "$branch"
  git -c rebase.autoStash=true pull --rebase "$remote" "$branch" "$@" || rc=$?
  pull_guard_restore
  return "$rc"
}
