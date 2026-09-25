#!/usr/bin/env bash
# clawock-patrol: round-the-clock review of KCNyu/clawock by the free opencode model.
# Each round is an ordinary agent-dispatch opencode task (status/append/cancel all work on it);
# it reads the repo in a detached worktree and may only file issues through the gate
# (file_issue.sh). This supervisor picks the round's area, keeps the worktree and issue snapshot
# fresh, gives way to kcn's own dispatched tasks, and backs off while the free tier is down.
# Maintained here; installed at /root/tools/clawock-patrol/patrol.sh (see README.md).
#
#   patrol.sh start | stop | status       # systemd service clawock-patrol
#   patrol.sh steer [--now] < note.md     # standing instruction for every later round
#                                         # (--now: also append it to the round running now)
#   patrol.sh once                        # one round in the foreground (trial)
#   patrol.sh run                         # the loop (what the service runs)
#
# Lessons carried over from the 08-25..09-06 issue loops (shared memory: clawock-issue-loop-0905,
# lessons-llm-output-and-reviews): rules the model does not follow must be gates; assign the area
# instead of letting the model pick; fresh session per round; fast-forward to origin/master every
# round; a free tier that is out of quota looks dead, so wait with backoff and never exit.
set -uo pipefail
export TZ=Asia/Shanghai HOME=/root
# Keep a PATH the caller already set (the service unit and tests provide one) and append the
# host's tool directories, so a caller-provided stub still wins.
export PATH="${PATH:+$PATH:}/root/.local/bin:/root/.local/share/pnpm:/root/.nvm/versions/node/v22.23.1/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

TOOL=${PATROL_TOOL_DIR:-/root/tools/clawock-patrol}
STATE=${PATROL_STATE_DIR:-/root/logs/clawock-patrol}
WT=/root/wt-patrol
LIVE=/root/.openclaw/workspace
REPO=KCNyu/clawock
DISPATCH_DIR=${PATROL_DISPATCH_DIR:-/root/tools/agent-dispatch}
DISPATCH=$DISPATCH_DIR/dispatch.sh
TASKS=${PATROL_TASKS_DIR:-/root/logs/agent-dispatch}
UNIT=clawock-patrol
# Same file the runner reads, so "how many slots exist" cannot drift between them.
. "$DISPATCH_DIR/limits.env"
# Run slots are per agent (slot-<agent>-<n>.lock, kcn 2026-09-25): a round only ever holds an
# opencode slot, so claude/codex work never waits for one. Runners from before that shared
# slot-1..2 among all agents; a task started then may run up to 72h, and while one does its
# slot contention is still real. LEGACY_SLOTS keeps it visible; drop it after 2026-09-29.
ROUND_AGENT=opencode
AGENT_SLOTS="${AGENT_DISPATCH_MAX_RUNNING_OPENCODE:-${MAX_RUNNING_OPENCODE:-1}}"
LEGACY_SLOTS=2
. "$DISPATCH_DIR/resource-pressure.sh"
# Area order: $TOOL/rotation (read every round, so edits apply without a restart).
ROUND_GAP="${PATROL_ROUND_GAP:-600}"        # pause after a finished round
ROUND_DEADLINE_H="${PATROL_ROUND_HOURS:-3}"  # whole round incl. retries
ATTEMPT_TIMEOUT="${PATROL_ATTEMPT_TIMEOUT:-5400}"
PREEMPT_GRACE="${PATROL_PREEMPT_GRACE:-300}"  # wrap-up time a preempted round gets; 0 = cancel at once
[[ $PREEMPT_GRACE =~ ^[0-9]+$ ]] || PREEMPT_GRACE=300
mkdir -p "$STATE/drafts" "$STATE/filed"

log() { echo "$(date '+%F %T') $*"; }
now() { date +%s; }
notify() {
  # shellcheck disable=SC1091
  ( . /root/tools/agent-dispatch/notify.env
    timeout 60 openclaw message send --channel "$NOTIFY_CHANNEL" --target "$NOTIFY_TARGET" -m "$1" >/dev/null 2>&1 ) \
    || log "notify failed"
}
current_round() { cat "$STATE/current-round" 2>/dev/null; }
round_active() { [ -n "${1:-}" ] && [ "$(systemctl is-active "agent-dispatch-$1.service" 2>/dev/null)" = active ]; }

# Demand preempts patrol; capacity only gates admission. Counting all locks during a round
# counts patrol itself and cancels useful work when nobody is waiting. Always probe actual
# locks: SLOT reports can be stale or absent in older runners.
slots_held() {  # <lock name prefix> <count>: how many of those slot locks are held now
  local i held=0
  for i in $(seq "$2"); do
    exec 7>"$TASKS/$1$i.lock"
    flock -n 7 || held=$((held + 1))
    exec 7>&-
  done
  echo "$held"
}
own_slots_busy() { [ "$(slots_held "slot-$ROUND_AGENT-" "$AGENT_SLOTS")" -ge "$AGENT_SLOTS" ]; }
# With no round running (admission) the next round's runner may still be an old one; a running
# round stands in the way of a shared-slot waiter only if it holds a shared slot itself.
legacy_slots_busy() {
  local own slot
  own=$(current_round)
  if [ -n "$own" ]; then
    slot=$( SLOT=""; . "$TASKS/$own/result.env" 2>/dev/null; printf '%s' "$SLOT" )
    [[ $slot =~ ^[0-9]+$ ]] || return 1
  fi
  [ "$(slots_held slot- "$LEGACY_SLOTS")" -ge "$LEGACY_SLOTS" ]
}

task_agent() { sed -n 's/^AGENT=//p' "$1/meta.env" 2>/dev/null | head -1; }

# Only work the round can stand in the way of is demand: an opencode task (in practice a manual
# one) queued for the opencode lock or slot, or a task of an old runner queued for the shared
# slots while they are all busy. A claude/codex task queued for its own lock or slot waits for
# its own agent; giving way would not start it any sooner (kcn 2026-09-25).
others_need_slot() {
  local unit id d mode=${1:-admission} own units parked=" " agent
  # Skip only this supervisor's own round, named by the authoritative current-round
  # marker. Skipping every `patrol-*` id also hid manual tasks that happened to use
  # that name, so a round ran on while they queued (2026-09-23).
  own=$(current_round)
  units=$(systemctl list-units 'agent-dispatch-*' --state=active --no-legend --plain 2>/dev/null | awk '{print $1}')
  # An agent asleep on a quota reset holds its lock until that reset, so every task
  # queued behind it is parked with it: neither side can start for hours. Counting that
  # queue as demand left patrol idle beside two free run slots while kcn's own tasks
  # waited for the reset (2026-09-24). Only the queue's own agent counts.
  for unit in $units; do
    id=${unit#agent-dispatch-}; id=${id%.service}
    [ -n "$own" ] && [ "$id" = "$own" ] && continue
    d=$TASKS/$id
    grep -qs '^WAITING=quota' "$d/result.env" || continue
    agent=$(task_agent "$d")
    [ -n "$agent" ] && parked="$parked$agent "
  done
  for unit in $units; do
    id=${unit#agent-dispatch-}; id=${id%.service}
    [ -n "$own" ] && [ "$id" = "$own" ] && continue
    d=$TASKS/$id
    agent=$(task_agent "$d")
    if grep -qs '^WAITING=slot' "$d/result.env"; then
      if [ "$agent" = "$ROUND_AGENT" ]; then echo "$id is waiting for an $ROUND_AGENT run slot"; return; fi
      if legacy_slots_busy; then echo "$id is waiting for a run slot and all $LEGACY_SLOTS shared slots are busy"; return; fi
      continue
    fi
    [ "$agent" = "$ROUND_AGENT" ] || continue
    # The runner asks for a slot only after it holds its agent lock, so a task queued
    # behind that lock never wrote WAITING=slot and patrol kept its round (2026-09-23).
    # WAITING=lock is that queue: manual work outranks patrol, so it counts as demand —
    # unless that agent is parked on quota above, because then giving way frees a slot
    # for a task that cannot start.
    if grep -qs '^WAITING=lock' "$d/result.env"; then
      case "$parked" in *" $agent "*) continue ;; esac
      echo "$id is waiting for its agent lock"; return
    fi
    # Runners from before the WAITING=lock marker show only the queued state.
    if grep -qs '^STATE=queued' "$d/result.env"; then
      echo "$id is waiting for the opencode lock"; return
    fi
  done
  if [ "$mode" = admission ]; then
    if own_slots_busy; then echo "the $ROUND_AGENT run slot is busy"; return; fi
    if legacy_slots_busy; then echo "all $LEGACY_SLOTS shared run slots are busy"; return; fi
    memory_pressure_reason
  fi
  return 0
}

# Demand the round itself stands in the way of, so a wrap-up grace would make it wait:
# an opencode task queued behind the lock or slot this round holds, or an old runner's task
# waiting while every shared slot is taken. Rechecked at every poll of the grace.
round_blocks_someone() {
  local unit id d own agent
  own=$(current_round)
  for unit in $(systemctl list-units 'agent-dispatch-*' --state=active --no-legend --plain 2>/dev/null | awk '{print $1}'); do
    id=${unit#agent-dispatch-}; id=${id%.service}
    [ -n "$own" ] && [ "$id" = "$own" ] && continue
    d=$TASKS/$id
    agent=$(task_agent "$d")
    if grep -qs '^WAITING=slot' "$d/result.env"; then
      if [ "$agent" = "$ROUND_AGENT" ] && own_slots_busy; then
        echo "$id is waiting for an $ROUND_AGENT run slot and all $AGENT_SLOTS are busy"; return
      fi
      if legacy_slots_busy; then
        echo "$id is waiting for a run slot and all $LEGACY_SLOTS shared slots are busy"; return
      fi
    fi
    if [ "$agent" = "$ROUND_AGENT" ] && grep -qsE '^(WAITING=lock|STATE=queued)' "$d/result.env"; then
      echo "$id is queued behind the round's opencode lock"; return
    fi
  done
}

round_session() { ( SESSION=""; . "$TASKS/$1/result.env" 2>/dev/null; printf '%s' "$SESSION" ); }

# Appended to a round that has to give way: land what it has before the hard cancel.
wrapup_note() {  # <round no>
  cat <<NOTE
【巡检让路】有人工任务在排队，本轮要提前收尾：${PREEMPT_GRACE}s 内没结束会被直接取消，取消后会话不可续，没落地的发现全部丢失。
现在停止新的调查，只做下面三件事：
1. 已经对照 closed-lessons 反证仍成立的候选：按 $TOOL/issue-format.md 写成 $STATE/drafts/R$1-<slug>.md，运行 $TOOL/file_issue.sh <草稿> 提报。闸的规则和每轮上限照旧，证据不够的不要提。
2. 按收尾要求重写 $STATE/ledger.md（整份不超过 60 行）：「已覆盖」只写实际查完的；没查完的线索和证据不够的放进「候选」，写清缺什么证据；recent 轮留出未检查的提交。
3. 用中文简短报告本轮结论，最后一行输出 \`STATUS: PARTIAL\`，然后结束。
NOTE
}

prepare_worktree() {
  if [ ! -d "$WT/.git" ] && [ ! -f "$WT/.git" ]; then
    git -C "$LIVE" worktree add --detach "$WT" origin/master >/dev/null 2>&1 || return 1
  fi
  git -C "$WT" fetch -q origin master || return 1
  git -C "$WT" checkout -q --detach origin/master && git -C "$WT" reset -q --hard origin/master \
    && git -C "$WT" clean -fdq
}

snapshot_issues() {
  local tmp="$STATE/.issues.json"
  gh issue list -R "$REPO" --state all --limit 2000 \
    --json number,title,state,stateReason,createdAt,closedAt >"$tmp" 2>/dev/null || return 1
  python3 - "$tmp" "$STATE" <<'PY' || return 1
import datetime, json, sys
from pathlib import Path
issues = json.load(open(sys.argv[1]))
state = Path(sys.argv[2])
(state / "issue_snapshot.json").write_text(json.dumps({"all": issues}, ensure_ascii=False))
cut = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat()
open_ = [i for i in issues if i["state"] == "OPEN"]
closed = [i for i in issues if i["state"] == "CLOSED" and (i.get("closedAt") or "") >= cut]
lines = [f"# clawock issues（快照 {datetime.datetime.now():%F %H:%M}）", "", f"## open（{len(open_)}）"]
lines += [f"- #{i['number']} {i['title']}" for i in open_] or ["- （无）"]
lines += ["", "## 最近 30 天关闭（原因：COMPLETED=修了，NOT_PLANNED=不做/不成立）"]
lines += [f"- #{i['number']} [{i.get('stateReason') or '-'}] {i['title']}" for i in closed[:120]] or ["- （无）"]
(state / "open-issues.md").write_text("\n".join(lines) + "\n")
PY
}

# Replace {{KEY}} placeholders; values come from the environment of this function's caller.
render() {
  python3 - "$TOOL/round-prompt.md" <<'PY'
import os, re, sys
text = open(sys.argv[1]).read()
print(re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: os.environ.get("P_" + m.group(1), m.group(0)), text), end="")
PY
}

# Issues whose title carries the prefix but whose body lacks the gate's marker went around it.
audit_ungated() {  # <epoch the round started>
  local since; since=$(date -u -d "@$1" +%FT%TZ)
  gh issue list -R "$REPO" --state all --search "\"[patrol]\" in:title created:>=$since" --limit 20 \
    --json number,title,body 2>/dev/null | python3 -c '
import json, sys
for i in json.load(sys.stdin):
    if "patrol-gate: passed" not in (i.get("body") or ""):
        print("#{} {}".format(i["number"], i["title"]))'
}

ROUND_ID=""
run_round() {  # returns 0 when the round finished (whatever it found), 1 when it failed/was preempted
  local n axis title body since start rid state reason
  rid=$(current_round)
  # Adopt the existing independent unit after a supervisor-only upgrade/crash.
  # Never refresh/reset its worktree while that worker may still be reading it.
  if [ -n "$rid" ] && [ -r "$TASKS/$rid/meta.env" ]; then
    n=$(cat "$STATE/round-no")
    axis=${rid#patrol-}; axis=${axis%-????????-??????}
    start=$( . "$TASKS/$rid/meta.env"; date -d "$CREATED" +%s )
    ROUND_ID=$rid
    log "adopting round R$n ($axis): $rid"
  else
    n=$(( $(cat "$STATE/round-no" 2>/dev/null || echo 0) + 1 ))
    read -r -a axes <<<"${PATROL_ROTATION:-$(sed 's/#.*//' "$TOOL/rotation" | xargs)}"
    axis=${axes[$(( (n - 1) % ${#axes[@]} ))]}
    IFS=$'\t' read -r _ title body < <(grep -P "^$axis\t" "$TOOL/axes.tsv")
    [ -n "${title:-}" ] || { log "unknown axis $axis"; return 1; }
  
    prepare_worktree || { log "worktree refresh failed"; return 1; }
    snapshot_issues || { log "issue snapshot failed"; return 1; }
    [ -f "$STATE/ledger.md" ] || printf '# clawock-patrol ledger\n\n（还没有轮次记录）\n' >"$STATE/ledger.md"
    since=$(cat "$STATE/recent-since" 2>/dev/null || date -d '-3 days' '+%F %T')
  
    export P_ROUND=$n P_AXIS_TITLE=$title P_HEAD="$(git -C "$WT" log -1 --format='%h %s' | cut -c1-80)"
    export P_AXIS_BODY=${body//'{{RECENT_SINCE}}'/$since}
    if [ -s "$STATE/steer.md" ]; then export P_STEER; P_STEER=$(cat "$STATE/steer.md"); else export P_STEER="（暂无）"; fi
    render >"$STATE/round-prompt.md"
  
    start=$(date +%s)
    # dispatch.sh reserves the patrol- name prefix for this supervisor.
    rid=$(AGENT_DISPATCH_PATROL=1 "$DISPATCH" opencode --name "patrol-$axis" --notify none --timeout "$ATTEMPT_TIMEOUT" \
            --deadline "$(date -d "+$ROUND_DEADLINE_H hours" '+%F %H:%M')" \
            --prompt-file "$STATE/round-prompt.md" 2>&1 | awk '/^dispatched /{print $2}')
    [ -n "$rid" ] || { log "dispatch failed"; return 1; }
    echo "$n" >"$STATE/round-no"; echo "$rid" >"$STATE/current-round"; ROUND_ID=$rid
    log "round R$n ($axis) dispatched as $rid"
  fi

  # Give way gracefully when that costs nobody: tell the round to file what it has confirmed
  # and rewrite the ledger, and cancel it only if it is still running PREEMPT_GRACE seconds
  # later (a hard cancel kept nothing but already-filed issues). Cancel at once when the
  # round blocks someone, or has no session: then no step has run, there is nothing to
  # land, and an append could not reach the attempt anyway. The marker survives a
  # supervisor restart, so an adopted round is not told twice.
  local demand blocker yield_at=""
  reason=""
  [ "$(cut -d' ' -f1 "$STATE/yielding" 2>/dev/null)" = "$rid" ] && yield_at=$(cut -d' ' -f2 "$STATE/yielding")
  [[ $yield_at =~ ^-?[0-9]+$ ]] || yield_at=""
  while round_active "$rid" || [ ! -r "$TASKS/$rid/result.env" ]; do
    sleep 30
    if ! round_active "$rid" && [ -r "$TASKS/$rid/result.env" ]; then break; fi
    demand=$(others_need_slot monitor)
    [ -n "$demand" ] || continue
    blocker=$(round_blocks_someone)
    if [ -z "$yield_at" ] && [ -z "$blocker" ] && [ "$PREEMPT_GRACE" -gt 0 ] && [ -n "$(round_session "$rid")" ] \
       && wrapup_note "$n" | "$DISPATCH" append "$rid" >/dev/null 2>&1; then
      yield_at=$(now); echo "$rid $yield_at" >"$STATE/yielding"
      log "asking $rid to wrap up within ${PREEMPT_GRACE}s: $demand"
      continue
    fi
    if [ -n "$yield_at" ] && [ -z "$blocker" ] && [ $(( $(now) - yield_at )) -lt "$PREEMPT_GRACE" ]; then continue; fi
    reason=${blocker:-$demand}
    log "preempting $rid${yield_at:+ after a $(( $(now) - yield_at ))s wrap-up grace}: $reason"
    "$DISPATCH" cancel "$rid" >/dev/null 2>&1
    break
  done
  # Keep the completed round available for adoption if the GitHub audit fails.
  # Retrying must neither reset the worktree nor dispatch another worker.
  local bad
  if ! bad=$(audit_ungated "$start"); then
    log "issue audit failed for $rid; bypass status unknown; will retry"
    return 1
  fi
  ROUND_ID=""; rm -f "$STATE/current-round" "$STATE/yielding"
  # (subshell: result.env's STATE must not clobber this script's STATE directory)
  state=$( STATE="" OUTCOME=""; . "$TASKS/$rid/result.env" 2>/dev/null; printf '%s' "${STATE:-unknown}${OUTCOME:+/$OUTCOME}" )
  local how=""
  if [ -n "$reason" ]; then how=preempted; elif [ -n "$yield_at" ]; then how=yielded; fi
  printf '%s\tR%s\t%s\t%s\t%s\t%ss\n' "$(date '+%F %T')" "$n" "$axis" "$rid" "${how:+$how:}$state" "$(( $(date +%s) - start ))" >>"$STATE/rounds.tsv"
  log "round R$n ($axis) ended: ${how:+$how, }$state"

  if [ -n "$bad" ]; then
    log "UNGATED issues: $bad"
    printf '%s R%s %s\n' "$(date '+%F %T')" "$n" "$bad" >>"$STATE/ungated.log"
    notify "⚠️ clawock 巡检 R$n 绕过闸直接开了 issue：$bad"
  fi
  [ -z "$reason" ] || return 1
  case "$state" in
    ok*|partial*|unverified*)
      # A round cut short never finished its review, whatever its last line claims.
      [ "$axis" = recent ] && [ "$state" = ok/DONE ] && [ -z "$yield_at" ] && date -d "@$start" '+%F %T' >"$STATE/recent-since"
      return 0 ;;
  esac
  return 1
}

prune() {  # patrol rounds are ours: keep a week of them
  find "$TASKS" -maxdepth 1 -type d -name 'patrol-*' -mtime +7 -exec rm -rf {} + 2>/dev/null
  find "$STATE/drafts" -type f -mtime +14 -delete 2>/dev/null
}

on_stop() {
  # The worker is an independent unit. Keep its marker/worktree for adoption after
  # restart; stopping supervision is not authorization to cancel dispatched work.
  log "supervisor stopping; preserving round ${ROUND_ID:-$(current_round)} for adoption"
  exit 0
}

loop() {
  trap on_stop TERM INT
  local fails=0 wait reason alerted=0
  log "patrol loop started ($ROUND_AGENT slots: $AGENT_SLOTS; rotation: $(sed 's/#.*//' "$TOOL/rotation" | xargs))"
  while :; do
    # An adopted worker already holds its slot. Monitor it first so a waiting
    # user task can preempt it; waiting here would leave both sides blocked.
    reason=""
    [ -n "$(current_round)" ] || reason=$(others_need_slot)
    if [ -n "$reason" ]; then
      log "waiting: $reason"
      while [ -n "$(others_need_slot)" ]; do sleep 60 & wait $!; done
    fi
    if run_round; then
      fails=0 alerted=0 wait=$ROUND_GAP
    else
      fails=$((fails + 1))
      wait=$(( 300 * (1 << (fails > 4 ? 4 : fails - 1)) )); [ "$wait" -gt 3600 ] && wait=3600
      # One message per outage: the free tier going away for hours is expected, not an emergency.
      if [ "$fails" -ge 6 ] && [ "$alerted" = 0 ]; then
        notify "⏸️ clawock 巡检连续 $fails 次未完成（执行、抢占或审计失败），继续按 ${wait}s 退避重试。看情况：/root/tools/clawock-patrol/patrol.sh status"
        alerted=1
      fi
    fi
    prune
    log "next round in ${wait}s"
    sleep "$wait" & wait $!
  done
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then return 0; fi

case "${1:-}" in
  run) loop ;;
  once) trap on_stop TERM INT; run_round ;;
  start)
    install -m 0644 "$TOOL/clawock-patrol.service" /etc/systemd/system/clawock-patrol.service
    systemctl daemon-reload && systemctl enable --now "$UNIT" && systemctl --no-pager status "$UNIT" | head -5 ;;
  stop) systemctl disable --now "$UNIT"; echo "stopped (issues filed so far: $STATE/filed/created.tsv)" ;;
  steer)
    now=""; [ "${2:-}" = --now ] && now=1
    note=$(cat); [ -n "$note" ] || { echo "empty note" >&2; exit 2; }
    printf -- '- （%s）%s\n' "$(date '+%m-%d %H:%M')" "$note" >>"$STATE/steer.md"
    echo "saved to $STATE/steer.md; every later round reads it"
    rid=$(current_round)
    if [ -n "$now" ] && round_active "$rid"; then
      printf '%s\n' "$note" | "$DISPATCH" append "$rid"
    fi ;;
  status)
    echo "service: $(systemctl is-active "$UNIT" 2>/dev/null) / $(systemctl is-enabled "$UNIT" 2>/dev/null)"
    rid=$(current_round); echo "current round: ${rid:-none}"
    [ -s "$STATE/yielding" ] && echo "wrapping up since $(date -d "@$(cut -d' ' -f2 "$STATE/yielding")" '+%F %T') to give way"
    [ -n "$rid" ] && "$DISPATCH" status "$rid" | grep -E '^(STATE|ATTEMPTS|SESSION|WAITING)=|^unit:'
    echo "--- last rounds"; tail -n 8 "$STATE/rounds.tsv" 2>/dev/null
    echo "--- issues filed in the last 24h: $(awk -v t=$(( $(date +%s) - 86400 )) -F'\t' '$1 > t' "$STATE/filed/created.tsv" 2>/dev/null | wc -l)"
    tail -n 5 "$STATE/filed/created.tsv" 2>/dev/null | cut -f3,4
    echo "--- gate rejections (last 5)"; grep -E '^\[' "$STATE/gate-rejections.log" 2>/dev/null | tail -n 5
    echo "--- supervisor log"; journalctl -u "$UNIT" -n 8 --no-pager -o cat 2>/dev/null ;;
  *) sed -n '2,14p' "$0" >&2; exit 2 ;;
esac
