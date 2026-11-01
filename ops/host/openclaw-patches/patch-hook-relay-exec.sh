#!/usr/bin/env bash
# Backport of upstream openclaw#109446 (merged 2026-07-21, after 2026.7.1):
# Codex runs each native hook as `sh -c "<cmd>"` and on its hook timeout (10s)
# kills only that shell. Without `exec` the `openclaw hooks relay` node child
# survives as an orphan (~210MB each). On 2026-10-19 ~20 of them piled up
# under swap pressure and froze the 2GB host. With `exec` the relay *is* the
# shell process, so the timeout kills it. No behaviour change otherwise.
#
# Lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every upgrade;
# re-run after each upgrade (ops/host/reapply_openclaw_patches.sh). Idempotent;
# refuses to edit when the source anchor no longer matches exactly.
set -euo pipefail

OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
DIST="$OCLAW_REAL/dist"
MARKER="clawock-hook-relay-exec"
F=$(grep -rl "function buildNativeHookRelayCommand" "$DIST" --include='*.js' 2>/dev/null | head -1)

if [ -z "${F:-}" ] || [ ! -f "$F" ]; then
  echo "[patch] ERROR: buildNativeHookRelayCommand not found in $DIST" >&2
  exit 1
fi
if grep -q "$MARKER" "$F"; then
  echo "[patch] already applied: $F"
  exit 0
fi
if grep -q 'NATIVE_HOOK_RELAY_EXEC_PREFIX\|`exec ${command}`' "$F"; then
  echo "[patch] upstream already execs relays (#109446); nothing to do: $F"
  exit 0
fi

cp -p "$F" "$F.pre-hook-relay-exec.bak"
python3 - "$F" "$MARKER" <<'PY'
import sys
from pathlib import Path
path, marker = Path(sys.argv[1]), sys.argv[2]
src = path.read_text()
start = src.index("function buildNativeHookRelayCommand(params) {")
end = src.index("\n}\n", start)
body = src[start:end]
old = "\treturn shellQuoteArgs(["
if body.count(old) != 1:
    sys.exit(f"[patch] ERROR: anchor count {body.count(old)} != 1 in buildNativeHookRelayCommand")
new = f'\treturn (process.platform === "win32" ? "" : "exec ") /* {marker} */ + shellQuoteArgs(['
path.write_text(src[:start] + body.replace(old, new) + src[end:])
PY
node --check "$F"
grep -q "$MARKER" "$F"
echo "[patch] applied: $F (restart the gateway to take effect)"
