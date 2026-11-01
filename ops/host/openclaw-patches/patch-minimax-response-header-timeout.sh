#!/usr/bin/env bash
# MiniMax can hold a streaming request for 100–143 seconds before returning an
# HTTP 429 overloaded_error. OpenClaw's existing 300s request timeout protects
# valid slow generations, so do not lower it. Instead, add a MiniMax-only
# deadline for receiving HTTP response headers. Once headers arrive, the timer
# is cleared and the original stream/generation timeout remains in force.
#
# THE DEADLINE IS A CALIBRATION, NOT A CONSTANT. It separates two measured
# populations, and the success population drifts right as injected context
# grows. Re-measure separately before assuming the current value is safe.
# The patch kit intentionally contains no credential lookup or live provider probe.
#
#   2026-07-29/30, deadline 30s:
#     91 successful M3 requests: max header latency  18.362s
#      6 overloaded 429s:        min header latency 101.530s
#
#   2026-08-13, same deadline, after context growth (issue #506):
#     header latency scales with prefill size, measured on this host —
#       244 KB ->  4.07s | 489 KB ->  7.51s | 978 KB -> 24.0s (cold 27.7s)
#     The pre-open brief carries the largest context of the 11 cron jobs, so it
#     was the only one to cross 30s. Both its 08:00 run and its 08:30 retry
#     aborted; that is criterion (1) for reopening the fallback-chain question.
#     Deadline raised 30s -> 60s: still far under the 101.5s overload floor,
#     with headroom over the 28s worst observed success.
#
# This dist patch is wiped by every OpenClaw upgrade. It is idempotent and
# refuses to edit unless all source anchors match exactly once.
set -euo pipefail

# The one place the deadline is defined. Everything else is derived.
DEADLINE_MS=60000
DEADLINE_LITERAL=6e4

MARKER="clawock-minimax-response-header-timeout-v3"
MARKER_V2="clawock-minimax-response-header-timeout-v2"
MARKER_V1="clawock-minimax-response-header-timeout"

OCLAW_REAL="${CLAWOCK_PATCH_STAGE:?Use manage_openclaw_patches.py; adapters only edit a staging tree}"
DIST="$OCLAW_REAL/dist"

F=$(grep -rl 'function buildGuardedModelFetch(model, timeoutMs, options)' "$DIST" \
  --include='*.js' 2>/dev/null | head -1)

if [ -z "${F:-}" ] || [ ! -f "$F" ]; then
  echo "[patch] ERROR: provider transport bundle not found in $DIST" >&2
  exit 1
fi

if grep -q "$MARKER" "$F"; then
  echo "[patch] already applied: $F"
  exit 0
fi

# Marker order matters: v1's string is a prefix of v2's and v3's, so the newest
# must be ruled out first. (Checked above.)
if grep -q "$MARKER_V2" "$F"; then
  cp -p "$F" "$F.pre-minimax-header-timeout-v3.bak"
elif grep -q "$MARKER_V1" "$F"; then
  cp -p "$F" "$F.pre-minimax-header-timeout-v2.bak"
else
  cp -p "$F" "$F.pre-minimax-header-timeout.bak"
fi

python3 - "$F" "$MARKER" "$MARKER_V2" "$MARKER_V1" "$DEADLINE_MS" "$DEADLINE_LITERAL" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
marker, marker_v2, marker_v1 = sys.argv[2], sys.argv[3], sys.argv[4]
deadline_ms, deadline_literal = sys.argv[5], sys.argv[6]
source = path.read_text(encoding="utf-8", errors="replace")

MESSAGE_RE = re.compile(r'MiniMax response-header timeout after \d+ms')
TIMER_RE = re.compile(
    r'(responseHeaderAbortController\.abort\(new DOMException\("MiniMax '
    r'response-header timeout after \d+ms", "TimeoutError"\)\);\n\t\t\}, )'
    r'(\d+(?:e\d+)?)(\);)'
)


def retune(text, old_marker):
    """Move an already-patched bundle onto the current deadline.

    Every number is rewritten from the source of truth in the shell header, so
    a future change is one edit and never a hunt for stray literals.
    """
    messages = len(MESSAGE_RE.findall(text))
    if messages != 2:
        raise SystemExit(
            f"[patch] ERROR: expected 2 deadline messages, found {messages}"
        )
    timers = len(TIMER_RE.findall(text))
    if timers != 1:
        raise SystemExit(
            f"[patch] ERROR: expected 1 deadline timer, found {timers}"
        )
    if text.count(old_marker) != 1:
        raise SystemExit(
            f"[patch] ERROR: marker matched {text.count(old_marker)} times"
        )
    text = MESSAGE_RE.sub(
        f"MiniMax response-header timeout after {deadline_ms}ms", text
    )
    text = TIMER_RE.sub(rf"\g<1>{deadline_literal}\g<3>", text)
    return text.replace(old_marker, marker, 1)


if marker_v2 in source:
    path.write_text(retune(source, marker_v2), encoding="utf-8")
    print(f"[patch] retuned MiniMax response-header deadline to "
          f"{deadline_ms}ms (v3) -> {path}")
    raise SystemExit(0)

if marker_v1 in source:
    legacy_catch = '''\t\t} catch (error) {
\t\t\tif (responseHeaderTimer) clearTimeout(responseHeaderTimer);
\t\t\tlog.warn(`[model-fetch] error provider=${model.provider} api=${model.api} model=${model.id} elapsedMs=${Date.now() - fetchStartedAt} ${summarizeError(error)}`);
\t\t\tlocalServiceLease?.release();
\t\t\tthrow error;
\t\t}'''
    upgraded_catch = '''\t\t} catch (error) {
\t\t\tif (responseHeaderTimer) clearTimeout(responseHeaderTimer);
\t\t\tlog.warn(`[model-fetch] error provider=${model.provider} api=${model.api} model=${model.id} elapsedMs=${Date.now() - fetchStartedAt} ${summarizeError(error)}`);
\t\t\tlocalServiceLease?.release();
\t\t\tif (responseHeaderAbortController?.signal.aborted) {
\t\t\t\tconst timeoutError = new Error("MiniMax response-header timeout after 30000ms", { cause: error });
\t\t\t\ttimeoutError.name = "TimeoutError";
\t\t\t\tthrow timeoutError;
\t\t\t}
\t\t\tthrow error;
\t\t}'''
    if source.count(legacy_catch) != 1:
        raise SystemExit(
            f"[patch] ERROR: v1 catch anchor matched {source.count(legacy_catch)} times"
        )
    source = source.replace(legacy_catch, upgraded_catch, 1)
    path.write_text(retune(source, marker_v1), encoding="utf-8")
    print(f"[patch] upgraded v1 and retuned deadline to "
          f"{deadline_ms}ms (v3) -> {path}")
    raise SystemExit(0)

signal_before = '''\t\tconst synthesizeJsonAsSse = await requestBodyHasStreamTrue(request, baseInit);
\t\tconst baseSignal = baseInit?.signal ?? void 0;
\t\tconst localServiceSignal = buildModelRequestSignal(baseSignal, requestTimeoutMs);
\t\tconst guardedFetchOptions = {'''
signal_after = f'''\t\tconst synthesizeJsonAsSse = await requestBodyHasStreamTrue(request, baseInit);
\t\tconst baseSignal = baseInit?.signal ?? void 0;
\t\tconst isMinimaxAnthropicRequest = model.api === "anthropic-messages" && (model.provider === "minimax" || model.provider === "minimax-2");
\t\tconst responseHeaderAbortController = isMinimaxAnthropicRequest ? new AbortController() : void 0;
\t\tconst responseHeaderSignal = responseHeaderAbortController ? baseSignal ? AbortSignal.any([baseSignal, responseHeaderAbortController.signal]) : responseHeaderAbortController.signal : baseSignal;
\t\tconst localServiceSignal = buildModelRequestSignal(baseSignal, requestTimeoutMs);
\t\tconst guardedFetchOptions = {{'''

guard_signal_before = '''\t\t\ttimeoutMs: requestTimeoutMs,
\t\t\t...baseSignal ? { signal: baseSignal } : {},
\t\t\tallowCrossOriginUnsafeRedirectReplay: false,'''
guard_signal_after = '''\t\t\ttimeoutMs: requestTimeoutMs,
\t\t\t...responseHeaderSignal ? { signal: responseHeaderSignal } : {},
\t\t\tallowCrossOriginUnsafeRedirectReplay: false,'''

fetch_before = '''\t\temitModelTransportDebug(log, `[model-fetch] start provider=${model.provider} api=${model.api} model=${model.id} method=${baseInit?.method ?? "GET"} url=${formatModelTransportDebugUrl(rawUrl)} timeoutMs=${requestTimeoutMs} proxy=${dispatcherPolicy ? "configured" : useEnvProxy ? "env" : "none"} policy=${policy ? "custom" : "default"}`);
\t\ttry {
\t\t\tlocalServiceLease = await ensureModelProviderLocalService(model, rawHeaders, localServiceSignal);
\t\t\tresult = await fetchWithSsrFGuard(useEnvProxy ? withTrustedEnvProxyGuardedFetchMode(guardedFetchOptions) : guardedFetchOptions);
\t\t} catch (error) {
\t\t\tlog.warn(`[model-fetch] error provider=${model.provider} api=${model.api} model=${model.id} elapsedMs=${Date.now() - fetchStartedAt} ${summarizeError(error)}`);
\t\t\tlocalServiceLease?.release();
\t\t\tthrow error;
\t\t}
\t\tlet response = result.response;'''
fetch_after = f'''\t\temitModelTransportDebug(log, `[model-fetch] start provider=${{model.provider}} api=${{model.api}} model=${{model.id}} method=${{baseInit?.method ?? "GET"}} url=${{formatModelTransportDebugUrl(rawUrl)}} timeoutMs=${{requestTimeoutMs}} proxy=${{dispatcherPolicy ? "configured" : useEnvProxy ? "env" : "none"}} policy=${{policy ? "custom" : "default"}}`);
\t\tlet responseHeaderTimer;
\t\tif (responseHeaderAbortController) responseHeaderTimer = setTimeout(() => {{
\t\t\tlog.warn(`[model-fetch] MiniMax response-header timeout provider=${{model.provider}} model=${{model.id}} elapsedMs=${{Date.now() - fetchStartedAt}} marker={marker}`);
\t\t\tresponseHeaderAbortController.abort(new DOMException("MiniMax response-header timeout after {deadline_ms}ms", "TimeoutError"));
\t\t}}, {deadline_literal});
\t\ttry {{
\t\t\tlocalServiceLease = await ensureModelProviderLocalService(model, rawHeaders, localServiceSignal);
\t\t\tresult = await fetchWithSsrFGuard(useEnvProxy ? withTrustedEnvProxyGuardedFetchMode(guardedFetchOptions) : guardedFetchOptions);
\t\t}} catch (error) {{
\t\t\tif (responseHeaderTimer) clearTimeout(responseHeaderTimer);
\t\t\tlog.warn(`[model-fetch] error provider=${{model.provider}} api=${{model.api}} model=${{model.id}} elapsedMs=${{Date.now() - fetchStartedAt}} ${{summarizeError(error)}}`);
\t\t\tlocalServiceLease?.release();
\t\t\tif (responseHeaderAbortController?.signal.aborted) {{
\t\t\t\tconst timeoutError = new Error("MiniMax response-header timeout after {deadline_ms}ms", {{ cause: error }});
\t\t\t\ttimeoutError.name = "TimeoutError";
\t\t\t\tthrow timeoutError;
\t\t\t}}
\t\t\tthrow error;
\t\t}}
\t\tif (responseHeaderTimer) clearTimeout(responseHeaderTimer);
\t\tlet response = result.response;'''

for label, before in (
    ("signal", signal_before),
    ("guard signal", guard_signal_before),
    ("fetch", fetch_before),
):
    if source.count(before) != 1:
        raise SystemExit(f"[patch] ERROR: {label} anchor matched {source.count(before)} times")

patched = source.replace(signal_before, signal_after, 1)
patched = patched.replace(guard_signal_before, guard_signal_after, 1)
patched = patched.replace(fetch_before, fetch_after, 1)
path.write_text(patched, encoding="utf-8")
print(f"[patch] MiniMax {deadline_ms}ms response-header deadline -> {path}")
PY

node --check "$F"
grep -q "$MARKER" "$F"
grep -q "MiniMax response-header timeout after ${DEADLINE_MS}ms" "$F"
echo "[patch] syntax, marker and ${DEADLINE_MS}ms deadline verified"
echo "[patch] restart the gateway after confirming no cron run is in flight"
