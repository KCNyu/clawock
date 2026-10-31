#!/usr/bin/env bash
# Dispatch a headless Claude Code / Codex / opencode / dsh task as an independent systemd unit.
# The caller (OpenClaw chat turn, dsh, a terminal) returns immediately; the task
# survives the caller's process, gateway restarts and dsh restarts.
#
#   dispatch.sh claude|codex|opencode|dsh --name <slug> [options] < prompt.md
#   dispatch.sh append <id> [--queue] < more.md   # add instructions to a task, same session
#   dispatch.sh status [--all] [<id>]  # recent tasks (--all includes patrol-* rounds), or one task
#   dispatch.sh result <id> [--run N] # terminal envelope and selected model report
#   dispatch.sh inbox <id>           # JSON brief + pending/attached/not-delivered appends
#   dispatch.sh log <id>             # redacted runner log tail
#   dispatch.sh summary [--since YYYY-MM-DD] [--agent a,b] [--all] [--json]  # per-agent totals (frozen results; cost is an estimate)
#   dispatch.sh mandate <id> [check <action>]  # machine-readable authorization created at dispatch
#   dispatch.sh cancel <id>          # stop a running task (records state=cancelled)
#   dispatch.sh queue [--json]       # each agent's lock holder and queue in real order (task_queue_ops.py)
#   dispatch.sh adopt <bg-id|session-id> [--dry-run] [options] [< more.md]
#                                    # resume a claude session dispatch did not start (a `claude --bg`
#                                    # session, a terminal one that died) as a task; stops the bg copy
#
# append: while the task runs, its current step is stopped within seconds and the same session
# resumes with the new instructions (--queue: deliver when the current attempt ends instead).
# Before the task starts they join the prompt; after it ended, a new task resumes its session.
# Exit 3 queued nothing: task_finishing (wrapping up, ~1-2 min) or legacy_runner (may be hours)
# - wait until the task ended, then append again; task_starting - retry in a few seconds.
#
# Options:
#   --name <slug>          short task label (required)
#   --prompt-file <f>      read the prompt from a file instead of stdin
#   --template <name>      append templates/<name>.md before the contract (repeatable; e.g. review)
#   --quota-resumes <n>   automatic resumes after quota waits (default 3; 0 disables; also bounded by attempts/deadline)
#   --resume <session>     continue an existing claude/codex/opencode/dsh session (to finish interrupted work;
#                          a re-review is a new task quoting the earlier findings, not a resume)
#   --cwd <dir>            only with --resume, for a session recorded under another project dir;
#                          new tasks always run in /root (AGENTS/CLAUDE.md + shared memory load from there)
#   --model <m>            default: claude-opus-5-5 / gpt-6.1-sol (gpt-6-astra costs several times the quota)
#                          / opencode: the pool file's first model (see --fallback-models)
#                          / dsh: <provider>/<model> of a dsh route, deepseek-official/deepseek-flash
#                          (DeepSeek-V4.1-Flash-1017); paid per token from the DeepSeek balance
#   --fallback-models a,b  opencode only: after a failed attempt continue the same session on the next
#                          model (wraps around). Default: opencode-fallback-models, which also supplies
#                          the primary; set explicitly to override the whole pool.
#   --effort <e>           default: high for claude, medium for codex, none for opencode (its --variant),
#                          max for dsh (off|low|high|max, the headless profile's own default)
#   --timeout <sec>        per attempt (default 21600 = 6h)
#   --deadline <datetime>  absolute end for the whole task, Asia/Shanghai (default: now + 24h, max 72h)
#   --notify <channels>    comma list of weixin|telegram for the completion message
#                          (default weixin,telegram; patrol rounds pass none)
#   --origin-session <key> the OpenClaw session that gets a turn when the task ends or runs out of
#                          quota. Default: the chat turn running this command (wake-session.py
#                          finds it); nothing when no turn is. `none` asks for no turn.
#   --no-restart           deny `gateway.restart` in the task's mandate. The default allows a
#                          restart when it is needed to make the task's change effective;
#                          refresh_live.sh and restart_gateway.sh check the mandate.
set -euo pipefail
export TZ=Asia/Shanghai

BASE=/root/logs/agent-dispatch
RUNNER=/root/tools/agent-dispatch/run-agent.sh
HELPER_DIR=$(dirname "$(readlink -f "$0")")
mkdir -p "$BASE"

show_state() {  # prints STATE/OUTCOME for a task dir
  local d=$1
  if [ -r "$d/result.env" ]; then
    ( . "$d/result.env"; printf '%s%s' "$STATE" "${OUTCOME:+/$OUTCOME}"; printf ' notify_sent=%s notify_failed=%s stop=%s stage=%s needs=%s attention=%s' \
        "${NOTIFIED:-unknown}" "${NOTIFY_FAILED:--}" "${STOP_REASON:--}" "${STAGE:--}" "${NEEDS:--}" "${ATTENTION:--}" )
  else
    printf 'pending'
  fi
}

cmd="${1:-}"; shift || true
ADOPT_STOP=""
case "$cmd" in
  result)
    exec python3 /root/tools/agent-dispatch/read-result.py "$@" ;;
  log)
    exec python3 /root/tools/agent-dispatch/task_queue_ops.py log "$@" ;;
  summary)
    if [ "${1:-}" = --json ]; then shift; exec python3 /root/tools/agent-dispatch/task_queue_ops.py --json summary "$@"; fi
    exec python3 /root/tools/agent-dispatch/task_queue_ops.py summary "$@" ;;
  inbox)
    exec python3 /root/tools/agent-dispatch/task_queue_ops.py --json brief "${1:-}" ;;
  queue)
    # `status` lists by directory mtime; the order tasks actually take their agent lock in is the
    # queue's (priority, QUEUED_AT, fairness), decided by the versioned ops entry.
    if [ "${1:-}" = --json ]; then exec python3 /root/tools/agent-dispatch/task_queue_ops.py --json list; fi
    exec python3 /root/tools/agent-dispatch/task_queue_ops.py list ;;
  status)
    ALL=""; if [ "${1:-}" = --all ]; then ALL=1; shift; fi
    if [ -n "${1:-}" ]; then
      d="$BASE/$1"; [ -d "$d" ] || { echo "no task $1" >&2; exit 1; }
      cat "$d/meta.env"; echo "--- result"; cat "$d/result.env" 2>/dev/null || echo "(not started)"
      [ ! -r "$d/inbox-state" ] || echo "inbox_phase: $(cat "$d/inbox-state")"
      for wake_file in "$d"/wake-{quota,end}.json; do
        [ ! -r "$wake_file" ] || { printf '%s: ' "$(basename "$wake_file")"; cat "$wake_file"; }
      done
      # Lineage and runs: which task this one continued, which continued it, and how each run of
      # the CLI went (attempt<N>.env; none for runners before api 4).
      parent=$(sed -n "s/^PARENT_TASK_ID=//p" "$d/meta.env" | tr -d "'\"")
      [ -z "$parent" ] || echo "parent: $parent"
      children=$(grep -lx "PARENT_TASK_ID=$1" "$BASE"/*/meta.env 2>/dev/null | xargs -r -n1 dirname | xargs -r -n1 basename | xargs) || true
      [ -z "$children" ] || echo "children: $children"
      for run_file in $(printf '%s\n' "$d"/attempt*.env | sort -V); do
        [ -e "$run_file" ] || continue
        # shellcheck disable=SC1090  # the runner's own attempt<N>.env, written with printf %q
        ( RUN_NO="" KIND="" STARTED_EPOCH="" RC="" AKIND=""; . "$run_file"
          printf 'run %s: prompt=%s started=%s rc=%s result=%s\n' "$RUN_NO" "${KIND:--}" "$([ -n "$STARTED_EPOCH" ] && echo yes || echo no)" "${RC:--}" "${AKIND:--}" )
      done
      echo "unit: $(systemctl is-active "agent-dispatch-$1.service" 2>/dev/null || true)"
      n=$(find "$d/inbox" -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l) || n=0
      if [ "$n" -gt 0 ]; then echo "inbox: $n appended instruction(s) not delivered yet"; fi
      ( . "$d/meta.env"; SESSION=""; [ -r "$d/result.env" ] && . "$d/result.env"
        [ -n "$SESSION" ] || exit 0
        case "$AGENT" in
          claude) echo "open:     cd $CWD && claude --resume $SESSION" ;;
          opencode) echo "open:     cd $CWD && opencode -s $SESSION" ;;
          dsh) echo "open:     cd $CWD && dsh --profile headless --session-id $SESSION \"<message>\"" ;;
          *) echo "open:     cd $CWD && codex resume $SESSION" ;;
        esac
        echo "continue: $0 append $ID < more.md" )
      echo "--- log tail"; tail -n 15 "$d/run.log" 2>/dev/null || true
    else
      # clawock-patrol rounds run around the clock and would push everything else off the list.
      for d in $(ls -1dt "$BASE"/*/ 2>/dev/null | if [ -n "$ALL" ]; then cat; else grep -v '/patrol-' || true; fi | if [ -n "$ALL" ]; then cat; else head -10; fi); do
        id=$(basename "$d")
        printf '%-44s %-9s %s\n' "$id" "$(systemctl is-active "agent-dispatch-$id.service" 2>/dev/null || true)" "$(show_state "$d")"
      done
    fi
    exit 0 ;;
  mandate)
    id="${1:-}"; [ -n "$id" ] || { echo "usage: dispatch.sh mandate <id> [check <action>]" >&2; exit 2; }
    d="$BASE/$id"; [ -r "$d/mandate.json" ] || { echo "no mandate for $id (a task dispatched before mandates, or an unknown id)" >&2; exit 1; }
    shift
    if [ "${1:-}" = check ]; then
      [ -n "${2:-}" ] || { echo "usage: dispatch.sh mandate <id> check <action>" >&2; exit 2; }
      exec python3 "$HELPER_DIR/mandate.py" check --file "$d/mandate.json" --action "$2" --task-dir "$d" --source "dispatch.sh mandate"
    fi
    exec python3 "$HELPER_DIR/mandate.py" show --file "$d/mandate.json" ;;
  cancel)
    [ -n "${1:-}" ] || { echo "usage: dispatch.sh cancel <id>" >&2; exit 2; }
    # CLI and chip share the durable marker, launch barrier and audited stop path.
    exec python3 /root/tools/agent-dispatch/task_queue_ops.py --source cli cancel "$1" ;;
  append)
    if [ -n "${AGENT_DISPATCH_TASK_ID:-}" ]; then
      echo "refused: this is dispatched task $AGENT_DISPATCH_TASK_ID; it does not steer other tasks" >&2; exit 2
    fi
    id="${1:-}"; shift || true
    d="$BASE/$id"
    if ! [[ "$id" =~ ^[a-z0-9][a-z0-9-]*$ ]] || [ ! -r "$d/meta.env" ]; then
      echo "usage: dispatch.sh append <id> [--queue] [--prompt-file f] < more.md (no task '$id')" >&2; exit 2
    fi
    mode=now PROMPT_FILE="" require_active=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --queue) mode=queue; shift ;;
        --require-active) require_active=1; shift ;;
        --prompt-file) PROMPT_FILE=$2; shift 2 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
      esac
    done
    tmp=$(mktemp "$BASE/.append.XXXXXX")
    if [ -n "$PROMPT_FILE" ]; then cat "$PROMPT_FILE" >"$tmp"; else cat >"$tmp"; fi
    [ -s "$tmp" ] || { rm -f "$tmp"; echo "empty instruction" >&2; exit 2; }
    exec 4>"$d/inbox.lock"
    flock -x 4
    if [ "$(systemctl is-active "agent-dispatch-$id.service" 2>/dev/null || true)" = active ]; then
      phase=$(cat "$d/inbox-state" 2>/dev/null || true)
      if [ "$phase" != accepting ]; then
        rm -f "$tmp"
        # Exit 3 always means nothing was queued; the prefix says how long until a retry works.
        # A runner writes inbox-state before its first result.env, so a result.env without one is
        # a runner from before the handshake (installed 2026-10-16, #3014), not a starting task.
        if [ "$phase" = finishing ] || [ "$phase" = terminal ]; then
          echo "task_finishing: $id has stopped taking instructions and is wrapping up (usage, notification; usually 1-2 minutes); nothing queued. Wait until status shows it ended, then append again to continue its session as a new task." >&2
        elif [ -r "$d/result.env" ]; then
          api=$(sed -n "s/^RUNNER_API=//p" "$d/result.env" 2>/dev/null | tr -d "'\"" || true)
          echo "legacy_runner: $id runs on runner api ${api:-1} from before the append handshake (no inbox-state); nothing queued. It cannot take appends until it ends, possibly hours away (queue and quota waits run to its deadline); append again after it ends to continue its session as a new task." >&2
        else
          echo "task_starting: $id has not opened its inbox yet (runner starting); nothing queued. Retry in a few seconds." >&2
        fi
        exit 3
      fi
      mkdir -p "$d/inbox"
      message_id="$(date +%Y%m%d-%H%M%S)-$$-$mode.md"
      mv "$tmp" "$d/inbox/$message_id"
      flock -u 4; exec 4>&-
      printf 'receipt: {"requested_task_id":"%s","actual_task_id":"%s","message_id":"%s","disposition":"accepted"}\n' "$id" "$id" "$message_id"
      echo "queued for task $id; not yet attached to a model run (mode=$mode)"
      exit 0
    fi
    flock -u 4; exec 4>&-
    if [ -n "$require_active" ]; then
      rm -f "$tmp"; echo "task_ended: $id; nothing queued" >&2; exit 3
    fi
    # The task has ended: continue its session as a new task.
    ( . "$d/meta.env"; SESSION=""; [ -r "$d/result.env" ] && . "$d/result.env"
      if [ -z "$SESSION" ]; then
        echo "task $id has ended and recorded no session; dispatch a new task instead" >&2; rm -f "$tmp"; exit 2
      fi
      # Continuing is manual work. An ended patrol round, or a manual task named before the
      # patrol- prefix was reserved (e.g. patrol-source-sync-*), continues under a manual name.
      if [[ "$NAME" == patrol-* ]] && [ "${AGENT_DISPATCH_PATROL:-}" != 1 ]; then NAME=task-$NAME; NAME=${NAME:0:40}; fi
      args=("$AGENT" --name "$NAME" --cwd "$CWD" --resume "$SESSION" --model "$MODEL" --notify "$NOTIFY" --prompt-file "$tmp")
      # Whoever continues the task hears about it; continued from outside a chat turn, the
      # session that dispatched it still does.
      export AGENT_DISPATCH_ORIGIN_FALLBACK="${ORIGIN_SESSION:-}"
      export AGENT_DISPATCH_PARENT_TASK_ID="$id"
      [ -n "$EFFORT" ] && args+=(--effort "$EFFORT")
      [ -n "${FALLBACK_MODELS:-}" ] && args+=(--fallback-models "$FALLBACK_MODELS")
      echo "task $id has ended ($(show_state "$d")); continuing session $SESSION as a new task"
      rc=0; "$0" "${args[@]}" || rc=$?; rm -f "$tmp"; exit "$rc" )
    exit $? ;;
  adopt)
    # A claude session dispatch did not start (a native `claude --bg` session, a terminal session
    # that died with its SSH connection) becomes a task that resumes it: the runner then waits
    # out a usage limit and continues, which the CLI does not do for those sessions
    # (docs/architecture/task-queue.md § Native background sessions).
    if [ -n "${AGENT_DISPATCH_TASK_ID:-}" ]; then
      echo "refused: this is dispatched task $AGENT_DISPATCH_TASK_ID; it does not adopt sessions" >&2; exit 2
    fi
    ref="${1:-}"; shift || true
    [ -n "$ref" ] && [ "${ref#-}" = "$ref" ] || { echo "usage: dispatch.sh adopt <bg-id|session-id> [--dry-run] [--name n] [options] [< instructions.md]" >&2; exit 2; }
    DRY_RUN="" rest=() ADOPT_NAME="" ADOPT_PROMPT=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        --name) ADOPT_NAME=$2; shift 2 ;;
        --prompt-file) ADOPT_PROMPT=$2; shift 2 ;;
        --resume|--cwd) echo "adopt finds the session and its directory itself; $1 is not taken" >&2; exit 2 ;;
        *) rest+=("$1"); shift ;;
      esac
    done
    helper="$(dirname "$(readlink -f "$0")")/claude-session.py"
    agents=$(mktemp "$BASE/.adopt-agents.XXXXXX")
    timeout 20 claude agents --json >"$agents" 2>/dev/null || : >"$agents"
    resolved=$(python3 "$helper" resolve "$ref" --agents-json "$agents") || { rm -f "$agents"; exit 2; }
    rm -f "$agents"
    eval "$resolved"
    echo "session:  $SESSION (cwd $CWD)"
    [ -z "$BG_ID" ] || echo "background: $BG_ID, ${BG_STATE:-unknown}${BG_DETAIL:+ — $BG_DETAIL}"
    [ -z "$LIMIT_TEXT" ] || echo "stopped on: $LIMIT_TEXT (at $LIMIT_AT); the first attempt meets it again if it has not reset, then the runner waits for the reset"
    case "$ACTION" in
      stop-then-resume) echo "plan:     claude stop $BG_ID, then a dispatched task resumes the session" ;;
      *) echo "plan:     a dispatched task resumes the session" ;;
    esac
    if [ -n "$DRY_RUN" ]; then echo "dry run: nothing stopped or dispatched"; exit 0; fi
    # The instructions: --prompt-file, else stdin when it is not a terminal, else a plain continue.
    ADOPT_TMP=$(mktemp "$BASE/.adopt.XXXXXX")
    trap 'rm -f "$ADOPT_TMP"' EXIT
    if [ -n "$ADOPT_PROMPT" ]; then cat "$ADOPT_PROMPT" >"$ADOPT_TMP"; elif [ ! -t 0 ]; then cat >"$ADOPT_TMP"; fi
    [ -s "$ADOPT_TMP" ] || echo "继续完成这个会话里被中断的任务：先检查当前真实状态（git/PR/CI/文件），复用已有产物，不要重复已完成的步骤。" >"$ADOPT_TMP"
    [ "$ACTION" = stop-then-resume ] && ADOPT_STOP=$BG_ID
    AGENT=claude
    set -- --name "${ADOPT_NAME:-adopt-${SESSION:0:8}}" --resume "$SESSION" --cwd "$CWD" --prompt-file "$ADOPT_TMP" ${rest[@]+"${rest[@]}"} ;;
  claude|codex|opencode|dsh) AGENT=$cmd ;;
  *) sed -n '2,53p' "$0" >&2; exit 2 ;;
esac
if [ -n "${AGENT_DISPATCH_TASK_ID:-}" ]; then
  echo "refused: this is already dispatched task $AGENT_DISPATCH_TASK_ID; do the work here instead of dispatching another task" >&2
  exit 2
fi

FREE_POOL_REPORT="" POOL_SELECTION=""
FALLBACK_MODELS="" NAME="" PROMPT_FILE="" CWD=/root RESUME="" MODEL="" EFFORT="" TIMEOUT=21600 NOTIFY=weixin,telegram DEADLINE=""
RESTART_ALLOWED=1   # kcn 2026-11-01: making a task's change effective may restart the gateway;
                    # the default contract records it and --no-restart is the explicit denial
QUOTA_RESUMES=3   # keep in step with run-agent.sh's default (kcn 2026-09-23): long Opus tasks do
                  # not fit in one 5-hour window; pass --quota-resumes 0/1 for short, cheap ones
TEMPLATE_DIR=/root/tools/agent-dispatch/templates TEMPLATES=()
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME=$2; shift 2 ;;
    --prompt-file) PROMPT_FILE=$2; shift 2 ;;
    --template)
      [[ "$2" =~ ^[a-z0-9-]+$ ]] && [ -r "$TEMPLATE_DIR/$2.md" ] \
        || { echo "unknown template $2 (have: $(ls "$TEMPLATE_DIR" 2>/dev/null | sed 's/\.md$//' | tr '\n' ' '))" >&2; exit 2; }
      TEMPLATES+=("$2"); shift 2 ;;
    --cwd) CWD=$2; shift 2 ;;
    --resume) RESUME=$2; shift 2 ;;
    --quota-resumes) QUOTA_RESUMES=$2; shift 2 ;;
    --model) MODEL=$2; shift 2 ;;
    --fallback-models) FALLBACK_MODELS=$2; shift 2 ;;
    --effort) EFFORT=$2; shift 2 ;;
    --timeout) TIMEOUT=$2; shift 2 ;;
    --deadline) DEADLINE=$2; shift 2 ;;
    --notify) NOTIFY=$2; shift 2 ;;
    --origin-session) export AGENT_DISPATCH_ORIGIN_SESSION=$2; shift 2 ;;
    --no-restart) RESTART_ALLOWED=0; shift ;;
    --allow-restart) RESTART_ALLOWED=1; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done
[[ "$NAME" =~ ^[a-z0-9][a-z0-9-]{0,39}$ ]] || { echo "--name must be a short lowercase slug" >&2; exit 2; }
# patrol-* ids are clawock-patrol rounds: the runner memory-gates them as expendable, `status`
# hides them and the supervisor prunes them after a week. A manual task with that name got all of
# that (patrol-issues-batch 2026-09-17, patrol-source-sync 2026-09-23), so the prefix is reserved.
if [[ "$NAME" == patrol-* ]] && [ "${AGENT_DISPATCH_PATROL:-}" != 1 ]; then
  echo "--name patrol-* is reserved for clawock-patrol rounds; choose another name" >&2; exit 2
fi
[ -d "$CWD" ] || { echo "cwd $CWD does not exist" >&2; exit 2; }
if [ "$CWD" != /root ] && [ -z "$RESUME" ]; then
  echo "new tasks must run in /root (agent guidance and shared memory are rooted there); --cwd is only for --resume" >&2; exit 2
fi
[[ "$TIMEOUT" =~ ^[0-9]+$ ]] || { echo "--timeout must be seconds" >&2; exit 2; }
[[ "$QUOTA_RESUMES" =~ ^[0-9]+$ ]] && [ "${#QUOTA_RESUMES}" -le 3 ] && [[ "$QUOTA_RESUMES" = 0 || "$QUOTA_RESUMES" != 0* ]] || { echo "--quota-resumes must be an integer 0..999" >&2; exit 2; }
# kcn 2026-09-26: user tasks notify on both channels by default; patrol rounds pass none and
# the supervisor tells Telegram itself (WeChat drops silently on a cold session).
# Normalised here (lower case, no spaces, each channel once) so meta.env holds exactly what the
# runner will send; an empty list (`--notify ,`) used to pass and silently notify nobody.
if [ "$NOTIFY" != none ]; then
  IFS=, read -r -a nchs <<<"${NOTIFY,,}"
  NOTIFY=""
  for nch in ${nchs[@]+"${nchs[@]}"}; do
    nch=${nch//[[:space:]]/}
    case "$nch" in
      weixin|telegram) case ",$NOTIFY," in *",$nch,"*) ;; *) NOTIFY=${NOTIFY:+$NOTIFY,}$nch ;; esac ;;
      "") ;;
      *) echo "--notify takes weixin, telegram, weixin,telegram or none" >&2; exit 2 ;;
    esac
  done
  [ -n "$NOTIFY" ] || { echo "--notify takes weixin, telegram, weixin,telegram or none" >&2; exit 2; }
fi
# Codex defaults to sol/medium: astra/high spent 42 of 100 five-hour points in 8.5 minutes on a
# docs/version check (codex token audit, 2026-09-15). Pass --model/--effort for harder work.
# opencode: automatically selected free Zen models only, no variants. The immutable pool
# supplies reviewed seed priorities; fresh evidence controls admission. 2026-09-19: the old
# hardcoded default opencode/union-alpha was retired upstream and failed every attempt.
if [ -n "$FALLBACK_MODELS" ] && [ "$AGENT" != opencode ]; then echo "--fallback-models is for opencode" >&2; exit 2; fi
case "$AGENT" in
  claude) MODEL=${MODEL:-claude-opus-5-5} EFFORT=${EFFORT:-high} ;;
  codex) MODEL=${MODEL:-gpt-6.1-sol} EFFORT=${EFFORT:-medium} ;;
  # dsh headless (0.2.1+) runs one task per process like `claude -p`; the runner turns MODEL and
  # EFFORT into a patch overlay for the headless profile, so they must name a dsh route.
  dsh) MODEL=${MODEL:-deepseek-official/deepseek-flash} EFFORT=${EFFORT:-max}
    [[ "$MODEL" =~ ^[a-z0-9][a-z0-9-]*/[A-Za-z0-9._:-]+$ ]] || { echo "--model for dsh is <provider>/<model>, e.g. deepseek-official/deepseek-v4-pro" >&2; exit 2; }
    [[ "$EFFORT" =~ ^(off|low|high|max)$ ]] || { echo "--effort for dsh takes off, low, high or max" >&2; exit 2; } ;;
  opencode)
    # The reviewed immutable file is a seed order. Fresh free candidates become
    # executable automatically; explicit selections cannot bypass the same gates.
    helper_dir=$(dirname "$(readlink -f "$0")")
    POOL="$helper_dir/opencode-fallback-models"
    FREE_POOL_REPORT=/root/logs/clawock-patrol/free-pool-audit.json
    timeout 50 python3 "$helper_dir/audit-free-pool.py" --due --pool "$POOL" \
      --repo-pool /root/.openclaw/workspace/ops/host/agent-dispatch/opencode-fallback-models \
      --report "$FREE_POOL_REPORT" >/dev/null || echo "free pool audit needs attention" >&2
    selection_args=(--pool "$POOL" --report "$FREE_POOL_REPORT")
    if [ -n "$FALLBACK_MODELS" ]; then
      selection_args+=(--models "${MODEL:+$MODEL,}$FALLBACK_MODELS")
    elif [ -n "$MODEL" ]; then
      selection_args+=(--prefer "$MODEL")
    fi
    POOL_SELECTION=$(python3 "$helper_dir/select-free-models.py" "${selection_args[@]}") || exit 2
    mapfile -t POOL_MODELS < <(python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin)["models"]))' <<<"$POOL_SELECTION")
    MODEL=${POOL_MODELS[0]}
    FALLBACK_MODELS=$(IFS=,; echo "${POOL_MODELS[*]:1}") ;;

esac
if [ -n "$DEADLINE" ]; then
  DEADLINE_EPOCH=$(date -d "$DEADLINE" +%s) || { echo "bad --deadline" >&2; exit 2; }
else
  DEADLINE_EPOCH=$(( $(date +%s) + 24 * 3600 ))
fi
[ "$DEADLINE_EPOCH" -le $(( $(date +%s) + 72 * 3600 )) ] || { echo "deadline is more than 72h away" >&2; exit 2; }
[ "$DEADLINE_EPOCH" -gt $(( $(date +%s) + 600 )) ] || { echo "deadline is less than 10 minutes away" >&2; exit 2; }
DEADLINE=$(date -d "@$DEADLINE_EPOCH" '+%F %T')

ID="$NAME-$(date +%Y%m%d-%H%M%S)"
DIR="$BASE/$ID"
mkdir -p "$DIR"
[ -z "$POOL_SELECTION" ] || printf '%s\n' "$POOL_SELECTION" >"$DIR/free-pool-selection.json"
if [ -n "$PROMPT_FILE" ]; then cp "$PROMPT_FILE" "$DIR/prompt.md"; else cat >"$DIR/prompt.md"; fi
[ -s "$DIR/prompt.md" ] || { echo "empty prompt" >&2; rm -rf "$DIR"; exit 2; }
for t in "${TEMPLATES[@]}"; do cat "$TEMPLATE_DIR/$t.md" >>"$DIR/prompt.md"; done
# Resumed sessions get the contract too: without it the model may skip the STATUS line
# (fix-merge-1512-continue, 2026-09-14), and the runner then cannot tell done from not done.
# The middle lines borrow the follow-through / scope / verification blocks of the Codex
# plugin's prompting guide, kept short because most dispatched work is not a review.
cat >>"$DIR/prompt.md" <<'EOF'

---
【派发约定】这是无人值守的独立任务：不要向人提问或等确认；不要开后台任务再等待通知。
- 你本身就是被派发的任务：活自己干完，包括长时间的等待。不要用 dispatch.sh / agent-dispatch 技能再派任务，那份技能说明是写给发起派发的一方的。
- 缺信息先自己查。查不到就按风险最低的合理理解继续；只有缺口会影响正确性、安全或不可逆操作时，才停下报 BLOCKED。
- 改动只限于任务本身，不要顺手重构或清理。合并、发布、推 tag、删除这类不可逆操作，先确认符合任务要求和仓库规则再做。
- 默认授权（机器可读：任务目录的 `mandate.json`）允许你为了让改动真正生效而重启网关：可以执行 `ops/host/refresh_live.sh` 和 `ops/host/restart_gateway.sh`，不必回来问。若本次任务的 mandate 写了 `gateway.restart: deny`（派发方用了 `--no-restart`），这些入口会拒绝并把越权记进 `mandate-violations.jsonl`，不要绕过。brief 与 mandate 冲突时按更严格的一条执行，并在报告里指出冲突；派发方要禁止重启应加 `--no-restart`，不要只写在 brief 里。做过重启就在报告里写一行 `RESTART: <命令/时间/结果>`。
- 结束前对照任务要求核对真实状态（文件、git、PR、CI），没达到就接着做，不要交第一稿。
- 测试只跑和改动相关的定向测试，整套测试交给 CI；任务明确要求本地全量时才跑全量。
- 等 CI 或长命令时，一次调用阻塞等到结束，不要每隔几十秒查一次（每查一次都要重发整个上下文）。等 CI 用 `gh pr checks <PR> --watch --fail-fast >/dev/null 2>&1; gh pr checks <PR>`，别让 `--watch` 的刷新输出进上下文；把这次调用的超时设到工具允许的上限（Claude 的 Bash timeout 600000，Codex 的 yield_time_ms 设大），到点还没完就原样再等一次。
- 不要 resume 或写入其他任务的会话（`claude --resume`、`codex exec resume` 别的会话 id）；要验证 resume 行为就自己开一次性会话。
结束时用中文写简短报告：做了什么，改了哪些文件或 commit，验证了什么，还有什么没做或有什么风险。报告最后两行固定为：
`NEEDS: none`（无事可做）或 `NEEDS: <一句具体、可执行的人的动作>`（要人决定/审核/授权/处理）
`STATUS: DONE|PARTIAL|BLOCKED`
只有 `NEEDS` 非 `none`，或 `STATUS` 非 `DONE` 时，派发方才通知人；无事时不要编一个动作。
EOF

# Which session dispatched this, and how deep in a chain of wake turns (kcn 2026-10-12: the task
# reports back where it was dispatched). Prints ORIGIN_SESSION= and WAKE_DEPTH=; empty when this
# is not a chat turn, or the helper is missing: the task then only sends its messages.
ORIGIN_SESSION="" WAKE_DEPTH=0
export AGENT_DISPATCH_SESSIONS_GLOB="${AGENT_DISPATCH_SESSIONS_GLOB:-/root/.openclaw/agents/*/sessions/sessions.json}"
eval "$(python3 "$(dirname "$(readlink -f "$0")")/wake-session.py" origin 2>/dev/null | grep -E '^(ORIGIN_SESSION|WAKE_DEPTH)=[A-Za-z0-9@._:+'"'"'-]*$')" || true

# Machine-readable authorization (docs/architecture/task-queue.md § Mandate). The policy
# version is the pair of scripts that define the contract, so a mandate states which text it
# was accepted under. --no-restart denies the one host action that used to ride on brief prose.
MANDATE_POLICY_VERSION="dispatch-$( { cat "$HELPER_DIR/dispatch.sh" "$HELPER_DIR/run-agent.sh"; } | sha256sum | cut -c1-12 )"
if [ "${AGENT_DISPATCH_PATROL:-}" = 1 ]; then MANDATE_SOURCE_KIND=patrol
elif [ -n "${AGENT_DISPATCH_PARENT_TASK_ID:-}" ]; then MANDATE_SOURCE_KIND=task
elif [ -n "$ORIGIN_SESSION" ]; then MANDATE_SOURCE_KIND=chat
else MANDATE_SOURCE_KIND=terminal
fi
MANDATE_SOURCE_ID="${ORIGIN_SESSION:-${AGENT_DISPATCH_PARENT_TASK_ID:-}}"
mandate_args=(create --dir "$DIR" --task-id "$ID" --name "$NAME" --agent "$AGENT" --cwd "$CWD"
  --policy-version "$MANDATE_POLICY_VERSION" --source-kind "$MANDATE_SOURCE_KIND"
  --source-id "$MANDATE_SOURCE_ID" --notify "$NOTIFY")
[ "$RESTART_ALLOWED" = 1 ] || mandate_args+=(--deny-restart)
python3 "$HELPER_DIR/mandate.py" "${mandate_args[@]}" >/dev/null \
  || { echo "could not write the task mandate" >&2; rm -rf "$DIR"; exit 2; }

cat >"$DIR/meta.env" <<EOF
ID=$(printf %q "$ID")
AGENT=$AGENT
NAME=$(printf %q "$NAME")
CWD=$(printf %q "$CWD")
RESUME=$(printf %q "$RESUME")
PARENT_TASK_ID=$(printf %q "${AGENT_DISPATCH_PARENT_TASK_ID:-}")
MODEL=$(printf %q "$MODEL")
FALLBACK_MODELS=$(printf %q "$FALLBACK_MODELS")
FREE_POOL_REPORT=$(printf %q "$FREE_POOL_REPORT")
EFFORT=$(printf %q "$EFFORT")
TIMEOUT=$TIMEOUT
QUOTA_RESUMES=$QUOTA_RESUMES
DEADLINE=$(printf %q "$DEADLINE")
DEADLINE_EPOCH=$DEADLINE_EPOCH
NOTIFY=$NOTIFY
MANDATE_POLICY_VERSION=$(printf %q "$MANDATE_POLICY_VERSION")
ORIGIN_SESSION=$(printf %q "$ORIGIN_SESSION")
WAKE_DEPTH=$WAKE_DEPTH
CREATED=$(printf %q "$(date '+%F %T')")
EOF

# adopt: a background session still open in the daemon is stopped last, after every check above
# passed, so a refused dispatch never leaves it stopped; and it must be gone before the task
# starts, or two processes would write one transcript.
if [ -n "$ADOPT_STOP" ]; then
  stopped=""
  if timeout 30 claude stop "$ADOPT_STOP" >/dev/null 2>&1; then
    for _ in $(seq 15); do
      agents=$(mktemp "$BASE/.adopt-agents.XXXXXX")
      timeout 20 claude agents --json >"$agents" 2>/dev/null || : >"$agents"
      live=$(python3 -c 'import json, sys
try:
    agents = json.load(open(sys.argv[1]))
except ValueError:
    agents = None
print("unknown" if not isinstance(agents, list) else
      "yes" if any(isinstance(a, dict) and a.get("sessionId") == sys.argv[2] and a.get("pid") for a in agents) else "no")' "$agents" "$RESUME")
      rm -f "$agents"
      [ "$live" = no ] && { stopped=1; break; }
      sleep 1
    done
  fi
  if [ -z "$stopped" ]; then
    rm -rf "$DIR"
    echo "adopt: could not stop background session $ADOPT_STOP (claude stop failed, or it is still listed as running); nothing dispatched" >&2
    exit 1
  fi
  echo "stopped background session $ADOPT_STOP; do not attach to it until this task ends"
fi

# --collect: the transient unit disappears after it ends; results stay in $DIR.
systemd-run --unit "agent-dispatch-$ID" --collect --quiet \
  --description "agent-dispatch $AGENT: $NAME" \
  -p TimeoutStartSec=infinity -p TimeoutStopSec=90s -p KillMode=control-group \
  "$RUNNER" "$DIR"

echo "dispatched $ID"
# Continued from an ended task by `append`: the same receipt shape as an accepted append, naming
# the task that will actually read the instruction (it is this new task's prompt, not a message).
# shellcheck disable=SC2031  # exported by the dispatch.sh process that re-ran "$0", not a subshell
[ -z "${AGENT_DISPATCH_PARENT_TASK_ID:-}" ] || printf 'receipt: {"requested_task_id":"%s","actual_task_id":"%s","message_id":null,"disposition":"continued_as_new_task"}\n' "$AGENT_DISPATCH_PARENT_TASK_ID" "$ID"
echo "  unit:     agent-dispatch-$ID.service ($AGENT $MODEL${EFFORT:+/$EFFORT}, cwd $CWD)"
echo "  deadline: $DEADLINE"
[ -z "$ORIGIN_SESSION" ] || echo "  wake:     this session gets a turn when it ends (off: --origin-session none)"
echo "  log:      $DIR/run.log"
echo "  status:   /root/tools/agent-dispatch/dispatch.sh status $ID"
echo "  append:   /root/tools/agent-dispatch/dispatch.sh append $ID < more.md   (change the task without cancelling it)"
# A prompt only (kcn left admission to the agent 2026-10-16; decision: inform, never refuse,
# downgrade or re-route): the account's windows as the dispatcher sees them now. quota.mjs caches
# for 90s, so back-to-back dispatches do not poll the usage endpoint; bounded, and never fatal.
case "$AGENT" in claude|codex)
  # shellcheck disable=SC2086  # a command line, split like run-agent.sh's QUOTA_CMD
  quota=$(timeout 8 ${AGENT_DISPATCH_QUOTA_CMD:-node /root/tools/agent-dispatch/quota.mjs} "$AGENT" 2>/dev/null | head -1) || true
  echo "  quota:    ${quota:-额度：未读到（超时或读取脚本失败）} (informational; does not hold the task)" ;;
esac
