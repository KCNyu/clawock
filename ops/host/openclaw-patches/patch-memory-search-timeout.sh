#!/usr/bin/env bash
# Fix: `memory_search` fails on this 2-vCPU / 2GB VPS because openclaw gives the tool a
# hardcoded 15s deadline (MEMORY_SEARCH_TOOL_TIMEOUT_MS) that this hardware cannot meet
# from a cold provider. Measured 2026-07-27 on an already-clean index (471/471 files):
#
#   11:24:06 -> 11:24:21   15.4s  FAILED   ("memory_search timed out after 15s")
#   11:27:28 -> 11:27:40   11.8s  ok
#
# Same query, same index, no backlog. The variance is the 328MB embeddinggemma gguf being
# read back from disk: with 1.9GB of RAM the model is evicted from page cache constantly,
# so the load alone costs ~2s warm and ~9s cold, against a 15s total budget. The tool is
# therefore a coin flip rather than a broken feature, which is why it fails intermittently
# and reports an "embedding/provider error" that no provider config can fix.
#
# Raising the budget to 60s does not slow the healthy path down: the tool still returns as
# soon as the embedding resolves (11.8s in the run above). It only stops the deadline from
# firing while the model is still being paged in. 60s stays far inside the agent turn
# timeout (600s default).
#
# This patch lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every openclaw
# upgrade -> re-run this after each upgrade (idempotent). Same deal as
# patch-embedding-threads1.sh; memory_index_maintenance.py warns when either goes missing.
set -euo pipefail

TIMEOUT_MS="${1:-60000}"

# The argument is written straight into a JS bundle, so validate it here. A non-numeric
# value is not caught downstream: `const MEMORY_SEARCH_TOOL_TIMEOUT_MS = --check;` parses
# as a prefix decrement and passes `node --check`, then fails at runtime instead. This
# script takes no flags; anything that is not a plain millisecond count is a mistake.
if ! [[ "$TIMEOUT_MS" =~ ^[0-9]+$ ]]; then
  echo "[patch] ERROR: expected a millisecond count, got '${TIMEOUT_MS}' (this script takes no flags)" >&2
  exit 2
fi

OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
F=$(grep -rl "MEMORY_SEARCH_TOOL_TIMEOUT_MS" "$OCLAW_REAL/dist/" 2>/dev/null | head -1)
if [ -z "${F:-}" ] || [ ! -f "$F" ]; then
  echo "[patch] ERROR: MEMORY_SEARCH_TOOL_TIMEOUT_MS not found in $OCLAW_REAL/dist (bundle renamed?)" >&2
  exit 1
fi

CURRENT=$(grep -o "const MEMORY_SEARCH_TOOL_TIMEOUT_MS = [0-9e]*;" "$F" | head -1)
if [ -z "$CURRENT" ]; then
  echo "[patch] ERROR: could not read the current value in $F" >&2
  exit 1
fi

if [ "$CURRENT" = "const MEMORY_SEARCH_TOOL_TIMEOUT_MS = ${TIMEOUT_MS};" ]; then
  echo "[patch] already applied (${TIMEOUT_MS}ms): $F"
  exit 0
fi

python3 - "$F" "$TIMEOUT_MS" <<'PY'
import re, sys
path, value = sys.argv[1], sys.argv[2]
src = open(path, encoding="utf-8", errors="replace").read()
patched, n = re.subn(
    r"const MEMORY_SEARCH_TOOL_TIMEOUT_MS = [0-9e]+;",
    f"const MEMORY_SEARCH_TOOL_TIMEOUT_MS = {value};",
    src,
    count=1,
)
assert n == 1, "anchor 'const MEMORY_SEARCH_TOOL_TIMEOUT_MS = ...;' not found"
open(path, "w", encoding="utf-8").write(patched)
print(f"[patch] memory_search deadline -> {value}ms in {path}")
PY

echo "[patch] done. The constant is read at process start: restart the gateway to apply."
echo "[patch] Do NOT restart while a cron run is in flight (it orphans the run):"
echo "[patch]   openclaw cron list   # confirm nothing is 'running', then"
echo "[patch]   openclaw gateway restart"
