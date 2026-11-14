#!/usr/bin/env bash
# install_task_queue_ops.sh — put the reviewed task_queue_ops.py (and the model price table its
# `usage` action reads) where the runner and the dsh task chip call it, the same way patrol.sh is
# installed: keep what ran before, install, prove the bytes match, and say how to go back.
#
#   ops/host/install_task_queue_ops.sh             # install from this checkout
#   ops/host/install_task_queue_ops.sh --check     # exit 1 when an installed copy differs
#   ops/host/install_task_queue_ops.sh --rollback  # restore the copies saved by the last install
#
# Merging does not install: /root/tools/agent-dispatch is host-local, and refresh_live.sh
# installs it whenever the installed bytes differ, including when the checkout is current.
# The chip also shows installed vs. checkout hashes. Installation does not restart services.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST_DIR="${AGENT_DISPATCH_DIR:-/root/tools/agent-dispatch}"
FILES=(task_queue_ops.py model_prices.json)
# The tolerant JSON reader the ops entry imports; the runner installer ships the
# same bytes, so either installer makes it present and both --checks compare it.
SHARED=dispatch_json.py
SHARED_SRC="$ROOT/ops/host/agent-dispatch/$SHARED"

case "${1:-}" in
  --check)
    bad=0
    for f in "${FILES[@]}"; do
      if cmp -s "$ROOT/ops/host/$f" "$DEST_DIR/$f"; then echo "installed $f matches this checkout"
      else echo "installed $f differs from $ROOT/ops/host/$f (or is missing)" >&2; bad=1; fi
    done
    if cmp -s "$SHARED_SRC" "$DEST_DIR/$SHARED"; then echo "installed $SHARED matches this checkout"
    else echo "installed $SHARED differs from $SHARED_SRC (or is missing)" >&2; bad=1; fi
    exit "$bad" ;;
  --rollback)
    for f in "${FILES[@]}" "$SHARED"; do
      saved="$DEST_DIR/$f.before-update"
      if [ ! -f "$saved" ]; then echo "nothing to roll back for $f: $saved is missing"; continue; fi
      tmp=$(mktemp "$DEST_DIR/.$f.XXXXXX")
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
  tmp=$(mktemp "$DEST_DIR/.$f.XXXXXX")
  install -m "$([ "$f" = task_queue_ops.py ] && echo 0755 || echo 0644)" "$src" "$tmp"
  mv -f "$tmp" "$dest"
  cmp "$src" "$dest"
  echo "installed $dest"
done
src="$SHARED_SRC" dest="$DEST_DIR/$SHARED"
if [ -f "$dest" ]; then
  if cmp -s "$src" "$dest"; then echo "$SHARED already installed"
  else
    cp -p "$dest" "$dest.before-update"
    echo "saved the previous $SHARED as $dest.before-update"
  fi
fi
if [ ! -f "$dest" ] || ! cmp -s "$src" "$dest"; then
  tmp=$(mktemp "$DEST_DIR/.$SHARED.XXXXXX")
  install -m 0644 "$src" "$tmp"
  mv -f "$tmp" "$dest"
  cmp "$src" "$dest"
  echo "installed $dest"
fi
echo "ops entry: $(python3 "$DEST_DIR/task_queue_ops.py" version)"
echo "roll back: $0 --rollback"
