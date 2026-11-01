#!/usr/bin/env bash
# Fix: openclaw local embedding worker HANGS on this 2-core VM because node-llama-cpp
# multi-threaded embedding deadlocks intermittently (getEmbeddingFor never returns after
# 1-2 successful calls on a shared context). Root-caused 2026-07-08 via worker debug logging.
# Fix = force single-threaded embedding context (threads:1). node-llama-cpp itself is fine;
# only the concurrent-thread compute path deadlocks under the gateway's CPU load.
#
# This patch lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every openclaw
# upgrade -> re-run this after each upgrade (idempotent).
set -euo pipefail
OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
E="$OCLAW_REAL/dist/embeddings-Molb7Y3n.js"
# The bundled filename hash can change across versions; find the file that defines createEmbeddingContext for the local provider.
if [ ! -f "$E" ]; then
  E=$(grep -rl "createEmbeddingContext({" "$OCLAW_REAL/dist/" 2>/dev/null | xargs grep -l "createLocalEmbeddingProviderInProcess" 2>/dev/null | head -1)
fi
[ -z "${E:-}" ] || [ ! -f "$E" ] && { echo "[patch] ERROR: embeddings dist file not found (bundle renamed?); grep dist for createEmbeddingContext"; exit 1; }
if grep -q "threads: 1, batchSize: 512" "$E"; then
  echo "[patch] already applied: $E"; exit 0
fi
python3 - "$E" <<'PY'
import re,sys
E=sys.argv[1]; s=open(E,encoding="utf-8",errors="replace").read()
s2=re.sub(r'(createEmbeddingContext\(\{\s*)(contextSize,)', r'\1threads: 1, batchSize: 512, \2', s, count=1)
assert "threads: 1, batchSize: 512" in s2, "anchor 'createEmbeddingContext({ contextSize,' not found"
open(E,"w",encoding="utf-8").write(s2)
print("[patch] applied threads:1 ->", E)
PY
echo "[patch] done. Restart gateway: systemctl --user restart openclaw-gateway.service"
