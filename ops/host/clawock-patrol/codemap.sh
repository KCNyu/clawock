#!/usr/bin/env bash
# Print the patrol code map path, rebuilding it only when the worktree's tracked code changed.
set -eu
WT=/root/wt-patrol OUT=/root/logs/clawock-patrol/codemap.md STAMP=/root/logs/clawock-patrol/.codemap.tree
tree=$(git -C "$WT" rev-parse HEAD^{tree})
if [ ! -s "$OUT" ] || [ "$(cat "$STAMP" 2>/dev/null)" != "$tree" ]; then
  python3 /root/tools/clawock-patrol/build_codemap.py "$WT" "$OUT.tmp" >&2 && mv -f "$OUT.tmp" "$OUT" && echo "$tree" >"$STAMP"
fi
echo "$OUT"
