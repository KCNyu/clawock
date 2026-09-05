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
#
# Neither needs npm publish or a PyPI release: publishing is for people who are
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

if [ "$behind" = "0" ]; then
  echo "live checkout is at $REMOTE/$BRANCH ($(git rev-parse --short HEAD))"
  exit 0
fi

changed="$(git diff --name-only "HEAD...$REMOTE/$BRANCH")"
needs_venv=0
needs_plugin=0
grep -qx 'pyproject.toml' <<<"$changed" && needs_venv=1
grep -q '^examples/dsh/packages/clawock-dsh/' <<<"$changed" && needs_plugin=1

echo "behind $REMOTE/$BRANCH by $behind commit(s):"
git --no-pager log --oneline "$range" | sed 's/^/  /'
[ "$needs_venv" = "1" ] && echo "  → pyproject.toml moved: the venv needs install_clawock_launcher.sh"
[ "$needs_plugin" = "1" ] && echo "  → clawock-dsh moved: the desk needs install_dsh_plugin.sh --restart"
if [ "$needs_venv" = "0" ] && [ "$needs_plugin" = "0" ]; then
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
  echo "✗ pull --rebase failed — checkout left untouched, investigate before retrying" >&2
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
  graph="$(curl -sN --max-time 5 http://127.0.0.1:3081/plugins/events 2>/dev/null \
           | grep -m1 '^data: ' || true)"
  url="$(printf '%s' "${graph#data: }" | python3 -c 'import json, sys
raw = sys.stdin.read().strip()
entries = json.loads(raw)["graph"]["entries"] if raw else []
print(next((e["url"] for e in entries if e["id"] == "clawock-dsh"), ""))' || true)"
  served="$(mktemp)"
  [ -n "$url" ] && curl -fs --max-time 30 -o "$served" "http://127.0.0.1:3081$url" || true
  if [ -s "$served" ] && head -c "$(wc -c < "$bundle")" "$served" | cmp -s - "$bundle"; then
    echo "dsh serves the checkout's client bundle"
    rm -f "$served"
  else
    rm -f "$served"
    echo "dsh is NOT serving $bundle — investigate before trusting the desk" >&2
    exit 1
  fi
fi
