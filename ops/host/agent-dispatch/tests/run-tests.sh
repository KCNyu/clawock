#!/usr/bin/env bash
# Fault-injection tests for /root/tools/agent-dispatch/run-agent.sh using fake CLIs.
# Runs the runner directly (no systemd; notifications go to a fake openclaw). Every run gets its
# own temp dir for fake state, tasks, locks, codex rollouts and claude transcripts, so concurrent
# runs cannot corrupt each other, and every case asserts its outcome: the script exits non-zero
# if any expectation fails.
set -euo pipefail
T=$(cd "$(dirname "$0")" && pwd)
R=${AGENT_DISPATCH_RUNNER:-/root/tools/agent-dispatch/run-agent.sh}  # a staged copy can be tested before install
WORK=$(mktemp -d /tmp/agent-dispatch-tests.XXXXXX)
export FAKE_DIR=$WORK/state AGENT_DISPATCH_LOCKDIR=$WORK/locks AGENT_DISPATCH_PATH_PREFIX=$T/bin
export AGENT_DISPATCH_NOTIFY_CONF=$WORK/notify.env CODEX_HOME=$WORK/codex CLAUDE_CONFIG_DIR=$WORK/claude
export MIN_RUN_SEC=30 RETRY_WAIT=20 AGENT_DISPATCH_POLL_SEC=1 AGENT_DISPATCH_QUOTA_CMD=$T/bin/fake-quota
# The queue: the runner asks task_queue_ops.py who goes next (a staged copy can be tested too).
export AGENT_DISPATCH_OPS=${AGENT_DISPATCH_OPS:-/root/tools/agent-dispatch/task_queue_ops.py}
export AGENT_DISPATCH_TASKS_DIR=$WORK/tasks AGENT_DISPATCH_QUEUE_POLL_SEC=1
mkdir -p "$FAKE_DIR" "$AGENT_DISPATCH_LOCKDIR" "$WORK/tasks" "$CODEX_HOME" "$CLAUDE_CONFIG_DIR"
printf 'NOTIFY_CHANNEL=test\nNOTIFY_TARGET=test\nTELEGRAM_CHANNEL=tg-test\nTELEGRAM_TARGET=tg-target\n' >"$AGENT_DISPATCH_NOTIFY_CONF"

cleanup() {
  cat "$FAKE_DIR"/*.pids 2>/dev/null | xargs -r kill 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

fail=0
expect() {  # <description> <actual> <expected>
  if [ "$2" = "$3" ]; then echo "  ok    $1"; else echo "  FAIL  $1: got '$2', want '$3'"; fail=1; fi
}
expect_grep() {  # <description> <fixed string> <file>
  if grep -qF -- "$2" "$3"; then echo "  ok    $1"; else echo "  FAIL  $1: '$2' not in $(basename "$3")"; fail=1; fi
}
field() { ( . "$1/result.env"; printf '%s' "${!2}" ); }

mk() {  # <name> <agent> <seconds to deadline> <per-attempt timeout> [notify: none|weixin|weixin,telegram]
  local d=$WORK/tasks/$1
  mkdir -p "$d"; echo "fake task prompt" >"$d/prompt.md"
  cat >"$d/meta.env" <<EOF
ID=$1
AGENT=$2
NAME=$1
CWD=/root
RESUME=''
MODEL=fake
EFFORT=low
TIMEOUT=$4
DEADLINE='test'
DEADLINE_EPOCH=$(( $(date +%s) + $3 ))
NOTIFY=${5:-none}
CREATED=now
EOF
  echo "$d"
}
reset_fake() { rm -f "$FAKE_DIR"/*; echo "$2" >"$FAKE_DIR/$1.mode"; }

if [ "${DISPATCH_TEST_CASES:-}" = cancel-barrier ]; then
  echo '=== durable cancellation and wake/launch barriers (fake agents only)'
  reset_fake codex notice-then-ok
  d=$(mk startup-marker codex 900 300)
  touch "$d/cancel-requested"
  e=0; bash "$R" "$d" || e=$?
  expect 'marked task refuses startup' "$e/$(field "$d" STATE)" 143/cancelled
  expect 'no cold agent call' "$(test -f "$FAKE_DIR/codex.calls" && cat "$FAKE_DIR/codex.calls" || echo 0)" 0

  d=$(mk legacy-cancel codex 900 300)
  printf "STATE=cancelled\nSESSION=old-session\nATTEMPTS=7\nWAKE_AT=123\nWAITING=quota\nSLOT=1\n" >"$d/result.env"
  e=0; bash "$R" "$d" || e=$?
  expect 'legacy cancelled record refuses restart' "$e/$(field "$d" SESSION)/$(field "$d" ATTEMPTS)" 143/old-session/7
  expect 'legacy wait state cleared' "$(field "$d" WAKE_AT)/$(field "$d" WAITING)/$(field "$d" SLOT)" //
  expect 'legacy cancellation becomes durable' "$(test -e "$d/cancel-requested" && echo yes)" yes

  d=$(mk launch-race codex 900 300)
  exec 8>"$d/.launch.lock"; flock -x 8
  bash "$R" "$d" 8>&- & p=$!
  for _ in $(seq 100); do
    grep -q 'attempt 1/' "$d/run.log" 2>/dev/null && break
    sleep 0.05
  done
  touch "$d/cancel-requested"  # committed cancel owns the launch lock
  flock -u 8; exec 8>&-
  e=0; wait "$p" || e=$?
  expect 'cancel wins final launch race' "$e/$(field "$d" STATE)" 143/cancelled
  expect 'launch race spends no agent call' "$(test -f "$FAKE_DIR/codex.calls" && cat "$FAKE_DIR/codex.calls" || echo 0)" 0

  for kind in quota retry; do
    reset_fake codex quota-then-ok
    [ "$kind" != retry ] || echo quota-notice-then-other-failure >"$FAKE_DIR/codex.mode"
    rm -f "$AGENT_DISPATCH_LOCKDIR/.queue/codex.quota"
    d=$(mk "cancel-$kind" codex 900 300)
    FAKE_RESET_SEC=3 QUOTA_WAKE_PAD_SEC=0 RETRY_WAIT=3 bash "$R" "$d" & p=$!
    for _ in $(seq 100); do
      [ -r "$d/result.env" ] && [ "$(field "$d" WAITING)" = "$kind" ] && break
      sleep 0.05
    done
    expect "$kind wait reached" "$(field "$d" WAITING)" "$kind"
    # No signal: emulate a committed cancel whose stop races/fails. Wake alone
    # must notice it before any second CLI request.
    touch "$d/cancel-requested"
    e=0; wait "$p" || e=$?
    expect "$kind wake exits cancelled" "$e/$(field "$d" STATE)" 143/cancelled
    expect "$kind never calls fake agent again" "$(cat "$FAKE_DIR/codex.calls")" 1
    expect "$kind leaves no wake or slot" "$(field "$d" WAKE_AT)/$(field "$d" WAITING)/$(field "$d" SLOT)" //
    e=0; bash "$R" "$d" || e=$?
    expect "$kind restart still cannot call agent" "$e/$(cat "$FAKE_DIR/codex.calls")" 143/1
  done
fi

if [ -z "${DISPATCH_TEST_CASES:-}" ] || [[ ",$DISPATCH_TEST_CASES," == *,quota,* ]]; then
echo "=== [1+2] quota with a reset time -> notify, wait -> resume the same session ($(date +%T))"
reset_fake claude quota-then-ok; echo quota-then-ok >"$FAKE_DIR/codex.mode"
d1=$(mk claude-quota claude 900 300 weixin)
d2=$(mk codex-quota codex 900 300 weixin)
e1=0; e2=0
bash "$R" "$d1" & p1=$!
bash "$R" "$d2" & p2=$!
wait "$p1" || e1=$?
wait "$p2" || e2=$?
expect "claude exit" "$e1" 0
expect "claude state" "$(field "$d1" STATE)/$(field "$d1" OUTCOME)" ok/DONE
expect "claude attempts" "$(field "$d1" ATTEMPTS)" 2
sid1=$(grep -m1 -o -- '\[--session-id\] \[[0-9a-f-]*\]' "$FAKE_DIR/claude.argv" | sed 's/.*\[\(.*\)\]/\1/')
expect "claude session chosen up front" "$(field "$d1" SESSION)" "${sid1:-missing}"
expect_grep "claude 2nd call resumes the session" "[--resume] [$sid1]" "$FAKE_DIR/claude.argv"
expect_grep "agent sees its dispatch task id" "call 1 task id: claude-quota" "$FAKE_DIR/claude.argv"
expect_grep "claude reset parsed from the message" "(from message)" "$d1/run.log"
expect "codex exit" "$e2" 0
expect "codex state" "$(field "$d2" STATE)/$(field "$d2" OUTCOME)" ok/DONE
expect "codex attempts" "$(field "$d2" ATTEMPTS)" 2
expect "codex session" "$(field "$d2" SESSION)" 99999999-8888-7777-6666-555555555555
expect_grep "codex uses --json" "[--json]" "$FAKE_DIR/codex.argv"
expect_grep "codex 2nd call is exec resume <session> <prompt>" "call 2 argv: [exec] [resume]" "$FAKE_DIR/codex.argv"
expect_grep "codex resume passes session before the prompt" "[99999999-8888-7777-6666-555555555555] [继续" "$FAKE_DIR/codex.argv"
expect_grep "codex reset read from the rollout, not the message days away" "(from rollout)" "$d2/run.log"
expect "quota-wait and finish notices carry the remaining quota" "$(grep -c '额度：5h 剩 80%' "$FAKE_DIR/openclaw.messages")" 4
expect "quota line follows the do-not-cancel sentence" "$(grep -A1 '不用取消' "$FAKE_DIR/openclaw.messages" | grep -c '^额度：5h 剩 80%')" 2
expect "each quota wait sends a do-not-cancel notice" "$(grep -c '不用取消' "$FAKE_DIR/openclaw.messages")" 2
cf=$CLAUDE_CONFIG_DIR/projects/-root/$sid1.jsonl
expect "claude transcript relabeled for /resume" "$(grep -c '"entrypoint":"sdk-cli"' "$cf")/$(grep -c '"entrypoint":"cli"' "$cf")" 0/2
expect_grep "escaped entrypoint text inside a message untouched" '\"entrypoint\":\"sdk-cli\"' "$cf"
expect "relabeled transcript keeps its mode" "$(stat -c %a "$cf")" 600
expect_grep "final claude notice says how to open the session" "claude --resume $sid1" "$FAKE_DIR/openclaw.messages"

fi
if [ -z "${DISPATCH_TEST_CASES:-}" ] || [[ ",$DISPATCH_TEST_CASES," == *,deadline,* ]]; then
echo; echo "=== [3] deadline: agent never finishes ($(date +%T))"
reset_fake claude hang
d3=$(mk deadline claude 160 3600)
t0=$(date +%s); e3=0
bash "$R" "$d3" || e3=$?
expect "deadline exit" "$e3" 1
expect "deadline state" "$(field "$d3" STATE)/$(field "$d3" RC)" timeout/124
expect "deadline finished before the deadline" "$(( $(date +%s) - t0 < 160 ))" 1
sleep 3
left=0
for p in $(cat "$FAKE_DIR/claude.pids" 2>/dev/null); do kill -0 "$p" 2>/dev/null && left=$((left + 1)); done
expect "no leftover fake claude processes" "$left" 0
fi
# core: the single-task behaviours (status, codex errors, cancel, append, opencode, clip).
if [ -z "${DISPATCH_TEST_CASES:-}" ] || [[ ",$DISPATCH_TEST_CASES," == *,core,* ]]; then

echo; echo "=== [4] clean exit without a STATUS line -> unverified ($(date +%T))"
reset_fake claude ok-no-status
d4=$(mk no-status claude 900 300)
e4=0; bash "$R" "$d4" || e4=$?
expect "no-status exit" "$e4" 3
expect "no-status state" "$(field "$d4" STATE)" unverified

echo; echo "=== [5] codex out of credits, no reset time -> quota, no retry ($(date +%T))"
reset_fake codex no-credits
d5=$(mk codex-credits codex 900 300)
e5=0; bash "$R" "$d5" || e5=$?
expect "credits exit" "$e5" 75
expect "credits state" "$(field "$d5" STATE)" quota
expect "credits attempts" "$(field "$d5" ATTEMPTS)" 1
expect "credits session kept for resume" "$(field "$d5" SESSION)" 99999999-8888-7777-6666-555555555555

echo; echo "=== [7] codex non-fatal top-level error, then success -> ok ($(date +%T))"
reset_fake codex notice-then-ok
d7=$(mk codex-notice-ok codex 900 300)
e7=0; bash "$R" "$d7" || e7=$?
expect "notice-then-ok exit" "$e7" 0
expect "notice-then-ok state" "$(field "$d7" STATE)/$(field "$d7" OUTCOME)" ok/DONE

echo; echo "=== [8] codex quota-like notice, then an unrelated failure -> failed, not quota ($(date +%T))"
reset_fake codex quota-notice-then-other-failure
d8=$(mk codex-notice-fail codex 900 300)
e8=0; MAX_ATTEMPTS=1 bash "$R" "$d8" || e8=$?
expect "notice-then-failure exit" "$e8" 1
expect "notice-then-failure state" "$(field "$d8" STATE)" failed
expect_grep "reported error is the terminal one" "stream disconnected before completion" "$d8/run.log"

echo; echo "=== [9] cancel mid-attempt: a slow notification still goes out before the KILL ($(date +%T))"
# Like `systemctl stop`: TERM the outer timeout. The fake send takes 8s, longer than the old -k 5.
reset_fake claude hang; echo 8 >"$FAKE_DIR/openclaw.sleep"
d9=$(mk cancel claude 900 300 weixin)
bash "$R" "$d9" & p9=$!
for _ in $(seq 30); do grep -q 'attempt 1/' "$d9/run.log" 2>/dev/null && break; sleep 1; done
sleep 2
kill -TERM "$p9"; e9=0; wait "$p9" || e9=$?
expect "cancel exit" "$e9" 143
expect "cancel state" "$(field "$d9" STATE)" cancelled
expect_grep "cancel notification sent" "notify: sent" "$d9/run.log"
expect_grep "cancel end line written" "end state=cancelled" "$d9/run.log"
expect_grep "cancel message delivered" "cancelled" "$FAKE_DIR/openclaw.messages"

echo; echo "=== [10] reset times keep their date"
resetfn=$(sed -n '/^next_reset_epoch() {/,/^}/p' "$R")
at() { TZ=Asia/Shanghai date -d "$1" +%s; }
nre() { RESET_NOW=$(at "2026-09-15 00:30") bash -c "$resetfn; next_reset_epoch \"\$1\"" _ "$1" || echo none; }
expect "codex weekly reset with ordinal date" "$(nre "You've hit your usage limit. Upgrade to Pro or try again at Sep 20th, 2026 1:29 PM.")" "$(at '2026-09-20 13:29')"
expect "codex dated reset as the binary formats it" "$(nre "try again at Sep 20, 2026 1:29 PM.")" "$(at '2026-09-20 13:29')"
expect "codex same-day time" "$(nre "try again at 12:54 AM.")" "$(at '2026-09-15 00:54')"
expect "time already past today -> tomorrow" "$(nre "resets 12am (Asia/Shanghai)")" "$(at '2026-09-16 00:00')"
expect "claude weekly reset with date" "$(nre "You've hit your weekly limit · resets Sep 20, 3pm (Asia/Shanghai)")" "$(at '2026-09-20 15:00')"
expect "claude reset in next year" "$(nre "resets Jan 3, 2027, 1pm (Asia/Shanghai)")" "$(at '2027-01-03 13:00')"
expect "zone in parentheses is honoured" "$(nre "resets 9am (America/New_York)")" "$(TZ=America/New_York date -d '2026-09-15 09:00' +%s)"
expect "no reset time -> none" "$(nre "Your workspace is out of credits.")" none

echo; echo "=== [11] dispatch.sh refuses to start a task from inside a dispatched task"
e11=0; out11=$(AGENT_DISPATCH_TASK_ID=outer-task /root/tools/agent-dispatch/dispatch.sh codex --name nested-test </dev/null 2>&1) || e11=$?
expect "nested dispatch exit" "$e11" 2
expect "nested dispatch names the outer task" "$(printf '%s' "$out11" | grep -c 'already dispatched task outer-task')" 1
expect "nested dispatch created no task dir" "$(ls -d /root/logs/agent-dispatch/nested-test-* 2>/dev/null | wc -l)" 0

echo; echo "=== [12] append while running: the attempt stops, the same session resumes with it ($(date +%T))"
reset_fake claude hang-then-ok
d12=$(mk append-now claude 900 300 weixin)
bash "$R" "$d12" & p12=$!
for _ in $(seq 30); do grep -q 'attempt 1/' "$d12/run.log" 2>/dev/null && break; sleep 1; done
sleep 2
mkdir -p "$d12/inbox"; printf '顺便把 README 也改了\n' >"$d12/inbox/20260917-000000-1-now.md"
e12=0; wait "$p12" || e12=$?
sid12=$(field "$d12" SESSION)
expect "append-now exit" "$e12" 0
expect "append-now state" "$(field "$d12" STATE)/$(field "$d12" OUTCOME)" ok/DONE
expect "an append is not a retry" "$(field "$d12" ATTEMPTS)/$(field "$d12" APPENDS)" 1/1
expect_grep "append-now log says why it stopped" "appended instruction: stopping the attempt" "$d12/run.log"
expect "append-now 2nd call resumes the first session" "$(grep -c "call 2 argv:.*\[--resume\] \[$sid12\]" "$FAKE_DIR/claude.argv")" 1
expect_grep "append-now 2nd call carries the text" "顺便把 README 也改了" "$FAKE_DIR/claude.argv"
expect_grep "append-now 2nd call says it was interrupted" "被这条追加指令打断" "$FAKE_DIR/claude.argv"
expect "append-now inbox drained" "$(ls "$d12"/inbox/*.md 2>/dev/null | wc -l)/$(ls "$d12"/inbox/delivered/*.md | wc -l)" 0/1
expect "append-now sends one notice, at the end" "$(grep -c '^✅' "$FAKE_DIR/openclaw.messages")" 1

echo; echo "=== [13] queued append: delivered to the same session after the attempt ends ($(date +%T))"
reset_fake opencode queue
d13=$(mk append-queue opencode 900 300)
bash "$R" "$d13" & p13=$!
for _ in $(seq 30); do grep -q 'attempt 1/' "$d13/run.log" 2>/dev/null && break; sleep 1; done
mkdir -p "$d13/inbox"; printf 'also check the CI\n' >"$d13/inbox/20260917-000000-2-queue.md"
e13=0; wait "$p13" || e13=$?
expect "append-queue exit" "$e13" 0
expect "append-queue state" "$(field "$d13" STATE)/$(field "$d13" ATTEMPTS)/$(field "$d13" APPENDS)" ok/1/1
expect "queued append did not interrupt" "$(grep -c 'stopping the attempt' "$d13/run.log")" 0
expect "queued append resumes the opencode session" "$(grep -c 'call 2 argv:.*\[-s\] \[ses_fake0001\]' "$FAKE_DIR/opencode.argv")" 1
expect "queued append sends only the appended text" "$(grep 'call 2 argv:' "$FAKE_DIR/opencode.argv" | grep -c 'fake task prompt')" 0
expect_grep "opencode final text is the last message" "opencode call 2 done" "$d13/run.log"

echo; echo "=== [14] opencode exits 0 on a model error -> retried in the same session ($(date +%T))"
reset_fake opencode error-then-ok
d14=$(mk opencode-error opencode 900 300)
e14=0; RETRY_WAIT=2 bash "$R" "$d14" || e14=$?
expect "opencode error exit" "$e14" 0
expect "opencode error state" "$(field "$d14" STATE)/$(field "$d14" OUTCOME)/$(field "$d14" ATTEMPTS)" ok/DONE/2
expect "opencode has no subscription quota to read" "$(grep -c '^quota |' "$d14/run.log")" 0
expect_grep "opencode error recorded" "Rate limit exceeded" "$d14/run.log"
expect "opencode retry continues the session" "$(grep -c 'call 2 argv:.*\[-s\] \[ses_fake0001\] \[--\] \[继续' "$FAKE_DIR/opencode.argv")" 1
expect_grep "opencode effort becomes --variant" "[--variant] [low]" "$FAKE_DIR/opencode.argv"

echo; echo "=== [16] opencode fallback: a failing model hands the same session to the next one ($(date +%T))"
reset_fake opencode bad-model; echo fake >"$FAKE_DIR/opencode.badmodel"
d16=$(mk opencode-fallback opencode 900 300)
echo "FALLBACK_MODELS=good-a,good-b" >>"$d16/meta.env"
t16=$(date +%s); e16=0; RETRY_WAIT=600 FALLBACK_WAIT=2 bash "$R" "$d16" || e16=$?
expect "fallback exit" "$e16" 0
expect "fallback state" "$(field "$d16" STATE)/$(field "$d16" ATTEMPTS)/$(field "$d16" MODEL_USED)" ok/2/good-a
expect "fallback waited FALLBACK_WAIT, not RETRY_WAIT" "$(( $(date +%s) - t16 < 60 ))" 1
expect_grep "fallback second call uses the next model" "call 2 model: good-a" "$FAKE_DIR/opencode.argv"
expect "fallback keeps the session" "$(grep -c 'call 2 argv:.*\[-s\] \[ses_fake0001\]' "$FAKE_DIR/opencode.argv")" 1

echo; echo "=== [6] clip keeps UTF-8 intact, with and without python3"
clipfn=$(sed -n '/^clip() {/,/^}/p' "$R")
out=$(printf '%s' "中文结果不能被截成半个字" | bash -c "$clipfn; clip tail 5")
expect "clip tail by characters" "$out" "截成半个字"
nopy() {  # <text> <head|tail> <n>: run clip as if python3 were missing; fails on invalid UTF-8
  printf '%s' "$1" | bash -c "command() { [ \"\$2\" = python3 ] && return 1; builtin command \"\$@\"; }; $clipfn; clip $2 $3; echo \"rc=\$?\"" \
    | python3 -c 'import sys; print(sys.stdin.buffer.read().decode("utf-8"), end="")'
}
expect "fallback ascii head is capped" "$(nopy abcdefghijk head 4)" "abcdrc=0"
expect "fallback ascii tail is capped" "$(nopy abcdefghijk tail 4)" "hijkrc=0"
expect "fallback chinese head drops the partial char" "$(nopy 中文结果不能 head 13)" "中文结果rc=0"
expect "fallback chinese tail drops the partial char" "$(nopy 中文结果不能 tail 13)" "结果不能rc=0"
expect "fallback emoji head" "$(nopy 😀甲 head 5)" "😀rc=0"
expect "fallback cut inside the only char gives empty, rc 0" "$(nopy 😀甲 head 1)" "rc=0"

fi
if [ -z "${DISPATCH_TEST_CASES:-}" ] || [[ ",$DISPATCH_TEST_CASES," == *,slots,* ]]; then
echo; echo "=== [15] run slots are per agent: a busy claude slot queues claude only ($(date +%T))"
# The claude slot and both slots the pre-2026-09-25 runners shared are held by someone else.
# The opencode task must run at once; the claude task waits for its own slot, then runs.
reset_fake claude slow-ok; echo queue >"$FAKE_DIR/opencode.mode"
L=$AGENT_DISPATCH_LOCKDIR
flock -n "$L/slot-claude-1.lock" flock -n "$L/slot-1.lock" flock -n "$L/slot-2.lock" \
  bash -c 'touch "$FAKE_DIR/held15"; while [ ! -e "$FAKE_DIR/release15" ]; do sleep 0.2; done' & h15=$!
for _ in $(seq 150); do [ -e "$FAKE_DIR/held15" ] && break; sleep 0.2; done
expect "the claude slot and both shared slots are held" "$(for f in slot-claude-1 slot-1 slot-2; do flock -n "$L/$f.lock" true || echo held; done | wc -l)" 3
d15a=$(mk slot-a claude 900 300)
d15b=$(mk slot-b opencode 900 300)
e15a=0; e15b=0
bash "$R" "$d15a" & p15a=$!
bash "$R" "$d15b" & p15b=$!
for _ in $(seq 20); do [ "$(field "$d15a" WAITING 2>/dev/null)" = slot ] && break; sleep 1; done
expect "claude task waits for its own agent's slot" "$(field "$d15a" WAITING)" slot
wait "$p15b" || e15b=$?
expect "opencode task ran meanwhile, in its own slot" "$e15b/$(field "$d15b" STATE)/$(grep -c 'got run slot opencode-1' "$d15b/run.log")" 0/ok/1
expect "claude task is still waiting after that" "$(field "$d15a" WAITING)/$(field "$d15a" ATTEMPTS)" slot/0
touch "$FAKE_DIR/release15"; wait "$h15" 2>/dev/null || true
wait "$p15a" || e15a=$?
expect "claude task runs once its slot is free" "$e15a/$(field "$d15a" STATE)/$(field "$d15a" WAITING)/$(grep -c 'got run slot claude-1' "$d15a/run.log")" 0/ok//1

echo; echo "=== [17] one claude, one codex and one opencode attempt run at once, each in its agent's slot ($(date +%T))"
reset_fake claude slow-ok
echo slow-ok >"$FAKE_DIR/codex.mode"; echo slow-ok >"$FAKE_DIR/opencode.mode"
d17a=$(mk slot-one claude 900 300); d17b=$(mk slot-two codex 900 300); d17c=$(mk slot-three opencode 900 300)
e17a=0; e17b=0; e17c=0
# Hold all three fake CLIs at a barrier so the sample proves simultaneous occupancy.
# A historical SLOT value from an already-finished process is not evidence.
mkdir -p "$WORK/barrier-bin"
for agent in claude codex opencode; do
  printf '#!/bin/bash\nwhile [ ! -e "$FAKE_DIR/slot-release" ]; do sleep 0.1; done\nexec "%s/bin/%s" "$@"\n' "$T" "$agent" >"$WORK/barrier-bin/$agent"
  chmod +x "$WORK/barrier-bin/$agent"
done
slot_of() { ( [ -s "$1/result.env" ] && field "$1" SLOT ) || true; }
# Production limits (one slot per agent): no AGENT_DISPATCH_MAX_RUNNING_* override here.
AGENT_DISPATCH_PATH_PREFIX="$WORK/barrier-bin:$T/bin" bash "$R" "$d17a" & p17a=$!
AGENT_DISPATCH_PATH_PREFIX="$WORK/barrier-bin:$T/bin" bash "$R" "$d17b" & p17b=$!
AGENT_DISPATCH_PATH_PREFIX="$WORK/barrier-bin:$T/bin" bash "$R" "$d17c" & p17c=$!
for d in "$d17a" "$d17b" "$d17c"; do
  for _ in $(seq 30); do [ -n "$(slot_of "$d")" ] && break; sleep 1; done
done
observed17=$(printf '%s\n%s\n%s\n' "$(slot_of "$d17a")" "$(slot_of "$d17b")" "$(slot_of "$d17c")")
expect "three live attempts hold their agents' slots" "$(printf '%s\n' "$observed17" | xargs)" 'claude-1 codex-1 opencode-1'
for s in claude-1 codex-1 opencode-1; do
  expect "slot $s is actually locked" "$(flock -n "$AGENT_DISPATCH_LOCKDIR/slot-$s.lock" true && echo free || echo held)" held
done
expect "none of the shared pre-2026-09-25 slots is taken" "$(for i in 1 2 3; do flock -n "$AGENT_DISPATCH_LOCKDIR/slot-$i.lock" true || echo held; done | wc -l)" 0
touch "$FAKE_DIR/slot-release"
wait "$p17a" || e17a=$?; wait "$p17b" || e17b=$?; wait "$p17c" || e17c=$?
expect "all three slot tasks finish" "$e17a/$e17b/$e17c" 0/0/0
expect "no task is left waiting for a slot" "$(field "$d17c" WAITING)" ''

echo; echo "=== [18] limits.env is the single source for the slot counts ($(date +%T))"
lim() { bash -c '. "$2"; printf "%s" "${!1}"' _ "$1" "$(dirname "$R")/limits.env"; }
expect "limits.env ships one slot per agent" "$(lim MAX_RUNNING_CLAUDE)/$(lim MAX_RUNNING_CODEX)/$(lim MAX_RUNNING_OPENCODE)" 1/1/1
expect "the displayed total is their sum" "$(lim MAX_RUNNING)" "$(( $(lim MAX_RUNNING_CLAUDE) + $(lim MAX_RUNNING_CODEX) + $(lim MAX_RUNNING_OPENCODE) ))"
# Behavioral tests load a different shared limits file and exercise the runner and
# supervisor; grepping the number of mentions of a filename proves nothing.
python3 "$T/test_limits.py" || fail=1

echo; echo "=== [19] a task queued for its agent lock publishes WAITING=lock ($(date +%T))"
# The patrol supervisor decides whether to yield from result.env alone. A task blocked on
# the agent lock used to publish nothing, so it was invisible demand and a patrol round ran
# to completion while a manual task sat queued (2026-09-23).
reset_fake claude slow-ok; echo 14 >"$FAKE_DIR/claude.slow"
d19a=$(mk lock-holder claude 900 300); d19b=$(mk lock-waiter claude 900 300)
e19a=0; e19b=0
bash "$R" "$d19a" & p19a=$!
for _ in $(seq 30); do grep -q 'lock held' "$d19a/run.log" 2>/dev/null && break; sleep 1; done
bash "$R" "$d19b" & p19b=$!
for _ in $(seq 30); do [ "$(field "$d19b" WAITING 2>/dev/null)" = lock ] && break; sleep 1; done
expect "waiter publishes the agent-lock wait" "$(field "$d19b" WAITING)" lock
expect "waiter holds no run slot while it waits" "$(field "$d19b" SLOT)" ''
expect "waiter has not started an attempt" "$(field "$d19b" ATTEMPTS)" 0
wait "$p19a" || e19a=$?; wait "$p19b" || e19b=$?
expect "both tasks finish" "$e19a/$e19b" 0/0
expect "waiter state after the lock is free" "$(field "$d19b" STATE)/$(field "$d19b" WAITING)/$(field "$d19b" SLOT)" ok//
expect "the earlier task still owns its slot" "$(field "$d19a" STATE)" ok

echo; echo "=== [20] cancelling a queued task clears its WAITING marker ($(date +%T))"
# A cancelled task kept WAITING=lock in result.env, so it still read as queued demand
# (2026-09-23 dispatch-default-model-bump).
reset_fake claude slow-ok; echo 14 >"$FAKE_DIR/claude.slow"
d20a=$(mk cancel-holder claude 900 300); d20b=$(mk cancel-waiter claude 900 300)
e20a=0; e20b=0
bash "$R" "$d20a" & p20a=$!
for _ in $(seq 30); do grep -q 'lock held' "$d20a/run.log" 2>/dev/null && break; sleep 1; done
bash "$R" "$d20b" & p20b=$!
for _ in $(seq 30); do [ "$(field "$d20b" WAITING 2>/dev/null)" = lock ] && break; sleep 1; done
expect "waiter is queued on the lock" "$(field "$d20b" WAITING)" lock
kill -TERM "$p20b"; wait "$p20b" || e20b=$?
expect "cancelled waiter exit" "$e20b" 143
expect "cancelled waiter state/WAITING/SLOT" "$(field "$d20b" STATE)/$(field "$d20b" WAITING)/$(field "$d20b" SLOT)" cancelled//
wait "$p20a" || e20a=$?
expect "the lock holder is unaffected" "$e20a/$(field "$d20a" STATE)" 0/ok

fi
if [ -z "${DISPATCH_TEST_CASES:-}" ] || [[ ",$DISPATCH_TEST_CASES," == *,stall,* ]]; then
# A stalled attempt is stopped long before its timeout (300s here, 5400s for patrol) and the
# task moves on; an attempt that is slow but makes progress is never touched.
echo; echo "=== [22] opencode silent from the start -> stopped at STALL_FIRST, next model, fresh prompt ($(date +%T))"
reset_fake opencode silent-then-ok
d22=$(mk stall-first opencode 900 300)
echo "FALLBACK_MODELS=good-a,good-b" >>"$d22/meta.env"
t22=$(date +%s); e22=0
FAKE_SILENT=120 STALL_FIRST_SEC=6 STALL_IDLE_SEC=12 STALL_CHECK_SEC=1 FALLBACK_WAIT=1 bash "$R" "$d22" || e22=$?
expect "stall-first exit" "$e22" 0
expect "stall-first state/attempts/model/stalls" "$(field "$d22" STATE)/$(field "$d22" ATTEMPTS)/$(field "$d22" MODEL_USED)/$(field "$d22" STALLS)" ok/2/good-a/1
expect "stall-first did not wait out the silence" "$(( $(date +%s) - t22 < 60 ))" 1
expect_grep "stall-first log says why" "(no output at all; limit 6s): stopping the attempt as stalled" "$d22/run.log"
expect_grep "stall-first attempt end is marked" "kind=error session=- stalled" "$d22/run.log"
expect "stall-first retry had no session, so it sent the task again" "$(grep 'call 2 argv:' "$FAKE_DIR/opencode.argv" | grep -c '\[-s\].*fake task prompt')/$(grep 'call 2 argv:' "$FAKE_DIR/opencode.argv" | grep -c 'fake task prompt')" 0/1
expect "stall-first leaves no silent fake behind" "$(for p in $(cat "$FAKE_DIR/opencode.pids"); do kill -0 "$p" 2>/dev/null && echo x; done | wc -l)" 0

echo; echo "=== [23] opencode goes silent mid-run -> stopped at STALL_IDLE, same session on the next model ($(date +%T))"
reset_fake opencode silent-mid
d23=$(mk stall-mid opencode 900 300)
echo "FALLBACK_MODELS=good-a" >>"$d23/meta.env"
t23=$(date +%s); e23=0
STALL_FIRST_SEC=6 STALL_IDLE_SEC=8 STALL_CHECK_SEC=1 FALLBACK_WAIT=1 bash "$R" "$d23" || e23=$?
expect "stall-mid state/attempts/model/stalls" "$e23/$(field "$d23" STATE)/$(field "$d23" ATTEMPTS)/$(field "$d23" MODEL_USED)/$(field "$d23" STALLS)" 0/ok/2/good-a/1
expect "stall-mid stopped within the idle limit, not the timeout" "$(( $(date +%s) - t23 < 60 ))" 1
expect_grep "stall-mid log names the last output" "no tool at work; limit 8s): stopping the attempt as stalled" "$d23/run.log"
expect "stall-mid continues the session" "$(grep -c 'call 2 argv:.*\[-s\] \[ses_fake0001\] \[--\] \[继续' "$FAKE_DIR/opencode.argv")" 1

echo; echo "=== [24] slow but steady output is never stopped, however long it runs ($(date +%T))"
reset_fake opencode slow-steady
d24=$(mk stall-slow opencode 900 300)
e24=0; FAKE_STEP=3 FAKE_STEPS=8 STALL_FIRST_SEC=6 STALL_IDLE_SEC=6 STALL_CHECK_SEC=1 bash "$R" "$d24" || e24=$?
expect "slow-steady ran once to the end" "$e24/$(field "$d24" STATE)/$(field "$d24" ATTEMPTS)/$(field "$d24" STALLS)" 0/ok/1/0
expect "slow-steady outlived the idle limit several times over" "$(grep -c '"text":"step' "$d24/attempt1.jsonl")" 8
expect "slow-steady never marked stalled" "$(grep -c 'stalled' "$d24/run.log")" 0

echo; echo "=== [25] a working tool is not a stall, even with output after it started ($(date +%T))"
# The long tool starts, a parallel one's result is printed 2s later, then 20s of silence while
# the long one works. Dating tools against the last output (first cut) counted it as idle.
reset_fake opencode tool-long
d25=$(mk stall-tool opencode 900 300)
e25=0; FAKE_TOOL=20 STALL_FIRST_SEC=8 STALL_IDLE_SEC=8 STALL_CHECK_SEC=1 bash "$R" "$d25" || e25=$?
expect "tool-long ran once to the end" "$e25/$(field "$d25" STATE)/$(field "$d25" ATTEMPTS)/$(field "$d25" STALLS)" 0/ok/1/0

echo; echo "=== [27] an idle process left in the background does not hide a stall ($(date +%T))"
reset_fake opencode bg-idle
d27=$(mk stall-bg opencode 900 300)
t27=$(date +%s); e27=0
STALL_FIRST_SEC=8 STALL_IDLE_SEC=8 STALL_CHECK_SEC=1 RETRY_WAIT=1 bash "$R" "$d27" || e27=$?
expect "bg-idle stopped and retried" "$e27/$(field "$d27" STATE)/$(field "$d27" ATTEMPTS)/$(field "$d27" STALLS)" 0/ok/2/1
expect "bg-idle did not wait for its timeout" "$(( $(date +%s) - t27 < 60 ))" 1
expect "bg-idle leaves no idle process behind" "$(pgrep -fxc 'sleep 3599')" 0

echo; echo "=== [28] a busy leftover counts only for STALL_TOOL, then the stall is caught ($(date +%T))"
reset_fake opencode bg-busy
d28=$(mk stall-bg-busy opencode 900 300)
t28=$(date +%s); e28=0
STALL_FIRST_SEC=6 STALL_IDLE_SEC=6 STALL_TOOL_SEC=8 STALL_CHECK_SEC=1 RETRY_WAIT=1 bash "$R" "$d28" || e28=$?
expect "bg-busy stopped and retried" "$e28/$(field "$d28" STATE)/$(field "$d28" ATTEMPTS)/$(field "$d28" STALLS)" 0/ok/2/1
expect "bg-busy did not wait for its timeout" "$(( $(date +%s) - t28 < 60 ))" 1
expect_grep "bg-busy log names the tool that ran too long" "a tool has run for over 8s; limit 6s): stopping the attempt as stalled" "$d28/run.log"
expect "bg-busy leaves no busy job behind" "$(pgrep -fc 'busyjob-3598' || true)" 0

echo; echo "=== [29] codex waiting on an idle command is not a stall; a command that never ends is ($(date +%T))"
reset_fake codex idle-wait
d29a=$(mk stall-codex-wait codex 900 300)
e29=0; FAKE_WAIT=16 STALL_FIRST_SEC=6 STALL_IDLE_SEC=6 STALL_CHECK_SEC=1 bash "$R" "$d29a" || e29=$?
expect "codex idle 16s inside its own command ran once, not stalled" "$e29/$(field "$d29a" STATE)/$(field "$d29a" ATTEMPTS)/$(field "$d29a" STALLS)" 0/ok/1/0
reset_fake codex hang-cmd
d29b=$(mk stall-codex-hang codex 900 300)
t29=$(date +%s); e29=0
STALL_FIRST_SEC=6 STALL_IDLE_SEC=6 STALL_TOOL_SEC=8 STALL_CHECK_SEC=1 RETRY_WAIT=1 bash "$R" "$d29b" || e29=$?
expect "codex hung command stopped and the session resumed" "$e29/$(field "$d29b" STATE)/$(field "$d29b" ATTEMPTS)/$(field "$d29b" STALLS)/$(grep -c 'call 2 argv:.*\[resume\]' "$FAKE_DIR/codex.argv")" 0/ok/2/1/1
expect "codex hung command did not wait for its timeout" "$(( $(date +%s) - t29 < 60 ))" 1
expect_grep "codex hung command log names the tool" "a tool has run for over 8s; limit 6s): stopping the attempt as stalled" "$d29b/run.log"
expect "codex hung command leaves nothing behind" "$(pgrep -fxc 'sleep 3597' || true)" 0

echo; echo "=== [26] claude: its transcript is progress; a silent attempt is stopped and resumed ($(date +%T))"
reset_fake claude slow-transcript
d26a=$(mk stall-claude-slow claude 900 300)
e26=0; STALL_FIRST_SEC=6 STALL_IDLE_SEC=6 STALL_CHECK_SEC=1 bash "$R" "$d26a" || e26=$?
expect "claude writing only its transcript for 24s is not stalled" "$e26/$(field "$d26a" STATE)/$(field "$d26a" ATTEMPTS)/$(field "$d26a" STALLS)" 0/ok/1/0
reset_fake claude hang-then-ok
d26b=$(mk stall-claude-hang claude 900 300)
t26=$(date +%s); e26=0; STALL_FIRST_SEC=6 STALL_IDLE_SEC=6 STALL_CHECK_SEC=1 RETRY_WAIT=1 bash "$R" "$d26b" || e26=$?
sid26=$(field "$d26b" SESSION)
expect "silent claude attempt stopped and retried" "$e26/$(field "$d26b" STATE)/$(field "$d26b" ATTEMPTS)/$(field "$d26b" STALLS)" 0/ok/2/1
expect "silent claude attempt did not wait for its timeout" "$(( $(date +%s) - t26 < 60 ))" 1
expect "the retry resumes the same claude session" "$(grep -c "call 2 argv:.*\[--resume\] \[$sid26\]" "$FAKE_DIR/claude.argv")" 1
expect "a stall is not a quota resume" "$(field "$d26b" QUOTA_RESUMES_USED)" 0
fi
if [ -z "${DISPATCH_TEST_CASES:-}" ] || [[ ",$DISPATCH_TEST_CASES," == *,names,* ]]; then
echo; echo "=== [21] patrol-* names are reserved for clawock-patrol rounds"
# Rejected before anything is created; the allowed case stops at the next check (bad cwd).
e21=0; out21=$(env -u AGENT_DISPATCH_TASK_ID -u AGENT_DISPATCH_PATROL /root/tools/agent-dispatch/dispatch.sh codex --name patrol-manual-test </dev/null 2>&1) || e21=$?
expect "manual patrol-* name exit" "$e21" 2
expect "manual patrol-* name is refused as reserved" "$(printf '%s' "$out21" | grep -c 'reserved for clawock-patrol')" 1
e21=0; out21=$(env -u AGENT_DISPATCH_TASK_ID AGENT_DISPATCH_PATROL=1 /root/tools/agent-dispatch/dispatch.sh codex --name patrol-manual-test --cwd /nonexistent-dir </dev/null 2>&1) || e21=$?
expect "patrol's own dispatch passes the name check" "$e21/$(printf '%s' "$out21" | grep -c 'does not exist')" 2/1
expect "no task dir was created" "$(ls -d /root/logs/agent-dispatch/patrol-manual-test-* 2>/dev/null | wc -l)" 0
# Appending to an ended task under that prefix continues it under a manual name instead of
# being refused (the continuation stops at the bad cwd, so nothing is dispatched).
id21=patrol-ended-test-20000101-000000; d21=/root/logs/agent-dispatch/$id21; mkdir "$d21"
printf 'AGENT=codex\nNAME=patrol-ended-test\nCWD=/nonexistent-dir\nMODEL=fake\nEFFORT=\nNOTIFY=none\n' >"$d21/meta.env"
printf 'STATE=ok\nSESSION=fake-session\n' >"$d21/result.env"
e21=0; out21=$(echo more | env -u AGENT_DISPATCH_TASK_ID -u AGENT_DISPATCH_PATROL /root/tools/agent-dispatch/dispatch.sh append "$id21" 2>&1) || e21=$?
rm -rf "$d21"
expect "continuation is not refused as reserved" "$(printf '%s' "$out21" | grep -c 'reserved for clawock-patrol')" 0
expect "continuation reaches the next check" "$e21/$(printf '%s' "$out21" | grep -c 'does not exist')" 2/1

echo; echo "=== [40] dispatch.sh: a channel list that notifies nobody is refused; cancel names unknown tasks"
D=$(dirname "$R")/dispatch.sh
for bad in , '' 'weixin,bogus' 'none,telegram'; do
  e40=0; out40=$(env -u AGENT_DISPATCH_TASK_ID "$D" codex --name notify-check --notify "$bad" </dev/null 2>&1) || e40=$?
  expect "--notify '$bad' is refused" "$e40/$(printf '%s' "$out40" | grep -c 'notify takes')" 2/1
done
expect "no task dir was created" "$(ls -d /root/logs/agent-dispatch/notify-check-* 2>/dev/null | wc -l)" 0
e40=0; out40=$("$D" cancel no-such-task-20000101-000000 2>&1) || e40=$?
expect "cancel of an unknown id is an error" "$e40/$(printf '%s' "$out40" | grep -c 'no task no-such-task')" 4/1
fi
if [ -z "${DISPATCH_TEST_CASES:-}" ] || [[ ",$DISPATCH_TEST_CASES," == *,notify,* ]]; then
# kcn 2026-09-26: user tasks tell WeChat and Telegram. The outcome of every leg lands in
# result.env (NOTIFIED / NOTIFY_FAILED), and no notification outcome changes a task's state.
echo; echo "=== [35] dual send: both legs delivered and recorded ($(date +%T))"
reset_fake claude slow-ok; echo 1 >"$FAKE_DIR/claude.slow"
d35=$(mk notify-dual claude 900 300 weixin,telegram)
e35=0; bash "$R" "$d35" || e35=$?
expect "dual send exit/state" "$e35/$(field "$d35" STATE)" 0/ok
expect "both legs recorded as sent" "$(field "$d35" NOTIFIED)/$(field "$d35" NOTIFY_FAILED)" "weixin,telegram/"
expect "one send per leg, to each channel's own target" "$(sort "$FAKE_DIR/openclaw.sends" | xargs)" "test test tg-test tg-target"
expect_grep "the log names each leg" "notify: sent (telegram)" "$d35/run.log"

echo; echo "=== [36] a failing leg is recorded and changes nothing else ($(date +%T))"
reset_fake claude slow-ok; echo 1 >"$FAKE_DIR/claude.slow"; echo test >"$FAKE_DIR/openclaw.fail"
d36=$(mk notify-half claude 900 300 weixin,telegram)
e36=0; bash "$R" "$d36" || e36=$?
expect "a failed WeChat leg keeps the task ok and its exit 0" "$e36/$(field "$d36" STATE)/$(field "$d36" OUTCOME)" 0/ok/DONE
expect "receipts split by leg" "$(field "$d36" NOTIFIED)/$(field "$d36" NOTIFY_FAILED)" telegram/weixin
expect_grep "the failed leg is in the log" "notify: send failed (weixin)" "$d36/run.log"

echo; echo "=== [37] channel list edge cases: case, spaces, duplicates, none, unknown, empty items ($(date +%T))"
reset_fake claude slow-ok; echo 1 >"$FAKE_DIR/claude.slow"
d37=$(mk notify-messy claude 900 300)
echo "NOTIFY=' Weixin,weixin,,none, TELEGRAM ,bogus,'" >>"$d37/meta.env"
e37=0; bash "$R" "$d37" || e37=$?
expect "messy list: exit/state" "$e37/$(field "$d37" STATE)" 0/ok
expect "each known channel once, the unknown one failed" "$(field "$d37" NOTIFIED)/$(field "$d37" NOTIFY_FAILED)" "weixin,telegram/bogus"
expect "exactly two sends" "$(wc -l <"$FAKE_DIR/openclaw.sends")" 2
expect_grep "unknown channel logged" "notify: unknown channel 'bogus'" "$d37/run.log"
# A glob character in the list must not expand to file names in the runner's cwd.
reset_fake claude slow-ok; echo 1 >"$FAKE_DIR/claude.slow"
d37b=$(mk notify-glob claude 900 300)
echo "NOTIFY='*'" >>"$d37b/meta.env"
( cd "$T" && bash "$R" "$d37b" ) || true
expect "a '*' is one unknown channel, not a file list" "$(field "$d37b" NOTIFY_FAILED)" '*'

echo; echo "=== [38] telegram target missing: that leg fails in the log, weixin still goes ($(date +%T))"
reset_fake claude slow-ok; echo 1 >"$FAKE_DIR/claude.slow"
cp "$AGENT_DISPATCH_NOTIFY_CONF" "$WORK/notify.full"
printf 'NOTIFY_CHANNEL=test\nNOTIFY_TARGET=test\n' >"$AGENT_DISPATCH_NOTIFY_CONF"
d38=$(mk notify-no-tg claude 900 300 weixin,telegram)
e38=0; bash "$R" "$d38" || e38=$?
cp "$WORK/notify.full" "$AGENT_DISPATCH_NOTIFY_CONF"
expect "missing telegram target: state and receipts" "$e38/$(field "$d38" STATE)/$(field "$d38" NOTIFIED)/$(field "$d38" NOTIFY_FAILED)" 0/ok/weixin/telegram
expect_grep "says the target is not configured" "notify: telegram target not configured" "$d38/run.log"

echo; echo "=== [39] legs go out in parallel: two slow legs fit one timeout, also when cancelled ($(date +%T))"
reset_fake claude hang; echo 8 >"$FAKE_DIR/openclaw.sleep"
d39=$(mk notify-slow-cancel claude 900 300 weixin,telegram)
bash "$R" "$d39" & p39=$!
for _ in $(seq 30); do grep -q 'attempt 1/' "$d39/run.log" 2>/dev/null && break; sleep 1; done
sleep 2
t39=$(date +%s); kill -TERM "$p39"; e39=0; wait "$p39" || e39=$?
expect "cancel with two slow legs: exit/state" "$e39/$(field "$d39" STATE)" 143/cancelled
expect "both legs delivered" "$(field "$d39" NOTIFIED)" "weixin,telegram"
expect "the two 8s sends overlapped (well under 16s)" "$(( $(date +%s) - t39 < 14 ))" 1
expect_grep "the end line is still written" "end state=cancelled" "$d39/run.log"
fi

if [ -z "${DISPATCH_TEST_CASES:-}" ] || [[ ",$DISPATCH_TEST_CASES," == *,queue,* ]]; then
# The agent lock is taken in queue order (task_queue_ops.py head <agent>); see the runner's
# "locks" section. Every case holds the lock with a first task so the others queue.
hold_lock() {  # <agent> <marker>: hold <agent>.lock until $FAKE_DIR/<marker>.release exists
  flock -n "$AGENT_DISPATCH_LOCKDIR/$1.lock" bash -c 'touch "$FAKE_DIR/$1.held"; while [ ! -e "$FAKE_DIR/$1.release" ]; do sleep 0.2; done' _ "$2" &
  for _ in $(seq 50); do [ -e "$FAKE_DIR/$2.held" ] && break; sleep 0.2; done
}
queued() {  # <task dir>: wait until the runner has registered it as waiting for the lock
  for _ in $(seq 30); do [ "$(field "$1" WAITING 2>/dev/null)" = lock ] && break; sleep 1; done
}
held_at() { grep -m1 ' lock held$' "$1/run.log" | cut -c1-19; }

echo; echo "=== [30] a higher-priority task goes first; the waiter it passes logs who went before it ($(date +%T))"
reset_fake claude slow-ok; echo 2 >"$FAKE_DIR/claude.slow"
hold_lock claude h30
d30a=$(mk prio-first-in claude 900 300); d30b=$(mk prio-bumped claude 900 300)
bash "$R" "$d30a" & p30a=$!; queued "$d30a"; sleep 1
bash "$R" "$d30b" & p30b=$!; queued "$d30b"
expect "QUEUED_AT is published and ordered" "$(( $(field "$d30a" QUEUED_AT) < $(field "$d30b" QUEUED_AT) ))" 1
expect "the queue says first-in goes first" "$(python3 "$AGENT_DISPATCH_OPS" head claude)" prio-first-in
echo "PRIORITY=1" >"$d30b/override.env"
expect "after the bump the queue says bumped goes first" "$(python3 "$AGENT_DISPATCH_OPS" head claude)" prio-bumped
sleep 2; touch "$FAKE_DIR/h30.release"
e30a=0; e30b=0; wait "$p30a" || e30a=$?; wait "$p30b" || e30b=$?
expect "both finish" "$e30a/$e30b" 0/0
expect "the bumped task took the lock first" "$([[ "$(held_at "$d30b")" < "$(held_at "$d30a")" ]] && echo yes)" yes
expect_grep "the passed task logs who went before it" "queue: prio-bumped goes before this task" "$d30a/run.log"
expect "no queue entry is left behind" "$(ls "$AGENT_DISPATCH_LOCKDIR/.queue/claude" | wc -l)" 0

echo; echo "=== [31] patrol goes last, whatever its priority says, even without the ops entry ($(date +%T))"
for ops in "$AGENT_DISPATCH_OPS" /nonexistent/task_queue_ops.py; do
  reset_fake claude slow-ok; echo 2 >"$FAKE_DIR/claude.slow"
  hold_lock claude h31
  tag=$([ -r "$ops" ] && echo ops || echo no-ops)
  d31p=$(mk "patrol-test-$tag" claude 900 300); echo "PRIORITY=99" >"$d31p/override.env"
  d31m=$(mk "manual-late-$tag" claude 900 300)
  AGENT_DISPATCH_OPS=$ops bash "$R" "$d31p" & p31p=$!; queued "$d31p"; sleep 1
  AGENT_DISPATCH_OPS=$ops bash "$R" "$d31m" & p31m=$!; queued "$d31m"
  touch "$FAKE_DIR/h31.release"
  e31p=0; e31m=0; wait "$p31p" || e31p=$?; wait "$p31m" || e31m=$?
  expect "[$tag] both finish" "$e31p/$e31m" 0/0
  expect "[$tag] the manual task queued later took the lock first" "$([[ "$(held_at "$d31m")" < "$(held_at "$d31p")" ]] && echo yes)" yes
done
expect_grep "the round says why it waits" "queue: a manual claude task is waiting; patrol goes last" "$d31p/run.log"

echo; echo "=== [32] a task past the fair wait cannot be overtaken by a bumped one ($(date +%T))"
reset_fake claude slow-ok; echo 2 >"$FAKE_DIR/claude.slow"
hold_lock claude h32
d32a=$(mk fair-old claude 900 300); d32b=$(mk fair-bumped claude 900 300)
AGENT_DISPATCH_FAIR_WAIT_SEC=4 bash "$R" "$d32a" & p32a=$!; queued "$d32a"
echo "PRIORITY=9" >"$d32b/override.env"
AGENT_DISPATCH_FAIR_WAIT_SEC=4 bash "$R" "$d32b" & p32b=$!; queued "$d32b"
sleep 5
expect "the old task is protected now" "$(AGENT_DISPATCH_FAIR_WAIT_SEC=4 python3 "$AGENT_DISPATCH_OPS" head claude)" fair-old
touch "$FAKE_DIR/h32.release"
e32a=0; e32b=0; wait "$p32a" || e32a=$?; wait "$p32b" || e32b=$?
expect "the protected task went first" "$e32a/$e32b/$([[ "$(held_at "$d32a")" < "$(held_at "$d32b")" ]] && echo yes)" 0/0/yes

echo; echo "=== [33] a quota wait releases the agent lock, keeps the session lock; the next task waits without an attempt ($(date +%T))"
# Q hits codex's quota (reset in 14s); W is queued behind Q. During Q's wait the agent lock is
# free and the session lock is not; W takes the lock, sees Q's quota hint and waits for the same
# reset without calling codex. After the reset Q (queued first) resumes its session, then W runs.
reset_fake codex quota-then-ok
dq=$(mk quota-sleeper codex 900 300); dw=$(mk quota-next codex 900 300)
export FAKE_CODEX_SID_PER_TASK=1
FAKE_RESET_SEC=14 QUOTA_WAKE_PAD_SEC=1 bash "$R" "$dq" & pq=$!
for _ in $(seq 30); do grep -q 'attempt 1/' "$dq/run.log" 2>/dev/null && break; sleep 0.5; done
QUOTA_WAKE_PAD_SEC=1 bash "$R" "$dw" & pw=$!
for _ in $(seq 30); do grep -q 'released the codex lock' "$dq/run.log" 2>/dev/null && break; sleep 0.5; done
sq=$(field "$dq" SESSION)
expect "the sleeper publishes its wait" "$(field "$dq" WAITING)/$([ -n "$(field "$dq" WAKE_AT)" ] && echo wake)" quota/wake
for _ in $(seq 20); do [ "$(field "$dw" WAITING 2>/dev/null)" = quota ] && break; sleep 0.5; done
expect "the next task waits on the same reset (2 polls later), without an attempt" "$(field "$dw" WAITING)/$(field "$dw" ATTEMPTS)/$(( $(field "$dw" WAKE_AT) - $(field "$dq" WAKE_AT) ))" quota/0/2
expect "flock -n gets codex.lock during the wait" "$(flock -n "$AGENT_DISPATCH_LOCKDIR/codex.lock" true && echo free || echo held)" free
expect "the sleeper's session lock stays held" "$(flock -n "$AGENT_DISPATCH_LOCKDIR/session-$sq.lock" true && echo free || echo held)" held
e33q=0; e33w=0; wait "$pq" || e33q=$?; wait "$pw" || e33w=$?
unset FAKE_CODEX_SID_PER_TASK
expect "both finish ok" "$e33q/$(field "$dq" STATE)/$e33w/$(field "$dw" STATE)" 0/ok/0/ok
expect "codex was called three times: quota, the resume, the next task" "$(cat "$FAKE_DIR/codex.calls")" 3
expect "call 2 is the sleeper resuming its own session" "$(grep -c "call 2 argv: \[exec\] \[resume\].*\[$sq\]" "$FAKE_DIR/codex.argv")" 1
expect "the next task spent one attempt, not two" "$(field "$dw" ATTEMPTS)" 1
expect "the sleeper kept its QUEUED_AT across the wait" "$(( $(field "$dq" QUEUED_AT) < $(field "$dw" QUEUED_AT) ))" 1
expect_grep "the next task says whose quota it waits for" "quota: codex is out of quota (quota-sleeper hit it)" "$dw/run.log"
[ "$fail" = 0 ] || tail -n 25 "$dq/run.log" "$dw/run.log" "$FAKE_DIR/codex.argv" | cut -c1-160
expect "the successful attempt cleared the hint" "$([ -e "$AGENT_DISPATCH_LOCKDIR/.queue/codex.quota" ] && echo left || echo gone)" gone

echo; echo "=== [34] override: a queued task starts on the new model/effort; a retry switches mid-task ($(date +%T))"
reset_fake claude slow-ok; echo 1 >"$FAKE_DIR/claude.slow"
hold_lock claude h34
d34=$(mk override-queued claude 900 300)
bash "$R" "$d34" & p34=$!; queued "$d34"
printf 'MODEL=claude-other\nEFFORT=max\n' >"$d34/override.env"
touch "$FAKE_DIR/h34.release"
e34=0; wait "$p34" || e34=$?
expect "queued override: exit/model/effort used" "$e34/$(field "$d34" MODEL_USED)/$(field "$d34" EFFORT_USED)" 0/claude-other/max
expect "claude was called with them" "$(grep -c 'call 1 argv:.*\[--model\] \[claude-other\] \[--effort\] \[max\]' "$FAKE_DIR/claude.argv")" 1
reset_fake opencode error-then-ok
d34b=$(mk override-retry opencode 900 300)
echo "FALLBACK_MODELS=good-a,good-b" >>"$d34b/meta.env"
RETRY_WAIT=6 FALLBACK_WAIT=6 bash "$R" "$d34b" & p34b=$!
for _ in $(seq 30); do [ "$(field "$d34b" WAITING 2>/dev/null)" = retry ] && break; sleep 0.5; done
echo "MODEL=good-b" >"$d34b/override.env"
e34b=0; wait "$p34b" || e34b=$?
expect "the retry after the override ran on it" "$e34b/$(field "$d34b" ATTEMPTS)/$(field "$d34b" MODEL_USED)" 0/2/good-b
expect_grep "call 2 used the override, not the pool's next model" "call 2 model: good-b" "$FAKE_DIR/opencode.argv"
expect_grep "the switch is logged" "override: model good-b; the next attempt uses good-b" "$d34b/run.log"
fi
if [ -z "${DISPATCH_TEST_CASES:-}" ] || [[ ",$DISPATCH_TEST_CASES," == *,budget,* ]]; then
# Runner api 3: budgets from override.env (task_queue_ops.py deadline/attempts/resumes) and the
# usage fields. hold_lock/queued are the queue group's helpers, repeated so this group runs alone.
hold_lock() {
  flock -n "$AGENT_DISPATCH_LOCKDIR/$1.lock" bash -c 'touch "$FAKE_DIR/$1.held"; while [ ! -e "$FAKE_DIR/$1.release" ]; do sleep 0.2; done' _ "$2" &
  for _ in $(seq 50); do [ -e "$FAKE_DIR/$2.held" ] && break; sleep 0.2; done
}
queued() { for _ in $(seq 30); do [ "$(field "$1" WAITING 2>/dev/null)" = lock ] && break; sleep 1; done; }

echo; echo "=== [41] a queued task takes new budgets from override.env within a poll, keeps its place, no restart ($(date +%T))"
reset_fake claude usage-ok
hold_lock claude h41
d41=$(mk budget-queued claude 300 300)
bash "$R" "$d41" & p41=$!; queued "$d41"
q41=$(field "$d41" QUEUED_AT); new41=$(( $(date +%s) + 1200 ))
printf 'DEADLINE_EPOCH=%s\nMAX_ATTEMPTS=1\nQUOTA_RESUMES=0\n' "$new41" >"$d41/override.env"
for _ in $(seq 20); do [ "$(field "$d41" DEADLINE_EPOCH)" = "$new41" ] && break; sleep 0.5; done
expect "published while still queued: deadline/attempts/resumes/waiting" \
  "$(field "$d41" DEADLINE_EPOCH)/$(field "$d41" MAX_ATTEMPTS)/$(field "$d41" QUOTA_RESUMES)/$(field "$d41" WAITING)" "$new41/1/0/lock"
touch "$FAKE_DIR/h41.release"
e41=0; wait "$p41" || e41=$?
expect "it ran and finished" "$e41/$(field "$d41" STATE)/$(field "$d41" RUNNER_API)" 0/ok/3
[ "$(field "$d41" STATE)" = ok ] || tail -n 20 "$d41/run.log"
expect "QUEUED_AT kept (no restart)" "$(field "$d41" QUEUED_AT)" "$q41"
expect "one runner start in the log" "$(grep -c ' budget-queued start ====' "$d41/run.log")" 1
expect_grep "the change is logged" "budget: deadline now" "$d41/run.log"
expect "usage in result.env, each API message once" \
  "$(field "$d41" TOKENS_IN)/$(field "$d41" TOKENS_CACHE_W)/$(field "$d41" TOKENS_CACHE_R)/$(field "$d41" TOKENS_OUT)/$(field "$d41" TOKENS_TOTAL)/$(field "$d41" COST_USD)" \
  10/1000/100000/500/101510/0.04

echo; echo "=== [42] a deadline moved past the original one is honoured: the outer timer sits at the 72h ceiling ($(date +%T))"
reset_fake claude hang
hold_lock claude h42
d42=$(mk budget-extended claude 115 3600)
t42=$(date +%s)
bash "$R" "$d42" & p42=$!; queued "$d42"
printf 'DEADLINE_EPOCH=%s\n' "$(( t42 + 215 ))" >"$d42/override.env"
sleep 2; touch "$FAKE_DIR/h42.release"
e42=0; wait "$p42" || e42=$?
el42=$(( $(date +%s) - t42 ))
expect "the attempt ran into the moved deadline, not the dispatched one" \
  "$(field "$d42" STATE)/$(field "$d42" RC)/$(( el42 > 115 ))/$(( el42 < 215 ))" timeout/124/1/1
expect "no cancelled state from an outer timer" "$(grep -c 'state=cancelled' "$d42/run.log")" 0

echo; echo "=== [43] a lowered retry budget stops retries at the next decision ($(date +%T))"
reset_fake opencode error-then-ok
d43=$(mk budget-attempts opencode 900 300)
echo "MAX_ATTEMPTS=1" >"$d43/override.env"
e43=0; RETRY_WAIT=6 bash "$R" "$d43" || e43=$?
expect "one attempt, then failed instead of a retry" "$e43/$(field "$d43" ATTEMPTS)/$(field "$d43" MAX_ATTEMPTS)/$(field "$d43" STATE)" 1/1/1/failed
fi

echo
if [ "$fail" = 0 ]; then echo "=== PASS $(date +%T)"; else echo "=== FAILED $(date +%T)"; exit 1; fi
