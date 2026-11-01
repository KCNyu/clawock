#!/usr/bin/env bash
# Expose the unrounded cache-hit percentage to the reply footer template.
#
# `buildUsageContract` rounds cacheRead/promptTotal to an integer for
# `usage.cache_hit_pct`, so a true 99.7% reaches the template as 100 and no
# template decimal can recover it. This patch adds
# `usage.cache_hit_pct_exact` (0-100 float, not rounded) and leaves the
# integer field, its semantics and the `last` block untouched.
#
# Lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every upgrade;
# re-run after each upgrade (ops/host/reapply_openclaw_patches.sh). Idempotent;
# refuses to edit when a source anchor no longer matches exactly.
#
# Usage:
#   patch-cache-hit-pct-exact.sh            # apply (safe to re-run)
#   patch-cache-hit-pct-exact.sh --revert   # remove only this patch's lines
set -euo pipefail

OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
DIST="$OCLAW_REAL/dist"
MARK="clawock-cache-hit-pct-exact-v1"
MODE="${1:-apply}"

F=$(grep -rlF --include='*.js' -- "function buildUsageContract" "$DIST" 2>/dev/null | head -1 || true)
if [ -z "$F" ] || [ ! -f "$F" ]; then
  echo "[patch] ERROR: cannot locate bundle containing buildUsageContract under $DIST" >&2
  exit 1
fi

case "$MODE" in
  apply)
    if grep -qF -- "$MARK" "$F"; then
      echo "[patch] already applied: $F"
      exit 0
    fi
    # Keep a pristine copy for emergency/manual rollback. `--revert` is
    # surgical instead, because other host patches also edit this bundle.
    if [ ! -f "$F.pre-cache-hit-exact.bak" ]; then
      cp -p "$F" "$F.pre-cache-hit-exact.bak"
    fi

    ROLLBACK=$(mktemp "$F.cache-hit-exact.rollback.XXXXXX")
    cp -p "$F" "$ROLLBACK"
    trap 'rm -f "$ROLLBACK"' EXIT

    python3 - "$F" "$MARK" <<'PY'
from pathlib import Path
import os
import sys
import tempfile

path = Path(sys.argv[1])
mark = sys.argv[2]
src = path.read_text()

anchor_fn = '\tconst cacheHitPct = promptTotal > 0 ? Math.round((cacheRead ?? 0) / promptTotal * 100) : void 0;\n'
added_fn = (
    anchor_fn
    + f'\tconst cacheHitPctExact = promptTotal > 0 ? (cacheRead ?? 0) / promptTotal * 100 : void 0; /* {mark} */\n'
)
if src.count(added_fn) == 1:
    raise SystemExit("[patch] ERROR: exact field already present without marker; refusing to guess")
if src.count(anchor_fn) != 1:
    raise SystemExit(f"[patch] ERROR: cacheHitPct anchor count {src.count(anchor_fn)} != 1")

anchor_prop = '\t\t\tcache_hit_pct: cacheHitPct,\n'
added_prop = (
    anchor_prop
    + '\t\t\tcache_hit_pct_exact: cacheHitPctExact,\n'
)
if src.count(anchor_prop) != 1:
    raise SystemExit(f"[patch] ERROR: cache_hit_pct property anchor count {src.count(anchor_prop)} != 1")
if "cache_hit_pct_exact" in src:
    raise SystemExit("[patch] ERROR: cache_hit_pct_exact already present without marker; refusing to guess")

patched = src.replace(anchor_fn, added_fn, 1).replace(anchor_prop, added_prop, 1)
if patched.count(mark) != 1 or patched.count("cache_hit_pct_exact: cacheHitPctExact") != 1:
    raise SystemExit("[patch] ERROR: marker/property missing after edit")

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
      cp -p "$ROLLBACK" "$F"
      exit 1
    fi
    grep -qF -- "cache_hit_pct_exact: cacheHitPctExact" "$F"
    echo "[patch] applied: $F"
    echo "[patch] restart the gateway to take effect"
    ;;
  --revert)
    if ! grep -qF -- "$MARK" "$F"; then
      echo "[patch] not applied: $F"
      exit 0
    fi

    ROLLBACK=$(mktemp "$F.cache-hit-exact.rollback.XXXXXX")
    cp -p "$F" "$ROLLBACK"
    trap 'rm -f "$ROLLBACK"' EXIT

    python3 - "$F" "$MARK" <<'PY'
from pathlib import Path
import os
import sys
import tempfile

path = Path(sys.argv[1])
mark = sys.argv[2]
src = path.read_text()

added_fn = f'\tconst cacheHitPctExact = promptTotal > 0 ? (cacheRead ?? 0) / promptTotal * 100 : void 0; /* {mark} */\n'
added_prop = '\t\t\tcache_hit_pct_exact: cacheHitPctExact,\n'
if src.count(added_fn) != 1:
    raise SystemExit(f"[patch] ERROR: added function line count {src.count(added_fn)} != 1")
if src.count(added_prop) != 1:
    raise SystemExit(f"[patch] ERROR: added property line count {src.count(added_prop)} != 1")

reverted = src.replace(added_fn, "", 1).replace(added_prop, "", 1)
if mark in reverted or "cache_hit_pct_exact" in reverted:
    raise SystemExit("[patch] ERROR: marker/property still present after revert")

fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".tmp.", suffix=".js")
try:
    with os.fdopen(fd, "w") as handle:
        handle.write(reverted)
    os.chmod(tmp, path.stat().st_mode)
    os.replace(tmp, path)
except BaseException:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
print(f"[patch] reverted {path}")
PY

    if ! node --check "$F"; then
      echo "[patch] ERROR: syntax check failed; restoring pre-revert bundle" >&2
      cp -p "$ROLLBACK" "$F"
      exit 1
    fi
    echo "[patch] reverted: $F"
    echo "[patch] restart the gateway to take effect"
    ;;
  *)
    echo "usage: $0 [--revert]" >&2
    exit 2
    ;;
esac
