#!/usr/bin/env bash
# Install the host extension outside pnpm. No configuration change or restart.
# --check verifies bytes; --rollback restores the last changed installation.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST_DIR="${SKILLHUB_PLUGIN_DIR:-${OPENCLAW_STATE_DIR:-$HOME/.openclaw}/extensions/skillhub}"
FILES=(index.ts openclaw.plugin.json)
case "${1:-}" in
  --check)
    for file in "${FILES[@]}"; do
      cmp "$ROOT/ops/host/skillhub/$file" "$DEST_DIR/$file"
    done
    echo "skillhub host extension matches this checkout"
    exit 0 ;;
  --rollback)
    # Require a complete recovery pair before replacing either file.
    for file in "${FILES[@]}"; do test -f "$DEST_DIR/$file.before-update"; done
    for file in "${FILES[@]}"; do
      stage="$(mktemp "$DEST_DIR/.$file.XXXXXX")"
      cp -p "$DEST_DIR/$file.before-update" "$stage"
      mv -f "$stage" "$DEST_DIR/$file"
    done
    echo "skillhub restored; restore the matching policy document before restarting"
    exit 0 ;;
  "") ;;
  *) echo "usage: $0 [--check|--rollback]" >&2; exit 2 ;;
esac
python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$ROOT/ops/host/skillhub/openclaw.plugin.json"
mkdir -p "$DEST_DIR"
changed=0
for file in "${FILES[@]}"; do
  cmp -s "$ROOT/ops/host/skillhub/$file" "$DEST_DIR/$file" || changed=1
done
if [ "$changed" = 1 ]; then
  # Save both, even when only one changed, so rollback cannot mix generations.
  for file in "${FILES[@]}"; do
    if [ -f "$DEST_DIR/$file" ]; then cp -p "$DEST_DIR/$file" "$DEST_DIR/$file.before-update"; fi
  done
  for file in "${FILES[@]}"; do
    stage="$(mktemp "$DEST_DIR/.$file.XXXXXX")"
    install -m 0644 "$ROOT/ops/host/skillhub/$file" "$stage"
    mv -f "$stage" "$DEST_DIR/$file"
  done
fi
bash "$ROOT/ops/host/install_skillhub_plugin.sh" --check
echo "gateway not restarted; schedule a safe restart to activate a changed hook"
