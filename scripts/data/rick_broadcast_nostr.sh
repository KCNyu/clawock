#!/usr/bin/env bash
# Autonomous Nostr broadcast: Rick's self-grading scorecard → public kind-1 note.
# Zero-touch — no account, no API key beyond the local Nostr secret.
# Key lives OUTSIDE the repo (never committed); only the env var is passed in.
set -euo pipefail

cd /root/.openclaw/workspace
KEYFILE=/root/.openclaw/nostr-rick.key

if [[ ! -r "$KEYFILE" ]]; then
  echo "$(date -Is) ERROR: Nostr key not readable at $KEYFILE" >&2
  exit 1
fi
export NOSTR_PRIVATE_KEY="$(cat "$KEYFILE")"

# Generate the post from live data, then sign + publish to public relays.
python3 scripts/data/rick_broadcast.py --lang en | node scripts/data/nostr_publish.js
