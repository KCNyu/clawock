#!/usr/bin/env bash
# Reapply and verify every host-local OpenClaw dist patch that an upgrade wipes.
#
# This script intentionally does not restart the gateway. The upgrade operator
# must first prove that no cron run is in flight, then restart exactly once.
set -euo pipefail

RUN_MODE="${1:-apply}"
PATCH_ROOT="/root/tools/openclaw/current"
PATCH_SCRIPTS=(
  "$PATCH_ROOT/patch-embedding-threads1.sh"
  "$PATCH_ROOT/patch-memory-search-timeout.sh"
  "$PATCH_ROOT/patch-minimax-m3-priority.sh"
  "$PATCH_ROOT/patch-minimax-response-header-timeout.sh"
)

case "$RUN_MODE" in
  apply)
    for patch_script in "${PATCH_SCRIPTS[@]}"; do
      if [[ ! -x "$patch_script" ]]; then
        echo "[openclaw-patches] ERROR: missing executable $patch_script" >&2
        exit 1
      fi
      "$patch_script"
    done
    ;;
  --check-only)
    ;;
  *)
    echo "usage: $0 [--check-only]" >&2
    exit 2
    ;;
esac

OCLAW_REAL="$(realpath /root/.local/share/pnpm/global/5/node_modules/openclaw)"
DIST="$OCLAW_REAL/dist"
if [[ ! -d "$DIST" ]]; then
  echo "[openclaw-patches] ERROR: OpenClaw dist directory missing: $DIST" >&2
  exit 1
fi

PATCH_MARKERS=(
  "threads: 1, batchSize: 512"
  "const MEMORY_SEARCH_TOOL_TIMEOUT_MS = 60000;"
  "clawock-minimax-m3-priority"
  "clawock-minimax-response-header-timeout-v2"
)
PATCH_LABELS=(
  "single-thread local embeddings"
  "60s memory_search deadline"
  "MiniMax-M3 priority admission"
  "MiniMax 30s response-header deadline"
)

declare -a syntax_targets=()
for index in "${!PATCH_MARKERS[@]}"; do
  marker="${PATCH_MARKERS[$index]}"
  label="${PATCH_LABELS[$index]}"
  mapfile -t matches < <(
    grep -rlF --include='*.js' -- "$marker" "$DIST" 2>/dev/null || true
  )
  if [[ "${#matches[@]}" -eq 0 ]]; then
    echo "[openclaw-patches] ERROR: marker missing for $label" >&2
    exit 1
  fi
  syntax_targets+=("${matches[@]}")
  echo "[openclaw-patches] marker ok: $label"
done

mapfile -t unique_targets < <(printf '%s\n' "${syntax_targets[@]}" | sort -u)
for target in "${unique_targets[@]}"; do
  node --check "$target"
done
python3 -m py_compile "$PATCH_ROOT/memory_index_maintenance.py"

echo "[openclaw-patches] all four patches and modified bundles verified"
echo "[openclaw-patches] gateway was not restarted"
