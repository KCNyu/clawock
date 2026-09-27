#!/usr/bin/env bash
# install_agent_dispatch.sh — put the reviewed agent-dispatch runner (run-agent.sh, dispatch.sh,
# their helpers, the review template and the runner's own tests) where it runs on this host:
# keep what ran before, install each file atomically, prove the bytes match, say how to go back.
#
#   ops/host/install_agent_dispatch.sh             # install from this checkout
#   ops/host/install_agent_dispatch.sh --check     # exit 1 when an installed copy differs
#   ops/host/install_agent_dispatch.sh --rollback  # undo the last install that changed anything
#
# ops/host/agent-dispatch/ mirrors /root/tools/agent-dispatch/ path for path. Merging does not
# install; refresh_live.sh runs this after a fast-forward that moved ops/host/agent-dispatch/.
# Not installed here, on purpose (docs/architecture/task-queue.md § What stays on the host):
# task_queue_ops.py + model_prices.json (install_task_queue_ops.sh owns them), limits.env
# (live policy shared with clawock-patrol), notify.env (delivery targets), *.before-update,
# __pycache__/, and everything under /root/logs/agent-dispatch.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/ops/host/agent-dispatch"
DEST_DIR="${AGENT_DISPATCH_DIR:-/root/tools/agent-dispatch}"
# Every tracked file under ops/host/agent-dispatch/, and nothing else
# (tests/test_install_agent_dispatch.py holds the two lists together).
FILES=(
  run-agent.sh
  dispatch.sh
  read-result.py
  quota.mjs
  resource-pressure.sh
  probe-free-models.sh
  opencode-fallback-models
  templates/review.md
  tests/run-tests.sh
  tests/test_limits.py
  tests/test_read_result.py
  tests/bin/claude
  tests/bin/codex
  tests/bin/fake-quota
  tests/bin/openclaw
  tests/bin/opencode
)
# The runner sources limits.env and cannot start without these; the host owns their values.
LIMIT_KEYS=(MAX_RUNNING_CLAUDE MAX_RUNNING_CODEX MAX_RUNNING_OPENCODE
            PATROL_MIN_AVAILABLE_KB PATROL_MAX_MEMORY_FULL_AVG60 QUEUE_FAIR_WAIT_SEC)
# What the last install changed, one "<saved|new>\t<file>" line each: --rollback undoes exactly
# that, not every .before-update lying around from older hand edits.
LAST="$DEST_DIR/.install-agent-dispatch.last"

limits_missing() {  # prints the LIMIT_KEYS the host's limits.env does not set
  [ -r "$DEST_DIR/limits.env" ] || { echo "limits.env"; return; }
  bash -c '. "$1"; shift; for k; do [ -n "${!k:-}" ] || echo "$k"; done' _ \
    "$DEST_DIR/limits.env" "${LIMIT_KEYS[@]}"
}

case "${1:-}" in
  --check)
    bad=0
    for f in "${FILES[@]}"; do
      if ! cmp -s "$SRC_DIR/$f" "$DEST_DIR/$f"; then
        echo "installed $f differs from $SRC_DIR/$f (or is missing)" >&2; bad=1
      fi
    done
    [ "$bad" = 0 ] && echo "all ${#FILES[@]} installed files match this checkout"
    missing="$(limits_missing)"
    if [ -n "$missing" ]; then echo "host limits.env lacks: $(echo $missing)" >&2; bad=1; fi
    [ -f "$DEST_DIR/notify.env" ] || echo "note: no $DEST_DIR/notify.env — tasks that ask for a notification will log 'missing'"
    exit "$bad" ;;
  --rollback)
    [ -s "$LAST" ] || { echo "nothing to roll back: $LAST is missing or empty"; exit 0; }
    while IFS=$'\t' read -r how f; do
      dest="$DEST_DIR/$f"
      if [ "$how" = new ]; then
        rm -f "$dest"; echo "removed $dest (the last install created it)"; continue
      fi
      tmp=$(mktemp "$(dirname "$dest")/.$(basename "$f").XXXXXX")
      cp -p "$dest.before-update" "$tmp" && mv -f "$tmp" "$dest"
      cmp "$dest.before-update" "$dest"
      echo "restored $dest from $dest.before-update"
    done <"$LAST"
    rm -f "$LAST"
    exit 0 ;;
  "") ;;
  *) sed -n '2,15p' "$0" >&2; exit 2 ;;
esac

test -d "$DEST_DIR" || { echo "no $DEST_DIR: this host has no agent-dispatch installation" >&2; exit 1; }
missing="$(limits_missing)"
if [ -n "$missing" ]; then
  echo "refusing: $DEST_DIR/limits.env must exist and set $(echo $missing) (host policy, not shipped)" >&2
  exit 1
fi
# Parse everything before replacing anything. No py_compile: it would drop __pycache__ into
# the checkout.
for f in "${FILES[@]}"; do
  src="$SRC_DIR/$f"
  test -f "$src" || { echo "missing from this checkout: $src" >&2; exit 1; }
  case "$f:$(head -n1 "$src")" in
    *.sh:*|*:'#!/usr/bin/env bash') bash -n "$src" ;;
    *.py:*) python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' "$src" ;;
    *.mjs:*) ! command -v node >/dev/null || node --check "$src" ;;
  esac
done

# One file at a time, each by rename: a runner that is running keeps reading the inode it
# opened (bash reads a script as it goes, so an in-place copy would corrupt running tasks);
# the next task starts on the new file.
changed=()
for f in "${FILES[@]}"; do
  src="$SRC_DIR/$f" dest="$DEST_DIR/$f"
  if cmp -s "$src" "$dest"; then continue; fi
  mkdir -p "$(dirname "$dest")"
  if [ -f "$dest" ]; then
    cp -p "$dest" "$dest.before-update"
    changed+=("saved	$f")
    echo "saved the previous $f as $dest.before-update"
  else
    changed+=("new	$f")
  fi
  tmp=$(mktemp "$(dirname "$dest")/.$(basename "$f").XXXXXX")
  install -m "$([ -x "$src" ] && echo 0755 || echo 0644)" "$src" "$tmp"
  mv -f "$tmp" "$dest"
  cmp "$src" "$dest"
  echo "installed $dest"
done

if [ "${#changed[@]}" = 0 ]; then
  echo "all ${#FILES[@]} files already installed"
  exit 0
fi
printf '%s\n' "${changed[@]}" >"$LAST"
echo "runner now: RUNNER_API=$(sed -n 's/^RUNNER_API=//p' "$DEST_DIR/run-agent.sh")"
echo "roll back: $0 --rollback"
