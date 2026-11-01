#!/usr/bin/env bash
# Upgrade entry: the tracked kit stages and verifies all dist patches before writing.
# Plugin installation stays separate. This script never restarts the gateway.
set -euo pipefail
HOST="$(cd "$(dirname "$0")" && pwd)"
case "${1:-apply}" in
  apply)
    python3 "$HOST/manage_openclaw_patches.py" apply
    bash "$HOST/install_skillhub_plugin.sh"
    bash "$HOST/install_memory_corpus_plugin.sh"
    ;;
  --check-only)
    python3 "$HOST/manage_openclaw_patches.py" check
    bash "$HOST/install_skillhub_plugin.sh" --check
    bash "$HOST/install_memory_corpus_plugin.sh" --check
    ;;
  --plan)
    exec python3 "$HOST/manage_openclaw_patches.py" plan
    ;;
  *) echo "usage: $0 [--plan|--check-only]" >&2; exit 2 ;;
esac
echo '[openclaw-patches] patch kit and host extensions verified; gateway was not restarted'
