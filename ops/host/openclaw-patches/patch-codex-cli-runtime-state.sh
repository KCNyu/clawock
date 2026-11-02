#!/usr/bin/env bash
# Compatibility shim for the CLI-metadata plugin load path on 2026.7.1-2.
#
# `loadOpenClawPluginCliRegistry` builds each plugin API with `runtime: {}`
# because CLI metadata loading has no gateway runtime. @openclaw/codex
# 2026.7.1-1 calls `api.runtime.state.openSyncKeyedStore(...)` at register time,
# so `api.runtime.state` is undefined and registration aborts with
# "Cannot read properties of undefined (reading 'openSyncKeyedStore')".
#
# Upstream later added createUnavailableRuntime("cli-metadata") and made the
# Codex plugin defer store access, but that pairing needs a newer core AND a
# newer plugin. This host is pinned to 2026.7.1-2, so give the CLI-metadata API
# a store that can be constructed eagerly but throws a clear error on first use.
# The Codex plugin only stores the reference during register; real gateway
# registration still receives the full runtime, so behavior there is unchanged.
#
# Lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every upgrade;
# re-run after each upgrade (ops/host/reapply_openclaw_patches.sh). Idempotent;
# refuses to edit when the source anchor no longer matches exactly.
set -euo pipefail

OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
DIST="$OCLAW_REAL/dist"
MARK="clawock-codex-cli-runtime-state-v1"
F=$(grep -rlF --include='*.js' -- 'registrationMode: "cli-metadata"' "$DIST" 2>/dev/null | head -1 || true)

if [ -z "${F:-}" ] || [ ! -f "$F" ]; then
  echo "[patch] ERROR: cannot locate CLI-metadata registration bundle under $DIST" >&2
  exit 1
fi
if grep -qF -- "$MARK" "$F"; then
  echo "[patch] already applied: $F"
  exit 0
fi

cp -p "$F" "$F.pre-codex-cli-runtime-state.bak"
python3 - "$F" "$MARK" <<'PY'
from pathlib import Path
import os
import sys
import tempfile

path = Path(sys.argv[1])
mark = sys.argv[2]
src = path.read_text()

old = (
    '\t\t\tregistrationMode: "cli-metadata",\n'
    '\t\t\tconfig: cfg,\n'
    '\t\t\tpluginConfig: validatedConfig.value,\n'
    '\t\t\truntime: {},\n'
)
new = (
    '\t\t\tregistrationMode: "cli-metadata",\n'
    '\t\t\tconfig: cfg,\n'
    '\t\t\tpluginConfig: validatedConfig.value,\n'
    '\t\t\truntime: { state: { openSyncKeyedStore: () => new Proxy({}, { get() { throw new Error("openSyncKeyedStore is unavailable during CLI metadata registration"); } }) } }, /* ' + mark + ' */\n'
)
if src.count(old) != 1:
    raise SystemExit(
        f"[patch] ERROR: CLI-metadata runtime anchor count {src.count(old)} != 1; "
        "inspect the current upstream loader"
    )

patched = src.replace(old, new, 1)
if patched.count(mark) != 1 or patched.count("openSyncKeyedStore is unavailable during CLI metadata registration") != 1:
    raise SystemExit("[patch] ERROR: marker/shim missing after edit")

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
  cp -p "$F.pre-codex-cli-runtime-state.bak" "$F"
  exit 1
fi
grep -qF -- "$MARK" "$F"
echo "[patch] applied: $F (restart the gateway to take effect)"
