#!/bin/bash
# Claude Code hook for the shared memory (registered in ~/.claude/settings.json).
#   claude-hook.sh post   PostToolUse: commit store edits, attributed to the session
#   claude-hook.sh start  SessionStart: shared index where Claude does not inject it natively
#                         (never inside a separate-memory context such as an OpenClaw workspace)
# Never fails the agent turn: always exits 0. The fast path is pure bash.
memctl="$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")/scripts/memctl"
store=$(readlink -f "${SHARED_MEMORY_DIR:-$HOME/.shared-memory}" 2>/dev/null)
input=$(cat)
case "$1" in
  post)
    case "$input" in
      *"/.shared-memory"*|*"memory.py"*|*"memctl"*) ;;
      *) [ -n "$store" ] && [[ $input == *"$store"* ]] || exit 0 ;;
    esac
    printf '%s' "$input" | timeout 15 python3 "$memctl" hook claude-post >/dev/null 2>&1
    ;;
  start)
    printf '%s' "$input" | timeout 10 python3 "$memctl" hook claude-start 2>/dev/null
    ;;
esac
exit 0
