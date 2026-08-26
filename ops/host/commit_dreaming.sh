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
# 鲁棒性: 只 stage MEMORY.md/DREAMS.md (不碰宿主其它在写的脏文件);push 被拒时用
# rebase.autoStash 自动绕开"工作区脏 → pull --rebase 拒跑"的坑;真冲突则留本地不死循环。
# -e: an unguarded failed `git add` used to fall through to
# `git diff --cached --quiet` == true and print 「无变化,跳过」 — a transient
# index.lock collision with the publisher (dream fires 03:20, publisher every
# 20min in the same worktree) silently dropped that night's promotion.
set -euo pipefail

WS=/root/.openclaw/workspace
cd "$WS" || exit 1

# Automated job → commit as the bot, but with `git -c` (per-invocation) NOT
# `git config` (persistent): writing local config here would pollute the identity
# that interactive Claude-Code sessions commit under (kcn wants those = KCNyu).
BOT_NAME="github-actions[bot]"
BOT_EMAIL="41898282+github-actions[bot]@users.noreply.github.com"

git add MEMORY.md DREAMS.md \
  || { echo "$(date -Is) dreaming-commit: git add 失败(疑似 index.lock 撞车)"; exit 1; }
if git diff --cached --quiet; then
  echo "$(date -Is) dreaming-commit: MEMORY/DREAMS 无变化,跳过"
  exit 0
fi

git -c user.name="$BOT_NAME" -c user.email="$BOT_EMAIL" \
  commit -q -m "memory: dreaming 促进自动提交 $(TZ=Asia/Hong_Kong date +%Y-%m-%d)" || { echo "$(date -Is) commit 失败"; exit 1; }
echo "$(date -Is) dreaming-commit: 已提交 $(git rev-parse --short HEAD)"

# 走统一的 safe_push.sh(已带 rebase.autoStash,自己绕开宿主脏工作区);真冲突它 exit 2 留本地。
exec bash "$WS/ops/publish/safe_push.sh"
