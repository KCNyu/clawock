#!/usr/bin/env bash
# Probe opencode free-tier models and report which are actually usable.
#
#   probe-free-models.sh [--timeout 75] [--batch 3] [model ...]
#
# Why: a retired/broken free model does not fail loudly at dispatch time — every
# attempt dies in seconds and the pool rotates to the next model, so the dead
# entry silently costs one failed attempt (plus FALLBACK_WAIT) per task.
# 2026-09-19: opencode/union-alpha returns "Endpoint is unavailable" instantly
# and is gone from the models.dev catalog; this script is how we find that out.
#
# Output: $OUT/<model>.jsonl (raw events) and $OUT/summary.tsv
#   model  verdict  first_event_s  total_s  detail
# verdict: OK | ERROR | RATE_LIMIT | TIMEOUT | EMPTY
#   OK        first event seen and the run ended by itself
#   ERROR     provider returned an error event (dead model, 404, upstream down)
#   RATE_LIMIT  free-tier throttling; model is alive, retry later
#   TIMEOUT   no usable answer inside --timeout
set -uo pipefail
export TZ=Asia/Shanghai

TIMEOUT=75
BATCH=3
DEFAULT_MODELS=(
  opencode/nemotron-3-ultra-free
  opencode/muse-spark-1.3-contributor-free
  opencode/mimo-v2.5-free
  opencode/union-alpha
  opencode/deepseek-v4-flash-free
  opencode/grok-code
)
MODELS=()
TOOL_PROBE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --timeout) TIMEOUT=$2; shift 2 ;;
    --batch) BATCH=$2; shift 2 ;;
    --tool) TOOL_PROBE=1; shift ;;   # also require a real tool call, not just chat
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) MODELS+=("$1"); shift ;;
  esac
done
[ ${#MODELS[@]} -eq 0 ] && MODELS=("${DEFAULT_MODELS[@]}")

OUT=${OUT:-/root/logs/free-model-probe/$(date +%Y%m%d-%H%M%S)}
mkdir -p "$OUT"
echo "probing ${#MODELS[@]} models, timeout=${TIMEOUT}s batch=${BATCH} -> $OUT"

run_one() {  # <model> ; writes $OUT/<slug>.jsonl + .meta
  local m=$1 slug start rc first last prompt
  slug=$(printf '%s' "$m" | tr '/' '_')
  if [ "$TOOL_PROBE" = 1 ]; then
    prompt='Run the bash tool exactly once with the command: echo TOOL-PROBE-OK — then reply with exactly: PROBE-OK'
  else
    prompt='reply with exactly: PROBE-OK'
  fi
  start=$(date +%s)
  timeout "$TIMEOUT" opencode run --format json -m "$m" "$prompt" \
    > "$OUT/$slug.jsonl" 2>"$OUT/$slug.err"
  rc=$?
  last=$(date +%s)
  first=$(head -1 "$OUT/$slug.jsonl" 2>/dev/null | grep -o '"timestamp":[0-9]*' | head -1 | cut -d: -f2)
  if [ -n "$first" ]; then first=$(( first / 1000 )); else first=0; fi
  { echo "rc=$rc"; echo "start=$start"; echo "end=$last"; echo "first_epoch=$first"; } > "$OUT/$slug.meta"
}

i=0
for m in "${MODELS[@]}"; do
  run_one "$m" &
  i=$((i+1))
  if [ $((i % BATCH)) -eq 0 ]; then wait; fi
done
wait

printf 'model\tverdict\tfirst_event_s\ttotal_s\tdetail\n' > "$OUT/summary.tsv"
for m in "${MODELS[@]}"; do
  slug=$(printf '%s' "$m" | tr '/' '_')
  f="$OUT/$slug.jsonl"; meta="$OUT/$slug.meta"
  [ -r "$meta" ] || { printf '%s\tMISSING\t\t\tno output\n' "$m" >> "$OUT/summary.tsv"; continue; }
  # shellcheck disable=SC1090
  . "$meta"
  total=$(( end - start )); fe=0; [ "$first_epoch" -gt 0 ] && fe=$(( first_epoch - start ))
  detail=$(grep -o '"message":"[^"]*"' "$f" 2>/dev/null | head -1 | cut -c12- | cut -c1-110)
  if grep -q '"type":"error"' "$f" 2>/dev/null; then
    case "$detail" in
      *"Rate limit"*|*"rate_limit"*|*"overloaded"*|*"temporarily"*) verdict=RATE_LIMIT ;;
      *) verdict=ERROR ;;
    esac
  elif [ "$rc" = 124 ]; then
    if [ "$fe" -gt 0 ]; then verdict=TIMEOUT; detail="first event after ${fe}s; $detail"; else verdict=TIMEOUT; detail="no event in ${TIMEOUT}s"; fi
  elif grep -q '"type":"text"' "$f" 2>/dev/null; then
    if [ "$TOOL_PROBE" = 1 ]; then
      if grep -q 'TOOL-PROBE-OK' "$f" 2>/dev/null; then verdict=OK; else verdict=NO_TOOL; detail="chat ok but no bash tool call: $detail"; fi
    else
      verdict=OK
    fi
  else
    verdict=EMPTY
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$m" "$verdict" "$fe" "$total" "$detail" >> "$OUT/summary.tsv"
done

echo
column -t -s $'\t' "$OUT/summary.tsv"
echo
echo "raw events: $OUT"
