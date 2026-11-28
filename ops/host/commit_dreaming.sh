#!/usr/bin/env bash
# The nightly job reviews candidates and updates the two local views.
set -uo pipefail

WS="${DREAMING_WORKSPACE:-/root/.openclaw/workspace}"
STORE="${SHARED_MEMORY_DIR:-$HOME/.shared-memory}"
# The cron PATH has no node and no pnpm prefix. The model review and intake
# shells run the OpenClaw CLI; give them the same prefix the gateway uses.
export PATH="/root/.local/share/pnpm:/root/.local/bin:/usr/local/bin:$PATH"
cd "$WS" || exit 1

if [ "${DREAMING_REVIEW_PAUSED:-0}" = 1 ]; then
  echo "dreaming-review: paused"
  exit 0
fi
if [ "$(pwd -P)" = /root/.openclaw/workspace ]; then
  hour=$(TZ=Asia/Hong_Kong date +%-H)
  if [ "$hour" -lt 3 ] || [ "$hour" -ge 6 ]; then
    echo "dreaming-review: outside the 03:00–06:00 HKT maintenance window"
    exit 0
  fi
fi

export MEMCTL_AGENT="${MEMCTL_AGENT:-rick}"

MEMORY_OK=1
DREAMS_OK=1
if ! python3 "$WS/ops/host/review_dreams.py" --workspace "$WS" --store "$STORE"; then
  echo "$(date -Is) dreaming-review: DREAMS review failed; DREAMS.md needs review"
  DREAMS_OK=0
fi
if [ "$DREAMS_OK" = 1 ] && ! python3 "$WS/ops/host/review_dreams.py" --workspace "$WS" --store "$STORE" --check; then
  echo "$(date -Is) dreaming-review: DREAMS check failed; DREAMS.md needs review"
  DREAMS_OK=0
fi

# Dispatch/task intake: a model distils the queued kcn words and task outcomes.
# Fail-soft: an unreachable model leaves the raw items private for the next run.
MEMORY_KIT="${SHARED_MEMORY_SKILL_DIR:-$HOME/.agents/skills/shared-memory}"
if [ -r "$MEMORY_KIT/scripts/intake.py" ]; then
  # Direct chat is a source even when the dreaming score ranked nothing: queue the
  # user lines from yesterday's and today's private corpus, then distil everything.
  for day in "$(date -d yesterday +%F)" "$(date +%F)"; do
    if ! timeout 60 python3 "$MEMORY_KIT/scripts/intake.py" capture-chat \
      --date "$day" --workspace "$WS" >/dev/null; then
      echo "$(date -Is) dreaming-review: direct-chat capture failed for $day" >&2
    fi
  done
  if ! timeout 600 python3 "$MEMORY_KIT/scripts/intake.py" --store "$STORE" \
      --repo "$WS" run --limit 20; then
    echo "$(date -Is) dreaming-review: memory intake failed; raw items stay queued"
  fi
fi

# The missing reviewer: the deterministic gate only approves an exact hash-bound
# receipt. This model writes one for clean candidates; failures leave them pending.
if ! timeout 600 python3 "$WS/ops/host/review_dreaming_llm.py" --workspace "$WS" --store "$STORE"; then
  echo "$(date -Is) dreaming-review: model review failed; candidates stay pending"
fi

# MEMORY: reviewed candidates -> public store topics -> regenerated MEMORY.md.
# promote_dreaming.py snapshots the store, writes only approved candidates, runs
# verify/doctor, and restores the previous projection if generation fails.
if ! python3 "$WS/ops/host/promote_dreaming.py" --workspace "$WS" --store "$STORE"; then
  echo "$(date -Is) dreaming-review: MEMORY promotion failed at the step above; MEMORY.md left at its previous version"
  MEMORY_OK=0
fi
if [ "$MEMORY_OK" = 1 ] && ! python3 "$WS/ops/host/review_dreaming.py" --workspace "$WS" --check; then
  echo "$(date -Is) dreaming-review: MEMORY check failed; MEMORY.md needs review"
  MEMORY_OK=0
fi

printf 'dreaming-review: local check results MEMORY_OK=%s DREAMS_OK=%s\n' "$MEMORY_OK" "$DREAMS_OK"
[ "$MEMORY_OK" = 1 ] || [ "$DREAMS_OK" = 1 ]
