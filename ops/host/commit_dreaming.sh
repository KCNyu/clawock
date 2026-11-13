#!/usr/bin/env bash
# commit_dreaming.sh — 兜底提交 openclaw "Memory Dreaming Promotion" 的产物。
#
# 背景 (2026-05-30): dreaming 是 openclaw core 内置 cron (03:00 HKT, delivery=none),
# 把短期记忆促进追加进顶层 MEMORY.md / DREAMS.md,但 **core 不自动 commit**;而 harness
# 各 postflight 的 `git add memory/` 又不含仓库根的 MEMORY.md/DREAMS.md → 促进内容长期脏在
# 工作区,直到某次手动 `git add -A` 才被捎带,且会害得别的 push 撞脏工作区 rebase。
# 本脚本由 system crontab 在 dreaming 之后 (03:20) 跑,只提交这两个文件。
#
# 2026-08-26 (#1074): #1072 把 MEMORY.md/DREAMS.md 当成 coding agent 的笔记一起
# 去追踪了,本脚本连同它那行 crontab 一起被退役。#1074 把两个根文件放回仓库,这个
# 脚本就必须一起回来 —— 否则 2026-05-30 那个坑原样复现:dreaming 每天追加、没人
# commit、工作区长期脏,然后把**别人的** safe_push 一起绊倒。文件回仓库和本脚本
# 回 crontab 是同一件事的两半,不能只做一半。
#
# 2026-11-08 (#3314 之后): MEMORY.md 已是 shared store 里 `publish: public` topic 的
# 生成物。本脚本不再让审阅闸直接改 MEMORY.md,而是由 promote_dreaming.py 复用
# review_dreaming.py 的 hash 绑定审阅,把通过审阅的候选写成 store 新 topic,再调用
# publish.py --write 重生成 MEMORY.md + manifest。失败时 promote_dreaming.py 恢复
# 上一版投影;store 里已写成的 topic 留给下一次重试,不静默丢候选。
#
# 鲁棒性: MEMORY 与 DREAMS 的审阅/提交互不拖死;只 stage 自己这两个半边的文件
# (不碰宿主其它在写的脏文件);push 被拒时用 rebase.autoStash 自动绕开"工作区脏 →
# pull --rebase 拒跑"的坑;真冲突则留本地不死循环。
# -e: an unguarded failed `git add` used to fall through to
# `git diff --cached --quiet` == true and print 「无变化,跳过」 — a transient
# index.lock collision with the publisher (dream fires 03:20, publisher every
# 20min in the same worktree) silently dropped that night's promotion.
set -uo pipefail

WS="${DREAMING_WORKSPACE:-/root/.openclaw/workspace}"
STORE="${SHARED_MEMORY_DIR:-$HOME/.shared-memory}"
cd "$WS" || exit 1

# Automated job → commit as the bot, but with `git -c` (per-invocation) NOT
# `git config` (persistent): writing local config here would pollute the identity
# that interactive Claude-Code sessions commit under (kcn wants those = KCNyu).
BOT_NAME="github-actions[bot]"
BOT_EMAIL="41898282+github-actions[bot]@users.noreply.github.com"

# The promotion is written on behalf of the OpenClaw assistant; keep store history
# attribution truthful when the cron has no agent marker in its environment.
export MEMCTL_AGENT="${MEMCTL_AGENT:-rick}"

# Review the two public files independently. A bad MEMORY candidate must not
# block the DREAMS commit (and vice versa); the failed file stays uncommitted and
# visible, never published. Raw candidates stay private.
MEMORY_OK=1
DREAMS_OK=1
if ! python3 "$WS/ops/host/review_dreams.py" --workspace "$WS" --store "$STORE"; then
  echo "$(date -Is) dreaming-commit: DREAMS review failed; DREAMS.md left uncommitted"
  DREAMS_OK=0
fi
if [ "$DREAMS_OK" = 1 ] && ! python3 "$WS/ops/host/review_dreams.py" --workspace "$WS" --store "$STORE" --check; then
  echo "$(date -Is) dreaming-commit: DREAMS check failed; DREAMS.md left uncommitted"
  DREAMS_OK=0
fi

# Dispatch/task intake: a model distils the queued kcn words and task outcomes.
# Fail-soft: an unreachable model leaves the raw items private for the next run.
MEMORY_KIT="${SHARED_MEMORY_SKILL_DIR:-$HOME/.agents/skills/shared-memory}"
if [ -r "$MEMORY_KIT/scripts/intake.py" ]; then
  # Direct chat is a source even when the dreaming score ranked nothing: queue the
  # user lines from yesterday's and today's private corpus, then distil everything.
  for day in "$(date -d yesterday +%F)" "$(date +%F)"; do
    timeout 60 python3 "$MEMORY_KIT/scripts/intake.py" capture-chat \
      --date "$day" --workspace "$WS" >/dev/null 2>&1 || true
  done
  if ! timeout 600 python3 "$MEMORY_KIT/scripts/intake.py" --store "$STORE" \
      --repo "$WS" run --limit 20; then
    echo "$(date -Is) dreaming-commit: memory intake failed; raw items stay queued"
  fi
fi

# The missing reviewer: the deterministic gate only approves an exact hash-bound
# receipt. This model writes one for clean candidates; failures leave them pending.
if ! timeout 600 python3 "$WS/ops/host/review_dreaming_llm.py" --workspace "$WS" --store "$STORE"; then
  echo "$(date -Is) dreaming-commit: model review failed; candidates stay pending"
fi

# MEMORY: reviewed candidates -> public store topics -> regenerated MEMORY.md.
# promote_dreaming.py snapshots the store, writes only approved candidates, runs
# verify/doctor, and restores the previous projection if generation fails.
if ! python3 "$WS/ops/host/promote_dreaming.py" --workspace "$WS" --store "$STORE"; then
  echo "$(date -Is) dreaming-commit: MEMORY promotion failed at the step above; MEMORY.md left at its previous version"
  MEMORY_OK=0
fi
if [ "$MEMORY_OK" = 1 ] && ! python3 "$WS/ops/host/review_dreaming.py" --workspace "$WS" --check; then
  echo "$(date -Is) dreaming-commit: MEMORY check failed; MEMORY.md left uncommitted"
  MEMORY_OK=0
fi

COMMITTED=0
commit_paths() {  # <label> <path...>; commit only these paths, never the rest of the index
  local label="$1"
  shift
  local files=()
  local path
  for path in "$@"; do
    [ -e "$path" ] && files+=("$path")
  done
  if [ "${#files[@]}" -eq 0 ]; then
    echo "$(date -Is) dreaming-commit: $label: no file present"
    return 0
  fi
  git add -- "${files[@]}" \
    || { echo "$(date -Is) dreaming-commit: $label: git add 失败(疑似 index.lock 撞车)"; return 1; }
  if git diff --cached --quiet -- "${files[@]}"; then
    echo "$(date -Is) dreaming-commit: $label: 已审阅文件无变化,跳过"
    return 0
  fi
  if ! git -c user.name="$BOT_NAME" -c user.email="$BOT_EMAIL" \
      commit -q -m "memory: dreaming $label $(TZ=Asia/Hong_Kong date +%Y-%m-%d)" -- "${files[@]}"; then
    echo "$(date -Is) dreaming-commit: $label: commit 失败"
    return 1
  fi
  echo "$(date -Is) dreaming-commit: $label 已提交 $(git rev-parse --short HEAD)"
  COMMITTED=1
  return 0
}

if [ "$MEMORY_OK" = 1 ]; then
  commit_paths "promotion" MEMORY.md ops/host/shared-memory/publish-manifest.json \
    || MEMORY_OK=0
fi
if [ "$DREAMS_OK" = 1 ]; then
  commit_paths "diary" DREAMS.md || DREAMS_OK=0
fi

if [ "$COMMITTED" = 0 ]; then
  if [ "$MEMORY_OK" = 1 ] && [ "$DREAMS_OK" = 1 ]; then
    echo "$(date -Is) dreaming-commit: 已审阅文件无变化,跳过"
    exit 0
  fi
  echo "$(date -Is) dreaming-commit: no reviewed file to commit (MEMORY_OK=$MEMORY_OK DREAMS_OK=$DREAMS_OK)" >&2
  exit 1
fi

# 走统一的 safe_push.sh(已带 rebase.autoStash,自己绕开宿主脏工作区);真冲突它 exit 2 留本地。
if ! bash "$WS/ops/publish/safe_push.sh"; then
  echo "$(date -Is) dreaming-commit: push failed; committed change stays local for the next retry" >&2
  exit 1
fi

if [ "$MEMORY_OK" = 0 ] || [ "$DREAMS_OK" = 0 ]; then
  echo "$(date -Is) dreaming-commit: one side failed; the other side was committed and pushed (MEMORY_OK=$MEMORY_OK DREAMS_OK=$DREAMS_OK)" >&2
fi
exit 0
