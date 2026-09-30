#!/usr/bin/env bash
# install_patrol_assets.sh — put the reviewed clawock-patrol round assets (prompts, lessons, axes,
# rotation, surfaces, the filing gate and its helpers, the service unit) where the patrol reads
# them on this host: keep what ran before, install each file atomically, prove the bytes match,
# say how to go back.
#
#   ops/host/install_patrol_assets.sh             # install from this checkout
#   ops/host/install_patrol_assets.sh --check     # exit 1 when an installed copy differs
#   ops/host/install_patrol_assets.sh --rollback  # undo the last install that changed anything
#
# ops/host/clawock-patrol/ mirrors /root/tools/clawock-patrol/ path for path. Every round reads
# these files afresh, so nothing is restarted; merging does not install, refresh_live.sh runs
# this when --check fails. Not installed here, on purpose: patrol.sh (ops/host/patrol.sh, its own
# install and restart in ops/host/README.md § Patrol supervisor), steer.md (kcn's standing
# instructions, written by `patrol.sh steer`), *.before-update, __pycache__/, and everything
# under /root/logs/clawock-patrol.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/ops/host/clawock-patrol"
DEST_DIR="${PATROL_TOOL_DIR:-/root/tools/clawock-patrol}"
# Every tracked file under ops/host/clawock-patrol/, and nothing else
# (tests/test_install_patrol_assets.py holds the two lists together).
FILES=(
  README.md
  round-prompt.md
  closed-lessons.md
  closed-lessons-examples.md
  hunting-patterns.md
  investigation-guide.md
  issue-format.md
  axes.tsv
  rotation
  surfaces.json
  gate_issue.py
  triage.py
  filing.py
  patrol_intel.py
  peers.json
  file_issue.sh
  issue-context.py
  codemap.sh
  build_codemap.py
  clawock-patrol.service
)
# What the last install changed, one "<saved|new>\t<file>" line each: --rollback undoes exactly
# that, not every .before-update lying around from older hand edits.
LAST="$DEST_DIR/.install-patrol-assets.last"

case "${1:-}" in
  --check)
    bad=0
    for f in "${FILES[@]}"; do
      if ! cmp -s "$SRC_DIR/$f" "$DEST_DIR/$f"; then
        echo "installed $f differs from $SRC_DIR/$f (or is missing)" >&2; bad=1
      fi
    done
    [ "$bad" = 0 ] && echo "all ${#FILES[@]} installed files match this checkout"
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
  *) sed -n '2,16p' "$0" >&2; exit 2 ;;
esac

test -d "$DEST_DIR" || { echo "no $DEST_DIR: this host has no clawock-patrol installation" >&2; exit 1; }
# Parse everything before replacing anything. No py_compile: it would drop __pycache__ into
# the checkout.
for f in "${FILES[@]}"; do
  src="$SRC_DIR/$f"
  test -f "$src" || { echo "missing from this checkout: $src" >&2; exit 1; }
  case "$f" in
    *.sh) bash -n "$src" ;;
    *.py) python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' "$src" ;;
    *.json) python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "$src" ;;
  esac
done

# One file at a time, each by rename: a round that is reading or running one keeps the inode it
# opened; the next read gets the new file.
changed=()
for f in "${FILES[@]}"; do
  src="$SRC_DIR/$f" dest="$DEST_DIR/$f"
  if cmp -s "$src" "$dest"; then continue; fi
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
if printf '%s\n' "${changed[@]}" | grep -q 'clawock-patrol\.service$'; then
  echo "note: the unit file changed; it takes effect after 'systemctl daemon-reload' and a restart of clawock-patrol.service (not done here)"
fi
echo "roll back: $0 --rollback"
