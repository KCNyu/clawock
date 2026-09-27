#!/usr/bin/env bash
# Dispatch a headless Claude Code / Codex / opencode task as an independent systemd unit.
# The caller (OpenClaw chat turn, dsh, a terminal) returns immediately; the task
# survives the caller's process, gateway restarts and dsh restarts.
#
#   dispatch.sh claude|codex|opencode --name <slug> [options] < prompt.md
#   dispatch.sh append <id> [--queue] < more.md   # add instructions to a task, same session
#   dispatch.sh status [--all] [<id>]  # recent tasks (--all includes patrol-* rounds), or one task
#   dispatch.sh result <id>          # latest final report, without raw tool logs
#   dispatch.sh cancel <id>          # stop a running task (records state=cancelled)
#   dispatch.sh queue [--json]       # each agent's lock holder and queue in real order (task_queue_ops.py)
#
# append: while the task runs, its current step is stopped within seconds and the same session
# resumes with the new instructions (--queue: deliver when the current attempt ends instead).
# Before the task starts they join the prompt; after it ended, a new task resumes its session.
#
# Options:
#   --name <slug>          short task label (required)
#   --prompt-file <f>      read the prompt from a file instead of stdin
#   --template <name>      append templates/<name>.md before the contract (repeatable; e.g. review)
#   --quota-resumes <n>   automatic resumes after quota waits (default 1; 0 disables)
#   --resume <session>     continue an existing claude/codex session (to finish interrupted work;
#                          a re-review is a new task quoting the earlier findings, not a resume)
#   --cwd <dir>            only with --resume, for a session recorded under another project dir;
#                          new tasks always run in /root (AGENTS/CLAUDE.md + shared memory load from there)
#   --model <m>            default: claude-opus-5-5 / gpt-6-sol (gpt-6-astra costs several times the quota)
#                          / opencode: the pool file's first model (see --fallback-models)
#   --fallback-models a,b  opencode only: after a failed attempt continue the same session on the next
#                          model (wraps around). Default: opencode-fallback-models, which also supplies
#                          the primary; set explicitly to override the whole pool.
#   --effort <e>           default: high for claude, medium for codex, none for opencode (its --variant)
#   --timeout <sec>        per attempt (default 21600 = 6h)
#   --deadline <datetime>  absolute end for the whole task, Asia/Shanghai (default: now + 24h, max 72h)
#   --notify <channels>    comma list of weixin|telegram for the completion message
#                          (default weixin,telegram; patrol rounds pass none)
set -euo pipefail
export TZ=Asia/Shanghai

BASE=/root/logs/agent-dispatch
RUNNER=/root/tools/agent-dispatch/run-agent.sh
mkdir -p "$BASE"

show_state() {  # prints STATE/OUTCOME for a task dir
  local d=$1
  if [ -r "$d/result.env" ]; then
    ( . "$d/result.env"; printf '%s%s' "$STATE" "${OUTCOME:+/$OUTCOME}" )
  else
    printf 'pending'
  fi
}

cmd="${1:-}"; shift || true
case "$cmd" in
  result)
    exec python3 /root/tools/agent-dispatch/read-result.py "${1:-}" ;;
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
      echo "unit: $(systemctl is-active "agent-dispatch-$1.service" 2>/dev/null || true)"
      n=$(find "$d/inbox" -maxdepth 1 -name '*.md' -type f 2>/dev/null | wc -l) || n=0
      if [ "$n" -gt 0 ]; then echo "inbox: $n appended instruction(s) not delivered yet"; fi
      ( . "$d/meta.env"; SESSION=""; [ -r "$d/result.env" ] && . "$d/result.env"
        [ -n "$SESSION" ] || exit 0
        case "$AGENT" in
          claude) echo "open:     cd $CWD && claude --resume $SESSION" ;;
          opencode) echo "open:     cd $CWD && opencode -s $SESSION" ;;
          *) echo "open:     cd $CWD && codex resume $SESSION" ;;
        esac
        echo "continue: $0 append $ID < more.md" )
      echo "--- log tail"; tail -n 15 "$d/run.log" 2>/dev/null || true
    else
      # clawock-patrol rounds run around the clock and would push everything else off the list.
      for d in $(ls -1dt "$BASE"/*/ 2>/dev/null | if [ -n "$ALL" ]; then cat; else grep -v '/patrol-' || true; fi | head -10); do
        id=$(basename "$d")
        printf '%-44s %-9s %s\n' "$id" "$(systemctl is-active "agent-dispatch-$id.service" 2>/dev/null || true)" "$(show_state "$d")"
      done
    fi
    exit 0 ;;
  cancel)
    [ -n "${1:-}" ] || { echo "usage: dispatch.sh cancel <id>" >&2; exit 2; }
    # The dsh chip cancels through task_queue_ops.py (idempotent, audited, reports the session);
    # this stays the blocking CLI form, but an unknown or ended id is an error, not "cancelled".
    [[ "$1" =~ ^[a-z0-9][a-z0-9-]*$ ]] && [ -r "$BASE/$1/meta.env" ] || { echo "no task $1 (unknown or already pruned)" >&2; exit 1; }
    if [ "$(systemctl is-active "agent-dispatch-$1.service" 2>/dev/null || true)" != active ]; then
      echo "task $1 is not running ($(show_state "$BASE/$1")); nothing to cancel" >&2; exit 1
    fi
    systemctl stop "agent-dispatch-$1.service"; echo "cancelled $1: $(show_state "$BASE/$1")"; exit 0 ;;
  append)
    if [ -n "${AGENT_DISPATCH_TASK_ID:-}" ]; then
      echo "refused: this is dispatched task $AGENT_DISPATCH_TASK_ID; it does not steer other tasks" >&2; exit 2
    fi
    id="${1:-}"; shift || true
    d="$BASE/$id"
    if ! [[ "$id" =~ ^[a-z0-9][a-z0-9-]*$ ]] || [ ! -r "$d/meta.env" ]; then
      echo "usage: dispatch.sh append <id> [--queue] [--prompt-file f] < more.md (no task '$id')" >&2; exit 2
    fi
    mode=now PROMPT_FILE=""
    while [ $# -gt 0 ]; do
      case "$1" in
        --queue) mode=queue; shift ;;
        --prompt-file) PROMPT_FILE=$2; shift 2 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
      esac
    done
    tmp=$(mktemp "$BASE/.append.XXXXXX")
    if [ -n "$PROMPT_FILE" ]; then cat "$PROMPT_FILE" >"$tmp"; else cat >"$tmp"; fi
    [ -s "$tmp" ] || { rm -f "$tmp"; echo "empty instruction" >&2; exit 2; }
    if [ "$(systemctl is-active "agent-dispatch-$id.service" 2>/dev/null || true)" = active ]; then
      mkdir -p "$d/inbox"
      mv "$tmp" "$d/inbox/$(date +%Y%m%d-%H%M%S)-$$-$mode.md"   # atomic: the runner never sees half a file
      echo "appended to running task $id ($(show_state "$d"))"
      if [ "$mode" = now ]; then
        echo "  its current step stops within seconds and the same session resumes with the new instructions"
        echo "  (while the task waits for a lock, a slot or a quota reset, they go with its next attempt)"
      else
        echo "  delivered to the same session when the current attempt ends"
      fi
      exit 0
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
      [ -n "$EFFORT" ] && args+=(--effort "$EFFORT")
      [ -n "${FALLBACK_MODELS:-}" ] && args+=(--fallback-models "$FALLBACK_MODELS")
      echo "task $id has ended ($(show_state "$d")); continuing session $SESSION as a new task"
      rc=0; "$0" "${args[@]}" || rc=$?; rm -f "$tmp"; exit "$rc" )
    exit $? ;;
  claude|codex|opencode) AGENT=$cmd ;;
  *) sed -n '2,31p' "$0" >&2; exit 2 ;;
esac
if [ -n "${AGENT_DISPATCH_TASK_ID:-}" ]; then
  echo "refused: this is already dispatched task $AGENT_DISPATCH_TASK_ID; do the work here instead of dispatching another task" >&2
  exit 2
fi

FALLBACK_MODELS="" NAME="" PROMPT_FILE="" CWD=/root RESUME="" MODEL="" EFFORT="" TIMEOUT=21600 NOTIFY=weixin,telegram DEADLINE=""
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
# opencode: free Zen models only, no variants. The pool file lists the primary on its first
# uncommented line and the fallbacks after it (docs on the file itself). 2026-09-19: the old
# hardcoded default opencode/union-alpha was retired upstream and failed every attempt.
if [ -n "$FALLBACK_MODELS" ] && [ "$AGENT" != opencode ]; then echo "--fallback-models is for opencode" >&2; exit 2; fi
case "$AGENT" in
  claude) MODEL=${MODEL:-claude-opus-5-5} EFFORT=${EFFORT:-high} ;;
  codex) MODEL=${MODEL:-gpt-6-sol} EFFORT=${EFFORT:-medium} ;;
  opencode)
    # Default opencode tasks take both the primary and the fallback pool from the pool file
    # (one model per line, # comments), read at dispatch time so the patrol service picks up
    # changes without a restart. An explicit --model still wins; the file then only supplies
    # fallbacks. A retired model may stay as the LAST line: the runner only reaches it after
    # every live model failed, so it costs nothing and picks the model up if it returns.
    POOL=/root/tools/agent-dispatch/opencode-fallback-models
    if [ -z "$FALLBACK_MODELS" ] && [ -r "$POOL" ]; then
      mapfile -t POOL_MODELS < <(sed 's/#.*//' "$POOL" | tr -s ' \t' '\n' | grep -v '^$')
      if [ -z "$MODEL" ] && [ "${#POOL_MODELS[@]}" -gt 0 ]; then
        MODEL=${POOL_MODELS[0]}
        POOL_MODELS=("${POOL_MODELS[@]:1}")
      fi
      # An explicit --model must not also sit in the pool: the runner would spend a second
      # attempt on the model that just failed.
      if [ -n "$MODEL" ]; then
        REMAIN=()
        for m in ${POOL_MODELS[@]+"${POOL_MODELS[@]}"}; do [ "$m" = "$MODEL" ] || REMAIN+=("$m"); done
        POOL_MODELS=(${REMAIN[@]+"${REMAIN[@]}"})
      fi
      FALLBACK_MODELS=$(IFS=,; echo "${POOL_MODELS[*]-}")
    fi
    MODEL=${MODEL:-opencode/muse-spark-1.3-contributor-free} ;;
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
- 结束前对照任务要求核对真实状态（文件、git、PR、CI），没达到就接着做，不要交第一稿。
- 测试只跑和改动相关的定向测试，整套测试交给 CI；任务明确要求本地全量时才跑全量。
- 等 CI 或长命令时，一次调用阻塞等到结束，不要每隔几十秒查一次（每查一次都要重发整个上下文）。等 CI 用 `gh pr checks <PR> --watch --fail-fast >/dev/null 2>&1; gh pr checks <PR>`，别让 `--watch` 的刷新输出进上下文；把这次调用的超时设到工具允许的上限（Claude 的 Bash timeout 600000，Codex 的 yield_time_ms 设大），到点还没完就原样再等一次。
- 不要 resume 或写入其他任务的会话（`claude --resume`、`codex exec resume` 别的会话 id）；要验证 resume 行为就自己开一次性会话。
结束时用中文写简短报告：做了什么，改了哪些文件或 commit，验证了什么，还有什么没做或有什么风险。最后单独一行输出 `STATUS: DONE`、`STATUS: PARTIAL` 或 `STATUS: BLOCKED`。
EOF

cat >"$DIR/meta.env" <<EOF
ID=$(printf %q "$ID")
AGENT=$AGENT
NAME=$(printf %q "$NAME")
CWD=$(printf %q "$CWD")
RESUME=$(printf %q "$RESUME")
MODEL=$(printf %q "$MODEL")
FALLBACK_MODELS=$(printf %q "$FALLBACK_MODELS")
EFFORT=$(printf %q "$EFFORT")
TIMEOUT=$TIMEOUT
QUOTA_RESUMES=$QUOTA_RESUMES
DEADLINE=$(printf %q "$DEADLINE")
DEADLINE_EPOCH=$DEADLINE_EPOCH
NOTIFY=$NOTIFY
CREATED=$(printf %q "$(date '+%F %T')")
EOF

# --collect: the transient unit disappears after it ends; results stay in $DIR.
systemd-run --unit "agent-dispatch-$ID" --collect --quiet \
  --description "agent-dispatch $AGENT: $NAME" \
  -p TimeoutStartSec=infinity -p TimeoutStopSec=90s -p KillMode=control-group \
  "$RUNNER" "$DIR"

echo "dispatched $ID"
echo "  unit:     agent-dispatch-$ID.service ($AGENT $MODEL${EFFORT:+/$EFFORT}, cwd $CWD)"
echo "  deadline: $DEADLINE"
echo "  log:      $DIR/run.log"
echo "  status:   /root/tools/agent-dispatch/dispatch.sh status $ID"
echo "  append:   /root/tools/agent-dispatch/dispatch.sh append $ID < more.md   (change the task without cancelling it)"
