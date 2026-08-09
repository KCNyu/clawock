#!/usr/bin/env bash
# gold_dca_refresh.sh — 黄金定投(000217 华安黄金ETF联接C)每日净值刷新 + 上线。
#
# 背景: 黄金是场外基金,一天一个净值(约 22:00–23:00 HKT 出),跟美股/港股盘中节奏不同,
# 故单独一档 system crontab。纯数据、无 LLM、无 key —— installed gold command 拉净值重算定投
# 指标写回 portfolio.json['gold_dca'],再 build_dashboard 刷 dashboard.json,最后 safe_push 上线。
# 排在 23:50 HKT(净值已 final),仅工作日(A 股交易日才出新净值;节假日跑也只是重写同值,无害)。
# ⚠️ 不可排 :00/:30 — 美股盘中盯盘 cron(*/30 22-23)同分钟开跑会 load-modify-write 覆盖
# 本脚本刚写入的 gold 字段(2026-06-10 23:30 撞车,gold 数据被回退一天,06-11 复盘后挪到 23:50)。
#
# 真值字段 principal_invested / units_held 由 kcn 对账后手填,本脚本绝不改。
set -uo pipefail

WS=/root/.openclaw/workspace
cd "$WS" || exit 1

clawock-kcnyu-gold-fetch                     || { echo "$(date -Is) gold fetch 失败"; exit 1; }
# 重建本机副本,但不再入库:四个产物已随 #314 迁到 data-plane 分支,
# 由定时 publisher 发布(最多落后 20 分钟)。这里再 `git add` 它们会因为
# .gitignore 直接失败,而不是静默跳过。
clawock dashboard-build                      || { echo "$(date -Is) gold dashboard-build 失败"; exit 1; }

# 自动任务 → 用 bot 身份提交,但走 `git -c`(单次注入)而非 `git config`(持久),
# 否则会污染交互 Claude-Code 会话的提交身份(kcn 要那些 = KCNyu)。
BOT_NAME="github-actions[bot]"
BOT_EMAIL="41898282+github-actions[bot]@users.noreply.github.com"

git add portfolio.json
if git diff --cached --quiet; then
  echo "$(date -Is) gold-refresh: 净值无变化,跳过"
  exit 0
fi

git -c user.name="$BOT_NAME" -c user.email="$BOT_EMAIL" \
  commit -q -m "gold: 黄金定投净值刷新 $(TZ=Asia/Hong_Kong date +%Y-%m-%d)" || { echo "$(date -Is) commit 失败"; exit 1; }
echo "$(date -Is) gold-refresh: 已提交 $(git rev-parse --short HEAD)"

exec bash "$WS/ops/publish/safe_push.sh"
