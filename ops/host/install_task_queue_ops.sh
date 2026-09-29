#!/usr/bin/env bash
# install_task_queue_ops.sh — put the reviewed task_queue_ops.py (and the model price table its
# `usage` action reads) where the runner and the dsh task chip call it, the same way patrol.sh is
# installed: keep what ran before, install, prove the bytes match, and say how to go back.
# The OpenClaw `/dispatch-list` plugin rides along in openclaw-dispatch-list/: it runs the entry
# installed next to it, so both always come from one install. OpenClaw loads it through
# plugins.load.paths (this script prints the one-time setup) and picks up a change on restart.
#
#   ops/host/install_task_queue_ops.sh             # install from this checkout
#   ops/host/install_task_queue_ops.sh --check     # exit 1 when an installed copy differs
#   ops/host/install_task_queue_ops.sh --rollback  # restore the copies saved by the last install
#
# Merging does not install: /root/tools/agent-dispatch is host-local, and refresh_live.sh
# leaves it alone. The chip shows both hashes (installed vs. this repository's copy in the live
# checkout), so a merged-but-not-installed entry is visible there.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST_DIR="${AGENT_DISPATCH_DIR:-/root/tools/agent-dispatch}"
FILES=(task_queue_ops.py model_prices.json openclaw-dispatch-list/openclaw.plugin.json openclaw-dispatch-list/index.ts)

case "${1:-}" in
  --check)
    bad=0
    for f in "${FILES[@]}"; do
      if cmp -s "$ROOT/ops/host/$f" "$DEST_DIR/$f"; then echo "installed $f matches this checkout"
      else echo "installed $f differs from $ROOT/ops/host/$f (or is missing)" >&2; bad=1; fi
    done
    exit "$bad" ;;
  --rollback)
    for f in "${FILES[@]}"; do
      saved="$DEST_DIR/$f.before-update"
      if [ ! -f "$saved" ]; then echo "nothing to roll back for $f: $saved is missing"; continue; fi
      tmp=$(mktemp "$(dirname "$DEST_DIR/$f")/.$(basename "$f").XXXXXX")
      cp -p "$saved" "$tmp" && mv -f "$tmp" "$DEST_DIR/$f"
      cmp "$saved" "$DEST_DIR/$f"
      echo "restored $DEST_DIR/$f from $saved"
    done
    echo "ops entry now $(python3 "$DEST_DIR/task_queue_ops.py" version)"; exit 0 ;;
  "") ;;
  *) sed -n '2,12p' "$0" >&2; exit 2 ;;
esac

test -d "$DEST_DIR" || { echo "no $DEST_DIR: this host has no agent-dispatch installation" >&2; exit 1; }
python3 -m py_compile "$ROOT/ops/host/task_queue_ops.py"
python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "$ROOT/ops/host/model_prices.json"
for f in "${FILES[@]}"; do
  src="$ROOT/ops/host/$f" dest="$DEST_DIR/$f"
  if [ -f "$dest" ]; then
    if cmp -s "$src" "$dest"; then echo "$f already installed"; continue; fi
    cp -p "$dest" "$dest.before-update"
    echo "saved the previous $f as $dest.before-update"
  fi
  mkdir -p "$(dirname "$dest")"
  tmp=$(mktemp "$(dirname "$dest")/.$(basename "$f").XXXXXX")
  install -m "$([ "$f" = task_queue_ops.py ] && echo 0755 || echo 0644)" "$src" "$tmp"
  mv -f "$tmp" "$dest"
  cmp "$src" "$dest"
  echo "installed $dest"
done
echo "ops entry: $(python3 "$DEST_DIR/task_queue_ops.py" version)"
plugin="$DEST_DIR/openclaw-dispatch-list"
config="${OPENCLAW_CONFIG_PATH:-$HOME/.openclaw/openclaw.json}"
if [ -f "$config" ] && ! grep -qF "\"$plugin\"" "$config"; then
  echo "OpenClaw does not load $plugin yet: add it to plugins.load.paths, then restart the gateway"
else
  echo "OpenClaw /dispatch-list: restart the gateway if its plugin files changed above"
fi
echo "roll back: $0 --rollback"
