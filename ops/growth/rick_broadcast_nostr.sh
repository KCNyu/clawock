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
#
# Broadcast-on-change: the scorecard text only moves when T+1 settlement moves
# it, and reposting a byte-identical note every evening is machine spam on the
# one channel that is fully automated (relay-verified: four consecutive days of
# identical content in Aug 2026). Skip when the rendered text matches the last
# SUCCESSFULLY published digest. Fail-open toward visibility: no state file or
# an unreadable one publishes as before, and the state only advances after
# nostr_publish.js exits 0 (a relay accepted), so a failed publish retries the
# next night instead of eating that day's post.
POST="$(python3 ops/growth/rick_broadcast.py --lang en)"
DIGEST="$(printf '%s' "$POST" | sha256sum | cut -d' ' -f1)"
STATE="$(pwd)/logs/nostr_last_post.sha256"

if [[ -f "$STATE" ]] && [[ "$(cat "$STATE" 2>/dev/null)" == "$DIGEST" ]]; then
  echo "$(date -Is) scorecard unchanged since last publish ($DIGEST) — skip duplicate"
  exit 0
fi

if printf '%s\n' "$POST" | node ops/growth/nostr_publish.js; then
  mkdir -p "$(dirname "$STATE")"
  echo "$DIGEST" > "$STATE"
else
  echo "$(date -Is) publish failed; digest not recorded — will retry next run" >&2
  exit 1
fi
