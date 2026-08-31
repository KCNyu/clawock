#!/usr/bin/env bash
# claude_6am_kicker.sh — 工作日 06:01 HKT 启动 Claude Code 处理 P1/P2 队列
#
# 背景 (2026-08-31): kcn 凌晨需要补觉,Claude Pro 5h 滚动额度深夜烧光,06:01
# HKT 距上次使用已超 5h → 配额窗口已回血。kcn 希望 6:01 自动把 claude 拉起来
# 跑 github.com/KCNyu/clawock 的 open P1/P2 队列,不要替用户做策略判断。
#
# 设计契约 (与 AGENTS.md 一致):
#   - 纯 issue/PR 处理,不动 portfolio.json/dashboard/memory/ 等 runtime 文件
#   - 代码改动走 worktree → claude/<task> 分支 → PR,不直推 master
#   - 任务说明书独立成 task file,本脚本只负责启动 + 日志 + 锁
#   - 用 flock 防止 6:01 还没死透时 8:00 brief 共用冲突
#   - 失败/超时/claude 崩了不重试:下一工作日 6:01 再说
#
# 用法 (system crontab):
#   1 6 * * 1-5 /root/.openclaw/workspace/ops/host/claude_6am_kicker.sh
#
# 维护:
#   - 任务说明: /root/.openclaw/workspace/ops/host/claude_6am_task.md
#   - 日志:      /root/.openclaw/logs/claude-6am-YYYYMMDD.log
#   - 锁:        /tmp/claude-6am.lock

set -uo pipefail

# Every path is a default, not a dependency: $LIVE_CHECKOUT is the same
# override `ops/host/refresh_live.sh` takes, and the task file and log dir
# follow it, so this runs against any checkout on any host that has a claude
# binary on PATH.
WORKDIR="${LIVE_CHECKOUT:-/root/.openclaw/workspace}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo /root/.nvm/versions/node/v22.23.1/bin/claude)}"
TASK_FILE="${TASK_FILE:-$WORKDIR/ops/host/claude_6am_task.md}"
LOG_DIR="${LOG_DIR:-$WORKDIR/../logs}"
LOCK_FILE="${LOCK_FILE:-/tmp/claude-6am.lock}"

# --- sanity checks ---------------------------------------------------------
if [ ! -x "$CLAUDE_BIN" ]; then
  echo "[$(date -Iseconds)] FATAL: $CLAUDE_BIN 不存在或不可执行" >> "$LOCK_FILE.log"
  exit 1
fi
if [ ! -f "$TASK_FILE" ]; then
  echo "[$(date -Iseconds)] FATAL: $TASK_FILE 丢失" >> "$LOCK_FILE.log"
  exit 1
fi
mkdir -p "$LOG_DIR"

# --- acquire lock (non-blocking) -------------------------------------------
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -Iseconds)] SKIP: claude 6am 已在跑 (lock held)" >> "$LOG_DIR/claude-6am.lock.log"
  exit 0
fi

LOG_FILE="$LOG_DIR/claude-6am-$(date +%Y%m%d).log"
echo "=== claude_6am_kicker fired $(date -Iseconds) ===" >> "$LOG_FILE"
echo "task_file=$TASK_FILE" >> "$LOG_FILE"
echo "claude_version=$($CLAUDE_BIN --version 2>&1 | head -1)" >> "$LOG_FILE"

# --- 启动 claude -----------------------------------------------------------
cd "$WORKDIR" || exit 1

# bypassPermissions 已经在 /root/.claude/settings.json 里设了 defaultMode,
# 这里再显式 --dangerously-skip-permissions 是双保险 (cron 没有 TTY 走 prompt 会卡住)。
#
# 喂 prompt 三种写法比较 (2026-08-31 kcn 提醒):
#   1. -p "..."                    ←  必加双引号, 换行仍会保留 (bash "$(...)" 不压扁)
#   2. -p "$(cat file)"            ←  当前写法; 多行 OK, 但 $ ` \ 等需转义
#   3. cat file | claude -p        ←  stdin, 多行 + 任意字符全保, 最稳
# 选 (3) 最稳: 任务说明含中文标点 + 反引号 + $变量示例, pipe 0 风险。
"$CLAUDE_BIN" --dangerously-skip-permissions -p < "$TASK_FILE" \
  >> "$LOG_FILE" 2>&1

EXIT=$?
echo "=== claude_6am_kicker exit=$EXIT $(date -Iseconds) ===" >> "$LOG_FILE"

# 释放锁 (exec fd 自动 close,但显式删文件方便下次排查)
rm -f "$LOCK_FILE"
exit "$EXIT"
