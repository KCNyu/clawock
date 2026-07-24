---
layout: default
title: clawock · scripts 详细参考
---

# 脚本详细参考（TOOLS_SCRIPTS.md）

> 从 TOOLS.md 外移（TOOLS.md 受 openclaw 16K bootstrap 注入上限约束）。
> 每个脚本/cron 的**完整说明**在此；TOOLS.md 只留精简索引 + 路由。需要细节时读这里。

## 现有脚本梳理

### 核心（当前在用）
- **`scripts/data/fetch_us_stocks.py`**：美股多 provider 抓取（7 路 fallback），自动写回 portfolio.json；prev_close 由 Polygon `/prev` 独立获取（带日期戳）
- **`scripts/data/analyze_us_stocks.py`**：美股完整分析 = 刷价格 + RSI-14/MA20/50 + Finnhub 新闻 + 信号
- **`scripts/data/fetch_us_filings.py`**：SEC EDGAR 对接 — 10-K/10-Q/8-K filings、XBRL 财务概念、Form 4 insider、13F-HR；无需 API key；Mode 3 fundamental 深挖时用。完整用法（2026-06-10 自 TOOLS.md 移入控 16K）：

| 数据 | 用法 |
|---|---|
| 最近 filings (10-K/10-Q/8-K) | `fetch_us_filings.py RKLB` （`--filings 10-K,10-Q` 指定表型） |
| XBRL 关键财务概念（营收/净利/现金/EPS 等 13 项）| `--financials` |
| Insider Form 4 / 13F-HR | `--form4` / `--13f` |
| 机器可读 | 任一模式加 `--json` |

  注意：速率限制 10 req/sec（脚本默认 8/sec）超量 403；`SEC_USER_AGENT` 可放 `.api_keys`；ticker→CIK 本地缓存 7 天；非美股票返回 "CIK not found"
- **`scripts/data/fetch_fx.py`**：USDHKD 汇率（Frankfurter → exchangerate.host → Yahoo HKD=X 三路 fallback）；4h 本地缓存；`--convert AMT FROM TO` 直接换算。**HK + US 算 book total 必须先调它**
- **`scripts/data/analyze_hk_stocks.py`**：港股完整分析 = Tencent + Eastmoney HK 双源对账 → stooq → yfinance 兜底 + 恒指/恒科 + Finnhub 新闻 + 信号；c/pc 偏差 > 1% 写入 `_divergence`
- `check_portfolio.sh`：快速查看持仓

### Cron harness 脚本（preflight + postflight 三明治）

所有 stock cron 都用同一套"preflight (确定性) → LLM (创造性) → postflight (校验)"模式。
确定性活强制脚本化执行；LLM 只做合成；postflight 自验证 + commit。

**Daily deep brief**（08:00 HKT cron）
- **`scripts/harness/brief_preflight.py`**：刷 US/HK 价 + FX + portfolio snapshot + HHI 算法 + SEC EDGAR (仅 `is_leveraged_etf=false`) + retrospective vs 上次 plan.json。输出 `memory/.tmp/brief-context-{date}.json`
- **`scripts/harness/brief_postflight.py`**：校验 `memory/{date}-pre-open.md` + `memory/{date}-plan.json`（段标记 / plan schema / HHI / FX / HKD+USD bug pattern）；pass/warn 自动 commit

**Mode 6 briefing**（HK 开/午/午后/收盘 + US 开/收盘 — 6 个 cron 共享）
- **`scripts/harness/report_preflight.py --market {hk|us} --phase {open|mid|pm|close}`**：跑 analyze_*.py + 抽信号 (WATCH/STOP/TRIM 计数) + 异动 (≥3% 涨跌) + 指数方向；输出 `memory/.tmp/report-context-{market}-{phase}-{date}.json`（`{date}` = 跑批当天），含 `raw_wechat_block`（LLM verbatim 用）+ `title` + `needs_risk_section`。**末行打印 `context_path: <绝对路径>`——读 context 一律照抄这行，别拼文件名**；同时清掉该 market+phase 其它日期的残留 context
- **`scripts/harness/report_postflight.py --market {hk|us} --phase {phase}`**：校验三段标记 / 原始数据块 verbatim / 异动票必须被提及 / 长度 / 敷衍词；pass/warn 自动刷新 snapshot/dashboard、scoped commit + push，并主发 WeChat + 镜像 Telegram。
- **`scripts/harness/report_watchdog.py --market {hk|us} --phase {phase} --job-name "{cron名}"`**：系统 crontab 的 LLM-free Telegram-only backstop。覆盖 HK 4 班 + US 开/收 2 班；读取 postflight delivery marker，只有 Telegram 未确认时才补投，绝不重发 WeChat。

**Mode 7 intraday**（HK + US 盘中盯盘 — 3 个 cron job 共享同一套脚本；季节化 slot 数和精确时间只看生成调度表，隔夜始终最晚 02:30 HKT）
- **`scripts/harness/intraday_preflight.py --market {hk|us}`**：跑 analyze_*.py + 异动检测 + `should_alert` 决策；输出 `memory/.tmp/intraday-context-{market}-latest.json`
- **`scripts/harness/intraday_postflight.py --market {hk|us} --text-file memory/.tmp/intraday-report-{hk|us}.md`**（**先写文件再调用，禁 heredoc/`<<<`**；空输入/超 20 分钟的旧文件判 `status: input_error` 并拒投）：校验 ▎我的看法 / 长度 / should_alert 触发时报告必须提异动票；不提交 `portfolio.json`，dashboard 仅在语义变化时 commit + push；无论有无 dashboard diff 都更新本地 slot heartbeat，交 single publisher 发布。

**共通设计点**：
- preflight 输出 `raw_wechat_block` 字段，LLM **必须 verbatim 拷贝**（不改时间戳/数字），postflight 用首行匹配验证
- preflight 输出 `anomalies` 字段，LLM 必须在报告里至少提一个 anomaly 票
- postflight 输出 `wechat_prefix`（pass=空串，warn=黄 banner，fail=红 banner），LLM 拼到 WeChat 输出前
- 所有 context.json 都放 `memory/.tmp/`（gitignore 排除）

### 辅助
- **Scrapling**：自适应爬虫框架，绕过反爬（Cloudflare 等），支持 JS 渲染。`pip3 install scrapling --break-system-packages`。详见 `skills/scrapling/SKILL.md`
- **`scripts/data/build_dashboard.py`**：聚合 `portfolio.json` + snapshots + v2 plans + `memory/decisions.jsonl` + risk/peer/context sidecars → `assets/data/dashboard.json`。决策字段统一为 `decision_metrics` / `episode_backtest` / `decision_delta` / `recent_decisions`；只计**被判定触发**的 episode，date-cluster CI，并公示判不了的条数(`coverage_active`)。⚠️ **`decision_money_impact` 已于 2026-07-15 停止发布**：它把从没执行过的 call 也算进去,不是任何真实交易序列的累计金额。三类 postflight 都自动刷新；size cap 200KB。
- **`scripts/data/portfolio_risk_metrics.py`**：算 β/Vol/Max DD/Sharpe/margin_at_risk → `assets/data/risk.json`。每日 brief preflight `[10/10]` 自动跑。Yahoo v8 429 限速 → 改用 Tencent gtimg primary + Polygon/AlphaVantage fallback。alert 类型：high_beta(>3) / high_vol(>50%) / deep_dd(<-10%) / high_leverage(>2.0) / negative_sharpe(<0)
- **`scripts/data/compute_regime.py`**：杠杆刻度盘 → `assets/data/lev_regime.json`。HSTECH 200日线趋势 + 20d 波动 → HK 杠杆ETF腿上限乘子(green×1 / amber×0.5 / red×0)；US 逐名(2x单股ETF 各自 200日线，趋势off+vol>70% 才强砍)。**2026-07 新增 `regime_history`**：逐日 regime(hk←HSTECH 全历史含200DMA+近10日动量；us←benchmark.json SPY 序列，仅动量因样本<200)，供 build_dashboard 把 `vs_baseline` 按 regime 分桶。brief preflight 自动跑；tencent 空 fetch 保留旧文件。
- **`scripts/data/mark_followed.py`**：v2 execution ground-truth 工具。`--list` 列出已触发但执行未知的 decision；`mark_followed.py DECISION_ID [--no]` 写 `execution.status`。Brier 衡量建议置信度，执行率单独展示。
- **`scripts/data/fetch_catalysts.py`**：未来 14d catalysts → `assets/data/catalysts.json`（7 US holding 财报 Finnhub + 2026 FOMC 硬编码 + 经济日历 NFP/CPI 规则）。brief_preflight `[11/11]` 自动跑。`catalysts.alerts` 触发时 LLM brief 必须 ▎事件日历 段提及。
- **`scripts/data/fetch_influencer_feed.py`**：高影响力人物市场异动 → `assets/data/influencer_feed.json`。Trump 原帖(trumpstruth.org/feed RSS, 全文)+ Musk(Google News RSS 代理, X 无可靠免费 RSS)。关键词预筛 → 单次 vendor LLM(`thinking_disabled` 结构化抽取)提相关性/stance/ticker/板块 → 代码交叉匹配持仓分三档：`held_hits` / `new_ideas` / `sector_hits`。merge-not-overwrite: 源**抓取失败**才保留旧条目（被 LLM 筛掉≠失败）。`MINIMAX_API_KEY` 主、`XIAOMI_API_KEY` 可选 fallback；两者都缺才降级 keyword-only。dashboard「影响力雷达」卡 + brief `▎名人异动/政策风向` 段消费。
- **`scripts/data/xiaomi_llm.py`**：Anthropic-Messages client，供 GH Action 直调（绕过 openclaw gateway）。**Primary MiniMax M3 → optional fallback Xiaomi MiMo v2.5-pro**；M2.7 + openai-completions 已废。单轮默认 thinking enabled + max_tokens 32K；结构化抽取传 `thinking_disabled=True`。`_clean()` 统一剥内联 `<think>…</think>` + markdown fence。retry 3 + 429 handling。env `MINIMAX_API_KEY` 必需；`XIAOMI_API_KEY` 可选且失效后自动跳过；`chat(fallback=False)` 可关 Xiaomi fallback。
- **`scripts/data/gh_action_*.py`**：3 个 GH Action 入口脚本（brief_fallback / weekly_review / news_digest），都用 `xiaomi_llm.chat()` 走 MiniMax M3 主路径。
- **`scripts/data/safe_push.sh`**：共享 git push 防 conflict 死循环工具。3 次 retry + 每次 rebase 失败 → `git rebase --abort` + exit 2（不死循环 push）。所有写文件的 GH Action workflow 用 `bash scripts/data/safe_push.sh` 替代原本的 push loop；harness 端 `scripts/harness/_harness_common.push_with_rebase_retry` **直接委托本脚本**（2026-06-10 统一，自动获得 rebase.autoStash + 冲突标记硬闸），全体 committer 单一 push 路径。
- **`scripts/data/reconcile.sh`**：手工成交后的唯一收口。先把成交写进对应 `holdings[].trades[]`（`action/date/shares/price`，卖出另记 `realized_pnl`），同步 broker 真值叶子（`shares` / `cost_basis`；新仓建 holding、平仓保留历史行并置 `shares=0`；存取款写 `cash_adjustments[]`），再运行本脚本重算 aggregates / cash / realized P&L 并执行完整性闸。它只派生和校验，不会替你猜成交。

### Cron map

精确的 11-job schedule、EDT/EST 表达式、Mode/harness 和 10 条 watchdog 映射由
`config/cron-schedules.json` 单源维护，生成的人读表见 [`CRON_SCHEDULES.md`](CRON_SCHEDULES.md)。
`sync_us_cron_dst.py --apply` 每日自动对齐美股 live cron + system watchdog；
`cron_heartbeat.py` 维护 Mode 7 slot ledger，由现有 single publisher 发布。

所有 harness preflight/postflight 都在 `scripts/harness/`。Mode 6 / brief / Mode 7 的 postflight
都会重建 dashboard；Mode 7 不提交 `portfolio.json`，dashboard 只发布语义变化，但每个
受监控 slot 的 heartbeat 都会发布并由 cron health 对账。

cron payload 是真实执行面，会为隔离 session 自包含关键步骤；SKILL.md 是详细规范。改格式时
必须同时 diff payload 与对应 Mode，尤其 Step 2.5 sidecar。schedule 的 runtime 真值来自 CLI，
tracked contract 在 `config/cron-schedules.json`；schedule、payload、watchdog 或生成文档漂移
都会被 `scripts/system_check.py` / CI 拦截。

**改 cron prompt 的安全步骤**（6.1 后只走 CLI，不碰文件）：
```bash
# 读：openclaw cron list --json | python3 -c '...'   （JSON 前可能有 Config warnings 噪音，find('{') 起切）
# 写：openclaw cron edit <job-id> --message "$NEW_MSG"   （只 patch message，schedule/tz 不动）
```
改 `--cron` 表达式时必须同时带 `--tz Asia/Shanghai`（否则 tz 被重置）。升级大版本后先 `openclaw cron list` 数 job 个数（应为 11），少了跑 `openclaw doctor --fix`。

### Cron 运行历史（自动 + 手动跨 job 聚合）

`openclaw cron runs` 必须带 `--id`，且单 job 视角。跨 job + 自动调度 + 手动 trigger 一起看用：

```bash
./check_crons.sh                 # 最近 20 次（auto + manual 混排，HKT 倒序）
./check_crons.sh 50              # 最近 50 次
./check_crons.sh --status error  # 只看失败
./check_crons.sh --kind cron     # 只看自动调度
./check_crons.sh --job 港股       # 按 job 名子串过滤
./check_crons.sh --full          # 摘要不截断
./check_crons.sh --json          # JSON 输出（喂给后续 pipeline）
```

运行历史同样优先经 OpenClaw CLI 读取；旧 `cron/runs/*.jsonl` 只作为迁移前 fallback。
脚本本体 `scripts/data/cron_runs.py`。

### 已废弃（不作为调用入口，但作为参考代码可读）
> 这些脚本**不要直接调起来跑**当主路径，但里面的 URL、header、fallback 思路、解析片段在调试或场景超出现役脚本时仍有参考价值。
- `scripts/legacy/stock_analyzer.py` — 被 `scripts/data/analyze_us_stocks.py` + `analyze_hk_stocks.py` 取代；仅保留早期 fallback 顺序作参考
- **完全删掉** (2026-05-16 大扫除)：`monday_signal.py` (含硬编码 key)、`api_retry_wrapper.py`、`baidu_search_wrapper.py`、`deep_analysis.py`、`final_analysis.py`、`find_opportunities.py`、`hk_ai_monitor.py`、`multi_agent_stock_analysis.py`、`price_alert_monitor.py`、`TradingAgents/` 整目录
- **完全删掉** (2026-07-04 清理)：`scripts/legacy/{hk_monitor,hk_open_monitor,hk_stock_fetcher,portfolio_monitor,portfolio_table,portfolio_visualization}.py`（无代码/cron 引用的死参考）、`scripts/data/brief_fallback_send.py`（被 `gh_action_brief_fallback.py` 取代）

---
