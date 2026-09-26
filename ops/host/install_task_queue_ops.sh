#!/usr/bin/env bash
# install_task_queue_ops.sh — put the reviewed task_queue_ops.py where the runner and the dsh
# task chip call it, the same way patrol.sh is installed: keep what ran before, install,
# prove the bytes match, and say how to go back.
#
#   ops/host/install_task_queue_ops.sh             # install from this checkout
#   ops/host/install_task_queue_ops.sh --check     # exit 1 when the installed copy differs
#   ops/host/install_task_queue_ops.sh --rollback  # restore the copy saved by the last install
#
# Merging does not install: /root/tools/agent-dispatch is host-local, and refresh_live.sh
# leaves it alone. The chip shows both hashes (installed vs. this repository's copy in the live
# checkout), so a merged-but-not-installed entry is visible there.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$ROOT/ops/host/task_queue_ops.py"
DEST_DIR="${AGENT_DISPATCH_DIR:-/root/tools/agent-dispatch}"
DEST="$DEST_DIR/task_queue_ops.py"
SAVED="$DEST.before-update"

case "${1:-}" in
  --check)
    if cmp -s "$SRC" "$DEST"; then echo "installed task_queue_ops.py matches $SRC"; exit 0; fi
    echo "installed task_queue_ops.py differs from $SRC (or is missing)" >&2; exit 1 ;;
  --rollback)
    [ -f "$SAVED" ] || { echo "nothing to roll back to: $SAVED is missing" >&2; exit 1; }
    tmp=$(mktemp "$DEST_DIR/.task_queue_ops.XXXXXX")
    cp -p "$SAVED" "$tmp" && chmod 0755 "$tmp" && mv -f "$tmp" "$DEST"
    cmp "$SAVED" "$DEST"
    echo "restored $DEST from $SAVED ($(python3 "$DEST" version))"; exit 0 ;;
  "") ;;
  *) sed -n '2,12p' "$0" >&2; exit 2 ;;
esac

test -d "$DEST_DIR" || { echo "no $DEST_DIR: this host has no agent-dispatch installation" >&2; exit 1; }
python3 -m py_compile "$SRC"
if [ -f "$DEST" ]; then
  if cmp -s "$SRC" "$DEST"; then echo "already installed ($(python3 "$DEST" version))"; exit 0; fi
  cp -p "$DEST" "$SAVED"
  echo "saved the previous copy as $SAVED"
fi
# Atomic: the runner may call the entry at any moment; it must see the old file or the new one.
tmp=$(mktemp "$DEST_DIR/.task_queue_ops.XXXXXX")
install -m 0755 "$SRC" "$tmp"
mv -f "$tmp" "$DEST"
cmp "$SRC" "$DEST"
echo "installed $DEST ($(python3 "$DEST" version))"
echo "roll back: $0 --rollback"
