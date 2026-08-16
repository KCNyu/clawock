#!/usr/bin/env bash
# Autonomous Nostr broadcast: Rick's self-grading scorecard → public kind-1 note.
# Zero-touch — no account, no API key beyond the local Nostr secret.
# Key lives OUTSIDE the repo (never committed); only the env var is passed in.
set -euo pipefail

cd /root/.openclaw/workspace

# cron runs with a minimal PATH that lacks nvm's node bin → `node: command not found`.
# Detect the newest installed nvm node and prepend it (survives node version bumps).
if ! command -v node >/dev/null 2>&1; then
  NODE_BIN="$(find /root/.nvm/versions/node -mindepth 2 -maxdepth 2 \
    -type d -name bin -print 2>/dev/null | sort -V | tail -1)"
  [[ -n "$NODE_BIN" ]] && export PATH="$NODE_BIN:$PATH"
fi

KEYFILE=/root/.openclaw/nostr-rick.key

if [[ ! -r "$KEYFILE" ]]; then
  echo "$(date -Is) ERROR: Nostr key not readable at $KEYFILE" >&2
  exit 1
fi
NOSTR_PRIVATE_KEY="$(cat "$KEYFILE")"
export NOSTR_PRIVATE_KEY

# Generate the post from live data, then sign + publish to public relays.
python3 ops/growth/rick_broadcast.py --lang en | node ops/growth/nostr_publish.js
