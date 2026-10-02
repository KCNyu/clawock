#!/usr/bin/env bash
# Runner for dispatch.sh, executed inside a transient systemd unit.
# Built from the 2026-09-14 overnight one-shot runners and Codex's review of them
# (/root/scratch/codex-followup-20260914/report-codex-review-oneshot.md):
#   - locks never bypassed; lock timeout is BLOCKED, not success
#   - one absolute deadline covers the whole run (lock wait, attempts, retry sleeps)
#   - success/quota decided from the CLI's structured result / final error line,
#     never by grepping tool output
#   - retries preserve the session; automatic quota resumes have a separate budget
#   - the runner owns a machine-readable result.env; the model's STATUS line is reported
#     separately (process success != task success)
#   - notification text is redacted and never includes raw tool logs
#   - `dispatch.sh append` drops instructions into $DIR/inbox; they reach the same session
#     (2026-09-17: tasks were being cancelled just to change their instructions, losing the work)
#   - the agent lock is taken in queue order, decided by the versioned task_queue_ops.py
#     (`head <agent>`): priority set from the dsh chip, patrol always last, no starvation;
#     a quota wait releases the lock and re-queues (kcn 2026-09-26, interactive-task-queue)
#   - $DIR/override.env (written only by task_queue_ops.py) changes MODEL/EFFORT for the next attempt,
#     and DEADLINE_EPOCH/MAX_ATTEMPTS/QUOTA_RESUMES at the next lock poll or attempt (api 3)
#   - after every attempt and at the end, task_queue_ops.py `usage` puts the task's tokens and
#     their API-price estimate into result.env (TOKENS_*, COST_USD)
set -uo pipefail
# What this runner publishes and honours; task_queue_ops.py refuses priority/model changes for a
# task whose result.env carries an older RUNNER_API (its runner cannot apply them), and budget
# changes (deadline, attempts, resumes) below api 3.
RUNNER_API=3

DIR="$1"
# shellcheck disable=SC1091
. "$DIR/meta.env"

export TZ=Asia/Shanghai HOME=/root
# AGENT_DISPATCH_PATH_PREFIX: test seam for fake CLIs. systemd-run does not pass the
# caller's environment, so dispatched tasks never see it.
export PATH="${AGENT_DISPATCH_PATH_PREFIX:+$AGENT_DISPATCH_PATH_PREFIX:}/root/.local/bin:/root/.local/share/pnpm:/root/.nvm/versions/node/v22.23.1/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Trust boundary: there is NO sandbox. Tasks run as root in an unconfined systemd unit,
# claude with --dangerously-skip-permissions and codex with
# --dangerously-bypass-approvals-and-sandbox — the same yolo setup kcn uses interactively
# on this dedicated host. IS_SANDBOX=1 only makes claude accept skip-permissions as root.
export IS_SANDBOX=1
# Dispatched agents see the agent-dispatch skill too. dispatch.sh refuses to start a task while
# this is set: verify-wait-codex handed its own `sleep 150` to a new task and reported DONE
# (2026-09-15).
export AGENT_DISPATCH_TASK_ID="$ID"
export CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1    # a headless run ends when the model stops
unset CLAWOCK_WORKSPACE 2>/dev/null || true

# AGENT_DISPATCH_LOCKDIR: test seam, so the fault-injection tests never wait on (or take)
# the slot lock of a real dispatched task.
LOCKDIR="${AGENT_DISPATCH_LOCKDIR:-/root/logs/agent-dispatch}"
# The queue: waiting tasks register as .queue/<agent>/<id>; the entry below decides who is next.
TASKS_DIR=$(dirname "$DIR")
QDIR="$LOCKDIR/.queue/$AGENT"
# Cancellation is durable across unit restarts, including pre-barrier task records.
# Preserve the old session/usage instead of initializing a fresh queued result.
# shellcheck disable=SC1091
previous_state=$( ( [ ! -r "$DIR/result.env" ] || . "$DIR/result.env"; printf '%s' "${STATE:-}" ) )
if [ -e "$DIR/cancel-requested" ] || [ "$previous_state" = cancelled ]; then
  : >>"$DIR/cancel-requested"
  rm -f "${QDIR:?}/${ID:?}"
  if [ -r "$DIR/result.env" ]; then
    sed -e 's/^STATE=.*/STATE=cancelled/' -e 's/^RC=.*/RC=143/' \
      -e "s/^\(WAITING\|WAKE_AT\|SLOT\)=.*/\1=''/" "$DIR/result.env" >"$DIR/.cancel-result.tmp"
    mv -f "$DIR/.cancel-result.tmp" "$DIR/result.env"
  else
    printf "STATE=cancelled\nRC=143\nWAITING=''\nWAKE_AT=''\nSLOT=''\n" >"$DIR/result.env"
  fi
  exit 143
fi
OPS="${AGENT_DISPATCH_OPS:-/root/tools/agent-dispatch/task_queue_ops.py}"
QUEUE_POLL_SEC="${AGENT_DISPATCH_QUEUE_POLL_SEC:-3}"
# More test seams of the same kind: notification config, codex rollouts, claude transcripts.
NOTIFY_CONF="${AGENT_DISPATCH_NOTIFY_CONF:-/root/tools/agent-dispatch/notify.env}"
QUOTA_CMD="${AGENT_DISPATCH_QUOTA_CMD:-node /root/tools/agent-dispatch/quota.mjs}"
CODEX_HOME_DIR="${CODEX_HOME:-/root/.codex}"
CLAUDE_HOME_DIR="${CLAUDE_CONFIG_DIR:-/root/.claude}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"
QUOTA_RESUMES="${QUOTA_RESUMES:-3}"  # explicit per-task override; 0 disables automatic quota resumes
# 3, not 1 (kcn 2026-09-23): a long Opus task does not fit in one 5-hour window, and a single
# resume meant the second exhaustion stopped it until someone typed an append. Each resume
# replays the session, so this is a real cost — keep it explicit for short, cheap tasks.
QUOTA_RESUMES_USED=0
RETRY_WAIT="${RETRY_WAIT:-600}"
MIN_RUN_SEC="${MIN_RUN_SEC:-600}"   # do not start an attempt with less than this left
KILL_MARGIN=70                      # inner timeout -k 60 plus bookkeeping
CONTINUE_PROMPT="继续完成上一轮被中断的同一任务：先检查当前真实状态（git/PR/CI/文件），复用已有产物，不要重复已完成的步骤。结束时按原要求输出 STATUS 行。"
# At most this many attempts of this agent run at once; see acquire_slot. Each agent has its own
# slots (kcn 2026-09-25): a patrol round (opencode) never holds one a claude/codex task needs.
# The numbers live in limits.env so clawock-patrol (which reads the same file) cannot drift from
# the runner that actually takes the slots. Waiting for quota or a retry sleep holds no slot.
. /root/tools/agent-dispatch/limits.env
slots_var=MAX_RUNNING_${AGENT^^} override_var=AGENT_DISPATCH_MAX_RUNNING_${AGENT^^}
AGENT_SLOTS="${!override_var:-${!slots_var:-1}}"
. /root/tools/agent-dispatch/resource-pressure.sh
POLL_SEC="${AGENT_DISPATCH_POLL_SEC:-5}"
INBOX="$DIR/inbox"
# Stalled attempts: stopped once they show no progress for this long, instead of waiting out
# TIMEOUT, which stays long on purpose (real tasks run for hours). See wait_attempt.
# opencode: of 238 patrol attempts the healthy ones printed their first event within 35s (p90,
# slowest 127s) and never went quiet for more than 523s (370 attempts); its tools are capped at
# 10 minutes. claude/codex give up on a silent API stream themselves well before 30 minutes.
# STALL_TOOL: how long one tool (a command the CLI started) can keep an attempt alive, by
# working or - codex only - by being a command codex is still waiting on; after that only the
# idle limit is left. Bounds a busy leftover (a spinning background job) and a hung command.
# codex runs a command to its end and prints item.started/item.completed around it, so a
# 30-minute idle wait (gh pr checks --watch, sleep) is its tool in flight, not a stall; the 60
# PR CI runs before 2026-09-26 took 308s at most, so 3600s is room for a slow queue. claude's
# and opencode's tools stop at 10 minutes; a process of theirs older than that is a leftover.
# STALL_FIRST_SEC / STALL_IDLE_SEC / STALL_TOOL_SEC override every agent (test seam; 0 disables).
case "$AGENT" in
  opencode) STALL_FIRST=300 STALL_IDLE=900 STALL_TOOL=900 ;;
  codex) STALL_FIRST=1800 STALL_IDLE=1800 STALL_TOOL=3600 ;;
  *) STALL_FIRST=1800 STALL_IDLE=1800 STALL_TOOL=1800 ;;
esac
STALL_FIRST="${STALL_FIRST_SEC:-$STALL_FIRST}" STALL_IDLE="${STALL_IDLE_SEC:-$STALL_IDLE}" STALL_TOOL="${STALL_TOOL_SEC:-$STALL_TOOL}"
STALL_CHECK_SEC="${STALL_CHECK_SEC:-30}"
STALLS=0

exec >>"$DIR/run.log" 2>&1

# Builtin clock, no subprocess: `systemctl stop` TERMs the whole cgroup, so a `date` forked
# inside on_signal could die first and leave an empty number (cancel vs timeout misjudged,
# review-merge-1514-1515, 2026-09-15).
now() { printf '%(%s)T\n' -1; }
remaining() { echo $(( DEADLINE_EPOCH - $(now) )); }
ts() { date '+%F %T'; }

# opencode free models: after a failed attempt the same session continues on the next model of
# MODEL + FALLBACK_MODELS (free tiers rate-limit per model, 2026-09-17). Wraps around.
FALLBACK_MODELS="${FALLBACK_MODELS:-}"
read -r -a MODEL_POOL <<<"$MODEL ${FALLBACK_MODELS//,/ }"
MODEL_IDX=0 CUR_MODEL=$MODEL
BASE_POOL=("${MODEL_POOL[@]}")
FALLBACK_WAIT="${FALLBACK_WAIT:-60}"
[ "${#MODEL_POOL[@]}" -gt 1 ] && MAX_ATTEMPTS=$(( MAX_ATTEMPTS > 2 * ${#MODEL_POOL[@]} ? MAX_ATTEMPTS : 2 * ${#MODEL_POOL[@]} ))
STATE=queued RC="" SESSION="${RESUME:-}" ATTEMPTS=0 OUTCOME="" STARTED=$(ts) FINAL_TEXT="" WAITING="" APPENDS=0
SLOT=""   # set by acquire_slot while this attempt holds a run slot; published in result.env
# QUEUED_AT: epoch when this task first waited for its agent lock (the queue's order, not dir
# mtime). WAKE_AT: epoch a quota/retry wait ends. NOTIFIED / NOTIFY_FAILED: the legs of the
# latest notification that were delivered / failed, at NOTIFY_AT; readers stop grepping run.log.
QUEUED_AT="" WAKE_AT="" NOTIFIED="" NOTIFY_FAILED="" NOTIFY_AT=""
META_EFFORT=$EFFORT
TOKENS_IN="" TOKENS_CACHE_W="" TOKENS_CACHE_R="" TOKENS_OUT="" TOKENS_TOTAL="" COST_USD=""
write_result() {
  local tmp="$DIR/.result.env.tmp"
  {
    printf 'QUOTA_RESUMES_USED=%q\nSTALLS=%q\n' "$QUOTA_RESUMES_USED" "$STALLS"
    printf 'STATE=%q\nRC=%q\nOUTCOME=%q\nSESSION=%q\nATTEMPTS=%q\nAPPENDS=%q\nWAITING=%q\nSLOT=%q\nMODEL_USED=%q\nSTARTED=%q\nUPDATED=%q\n' \
      "$STATE" "$RC" "$OUTCOME" "$SESSION" "$ATTEMPTS" "$APPENDS" "$WAITING" "$SLOT" "$CUR_MODEL" "$STARTED" "$(ts)"
    printf 'EFFORT_USED=%q\nQUEUED_AT=%q\nWAKE_AT=%q\nNOTIFIED=%q\nNOTIFY_FAILED=%q\nNOTIFY_AT=%q\nRUNNER_API=%q\n' \
      "$EFFORT" "$QUEUED_AT" "$WAKE_AT" "$NOTIFIED" "$NOTIFY_FAILED" "$NOTIFY_AT" "$RUNNER_API"
    printf 'DEADLINE_EPOCH=%q\nMAX_ATTEMPTS=%q\nQUOTA_RESUMES=%q\n' "$DEADLINE_EPOCH" "$MAX_ATTEMPTS" "$QUOTA_RESUMES"
    printf 'TOKENS_IN=%q\nTOKENS_CACHE_W=%q\nTOKENS_CACHE_R=%q\nTOKENS_OUT=%q\nTOKENS_TOTAL=%q\nCOST_USD=%q\n' \
      "$TOKENS_IN" "$TOKENS_CACHE_W" "$TOKENS_CACHE_R" "$TOKENS_OUT" "$TOKENS_TOTAL" "$COST_USD"
  } >"$tmp" && mv -f "$tmp" "$DIR/result.env"
}

# claude gets its session id before it starts (--session-id), but a transcript exists only once
# claude wrote one; resuming an id without it fails with "No conversation found".
session_exists() {
  [ -n "$SESSION" ] || return 1
  [ "$AGENT" = claude ] || return 0
  compgen -G "$CLAUDE_HOME_DIR/projects/*/$SESSION.jsonl" >/dev/null
}

# ---- inbox: `dispatch.sh append` writes inbox/<stamp>-now.md or -queue.md atomically ----
# -now interrupts the running attempt once the session is resumable; -queue waits for the
# attempt to end. Either way the text is delivered to the same session.
inbox_pending() { compgen -G "$INBOX/*.md" | wc -l; }
inbox_has_now() { compgen -G "$INBOX/*-now.md" >/dev/null; }
take_inbox() {  # moves pending messages to inbox/delivered and prints them as one prompt block
  local f any=""
  mkdir -p "$INBOX/delivered"
  for f in $(compgen -G "$INBOX/*.md" | sort); do
    mv -f "$f" "$INBOX/delivered/" || continue
    f="$INBOX/delivered/$(basename "$f")"
    any=1
    printf '\n【追加指令 %s】\n%s\n' "$(date -d "@$(stat -c %Y "$f")" '+%m-%d %H:%M')" "$(cat "$f")"
  done
  [ -n "$any" ]
}
APPEND_HEAD="kcn 在任务进行中追加了下面的要求。它们和原任务一起完成；和原任务冲突时以追加的为准。"
APPEND_TAIL="先检查当前真实状态（git/PR/CI/文件），再按调整后的要求继续。原任务的派发约定照旧，结束时照样输出 STATUS 行。"

# ---- override: model/effort for the next attempt ------------------------------------
# $DIR/override.env is written only by task_queue_ops.py (the dsh chip's "switch model"), which
# validates the values per agent. Read before every attempt, so a queued or sleeping task picks
# the change up (meta.env is read once at start and stays the record of what was dispatched).
# Order (kcn 2026-09-26): an explicit override > the fallback pool > the dispatched default. A new
# override model becomes the pool's head for the next attempt; failures after it rotate through
# the rest of the pool exactly like the fallback switch below. Clearing it goes back to MODEL.
# Budgets (api 3): DEADLINE_EPOCH, MAX_ATTEMPTS and QUOTA_RESUMES in override.env (the ops entry's
# `deadline`/`attempts`/`resumes`, which checks the bounds) replace the dispatched values. Read at every
# poll of the lock wait and before every attempt; an absent key goes back to the dispatched value.
# The deadline is enforced here (attempt caps, lock/slot budgets, sleeps), not by the outer timeout,
# which is armed at the dispatch + 72h ceiling so a later deadline can still be honoured.
META_DEADLINE_EPOCH=$DEADLINE_EPOCH META_MAX_ATTEMPTS=$MAX_ATTEMPTS META_QUOTA_RESUMES=$QUOTA_RESUMES
apply_budget() {
  local line od="" oa="" oq=""
  if [ -r "$DIR/override.env" ]; then
    while IFS= read -r line; do
      case "$line" in DEADLINE_EPOCH=*) od=${line#*=} ;; MAX_ATTEMPTS=*) oa=${line#*=} ;; QUOTA_RESUMES=*) oq=${line#*=} ;; esac
    done <"$DIR/override.env"
  fi
  [[ $od =~ ^[0-9]{9,11}$ ]] || od=$META_DEADLINE_EPOCH
  [[ $oa =~ ^[0-9]{1,2}$ ]] && [ "$oa" -ge 1 ] || oa=$META_MAX_ATTEMPTS
  [[ $oq =~ ^[0-9]{1,2}$ ]] || oq=$META_QUOTA_RESUMES
  local changed=""
  [ "$od" != "$DEADLINE_EPOCH" ] && { DEADLINE_EPOCH=$od; DEADLINE=$(date -d "@$od" '+%F %T'); changed=1; echo "---- $(ts) budget: deadline now $DEADLINE"; }
  [ "$oa" != "$MAX_ATTEMPTS" ] && { MAX_ATTEMPTS=$oa; changed=1; echo "---- $(ts) budget: attempts now $MAX_ATTEMPTS"; }
  [ "$oq" != "$QUOTA_RESUMES" ] && { QUOTA_RESUMES=$oq; changed=1; echo "---- $(ts) budget: quota resumes now $QUOTA_RESUMES"; }
  # Published at once: the chip shows what the runner uses, also while it waits.
  [ -z "$changed" ] || write_result
  return 0
}

# Tokens and their API-price estimate, from the agent's own session record (task_queue_ops.py
# `usage`, which also owns the price table). Only digits, a 2-decimal amount or `free` are taken.
update_usage() {  # [timeout seconds]
  local line
  [ -r "$OPS" ] || return 0
  while IFS= read -r line; do
    [[ $line =~ ^(TOKENS_IN|TOKENS_CACHE_W|TOKENS_CACHE_R|TOKENS_OUT|TOKENS_TOTAL|COST_USD)=([0-9]*|[0-9]+\.[0-9]{2}|free)$ ]] \
      && printf -v "${BASH_REMATCH[1]}" '%s' "${BASH_REMATCH[2]}"
  done < <(AGENT_DISPATCH_TASKS_DIR="$TASKS_DIR" timeout "${1:-30}" python3 "$OPS" usage "$ID" 2>/dev/null)
  return 0
}

APPLIED_MODEL="" APPLIED_EFFORT=""
apply_override() {
  local line om="" oe="" m pool
  apply_budget
  if [ -r "$DIR/override.env" ]; then
    while IFS= read -r line; do
      case "$line" in MODEL=*) om=${line#MODEL=} ;; EFFORT=*) oe=${line#EFFORT=} ;; esac
    done <"$DIR/override.env"
  fi
  [[ $om =~ ^[A-Za-z0-9._/:@-]*$ ]] || om=""
  [[ $oe =~ ^[a-z]*$ ]] || oe=""
  if [ "$om" != "$APPLIED_MODEL" ]; then
    APPLIED_MODEL=$om
    pool=(); [ -n "$om" ] && pool=("$om")
    for m in "${BASE_POOL[@]}"; do [ "$m" = "$om" ] || pool+=("$m"); done
    MODEL_POOL=("${pool[@]}"); MODEL_IDX=0; CUR_MODEL=${MODEL_POOL[0]}
    echo "---- $(ts) override: model ${om:-cleared}; the next attempt uses $CUR_MODEL"
  fi
  if [ "$oe" != "$APPLIED_EFFORT" ]; then
    APPLIED_EFFORT=$oe; EFFORT=${oe:-$META_EFFORT}
    echo "---- $(ts) override: effort ${oe:-cleared}; the next attempt uses ${EFFORT:-none}"
  fi
}

# ---- run slots: at most AGENT_SLOTS attempts of this agent at once --------------------
# A slot is held only while an attempt runs, not during quota or retry sleeps, and it is
# published as SLOT=<agent>-<n> in result.env. WAITING=slot tells the clawock-patrol supervisor
# that someone is queued for a slot. Lock files are slot-<agent>-<n>.lock (the shared slot-<n>.lock
# of the runners from before 2026-09-25 is no longer probed by anyone since 2026-09-27).
SLOT=""
acquire_slot() {  # <budget seconds>; returns 1 when no slot freed up in time
  local end=$(( $(now) + $1 )) i pressure
  while :; do
    pressure=""
    # Patrol is expendable background work. Recheck even after retry/quota sleeps;
    # waiting for memory holds neither a slot nor an attempt budget.
    case "$ID" in patrol-*) pressure=$(memory_pressure_reason) ;; esac
    if [ -n "$pressure" ]; then
      if [ "$WAITING" != memory ]; then
        WAITING=memory; write_result; echo "$(ts) waiting: $pressure"
      fi
      if [ "$(now)" -ge "$end" ]; then WAITING=""; write_result; return 1; fi
      sleep 15 & CHILD=$!; wait "$CHILD"; CHILD=""
      continue
    fi
    for i in $(seq "$AGENT_SLOTS"); do
      exec 6>"$LOCKDIR/slot-$AGENT-$i.lock"
      if flock -n 6; then
        SLOT=$AGENT-$i
        WAITING=""; write_result; echo "$(ts) got run slot $SLOT"
        return 0
      fi
      exec 6>&-
    done
    if [ "$WAITING" != slot ]; then
      WAITING=slot; write_result; echo "$(ts) waiting for a $AGENT run slot (at most $AGENT_SLOTS running)"
    fi
    if [ "$(now)" -ge "$end" ]; then WAITING=""; write_result; return 1; fi
    sleep 15 & CHILD=$!; wait "$CHILD"; CHILD=""
  done
}
release_slot() { if [ -n "$SLOT" ]; then exec 6>&-; SLOT=""; write_result; fi; }

# clip head|tail <chars>: cut by characters, not bytes, so Chinese text is never split
# mid-character (head -c / tail -c produced broken UTF-8 in WeChat messages).
# Without python3 (the preflight failure path still notifies) fall back to a conservative
# cut of <chars> BYTES — never longer than asked — and let iconv drop the partial character
# at the edge. iconv exits 1 on that partial character; the valid output is still what we want.
clip() {
  if command -v python3 >/dev/null; then
    python3 -c 'import sys
mode, n = sys.argv[1], int(sys.argv[2])
s = sys.stdin.read()
sys.stdout.write(s[:n] if mode == "head" else s[-n:])' "$1" "$2"
  elif [ "$1" = head ]; then
    head -c "$2" | iconv -c -f UTF-8 -t UTF-8 2>/dev/null || true
  else
    tail -c "$2" | iconv -c -f UTF-8 -t UTF-8 2>/dev/null || true
  fi
}

redact() {
  sed -E 's/(token|api[_-]?key|secret|password)=[^[:space:]&"]+/\1=<redacted>/Ig;
          s/(sk|ghp|gho|github_pat|xox[bp])[-_][A-Za-z0-9_-]{12,}/<redacted>/g'
}

# One channel, one try. The label lands in the log, so a run that only reached half its
# channels can be read back afterwards instead of looking like a plain success.
notify_one() {  # <label> <channel> <target> <message> <timeout>
  local label=$1 channel=$2 target=$3 msg=$4 tmo=$5
  if [ -z "$channel" ] || [ -z "$target" ]; then
    echo "notify: $label target not configured"
    return 1
  fi
  if timeout "$tmo" openclaw message send --channel "$channel" --target "$target" -m "$msg" >/dev/null 2>&1; then
    echo "notify: sent ($label)"
  else
    echo "notify: send failed ($label)"
    return 1
  fi
}

# NOTIFY is a channel list (kcn 2026-09-26): `weixin`, `telegram`, `weixin,telegram` for user
# tasks (dual send is the default) or `none` for patrol rounds. Telegram is the leg that
# survives: WeChat's per-conversation context_token drops silently on a cold session, so a
# task that only told WeChat could finish without kcn ever hearing about it. Always returns 0
# — a notification failure must never change a task's terminal state.
# The list is split on commas without globbing, trimmed, lower-cased and de-duplicated; `none`
# and empty items are skipped. The legs are sent in parallel, each with the full timeout: sent
# one after the other, two slow legs overran on_signal's budget (20s stop + 18s quota + 2x30s
# > the 80s kill-after), so a cancel could be KILLed before its end line (review 2026-09-26).
# The outcome lands in result.env (NOTIFIED / NOTIFY_FAILED / NOTIFY_AT).
notify() {  # <message> [send timeout in seconds, default 60]
  local raw ch seen=" " legs=() pids=() i ok="" bad=""
  IFS=, read -r -a raw <<<"${NOTIFY:-}"
  for ch in ${raw[@]+"${raw[@]}"}; do
    ch=${ch//[[:space:]]/}; ch=${ch,,}
    case "$ch" in ""|none) continue ;; esac
    case "$seen" in *" $ch "*) continue ;; esac
    seen="$seen$ch "; legs+=("$ch")
  done
  [ "${#legs[@]}" -gt 0 ] || return 0
  NOTIFIED="" NOTIFY_FAILED="" NOTIFY_AT=$(ts)
  if [ ! -r "$NOTIFY_CONF" ]; then
    echo "notify: $NOTIFY_CONF missing"
    NOTIFY_FAILED=$(IFS=,; echo "${legs[*]}"); write_result; return 0
  fi
  # shellcheck disable=SC1090
  . "$NOTIFY_CONF"
  local msg; msg=$(printf '%s' "$1" | redact | clip head 900)
  for ch in "${legs[@]}"; do
    case "$ch" in
      weixin)   notify_one weixin "${NOTIFY_CHANNEL:-}" "${NOTIFY_TARGET:-}" "$msg" "${2:-60}" & ;;
      telegram) notify_one telegram "${TELEGRAM_CHANNEL:-telegram}" "${TELEGRAM_TARGET:-}" "$msg" "${2:-60}" & ;;
      *) echo "notify: unknown channel '$ch'"; ( exit 1 ) & ;;
    esac
    pids+=($!)
  done
  for i in "${!legs[@]}"; do
    if wait "${pids[$i]}"; then ok="$ok,${legs[$i]}"; else bad="$bad,${legs[$i]}"; fi
  done
  NOTIFIED=${ok#,} NOTIFY_FAILED=${bad#,}
  write_result
  return 0
}

# Remaining subscription quota as "\n额度：…", read the same way as the dsh balance chip
# (quota.mjs); empty for opencode. Also logged as a `quota |` line. Bounded below the on_signal
# budget: 20s attempt stop + 18s here + 30s notify < 80s kill-after.
quota_line() {
  case "$AGENT" in claude|codex) ;; *) return 0 ;; esac
  local line; line=$(timeout 18 $QUOTA_CMD "$AGENT" 2>/dev/null | head -1)
  [ -n "$line" ] || line="额度：未读到（超时或读取脚本失败）"
  echo "quota | $line" >&2
  printf '\n%s' "$line"
}

finish() {
  local icon
  # Out of the queue and off the lock before the notification: the next task need not wait for it.
  rm -f "${QDIR:?}/${ID:?}" 2>/dev/null
  release_agent_lock
  # Bounded: on the cancel path this shares on_signal's 80s kill-after with the notification.
  update_usage "${FINISH_USAGE_TIMEOUT:-20}"
  case "$STATE" in ok) icon="✅" ;; unverified) icon="⚠️" ;; quota|blocked|timeout|cancelled) icon="⏸️" ;; *) icon="❌" ;; esac
  # A claude session id is chosen up front (--session-id); it only exists once claude wrote it.
  session_exists || SESSION=""
  write_result
  printf '%s\n' "$FINAL_TEXT" | tail -n 6 | redact | sed 's/^/final | /'
  local pending; pending=$(inbox_pending)
  [ "$pending" -gt 0 ] && echo "inbox: $pending appended message(s) not delivered"
  local resume_hint=""
  if [ -n "$SESSION" ]; then
    resume_hint="
继续或追加要求：dispatch.sh append $ID < 指令.md（同一会话续跑）"
    [ "$pending" -gt 0 ] && resume_hint="
有 $pending 条追加指令没送到，重发：dispatch.sh append $ID < 指令.md"
  fi
  local open_hint=""
  if [ "$AGENT" = claude ] && [ -n "$SESSION" ]; then
    open_hint="
查看会话：在 $CWD 下 claude --resume $SESSION"
  elif [ "$AGENT" = opencode ] && [ -n "$SESSION" ]; then
    open_hint="
查看会话：在 $CWD 下 opencode -s $SESSION"
  fi
  local quota; quota=$(quota_line)
  notify "$icon 委派任务 $NAME（$AGENT）：$STATE${OUTCOME:+ / 模型自报 $OUTCOME}
$(printf '%s' "$FINAL_TEXT" | clip tail 500)
${resume_hint}${open_hint}${quota}
id：$ID
日志：$DIR/run.log" "${FINISH_NOTIFY_TIMEOUT:-60}"
  echo "==================== $(ts) $ID end state=$STATE outcome=${OUTCOME:--} rc=${RC:--} ===================="
}

# ---- outer deadline: TERM from timeout/systemctl stop lands here --------------------
CHILD=""
on_signal() {
  if [ -n "$CHILD" ]; then
    kill -TERM "$CHILD" 2>/dev/null
    # Bounded: stopping the attempt plus the notification must fit inside the outer timeout's
    # kill-after (80s). An attempt's `timeout` leads its own process group; KILL that group if
    # the agent ignores TERM.
    local i
    for i in $(seq 20); do kill -0 "$CHILD" 2>/dev/null || break; sleep 1; done
    kill -KILL -- "-$CHILD" 2>/dev/null
    wait "$CHILD" 2>/dev/null
  fi
  release_slot  # notifications must not delay a waiting foreground attempt
  # A stopped task waits for nothing. Leaving WAITING=lock/slot/quota behind made a
  # cancelled task read as still queued (2026-09-23 dispatch-default-model-bump).
  WAITING="" WAKE_AT=""
  if [ -e "$DIR/cancel-requested" ] || [ "$(remaining)" -gt 15 ]; then
    STATE=cancelled
    : >>"$DIR/cancel-requested"
  else
    STATE=timeout
  fi
  RC=143
  FINISH_NOTIFY_TIMEOUT=30 FINISH_USAGE_TIMEOUT=8
  finish
  exit 143
}
trap on_signal TERM INT
cancel_guard() {
  [ ! -e "$DIR/cancel-requested" ] || on_signal
}
cancel_guard

if [ "${DISPATCH_WRAPPED:-0}" != 1 ]; then
  left=$(remaining)
  if [ "$left" -le $((MIN_RUN_SEC / 2)) ]; then
    STATE=blocked; RC=75; FINAL_TEXT="截止时间 $DEADLINE 已过或不足，未启动。"; finish; exit 75
  fi
  # -k 80: after TERM (systemctl stop, or this deadline) on_signal needs time to stop the attempt
  # and notify. With -k 5 the cancel of review-merge-1514-1515 was KILLed before its notification
  # went out (2026-09-15). Stays below the unit's TimeoutStopSec=90s.
  # Armed at the dispatch + 72h ceiling, not at the deadline (api 3): the deadline can move later
  # (task_queue_ops.py deadline) and is enforced inside; this timer is the backstop behind it.
  created=$(date -d "$CREATED" +%s 2>/dev/null) || created=0
  ceiling=$(( created + 72 * 3600 ))
  [ "$ceiling" -gt "$DEADLINE_EPOCH" ] || ceiling=$DEADLINE_EPOCH
  exec env DISPATCH_WRAPPED=1 timeout -k 80 "$(( ceiling - $(now) - 10 ))" bash "$0" "$@"
fi

echo "==================== $(ts) $ID start ===================="
echo "agent_slots=$AGENT_SLOTS quota_resumes=$QUOTA_RESUMES stall_first=${STALL_FIRST}s stall_idle=${STALL_IDLE}s stall_tool=${STALL_TOOL}s"
echo "agent=$AGENT model=$MODEL${FALLBACK_MODELS:+ (fallback: $FALLBACK_MODELS)} effort=$EFFORT cwd=$CWD resume=${RESUME:--} deadline=$DEADLINE"
free -m | sed -n '2p'
write_result

need=(timeout flock python3 openclaw "$AGENT")
for b in "${need[@]}"; do
  command -v "$b" >/dev/null || { STATE=failed; RC=127; FINAL_TEXT="预检失败：找不到 $b"; finish; exit 127; }
done

# ---- locks: one task per agent at a time, taken in queue order ----------------------
# Waiting here also holds a run slot in practice (the holder is a running attempt) and it
# publishes WAITING=lock, so the patrol supervisor sees a queued foreground task that it
# must give way to. Without this marker that wait was invisible: this task never reached
# acquire_slot, so it never wrote WAITING=slot and patrol kept running its round
# (2026-09-23: a 01:43 claude task sat queued behind a patrol round).
# Queue order (kcn 2026-09-26): the task registers in $QDIR and takes the lock only when
# task_queue_ops.py names it as the head of its agent's queue (priority from the dsh chip, then
# QUEUED_AT; a task that has waited QUEUE_FAIR_WAIT_SEC can no longer be overtaken; patrol last).
# Before that it was a blocking `flock -w`: the kernel picked a waiter, and nothing could be
# reordered. If the entry is missing or fails, a manual task takes the lock whenever it is free
# (the old behaviour); a patrol round still never takes it while a manual task of its agent waits.
queue_head() {
  [ -r "$OPS" ] || return 0
  timeout 10 python3 "$OPS" head "$AGENT" 2>/dev/null
}
manual_waiting() {  # a live registered waiter of this agent that is not a patrol round
  local f pid
  for f in "$QDIR"/*; do
    [ -f "$f" ] || continue
    case "${f##*/}" in patrol-*|"$ID") continue ;; esac
    pid=$(sed -n 's/^PID=//p' "$f")
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && return 0
  done
  return 1
}
LOCK_HELD=""
wait_agent_lock() {  # <budget seconds>: 0 = fd 8 holds the agent lock, 1 = the budget ran out
  local end=$(( $(now) + $1 )) head told=""
  [ -n "$QUEUED_AT" ] || QUEUED_AT=$(now)
  mkdir -p "$QDIR"
  printf 'PID=%s\nQUEUED_AT=%s\n' "$$" "$QUEUED_AT" >"$QDIR/.$ID.tmp" && mv -f "$QDIR/.$ID.tmp" "$QDIR/$ID"
  WAITING=lock; write_result
  echo "$(ts) waiting for $AGENT lock (budget ${1}s, queued since $(date -d "@$QUEUED_AT" '+%F %T'))"
  exec 8>"$LOCKDIR/$AGENT.lock"
  while :; do
    # Every caller's budget is "until the deadline leaves MIN_RUN_SEC + KILL_MARGIN"; the deadline
    # may move while this task waits (api 3), so the end is recomputed at every poll.
    apply_budget
    end=$(( DEADLINE_EPOCH - MIN_RUN_SEC - KILL_MARGIN ))
    # One poll before every look, the first included: tasks that (re-)enter the queue together,
    # e.g. at a quota reset, are all registered before anyone is picked.
    sleep "$QUEUE_POLL_SEC" & CHILD=$!; wait "$CHILD"; CHILD=""
    head=$(queue_head)
    if [[ $ID == patrol-* ]] && manual_waiting; then
      [ "$told" = manual ] || { told=manual; echo "$(ts) queue: a manual $AGENT task is waiting; patrol goes last"; }
    elif [ -z "$head" ] || [ "$head" = "$ID" ]; then
      if flock -n 8; then
        # Someone who outranks this task may have queued since the question above: give way.
        head=$(queue_head)
        if [ -z "$head" ] || [ "$head" = "$ID" ]; then break; fi
        flock -u 8
        echo "$(ts) queue: yielding the $AGENT lock to $head (it goes first by queue order)"
      fi
    elif [ "$head" != "$told" ]; then
      told=$head; echo "$(ts) queue: $head goes before this task"
    fi
    if [ "$(now)" -ge "$end" ]; then rm -f "${QDIR:?}/${ID:?}"; WAITING=""; write_result; return 1; fi
  done
  rm -f "${QDIR:?}/${ID:?}"
  printf 'ID=%s\nPID=%s\nSINCE=%s\n' "$ID" "$$" "$(now)" >"$LOCKDIR/.queue/.$AGENT.holder.$ID" \
    && mv -f "$LOCKDIR/.queue/.$AGENT.holder.$ID" "$LOCKDIR/.queue/$AGENT.holder"
  LOCK_HELD=1 WAITING=""; write_result
  echo "$(ts) lock held"
}
release_agent_lock() {
  [ -n "$LOCK_HELD" ] || return 0
  grep -qsx "ID=$ID" "$LOCKDIR/.queue/$AGENT.holder" && rm -f "${LOCKDIR:?}/.queue/${AGENT:?}.holder"
  flock -u 8 2>/dev/null; exec 8>&-
  LOCK_HELD=""
}
# A quota wait of another task of this agent (the account is out): wait for its reset instead of
# spending an attempt, a quota resume and a notification to find out the same. Agent-wide on
# purpose: claude's and codex's limits are per account. Written by the sleeper, never deleted
# early except by an attempt that got through (the quota is evidently back).
QUOTA_HINT="$LOCKDIR/.queue/$AGENT.quota" HINT_UNTIL=""
take_lock() {  # <budget seconds>: 0 = lock held; 1 = out of time (HINT_UNTIL set when a quota wait was the reason)
  local budget=$1 until by
  cancel_guard
  HINT_UNTIL=""
  while :; do
    wait_agent_lock "$budget" || return 1
    until=$(sed -n 's/^UNTIL=//p' "$QUOTA_HINT" 2>/dev/null); by=$(sed -n 's/^BY=//p' "$QUOTA_HINT" 2>/dev/null)
    if ! [[ $until =~ ^[0-9]+$ ]] || [ "$by" = "$ID" ] || [ "$until" -le $(( $(now) + QUEUE_POLL_SEC )) ] \
       || [ "$until" -ge $(( $(now) + 8 * 86400 )) ]; then
      return 0
    fi
    release_agent_lock
    if [ $(( DEADLINE_EPOCH - until )) -lt $(( MIN_RUN_SEC + KILL_MARGIN )) ]; then HINT_UNTIL=$until; return 1; fi
    # Wake a little after the task that hit the quota, so it is back in the queue first.
    until=$(( until + 2 * QUEUE_POLL_SEC ))
    WAITING=quota WAKE_AT=$until; write_result
    echo "---- $(ts) quota: $AGENT is out of quota ($by hit it); waiting without spending an attempt; sleeping until $(date -d "@$until" '+%F %T')"
    sleep "$(( until - $(now) ))" & CHILD=$!; wait "$CHILD"; CHILD=""
    WAKE_AT=""
    cancel_guard
    budget=$(( $(remaining) - MIN_RUN_SEC - KILL_MARGIN )); [ "$budget" -gt 0 ] || budget=0
  done
}
# One writer per session: held from the moment the session is known until the task ends, also
# across a quota wait that has released the agent lock (a resumed copy would write concurrently).
SESSION_LOCKED=""
lock_session() {
  [ -n "$SESSION" ] && [ "$SESSION_LOCKED" != "$SESSION" ] || return 0
  exec 7>"$LOCKDIR/session-$SESSION.lock"
  flock -n 7 || return 1
  SESSION_LOCKED=$SESSION
}
lock_budget=$(( $(remaining) - MIN_RUN_SEC - KILL_MARGIN ))
[ "$lock_budget" -gt 0 ] || lock_budget=0
if ! take_lock "$lock_budget"; then
  STATE=blocked; RC=75; FINAL_TEXT="另一个 $AGENT 委派任务一直占着执行槽，截止前没轮到，未启动。"
  [ -n "$HINT_UNTIL" ] && STATE=quota FINAL_TEXT="$AGENT 额度到 $(date -d "@$HINT_UNTIL" '+%m-%d %H:%M') 才恢复，截止前轮不到，未启动。"
  finish; exit 75
fi
if ! lock_session; then
  STATE=blocked; RC=75; FINAL_TEXT="会话 $SESSION 已有别的派发任务在写，拒绝并发续跑。"; finish; exit 75
fi

# ---- helpers ----------------------------------------------------------------------
# Echo the epoch of the reset named in a quota message. Wording from the binaries:
#   claude 2.1.270  "resets 1am (Asia/Shanghai)", beyond 24h "resets Sep 20, 3pm (Asia/Shanghai)",
#                   another year "resets Jan 3, 2027, 1pm (...)"
#   codex 0.154.0   "try again at 1:29 PM." / "try again at Sep 20, 2026 1:29 PM." ("20th" seen too)
# A time without a date means its next occurrence. The date used to be dropped, so a weekly
# reset days away woke the runner the next day (codex token audit B2, 2026-09-15).
# RESET_NOW (epoch) is a test seam.
next_reset_epoch() {
  python3 - "$1" "${2:-Asia/Shanghai}" <<'PY'
import datetime, os, re, sys, zoneinfo
text, tz = sys.argv[1], sys.argv[2]
zm = re.search(r'\(([A-Za-z_]+/[A-Za-z_/+-]+)\)', text)
if zm:
    try:
        zoneinfo.ZoneInfo(zm.group(1))
        tz = zm.group(1)
    except Exception:
        pass
z = zoneinfo.ZoneInfo(tz)
now = datetime.datetime.fromtimestamp(int(os.environ.get('RESET_NOW') or datetime.datetime.now().timestamp()), z)
MONTHS = 'jan feb mar apr may jun jul aug sep oct nov dec'.split()
d = re.search(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,\s*(\d{4})\b)?', text, re.I)
t = re.search(r'(?<![\d:])(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b', text[d.end():] if d else text, re.I)
if not t and not d:
    sys.exit(1)
h, mi = (int(t.group(1)) % 12 + (12 if t.group(3).lower() == 'p' else 0), int(t.group(2) or 0)) if t else (0, 0)
try:
    if d:
        year = int(d.group(3)) if d.group(3) else now.year
        r = datetime.datetime(year, MONTHS.index(d.group(1)[:3].lower()) + 1, int(d.group(2)), h, mi, tzinfo=z)
        if not d.group(3) and r < now - datetime.timedelta(days=1):
            r = r.replace(year=year + 1)
    else:
        r = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if r <= now:
            r += datetime.timedelta(days=1)
except ValueError:
    sys.exit(1)
print(int(r.timestamp()))
PY
}

# Codex rollouts carry each window's exact reset (rate_limits.primary/secondary.resets_at, epoch
# seconds); the message is only minute precision. Echo the latest future reset among the windows
# that are full in the session's newest non-empty sample (the very last one can be all null).
codex_reset_epoch() {
  local f
  f=$(find "$CODEX_HOME_DIR/sessions" -name "rollout-*-$1.jsonl" -newer "$DIR/meta.env" 2>/dev/null | head -1)
  [ -n "$f" ] || return 1
  python3 - "$f" "$(now)" <<'PY'
import json, sys
path, now = sys.argv[1], int(sys.argv[2])
sample = None
for line in open(path, errors='replace'):
    if '"token_count"' not in line:
        continue
    try:
        rl = (json.loads(line).get('payload') or {}).get('rate_limits') or {}
    except ValueError:
        continue
    if rl.get('primary') or rl.get('secondary'):
        sample = rl
resets = [int(w['resets_at']) for w in ((sample or {}).get('primary'), (sample or {}).get('secondary'))
          if w and (w.get('used_percent') or 0) >= 100 and isinstance(w.get('resets_at'), (int, float))]
resets = [r for r in resets if r > now]
if not resets:
    sys.exit(1)
print(max(resets))
PY
}

# `claude -p` labels its transcript entrypoint "sdk-cli", and the interactive /resume list hides
# those, so dispatched sessions could not be found there (2026-09-15). Relabel the finished
# attempt's transcript "cli". This is a Claude Code internal: on 2.1.270 a copy differing only in
# this field was listed. If a later version filters differently the session is just hidden again;
# `claude --resume <id>` opens it either way. Escaped occurrences inside message text never match.
show_in_resume_list() {
  local f
  for f in "$CLAUDE_HOME_DIR"/projects/*/"$1".jsonl; do
    [ -f "$f" ] && grep -qF '"entrypoint":"sdk-cli"' "$f" || continue
    sed 's/"entrypoint":"sdk-cli"/"entrypoint":"cli"/g' "$f" >"$f.relabel" \
      && chmod --reference="$f" "$f.relabel" && mv -f "$f.relabel" "$f"
  done
}

# Session ids appear in the CLI output as soon as it prints them (see wait_attempt).
learn_session() {  # <attempt output>
  case "$AGENT" in
    # -m1 stops at the first matching line, but -o still prints every match on it (an opencode
    # event names its sessionID twice), hence head -1.
    codex) SESSION=$(grep -m1 -o '"type":"thread.started","thread_id":"[^"]*"' "$1" 2>/dev/null | head -1 | sed 's/.*"thread_id":"//; s/"$//') ;;
    opencode) SESSION=$(grep -m1 -o '"sessionID":"[^"]*"' "$1" 2>/dev/null | head -1 | sed 's/.*:"//; s/"$//') ;;
  esac
}
# ---- stall detection ---------------------------------------------------------------
# 2026-09-24/25 (patrol R179-R186, R199, R202): opencode's free model answered "Rate limit
# exceeded" and opencode retried inside the run without printing anything; the attempt sat
# silent - 0 bytes, or no new event after its last step - until the 5400s timeout. Progress is
# anything a stuck CLI does not produce: new output (claude -p prints only at the end, so its
# transcript counts, subagent files included), or a tool at work: a process the CLI started
# that used CPU or started processes since the last check. An idle leftover (a server left in
# the background, a lazily started helper) does not hide a stall. A tool counts only for its first
# STALL_TOOL seconds, so a leftover that keeps using CPU (or keeps starting processes) cannot hide
# a stall either. codex also counts a command it is still waiting on (codex_waiting). A tool idle
# for longer than the limit is cut off with the attempt, so the limits stay above the agents' own
# 10-minute tool caps.
progress_mark() {  # <attempt output>: changes whenever the attempt wrote something
  stat -c '%s' "$1" "${1%.*}.err" 2>/dev/null
  if [ "$AGENT" = claude ] && [ -n "$SESSION" ]; then
    find "$CLAUDE_HOME_DIR"/projects/*/"$SESSION".jsonl "$CLAUDE_HOME_DIR"/projects/*/"$SESSION" \
      -type f -printf '%s %p\n' 2>/dev/null | sort
  fi
}
# <pid> <seconds since start>: "pid:cpu-ticks" of every process under <pid> except those started
# with the attempt (the CLI itself, a wrapper); changes when a tool works or starts another process.
# A tool is the outermost such process and everything under it; once it is STALL_TOOL old none of
# them is listed, and a line "over" says so.
tool_activity() {
  ps -e -o pid=,ppid=,etimes= 2>/dev/null | awk -v root="$1" -v cli="$(( $2 - 3 ))" -v max="$STALL_TOOL" '
    { parent[$1] = $2; age[$1] = $3 }
    END {
      for (p in parent) {
        if (p == root || age[p] >= cli) continue
        top = p
        for (q = parent[p]; q in parent && q != root && q > 1; q = parent[q]) if (age[q] < cli) top = q
        if (q != root) continue
        if (max > 0 && age[top] >= max) { over = 1; continue }
        f = "/proc/" p "/stat"
        if ((getline line < f) > 0) { sub(/.*\) /, "", line); split(line, v, " "); print p ":" v[12] + v[13] }
        close(f)
      }
      if (over) print "over"
    }' | sort
}
# <attempt output>: codex printed item.started for a command and not yet its item.completed.
codex_waiting() {
  [ "$AGENT" = codex ] || return 1
  awk '/"type":"item.started"/ && /"type":"command_execution"/ && match($0, /"id":"[^"]*"/) { open[substr($0, RSTART, RLENGTH)] = 1 }
       /"type":"item.completed"/ && match($0, /"id":"[^"]*"/) { delete open[substr($0, RSTART, RLENGTH)] }
       END { for (i in open) exit 0; exit 1 }' "$1" 2>/dev/null
}

# Wait for the running attempt. Learns the session id as soon as the CLI prints it, stops the
# attempt when an instruction was appended with -now and the session can be resumed, and stops
# it when it stalls (STALLED, STALL_QUIET).
wait_attempt() {  # <attempt output>; sets ARC, INTERRUPTED and STALLED
  INTERRUPTED="" STALLED="" STALL_QUIET=0
  local i mark last_mark act last_act="" over started quiet limit why wrote="" next_check=0 last_output last_alive
  started=$(now); last_output=$started; last_alive=$started; last_mark=$(progress_mark "$1")
  while kill -0 "$CHILD" 2>/dev/null; do
    if [ -z "$SESSION" ]; then
      learn_session "$1"
      [ -n "$SESSION" ] && write_result
    fi
    if [ -z "$INTERRUPTED" ] && inbox_has_now && session_exists; then
      INTERRUPTED=1
      echo "---- $(ts) appended instruction: stopping the attempt to deliver it to session $SESSION"
      kill -TERM "$CHILD" 2>/dev/null
      for i in $(seq 20); do kill -0 "$CHILD" 2>/dev/null || break; sleep 1; done
      kill -KILL -- "-$CHILD" 2>/dev/null
    fi
    if [ -z "$INTERRUPTED$STALLED" ] && [ "$STALL_IDLE" -gt 0 ] && [ "$(now)" -ge "$next_check" ]; then
      next_check=$(( $(now) + STALL_CHECK_SEC ))
      mark=$(progress_mark "$1")
      act=$(tool_activity "$CHILD" "$(( $(now) - started ))")
      over=""; [[ $'\n'$act$'\n' == *$'\n'over$'\n'* ]] && { over=1; act=$(grep -vx over <<<"$act" || true); }
      if [ "$mark" != "$last_mark" ]; then
        last_mark=$mark wrote=1 last_output=$(now) last_alive=$(now)
      elif [ -n "$act" ] && [ "$act" != "$last_act" ]; then
        last_alive=$(now)   # the model is waiting on a tool that is working
      elif [ -n "$act" ] && codex_waiting "$1"; then
        last_alive=$(now)   # codex is waiting on a command it started, idle as that may be
      fi
      last_act=$act
      limit=$STALL_IDLE; [ -z "$wrote" ] && limit=$STALL_FIRST
      quiet=$(( $(now) - last_alive ))
      if [ "$limit" -gt 0 ] && [ "$quiet" -ge "$limit" ]; then
        STALLED=1 STALL_QUIET=$quiet STALLS=$((STALLS + 1))
        if [ -n "$wrote" ]; then why="no new output since $(date -d "@$last_output" '+%T') and no tool at work"; else why="no output at all"; fi
        [ -n "$over" ] && why="$why; a tool has run for over ${STALL_TOOL}s"
        echo "---- $(ts) no progress for ${quiet}s ($why; limit ${limit}s): stopping the attempt as stalled"
        write_result
        kill -TERM "$CHILD" 2>/dev/null
        for i in $(seq 20); do kill -0 "$CHILD" 2>/dev/null || break; sleep 1; done
        kill -KILL -- "-$CHILD" 2>/dev/null
      fi
    fi
    sleep "$POLL_SEC" & wait $! 2>/dev/null
  done
  wait "$CHILD"; ARC=$?; CHILD=""
}

# NEXT_KIND says what this attempt sends: task (the prompt), continue (after a failure) or
# append (only the appended instructions). Pending inbox messages ride along with any of them.
NEXT_KIND=task INTERRUPT_NOTE="" RUN_NO=0
run_attempt() {  # <cap>; sets ARC, AKIND (ok|quota|error), ATEXT, INTERRUPTED, SESSION when learned
  local cap=$1 alog prompt block="" resumable=""
  RUN_NO=$((RUN_NO + 1)); alog="$DIR/attempt$RUN_NO"
  { session_exists || [ -n "${RESUME:-}" ]; } && resumable=1
  if block=$(take_inbox); then
    APPENDS=$(( APPENDS + $(grep -c '^【追加指令' <<<"$block") ))
    echo "---- $(ts) delivering appended instruction(s):"
    printf '%s\n' "$block" | head -n 12 | redact | sed 's/^/     > /'
    block="$APPEND_HEAD
$block

$APPEND_TAIL"
  else
    block=""
  fi
  [ -n "$INTERRUPT_NOTE" ] && block="（你上一步正在做的事被这条追加指令打断了：进程被停止，当时在跑的命令可能没跑完。）
$block"
  INTERRUPT_NOTE=""
  case "$NEXT_KIND" in
    continue) prompt=$CONTINUE_PROMPT ;;
    append) prompt="" ;;
    *) prompt=$(cat "$DIR/prompt.md") ;;
  esac
  # Nothing to resume (the CLI died before it saved a session): send the whole task again.
  [ "$NEXT_KIND" != task ] && [ -z "$resumable" ] && prompt=$(cat "$DIR/prompt.md")
  if [ -n "$block" ]; then prompt="${prompt:+$prompt

}$block"; fi
  [ -n "$prompt" ] || prompt=$CONTINUE_PROMPT
  # Serialize the final launch decision with the cancellation marker. The cancel
  # writer releases this lock before signalling; children close it before exec.
  exec 5>"$DIR/.launch.lock"
  flock -x 5
  cancel_guard
  # fd 6 is the run slot: agents and anything they leave running must not keep it locked.
  if [ "$AGENT" = claude ]; then
    local args=(-p --output-format json --model "$CUR_MODEL" --effort "$EFFORT" --dangerously-skip-permissions)
    if [ -n "$resumable" ]; then
      args+=(--resume "$SESSION")
    else
      # Choose the id up front: a cancel or an append then knows the session before claude's
      # final JSON exists (cancelled tasks used to end with no session to resume).
      [ -n "$SESSION" ] || SESSION=$(python3 -c 'import uuid; print(uuid.uuid4())')
      args+=(--session-id "$SESSION")
    fi
    write_result
    ( cd "$CWD" && exec timeout -k 60 "$cap" claude "${args[@]}" "$prompt" </dev/null ) \
      >"$alog.json" 2>"$alog.err" 6>&- 5>&- &
    CHILD=$!; flock -u 5; exec 5>&-; wait_attempt "$alog.json"
    eval "$(python3 - "$alog.json" <<'PY'
import json, re, shlex, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    d = {}
text = d.get('result') or ''
kind = 'ok' if d and not d.get('is_error') and d.get('subtype') == 'success' else 'error'
if re.search(r"hit your (session|usage|weekly) limit|usage limit reached", text, re.I):
    kind = 'quota'
print('AKIND=' + shlex.quote(kind))
print('ATEXT=' + shlex.quote(text))
print('ASESSION=' + shlex.quote(d.get('session_id') or ''))
PY
)"
    [ -n "$ASESSION" ] && SESSION=$ASESSION
    [ "$ARC" -ne 0 ] && [ "$AKIND" = ok ] && AKIND=error
    [ -z "$ATEXT" ] && ATEXT=$(tail -n 5 "$alog.err" 2>/dev/null)
    session_exists && show_in_resume_list "$SESSION"
  elif [ "$AGENT" = opencode ]; then
    # Permissions come from ~/.config/opencode/opencode.json ("permission": "allow").
    local args=(run --format json -m "$CUR_MODEL")
    [ -n "$EFFORT" ] && args+=(--variant "$EFFORT")
    [ -n "$resumable" ] && args+=(-s "$SESSION")
    ( cd "$CWD" && exec timeout -k 60 "$cap" opencode "${args[@]}" -- "$prompt" </dev/null ) \
      >"$alog.jsonl" 2>"$alog.err" 6>&- 5>&- &
    CHILD=$!; flock -u 5; exec 5>&-; wait_attempt "$alog.jsonl"
    # opencode 1.18 exits 0 even when the model call failed; the run's `error` events decide.
    eval "$(python3 - "$alog.jsonl" <<'PY'
import json, shlex, sys
session, texts, order, errors = '', {}, [], []
for line in open(sys.argv[1], errors='replace'):
    line = line.strip()
    if not line.startswith('{'):
        continue
    try:
        e = json.loads(line)
    except ValueError:
        continue
    session = session or e.get('sessionID') or ''
    part = e.get('part') or {}
    if e.get('type') == 'text':
        mid = part.get('messageID') or ''
        if mid not in texts:
            texts[mid] = []
            order.append(mid)
        texts[mid].append(part.get('text') or '')
    elif e.get('type') == 'error':
        err = e.get('error') or {}
        errors.append((err.get('data') or {}).get('message') or err.get('name') or 'error')
print('ASESSION=' + shlex.quote(session))
print('ATEXT=' + shlex.quote('\n'.join(texts[order[-1]]) if order else ''))
print('AERR=' + shlex.quote(errors[-1] if errors else ''))
PY
)"
    [ -n "$ASESSION" ] && SESSION=$ASESSION
    # Free-tier rate limits carry no reset time, so they are plain errors retried after RETRY_WAIT.
    if [ "$ARC" -eq 0 ] && [ -z "$AERR" ]; then
      AKIND=ok
    else
      AKIND=error; [ -n "$AERR" ] && ATEXT="${ATEXT:+$ATEXT
}$AERR"
      [ -z "$ATEXT" ] && ATEXT=$(tail -n 5 "$alog.err" 2>/dev/null)
    fi
  else
    local sub=(exec) tail_args=()
    [ -n "$resumable" ] && sub=(exec resume) && tail_args=("$SESSION")
    rm -f "$DIR/last-message.md"   # never report a previous attempt's message as this one's
    # --json: session id and errors come from structured events (thread.started, error,
    # turn.failed) instead of grepping human-readable output; -o keeps the final message.
    ( cd "$CWD" && exec timeout -k 60 "$cap" codex "${sub[@]}" --json \
        -c "model=\"$CUR_MODEL\"" -c "model_reasoning_effort=\"$EFFORT\"" \
        --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check \
        -o "$DIR/last-message.md" "${tail_args[@]}" "$prompt" </dev/null ) >"$alog.jsonl" 2>"$alog.err" 6>&- 5>&- &
    CHILD=$!; flock -u 5; exec 5>&-; wait_attempt "$alog.jsonl"
    eval "$(python3 - "$alog.jsonl" <<'PY'
import json, re, shlex, sys
# Quota wording from the codex 0.154.0 binary: usage limit (with or without a reset time),
# workspace out of credits / credit limit, spend cap. Only top-level error events count, so
# tool output that merely mentions these words is never mistaken for a quota stop.
QUOTA = re.compile(r"hit your usage limit|reached your usage limit|usage limit reached|"
                   r"out of credits|credit limit|spend cap", re.I)
session, top_errors, turn_failures = '', [], []
for line in open(sys.argv[1], errors='replace'):
    line = line.strip()
    if not line.startswith('{'):
        continue
    try:
        e = json.loads(line)
    except ValueError:
        continue
    t = e.get('type')
    if t == 'thread.started' and not session:
        session = e.get('thread_id') or ''
    elif t == 'error':
        top_errors.append(e.get('message') or '')
    elif t == 'turn.failed':
        turn_failures.append((e.get('error') or {}).get('message') or '')
# The terminal error is the last turn.failed; a top-level error only stands in when the run
# ended without one (killed, timed out). Earlier non-fatal notices never decide the outcome.
final = turn_failures[-1] if turn_failures else (top_errors[-1] if top_errors else '')
print('ASESSION=' + shlex.quote(session))
print('AQUOTA=' + shlex.quote(final if QUOTA.search(final) else ''))
print('AERR=' + shlex.quote(final))
PY
)"
    [ -n "$ASESSION" ] && SESSION=$ASESSION
    ATEXT=$(cat "$DIR/last-message.md" 2>/dev/null)
    if [ "$ARC" -eq 0 ]; then
      AKIND=ok
    elif [ -n "$AQUOTA" ]; then
      AKIND=quota; ATEXT=$AQUOTA
    else
      AKIND=error; [ -z "$ATEXT" ] && ATEXT=${AERR:-$(tail -n 5 "$alog.err" 2>/dev/null)}
    fi
  fi
}

# ---- attempts ---------------------------------------------------------------------
# ATTEMPTS counts tries at the task (first run, retries after failures). Delivering an appended
# instruction continues the current attempt in the same session and does not use up a retry.
STATE=running
while [ "$ATTEMPTS" -lt "$MAX_ATTEMPTS" ] || [ "$NEXT_KIND" = append ]; do
  cancel_guard
  slot_budget=$(( $(remaining) - MIN_RUN_SEC - KILL_MARGIN ))
  if ! acquire_slot "$(( slot_budget > 0 ? slot_budget : 0 ))"; then
    if [ "$ATTEMPTS" -eq 0 ]; then STATE=blocked; else STATE=timeout; fi
    FINAL_TEXT="${FINAL_TEXT:-同时在跑的 $AGENT 委派任务已满 $AGENT_SLOTS 个，截止前没轮到。}"; break
  fi
  cap=$(( $(remaining) - KILL_MARGIN ))
  [ "$cap" -gt "$TIMEOUT" ] && cap=$TIMEOUT
  min_start=$MIN_RUN_SEC
  [ "$TIMEOUT" -lt "$min_start" ] && min_start=$TIMEOUT
  if [ "$cap" -lt "$min_start" ]; then
    release_slot
    STATE=timeout; FINAL_TEXT="${FINAL_TEXT:-截止前剩余时间不足，未再尝试。}"; break
  fi
  kind=$NEXT_KIND
  [ "$kind" = append ] || ATTEMPTS=$((ATTEMPTS + 1))
  apply_override
  write_result
  echo "---- $(ts) attempt $ATTEMPTS/$MAX_ATTEMPTS ($kind) cap=${cap}s session=${SESSION:--} model=$CUR_MODEL${EFFORT:+/$EFFORT}"
  run_attempt "$cap"
  release_slot
  update_usage
  apply_budget   # a retry/resume budget changed during the attempt counts for the decision below
  if ! lock_session; then
    STATE=blocked; FINAL_TEXT="会话 $SESSION 已有别的派发任务在写，拒绝并发续跑。"; break
  fi
  # An attempt that got through proves the quota is back: drop a quota hint left by anyone.
  if [ "$AKIND" != quota ] && [ -e "$QUOTA_HINT" ]; then rm -f "${QUOTA_HINT:?}"; fi
  if [ -n "$STALLED" ]; then
    # A stall is a failed attempt: it uses the retry budget (MAX_ATTEMPTS), never QUOTA_RESUMES,
    # and goes down the ordinary error path - next pool model, same session when there is one.
    [ "$AKIND" = ok ] && AKIND=error
    ATEXT="${ATEXT:+$ATEXT
}runner：本次 attempt ${STALL_QUIET}s 没有任何进展（无新输出，也没有在干活的工具进程），判定卡死并中止。"
  fi
  RC=$ARC; FINAL_TEXT=$ATEXT
  echo "---- $(ts) attempt $ATTEMPTS ($kind) rc=$ARC kind=$AKIND session=${SESSION:--}${INTERRUPTED:+ interrupted}${STALLED:+ stalled}"
  printf '%s\n' "$ATEXT" | tail -n 8 | redact | sed 's/^/     | /'

  if [ -n "$INTERRUPTED" ]; then
    # The resumed session carries on this same attempt with the appended text.
    NEXT_KIND=append INTERRUPT_NOTE=1; write_result; continue
  fi
  if [ "$AKIND" = ok ]; then
    if [ "$(inbox_pending)" -gt 0 ] && session_exists; then
      echo "---- $(ts) finished with appended instruction(s) waiting; delivering them"
      NEXT_KIND=append; continue
    fi
    STATE=ok; break
  fi
  [ "$ARC" -eq 124 ] && echo "---- attempt hit its timeout"
  NEXT_KIND=continue

  wake=""
  if [ "$AKIND" = quota ]; then
    if [ "$AGENT" = codex ] && [ -n "$SESSION" ] && reset=$(codex_reset_epoch "$SESSION"); then
      wake=$((reset + ${QUOTA_WAKE_PAD_SEC:-60})); echo "---- quota resets $(date -d "@$reset" '+%F %T') (from rollout)"
    elif reset=$(next_reset_epoch "$ATEXT"); then
      # Minute precision: "12:54 AM" can mean 00:54:59.
      wake=$((reset + ${QUOTA_WAKE_PAD_SEC:-120})); echo "---- quota resets $(date -d "@$reset" '+%F %T') (from message)"
    fi
    if [ -z "$wake" ]; then STATE=quota; break; fi
  else
    wake=$(( $(now) + RETRY_WAIT ))
    if [ "${#MODEL_POOL[@]}" -gt 1 ]; then
      MODEL_IDX=$(( (MODEL_IDX + 1) % ${#MODEL_POOL[@]} ))
      CUR_MODEL=${MODEL_POOL[$MODEL_IDX]}
      echo "---- $(ts) switching to model $CUR_MODEL for the next attempt"
      # Another model is not rate-limited by this one: retry soon; wait the full time only
      # after the whole pool has failed once in a row.
      [ "$MODEL_IDX" -ne 0 ] && wake=$(( $(now) + FALLBACK_WAIT ))
    fi
  fi
  if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ] || [ -z "$SESSION" -a "$AKIND" = quota ] \
     || [ $(( DEADLINE_EPOCH - wake )) -lt $((MIN_RUN_SEC + KILL_MARGIN)) ]; then
    if [ "$AKIND" = quota ]; then
      STATE=quota
    elif [ "$ARC" -eq 124 ] || [ "$(remaining)" -lt $((MIN_RUN_SEC + KILL_MARGIN)) ]; then
      STATE=timeout   # the attempt ran into the deadline, or no time is left for another one
    else
      STATE=failed
    fi
    break
  fi
  if [ "$AKIND" = quota ]; then
    if [ "$QUOTA_RESUMES_USED" -ge "$QUOTA_RESUMES" ]; then
      STATE=quota
      FINAL_TEXT="$ATEXT
已达自动额度续跑上限 $QUOTA_RESUMES；保留会话与产物。再次 resume 会重放历史上下文，需显式追加任务或带产物另开任务。"
      echo "---- quota resume budget exhausted ($QUOTA_RESUMES_USED/$QUOTA_RESUMES)"
      break
    fi
    QUOTA_RESUMES_USED=$((QUOTA_RESUMES_USED + 1))
  fi
  WAITING=$AKIND WAKE_AT=$wake
  [ "$WAITING" = error ] && WAITING=retry
  echo "---- $(ts) $AKIND; sleeping until $(date -d "@$wake" '+%F %T')"
  # Persist the learned session and the wait before sleeping: `status` otherwise showed a
  # stale result.env (no session, UPDATED at start) for the whole quota wait.
  write_result
  if [ "$AKIND" = quota ]; then
    # A silent quota wait looked like a hang and got review-merge-1514-1515 cancelled (2026-09-15).
    # 60s like the end-of-task notice. It used to be 30s, and `openclaw message send` takes
    # 13-25s just to start on this host (both legs at once), so Telegram missed three of these
    # notices on 2026-09-26/27, each exactly at the limit. Nothing else bounds this wait (the
    # cancel path's 30s is bounded by the stop budget; this is not that path); the agent lock
    # is released right after it.
    notify "⏳ 委派任务 $NAME（$AGENT）额度用尽，$(date -d "@$wake" '+%m-%d %H:%M') 自动在同一会话续跑（第 $QUOTA_RESUMES_USED/$QUOTA_RESUMES 次，会重放历史上下文，缓存读取也有成本）。任务没卡住，不用取消。$(quota_line)
id：$ID
日志：$DIR/run.log" 60
    # The wait releases the agent lock (kcn 2026-09-26: a claude task asleep on its 5h reset held
    # claude.lock for 4 hours while three others queued). The session lock stays, so nothing else
    # can resume this session meanwhile. The hint tells the next task of this agent that the
    # account is out, so it waits too instead of spending an attempt to find out.
    printf 'UNTIL=%s\nBY=%s\n' "$wake" "$ID" >"$QUOTA_HINT.$ID" && mv -f "$QUOTA_HINT.$ID" "$QUOTA_HINT"
    release_agent_lock
    echo "---- $(ts) released the $AGENT lock for the quota wait (session lock kept)"
    sleep "$(( wake - $(now) ))" &
    CHILD=$!; wait "$CHILD"; CHILD=""
    WAKE_AT=""
    cancel_guard
    # Back in the queue with the original QUEUED_AT: by then it has usually waited long enough to
    # be protected, so it goes first among the tasks of its agent unless one was queued earlier.
    lock_budget=$(( $(remaining) - MIN_RUN_SEC - KILL_MARGIN ))
    if ! take_lock "$(( lock_budget > 0 ? lock_budget : 0 ))"; then
      STATE=timeout; FINAL_TEXT="$ATEXT
额度恢复后重新排队等 $AGENT 锁，截止前没轮到；会话保留。"; break
    fi
  else
    # A retry wait ends early when an instruction is appended with -now: there is no quota to wait for.
    while [ "$(now)" -lt "$wake" ] && ! inbox_has_now; do
      sleep "$POLL_SEC" & CHILD=$!; wait "$CHILD"; CHILD=""
    done
    WAKE_AT=""
    cancel_guard
  fi
done
cancel_guard
WAITING="" WAKE_AT=""
[ "$STATE" = running ] && STATE=failed

OUTCOME=$(printf '%s\n' "$FINAL_TEXT" | grep -oE 'STATUS:[[:space:]]*(DONE|PARTIAL|BLOCKED)' | tail -1 | awk '{print $NF}' | sed 's/STATUS://')
if [ "$STATE" = ok ] && [ -z "$OUTCOME" ]; then
  STATE=unverified   # process finished cleanly, but the agent never said whether the task is done
elif [ "$STATE" = ok ] && [ "$OUTCOME" != DONE ]; then
  STATE=partial   # process finished cleanly, but the agent says the task is not done
fi
finish
case "$STATE" in ok) exit 0 ;; partial|unverified) exit 3 ;; quota|blocked) exit 75 ;; *) exit 1 ;; esac
