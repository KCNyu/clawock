#!/usr/bin/env bash
# publish_generation.sh — put the generation currently in the workspace on the
# data branch, and ask for the site to be rebuilt.
#
# THE single entry point for that, because there are two kinds of caller and they
# must not drift: the scheduled publisher (`publish_dashboard.sh`, every 20
# minutes) and the harness postflights, which rebuild after a report and used to
# publish by committing (#328). Before #326 the commit itself matched
# `pages.yml`'s `paths:` and triggered the deploy; with the outputs untracked
# that path is gone, and a postflight's generation would otherwise sit in the
# worktree until the next scheduled tick — up to 20 minutes on every intraday
# slot, which is the opposite of what intraday monitoring is for.
#
# Identity selection lives here rather than in each caller: a Python caller
# cannot source a shell file, and restating the deploy-key logic is exactly the
# duplication #316 removed for safe_push.sh.
#
# Idempotent and self-healing by construction — the store compares against what
# the branch actually holds, so a redundant call is a no-op and a call that
# failed last time repairs itself with no new information.
set -uo pipefail

WS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$WS_ROOT"

# shellcheck source=scripts/data/publish_identity.sh
. "$WS_ROOT/scripts/data/publish_identity.sh"

exec python3 "$WS_ROOT/scripts/data/publish_data_branch.py" \
  --deploy --remote "${PUBLISH_REMOTE:-origin}"
