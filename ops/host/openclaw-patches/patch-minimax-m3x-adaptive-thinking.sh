#!/usr/bin/env bash
# MiniMax-M3.1 (MiniMax-M3.1-Flash-Preview) rejects `thinking: {type:"disabled"}`
# with HTTP 400 "requires adaptive thinking ... is not allowed (2013)", which
# OpenClaw surfaces as "LLM request failed: provider rejected the request
# schema or tool payload."
#
# OpenClaw 2026.7.1's MiniMax payload wrapper rewrites the Anthropic transport's
# thinking payload to `adaptive` for M3.x -- except when the resolved thinking
# level is "off" (a session-persisted `/think off`, or a level inherited from a
# Claude/GPT primary before falling back), where it lets `disabled` through.
# It also drops the field entirely when no level is resolved.
#
# Make M3.x always carry `thinking: {type:"adaptive"}`, the same thing dsh's
# pi-ai sends for forced-adaptive models. M2.x handling is untouched.
#
# This patch lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every
# OpenClaw upgrade. Re-run it after each upgrade. It is idempotent and refuses
# to edit when the expected source anchors no longer match exactly.
set -euo pipefail

OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
DIST="$OCLAW_REAL/dist"
MARKER="clawock-minimax-m3x-adaptive-thinking"
F=$(grep -rl "function createMinimaxThinkingDisabledWrapper" "$DIST" \
  --include='*.js' 2>/dev/null | head -1)

if [ -z "${F:-}" ] || [ ! -f "$F" ]; then
  echo "[patch] ERROR: MiniMax payload wrapper not found in $DIST" >&2
  exit 1
fi

if grep -q "$MARKER" "$F"; then
  echo "[patch] already applied: $F"
  exit 0
fi

cp -p "$F" "$F.pre-minimax-adaptive-thinking.bak"

python3 - "$F" "$MARKER" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
marker = sys.argv[2]
source = path.read_text(encoding="utf-8", errors="replace")

before = '''\t\t\t\t\t\tif (thinkingLevel === void 0 && isDisabledThinkingPayload(payloadObj.thinking)) delete payloadObj.thinking;
\t\t\t\t\t\telse if (thinkingLevel !== "off" && (isEnabledThinkingPayload(payloadObj.thinking) || isDisabledThinkingPayload(payloadObj.thinking))) {
\t\t\t\t\t\t\tpayloadObj.thinking = { type: "adaptive" };'''
after = f'''\t\t\t\t\t\tif (payloadObj.thinking === void 0 || isEnabledThinkingPayload(payloadObj.thinking) || isDisabledThinkingPayload(payloadObj.thinking)) {{ /* {marker} */
\t\t\t\t\t\t\tpayloadObj.thinking = {{ type: "adaptive" }};'''

if source.count(before) != 1:
    raise SystemExit("[patch] ERROR: MiniMax M3 thinking anchor did not match exactly once")

path.write_text(source.replace(before, after, 1), encoding="utf-8")
print(f"[patch] MiniMax-M3.x always-adaptive thinking -> {path}")
PY

node --check "$F"
grep -q "$MARKER" "$F"
echo "[patch] syntax and marker verified"
echo "[patch] restart the gateway after confirming no cron run is in flight"
