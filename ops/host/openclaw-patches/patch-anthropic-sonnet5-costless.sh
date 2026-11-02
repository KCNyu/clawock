#!/usr/bin/env bash
# Backport of upstream openclaw#102186 (merged 740e7687e, 2026-07-09) and its
# follow-up #115490: `openclaw models list` crashes with
# "Cannot read properties of undefined (reading 'input')" when an Anthropic
# Sonnet 5 row reaches normalization without a `cost` object.
#
# List rows are built without `cost`; `applyAnthropicSonnet5Cost` dereferences
# `params.model.cost.input` before falling through to the well-known Sonnet 5
# pricing the helper is meant to apply. Guard the comparison on an existing
# cost so a costless row gets the pricing instead of crashing.
#
# Lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every upgrade;
# re-run after each upgrade (ops/host/reapply_openclaw_patches.sh). Idempotent;
# refuses to edit when the source anchor no longer matches exactly.
set -euo pipefail

OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
DIST="$OCLAW_REAL/dist"
MARK="clawock-anthropic-sonnet5-costless-v1"
F=$(grep -rlF --include='*.js' -- "function applyAnthropicSonnet5Cost" "$DIST" 2>/dev/null | head -1 || true)

if [ -z "${F:-}" ] || [ ! -f "$F" ]; then
  echo "[patch] ERROR: cannot locate bundle containing applyAnthropicSonnet5Cost under $DIST" >&2
  exit 1
fi
if grep -qF -- "$MARK" "$F"; then
  echo "[patch] already applied: $F"
  exit 0
fi

cp -p "$F" "$F.pre-anthropic-sonnet5-costless.bak"
python3 - "$F" "$MARK" <<'PY'
from pathlib import Path
import os
import sys
import tempfile

path = Path(sys.argv[1])
mark = sys.argv[2]
src = path.read_text()

old = "\tif (params.model.cost.input === cost.input && params.model.cost.output === cost.output && params.model.cost.cacheRead === cost.cacheRead && params.model.cost.cacheWrite === cost.cacheWrite) return;\n"
new = (
    f"\tconst existingCost = params.model.cost; /* {mark} */\n"
    "\tif (existingCost && existingCost.input === cost.input && existingCost.output === cost.output && existingCost.cacheRead === cost.cacheRead && existingCost.cacheWrite === cost.cacheWrite) return;\n"
)
if src.count(old) != 1:
    raise SystemExit(
        f"[patch] ERROR: unguarded cost comparison anchor count {src.count(old)} != 1; "
        "inspect the current upstream implementation"
    )

patched = src.replace(old, new, 1)
if patched.count(mark) != 1 or patched.count("const existingCost = params.model.cost;") != 1:
    raise SystemExit("[patch] ERROR: marker/guard missing after edit")

fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".tmp.", suffix=".js")
try:
    with os.fdopen(fd, "w") as handle:
        handle.write(patched)
    os.chmod(tmp, path.stat().st_mode)
    os.replace(tmp, path)
except BaseException:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
print(f"[patch] edited {path}")
PY

if ! node --check "$F"; then
  echo "[patch] ERROR: syntax check failed; restoring pre-run bundle" >&2
  cp -p "$F.pre-anthropic-sonnet5-costless.bak" "$F"
  exit 1
fi
grep -qF -- "$MARK" "$F"
echo "[patch] applied: $F (restart the gateway to take effect)"
