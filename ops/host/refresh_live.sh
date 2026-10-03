#!/usr/bin/env bash
# refresh_live.sh — bring this host's live clawock up to `origin/master`.
#
# The desk does not wait for a release to run a merged fix, and it should not:
# `install_clawock_launcher.sh` installs the distribution **editable**, so
# /root/.openclaw/workspace *is* the implementation and a fast-forward changes
# behaviour with no reinstall (`tests/test_clawock_launcher.py` pins that).
# Two halves of the install do not follow the checkout on their own, and this
# script is the rule about them, executable:
#
#   1. the venv — pip recorded the dependency set and the `[project.scripts]`
#      entry points at install time. A merge that adds either needs the
#      installer re-run, or the new command is simply absent.
#   2. the DSH plugin — pnpm installs a *copy* of the packed package, so
#      `examples/dsh/packages/clawock-dsh` changes reach the desk only through
#      `install_dsh_plugin.sh` (see its header for why it packs a tarball).
#   3. the agent-dispatch runner — it runs from /root/tools/agent-dispatch, a
#      copy, so `ops/host/agent-dispatch/` changes reach it only through
#      `install_agent_dispatch.sh` (atomic per file, `.before-update`, cmp;
#      running tasks keep the file they opened). The queue ops entry next to it
#      (`install_task_queue_ops.sh`) is still installed by hand: the dsh chip
#      shows its installed-vs-checkout hash (docs/architecture/task-queue.md).
#   4. the patrol's round assets — prompts, lessons, axes and the filing gate are
#      read from /root/tools/clawock-patrol, a copy, so `ops/host/clawock-patrol/`
#      changes reach it only through `install_patrol_assets.sh` (same shape as
#      the runner's installer; nothing restarts, every round rereads them). The
#      supervisor `patrol.sh` itself stays a manual install (ops/host/README.md).
#
# None needs npm publish or a PyPI release: publishing is for people who are
# not this host. See docs/operations/release.md § Running the latest code here.
#
# Usage:
#   ops/host/refresh_live.sh            # fast-forward, then reinstall what moved
#   ops/host/refresh_live.sh --check    # report what is pending; write nothing
#                                       # (exit 1 when the desk is behind)
#
# Env: LIVE_CHECKOUT (default /root/.openclaw/workspace), LIVE_REMOTE (origin),
#      LIVE_BRANCH (master).
set -euo pipefail

CHECKOUT="${LIVE_CHECKOUT:-/root/.openclaw/workspace}"
REMOTE="${LIVE_REMOTE:-origin}"
BRANCH="${LIVE_BRANCH:-master}"
check_only=0
[ "${1:-}" = "--check" ] && check_only=1

test -d "$CHECKOUT/.git" || { echo "not a git checkout: $CHECKOUT" >&2; exit 2; }
cd "$CHECKOUT"

git fetch -q "$REMOTE" "$BRANCH"
range="HEAD..$REMOTE/$BRANCH"
behind="$(git rev-list --count "$range")"

# The runner is compared by content, not by what this fetch brought: cron's own pushes
# fast-forward this checkout too, so a runner change can arrive without passing through the
# range below, and "at origin/master" would then leave the host on the old runner.
RUNNER_DIR="${AGENT_DISPATCH_DIR:-/root/tools/agent-dispatch}"
runner_differs() {
  [ -d "$RUNNER_DIR" ] && [ -f ops/host/install_agent_dispatch.sh ] &&
    ! bash ops/host/install_agent_dispatch.sh --check-files >/dev/null 2>&1
}
install_runner() {
  bash ops/host/install_agent_dispatch.sh
  bash ops/host/install_agent_dispatch.sh --check
}
# The queue ops entry the runner and the desk's queue actions call is the installed copy in
# the same directory, not this checkout (ops/ is outside the editable install). Installing it
# stays a manual step (install_task_queue_ops.sh says why), so this script only names it —
# and never calls such a merge "python only" (#2067).
ops_differs() {
  [ -d "$RUNNER_DIR" ] && [ -f ops/host/install_task_queue_ops.sh ] &&
    ! bash ops/host/install_task_queue_ops.sh --check >/dev/null 2>&1
}
OPS_MANUAL="run ops/host/install_task_queue_ops.sh (manual; refresh_live does not install it)"
# Patrol assets, compared by content like the runner and for the same reason.
PATROL_DIR="${PATROL_TOOL_DIR:-/root/tools/clawock-patrol}"
patrol_differs() {
  [ -d "$PATROL_DIR" ] && [ -f ops/host/install_patrol_assets.sh ] &&
    ! bash ops/host/install_patrol_assets.sh --check >/dev/null 2>&1
}
install_patrol() {
  bash ops/host/install_patrol_assets.sh
  bash ops/host/install_patrol_assets.sh --check
}
PATROL_STALE="the installed patrol assets fail install_patrol_assets.sh --check: they need installing"

if [ "$behind" = "0" ]; then
  echo "live checkout is at $REMOTE/$BRANCH ($(git rev-parse --short HEAD))"
  ops_stale=0
  if ops_differs; then
    ops_stale=1
    echo "  → the installed queue ops entry differs from this checkout: $OPS_MANUAL"
  fi
  runner_stale=0
  if runner_differs; then
    runner_stale=1
    echo "  → the installed agent-dispatch runner fails install_agent_dispatch.sh --check: it needs installing"
  fi
  patrol_stale=0
  if patrol_differs; then
    patrol_stale=1
    echo "  → $PATROL_STALE"
  fi
  if [ "$check_only" = "1" ]; then
    [ $((runner_stale + patrol_stale)) -gt 0 ] && { echo "(--check: nothing written)"; exit 1; }
    [ "$ops_stale" = "1" ] && exit 1
    exit 0
  fi
  [ "$runner_stale" = "1" ] && install_runner
  [ "$patrol_stale" = "1" ] && install_patrol
  exit 0
fi

changed="$(git diff --name-only "HEAD...$REMOTE/$BRANCH")"
needs_venv=0
needs_plugin=0
needs_runner=0
grep -qx 'pyproject.toml' <<<"$changed" && needs_venv=1
grep -q '^examples/dsh/packages/clawock-dsh/' <<<"$changed" && needs_plugin=1
grep -qE '^ops/host/(agent-dispatch/|install_agent_dispatch\.sh$)' <<<"$changed" && needs_runner=1
needs_patrol=0
grep -qE '^ops/host/(clawock-patrol/|install_patrol_assets\.sh$)' <<<"$changed" && needs_patrol=1
needs_ops=0
grep -qE '^ops/host/(task_queue_ops\.py|model_prices\.json|install_task_queue_ops\.sh)$' <<<"$changed" && needs_ops=1

echo "behind $REMOTE/$BRANCH by $behind commit(s):"
git --no-pager log --oneline "$range" | sed 's/^/  /'
[ "$needs_venv" = "1" ] && echo "  → pyproject.toml moved: the venv needs install_clawock_launcher.sh"
[ "$needs_plugin" = "1" ] && echo "  → clawock-dsh moved: the desk needs install_dsh_plugin.sh --restart"
[ "$needs_runner" = "1" ] && echo "  → agent-dispatch runner moved: /root/tools/agent-dispatch needs install_agent_dispatch.sh"
if [ "$needs_patrol" = "1" ] || patrol_differs; then
  needs_patrol=1
  echo "  → patrol assets moved or differ: /root/tools/clawock-patrol needs install_patrol_assets.sh"
fi
pending=$((needs_venv + needs_plugin + needs_runner + needs_ops + needs_patrol))
if [ "$needs_runner" = "0" ] && runner_differs; then
  echo "  → the installed agent-dispatch runner fails install_agent_dispatch.sh --check: it needs installing"
  pending=$((pending + 1))
fi
[ "$needs_ops" = "1" ] && echo "  → queue ops entry moved: $OPS_MANUAL"
if [ "$needs_ops" = "0" ] && ops_differs; then
  echo "  → the installed queue ops entry differs from this checkout: $OPS_MANUAL"
  pending=$((pending + 1))
fi
# Only when nothing above is owed: "python only" next to an install line is a contradiction.
if [ "$pending" = "0" ]; then
  echo "  → python only: the editable install picks it up on fast-forward"
fi

if [ "$check_only" = "1" ]; then
  echo "(--check: nothing written)"
  exit 1
fi

# autostash because the live tree is nearly always dirty — cron writes market
# data into it all day. Same reasoning as ops/publish/safe_push.sh. The pull is
# wrapped in the #1038 migration guard: while master carries the daily-notes
# untracking, a dirty tracked diary meeting this pull would otherwise become a
# modify/delete stash-pop conflict.
# autostash: this checkout is almost always dirty with in-flight generated
# files (dashboard rebuilds, dreaming appends), and a plain --rebase refuses on
# a dirty tree.
git fetch -q "$REMOTE" "$BRANCH" >/dev/null 2>&1 || true
if ! git -c rebase.autoStash=true pull --rebase "$REMOTE" "$BRANCH" -q; then
  # A conflicting replay of local commits leaves the rebase in progress: HEAD
  # detached mid-replay, markers in the tree, the autostash not yet re-applied.
  # Every cron reading this checkout would run against that. Abort, which puts
  # back the original HEAD and the autostashed edits, so "untouched" is true.
  if [ -d "$(git rev-parse --git-path rebase-merge)" ] || \
     [ -d "$(git rev-parse --git-path rebase-apply)" ]; then
    git rebase --abort >/dev/null 2>&1 || true
  fi
  echo "✗ pull --rebase failed — checkout left untouched, investigate before retrying" >&2
  exit 1
fi
# The pull also exits 0 when the commits replayed but re-applying the autostash
# conflicted; git then leaves unmerged paths and keeps the stash. Say so rather
# than report a clean fast-forward over a tree with conflict markers in it.
unmerged="$(git diff --name-only --diff-filter=U)"
if [ -n "$unmerged" ]; then
  echo "✗ fast-forwarded, but re-applying local edits conflicted in: $(echo "$unmerged" | tr '\n' ' ')" >&2
  echo "  the edits are kept in the stash (git stash list); resolve before cron reads these files" >&2
  exit 1
fi
echo "fast-forwarded to $(git rev-parse --short HEAD)"

if [ "$needs_venv" = "1" ]; then
  bash ops/host/install_clawock_launcher.sh "$CHECKOUT"
fi
if [ "$needs_plugin" = "1" ]; then
  if command -v dsh >/dev/null; then
    bash ops/host/install_dsh_plugin.sh --restart
  else
    echo "dsh CLI not on PATH — skipped the plugin install" >&2
  fi
fi
if [ "$needs_runner" = "1" ] && [ ! -d "$RUNNER_DIR" ]; then
  echo "no agent-dispatch installation on this host — skipped the runner install" >&2
elif [ "$needs_runner" = "1" ] || runner_differs; then
  install_runner
fi
if [ "$needs_patrol" = "1" ] && [ ! -d "$PATROL_DIR" ]; then
  echo "no clawock-patrol installation on this host — skipped the patrol assets install" >&2
elif [ "$needs_patrol" = "1" ] || patrol_differs; then
  install_patrol
fi
if ops_differs; then
  echo "  → the installed queue ops entry differs from this checkout: $OPS_MANUAL"
fi

# Say what is live now rather than assuming the steps above took: an install
# that reports success while the desk serves the previous build is the failure
# this repo has already had twice (#709, and the pnpm store reuse in #731).
# By absolute path, not by name: under the user crontab's PATH=/usr/bin:/bin the
# launcher is not resolvable (tests/test_no_bare_clawock_invocation.py).
launcher="${CLAWOCK_LAUNCHER:-$HOME/.local/bin/clawock}"
[ -x "$launcher" ] && "$launcher" --version
if command -v dsh >/dev/null; then
  bundle="examples/dsh/packages/clawock-dsh/lib/client.js"
  # dsh 0.1.2 retired the per-plugin URL this check used to fetch: client
  # bundles are served only through the module loader's combo URL carrying the
  # current graph rev (`/plugins/clawock-dsh/client.js` answers 404 now, and
  # so does the combo shape with any other rev), and the body is the committed
  # file plus a trailing sourceMappingURL comment. The `/plugins/events` graph
  # is where that URL is published — and it is one of the few routes 0.1.2's
  # new browser-session auth leaves open, so this check still needs no cookie.
  # Both fetches land in a file: under `pipefail`, `head -c` closing the pipe
  # early would fail the whole pipeline on SIGPIPE and read as "not serving".
  served="$(mktemp)"
  bundle_matches=0
  # A restarted DSH may accept connections before its plugin graph is ready.
  # Retry the whole graph-and-bundle probe; a failed check must still fail after
  # the bounded readiness window.
  for attempt in 1 2 3; do
    graph="$(curl -sN --max-time 5 http://127.0.0.1:3081/plugins/events 2>/dev/null \
             | grep -m1 '^data: ' || true)"
    url="$(printf '%s' "${graph#data: }" | python3 -c 'import json, sys
raw = sys.stdin.read().strip()
entries = json.loads(raw)["graph"]["entries"] if raw else []
print(next((e["url"] for e in entries if e["id"] == "clawock-dsh"), ""))' || true)"
    # The graph may publish a path with or without a leading slash.
    [ -n "$url" ] && curl -fs --max-time 30 -o "$served" "http://127.0.0.1:3081/${url#/}" || true
    if [ -s "$served" ] && head -c "$(wc -c < "$bundle")" "$served" | cmp -s - "$bundle"; then
      bundle_matches=1
      break
    fi
    [ "$attempt" = 3 ] || sleep 3
  done
  if [ "$bundle_matches" = 1 ]; then
    echo "dsh serves the checkout's client bundle"
    rm -f "$served"
  else
    rm -f "$served"
    echo "dsh is NOT serving $bundle — investigate before trusting the desk" >&2
    exit 1
  fi
fi
