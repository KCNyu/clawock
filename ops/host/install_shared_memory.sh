#!/usr/bin/env bash
# install_shared_memory.sh — put the reviewed shared-memory toolkit (the skill coding agents
# load, memory.py, memctl, the Claude hook and the wiring file) where the agents find it:
# keep what ran before, install each file atomically, prove the bytes match, say how to go back.
#
#   ops/host/install_shared_memory.sh            # install from this checkout
#   ops/host/install_shared_memory.sh --check    # exit 1 when an installed file differs
#   ops/host/install_shared_memory.sh --units    # also render + enable the two systemd timers
#   ops/host/install_shared_memory.sh --rollback # undo the last install that changed anything
#
# ops/host/shared-memory/ mirrors the installed skill directory path for path
# (default ~/.agents/skills/shared-memory; SHARED_MEMORY_SKILL_DIR overrides). Each agent's own
# skill directory links there; `memctl doctor` checks the links. Not installed: the memory
# itself, its history and ledger (~/.local/state/shared-memory), and the OpenClaw corpus plugin
# (install_memory_corpus_plugin.sh). Merging does not install; refresh_live.sh runs this after
# a fast-forward that moved ops/host/shared-memory/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$ROOT/ops/host/shared-memory"
DEST_DIR="${SHARED_MEMORY_SKILL_DIR:-$HOME/.agents/skills/shared-memory}"
UNIT_DIR="${SHARED_MEMORY_UNIT_DIR:-/etc/systemd/system}"
# Every tracked file the skill directory holds (tests/test_install_shared_memory.py holds the
# list and the checkout together).
FILES=(
  SKILL.md
  README.md
  wiring.json
  references/maintenance.md
  scripts/memory.py
  scripts/memctl
  hooks/claude-hook.sh
  agents/openai.yaml
)
# Older installs shipped these; an install moves them aside (as .before-update) so the
# directory holds only the current toolkit.
RETIRED=(
  scripts/test_memory_format.py
)
UNITS=(
  shared-memory-snapshot.service
  shared-memory-snapshot.timer
  shared-memory-daily.service
  shared-memory-daily.timer
)
LAST="$DEST_DIR/.install-shared-memory.last"

render_unit() {  # <unit> -> stdout; the daily deep check needs every agent CLI on PATH
  local path="" bin
  for bin in node codex dsh opencode claude git; do
    bin=$(command -v "$bin" 2>/dev/null) || continue
    case ":$path:" in *":$(dirname "$bin"):"*) ;; *) path="${path:+$path:}$(dirname "$bin")" ;; esac
  done
  path="${path:+$path:}/usr/local/bin:/usr/bin:/bin"
  sed -e "s|@SKILL_DIR@|$DEST_DIR|g" -e "s|@HOME@|$HOME|g" -e "s|@PATH@|$path|g" "$SRC_DIR/systemd/$1"
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
      echo "restored $dest from $dest.before-update"
    done <"$LAST"
    rm -f "$LAST"
    exit 0 ;;
  ""|--units) ;;
  *) sed -n '2,16p' "$0" >&2; exit 2 ;;
esac

# Parse everything before replacing anything (no py_compile: it would write __pycache__).
for f in "${FILES[@]}"; do
  src="$SRC_DIR/$f"
  test -f "$src" || { echo "missing from this checkout: $src" >&2; exit 1; }
  case "$f:$(head -n1 "$src")" in
    *.sh:*) bash -n "$src" ;;
    *.py:*|*:'#!/usr/bin/env python3') python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' "$src" ;;
    *.json:*) python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "$src" ;;
  esac
done

mkdir -p "$DEST_DIR"
changed=()
for f in "${FILES[@]}"; do
  src="$SRC_DIR/$f" dest="$DEST_DIR/$f"
  if cmp -s "$src" "$dest"; then continue; fi
  mkdir -p "$(dirname "$dest")"
  if [ -f "$dest" ]; then
    cp -p "$dest" "$dest.before-update"
    changed+=("saved	$f")
  else
    changed+=("new	$f")
  fi
  tmp=$(mktemp "$(dirname "$dest")/.$(basename "$f").XXXXXX")
  install -m "$([ -x "$src" ] && echo 0755 || echo 0644)" "$src" "$tmp"
  mv -f "$tmp" "$dest"
  cmp "$src" "$dest"
  echo "installed $dest"
done
for f in "${RETIRED[@]}"; do
  if [ -f "$DEST_DIR/$f" ]; then
    mv -f "$DEST_DIR/$f" "$DEST_DIR/$f.before-update"
    changed+=("saved	$f")
    echo "retired $DEST_DIR/$f (kept as .before-update)"
  fi
done
if [ "${#changed[@]}" = 0 ]; then
  echo "all ${#FILES[@]} files already installed"
else
  printf '%s\n' "${changed[@]}" >"$LAST"
  echo "roll back: $0 --rollback"
fi

if [ "${1:-}" = "--units" ]; then
  reload=0
  for unit in "${UNITS[@]}"; do
    if ! render_unit "$unit" | cmp -s - "$UNIT_DIR/$unit"; then
      [ -f "$UNIT_DIR/$unit" ] && cp -p "$UNIT_DIR/$unit" "$UNIT_DIR/$unit.before-update"
      render_unit "$unit" >"$UNIT_DIR/.$unit.tmp" && mv -f "$UNIT_DIR/.$unit.tmp" "$UNIT_DIR/$unit"
      echo "wrote $UNIT_DIR/$unit"; reload=1
    fi
  done
  if [ "$reload" = 1 ] && [ "$UNIT_DIR" = /etc/systemd/system ]; then
    systemctl daemon-reload
    systemctl enable --now shared-memory-snapshot.timer shared-memory-daily.timer
  fi
fi
echo "first install on a host: $DEST_DIR/scripts/memctl init (history), then memctl doctor"
