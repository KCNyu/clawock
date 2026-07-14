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
- **`scripts/harness/report_preflight.py --market {hk|us} --phase {open|mid|pm|close}`**：跑 analyze_*.py + 抽信号 (WATCH/STOP/TRIM 计数) + 异动 (≥3% 涨跌) + 指数方向；输出 `memory/.tmp/report-context-{market}-{phase}-{date}.json`，含 `raw_wechat_block`（LLM verbatim 用）+ `title` + `needs_risk_section`
- **`scripts/harness/report_postflight.py --market {hk|us} --phase {phase}`**：校验三段标记 / 原始数据块 verbatim / 异动票必须被提及 / 长度 / 敷衍词；pass/warn 自动 commit portfolio.json
- **`scripts/harness/report_watchdog.py --market {hk|us} --phase close --job-name "{cron名}"`**：**LLM-free 兜底哨兵**（2026-05-29 加，见下方事件）。**系统 crontab** 跑（不是 openclaw cron），收盘报告 cron 预期完成后几分钟触发：读该 job 今日最后一条 run 的 `summary`，若不含 preflight `raw_wechat_block` 首行 ⇒ 判定 LLM stall/失败未送出 ⇒ 用 `openclaw message send` 直送 `raw_wechat_block`（带 `📨 自动补发` banner，纯数据无分析段）。发送目标从该 job 历史 `delivery.resolved` 自动解析（不硬编码账号）；`memory/.tmp/watchdog-{tag}-{date}.done` flag 防重复。**postflight 抓不到这类失败**——LLM 死在 Step 2 远早于 postflight，故必须 out-of-band。当前覆盖 HK/US 收盘（`15 16 * * 1-5` / `20 4 * * 2-6`）；扩展到开/午盘只需在系统 crontab 加同样格式行。

**Mode 7 intraday**（HK + US 盘中盯盘 — 2 个 cron 共享，每 30 分钟；HK 8 次/天，US 12 次/天，已错开阶段性报告）
- **`scripts/harness/intraday_preflight.py --market {hk|us}`**：跑 analyze_*.py + 异动检测 + `should_alert` 决策；输出 `memory/.tmp/intraday-context-{market}-latest.json`
- **`scripts/harness/intraday_postflight.py --market {hk|us}`**：校验 ▎我的看法 / 长度 / should_alert 触发时报告必须提异动票；**不 commit**（高频触发避免 commit log 刷屏）

**共通设计点**：
- preflight 输出 `raw_wechat_block` 字段，LLM **必须 verbatim 拷贝**（不改时间戳/数字），postflight 用首行匹配验证
- preflight 输出 `anomalies` 字段，LLM 必须在报告里至少提一个 anomaly 票
- postflight 输出 `wechat_prefix`（pass=空串，warn=黄 banner，fail=红 banner），LLM 拼到 WeChat 输出前
- 所有 context.json 都放 `memory/.tmp/`（gitignore 排除）

### 辅助
- **Scrapling**：自适应爬虫框架，绕过反爬（Cloudflare 等），支持 JS 渲染。`pip3 install scrapling --break-system-packages`。详见 `skills/scrapling/SKILL.md`
- **`scripts/data/build_dashboard.py`**：聚合 `portfolio.json` + snapshots + v2 plans + `memory/decisions.jsonl` + risk/peer/context sidecars → `assets/data/dashboard.json`。决策字段统一为 `decision_metrics` / `episode_backtest` / `decision_money_impact` / `decision_delta` / `recent_decisions`；只计已触发 episode，date-cluster CI。**`decision_money_impact` 是唯一有业务含义的口径**：`成交价 × 股数 × benefit` 按腿以本币**相加**(一次性下注,不复利),并附 `pnl_swing` 对照真实盈亏振幅;`episode_backtest` 的复合 benefit 是反事实评分不是钱。brief/report postflight 自动刷新；size cap 200KB。
- **`scripts/data/portfolio_risk_metrics.py`**：算 β/Vol/Max DD/Sharpe/margin_at_risk → `assets/data/risk.json`。每日 brief preflight `[10/10]` 自动跑。Yahoo v8 429 限速 → 改用 Tencent gtimg primary + Polygon/AlphaVantage fallback。alert 类型：high_beta(>3) / high_vol(>50%) / deep_dd(<-10%) / high_leverage(>2.0) / negative_sharpe(<0)
- **`scripts/data/compute_regime.py`**：杠杆刻度盘 → `assets/data/lev_regime.json`。HSTECH 200日线趋势 + 20d 波动 → HK 杠杆ETF腿上限乘子(green×1 / amber×0.5 / red×0)；US 逐名(2x单股ETF 各自 200日线，趋势off+vol>70% 才强砍)。**2026-07 新增 `regime_history`**：逐日 regime(hk←HSTECH 全历史含200DMA+近10日动量；us←benchmark.json SPY 序列，仅动量因样本<200)，供 build_dashboard 把 `vs_baseline` 按 regime 分桶。brief preflight 自动跑；tencent 空 fetch 保留旧文件。
- **`scripts/data/mark_followed.py`**：v2 execution ground-truth 工具。`--list` 列出已触发但执行未知的 decision；`mark_followed.py DECISION_ID [--no]` 写 `execution.status`。Brier 衡量建议置信度，执行率单独展示。
- **`scripts/data/fetch_catalysts.py`**：未来 14d catalysts → `assets/data/catalysts.json`（7 US holding 财报 Finnhub + 2026 FOMC 硬编码 + 经济日历 NFP/CPI 规则）。brief_preflight `[11/11]` 自动跑。`catalysts.alerts` 触发时 LLM brief 必须 ▎事件日历 段提及。
- **`scripts/data/fetch_influencer_feed.py`**：高影响力人物市场异动 → `assets/data/influencer_feed.json`。Trump 原帖(trumpstruth.org/feed RSS, 全文)+ Musk(Google News RSS 代理, X 无可靠免费 RSS)。关键词预筛 → 单次 Xiaomi LLM(`thinking_disabled` 结构化抽取, ~2.5K token)提相关性/stance/ticker/板块 → 代码交叉匹配持仓分三档：`held_hits`(撞持仓告警) / `new_ideas`(他们点名但 kcn 没持有的选股线索) / `sector_hits`(板块软关联, 非直接点名)。merge-not-overwrite: 源**抓取失败**才保留旧条目（被 LLM 筛掉≠失败）。env `XIAOMI_API_KEY`(缺则降级关键词-only)。dashboard「影响力雷达」卡 + brief `▎名人异动/政策风向` 段消费。
- **`scripts/data/xiaomi_llm.py`**：OpenAI-compat LLM client，供 GH Action 直调（绕过 openclaw gateway）。**Primary Xiaomi MiMo v2.5-pro → fallback MiniMax M3（Anthropic 协议，2026-06-01 起 M2.7+openai-completions 作废）**（Xiaomi 三次重试全挂即透明切 MiniMax，两家全挂才 raise）。**单轮默认 thinking enabled + max_tokens 32K**；多轮传 `thinking_disabled=True` 避 reasoning 400。`_clean()` 统一剥内联 `<think>…</think>` + markdown fence，json.loads 两家通用。retry 3 + 429 handling。env `XIAOMI_API_KEY` + `MINIMAX_API_KEY`(缺则跳过 fallback)。`chat(fallback=False)` 可关兜底。
- **`scripts/data/gh_action_*.py`**：3 个 GH Action 入口脚本（brief_fallback / weekly_review / news_digest），都用 xiaomi_llm.chat() 直调小米。
- **`scripts/data/safe_push.sh`**：共享 git push 防 conflict 死循环工具。3 次 retry + 每次 rebase 失败 → `git rebase --abort` + exit 2（不死循环 push）。所有写文件的 GH Action workflow 用 `bash scripts/data/safe_push.sh` 替代原本的 push loop；harness 端 `scripts/harness/_harness_common.push_with_rebase_retry` **直接委托本脚本**（2026-06-10 统一，自动获得 rebase.autoStash + 冲突标记硬闸），全体 committer 单一 push 路径。
- **`scripts/data/update_portfolio.py`** / **`update_us_portfolio.js`**：手动调仓后写 portfolio.json 的辅助

### Cron map（**11 个 job，6.1 起存 SQLite `~/.openclaw/state/openclaw.sqlite`，用 `openclaw cron list --json` 读——`cron/jobs.json` 已是死文件**）

| Job 名 | Schedule | Mode | Preflight | Postflight |
|---|---|---|---|---|
| Memory Dreaming Promotion | 03:00 daily | (system) | — | — |
| 📊 盘前深度简报 | **08:00 HKT 工作日** | `daily-deep-brief` (全 swarm + FX + SEC EDGAR) | `brief_preflight.py` | `brief_postflight.py` |
| 港股开盘报告 | 09:30 HKT 工作日 | Mode 6 | `report_preflight.py --market hk --phase open` | `report_postflight.py --market hk --phase open` |
| 港股盘中盯盘 | 10-11,14-15 每 30 分 HKT 工作日（共 8 次，错开 09:30/12:00/13:30/16:00 报告） | Mode 7 | `intraday_preflight.py --market hk` | `intraday_postflight.py --market hk` |
| 港股午盘报告 | 12:00 HKT 工作日 | Mode 6 | `report_preflight.py --market hk --phase mid` | `report_postflight.py --market hk --phase mid` |
| 港股午后快报 | 13:30 HKT 工作日 | Mode 6 | `report_preflight.py --market hk --phase pm` | `report_postflight.py --market hk --phase pm` |
| 港股收盘报告 | 16:00 HKT 工作日 | Mode 6 | `report_preflight.py --market hk --phase close` | `report_postflight.py --market hk --phase close` |
| 美股开盘报告 | **21:30 HKT** 工作日 (= 09:30 ET EDT, **HKT 表达式绕过 daemon ET tz bug**) | Mode 6 | `report_preflight.py --market us --phase open` | `report_postflight.py --market us --phase open` |
| 美股盘中盯盘 (evening) | **22:00-23:30 HKT** 工作日 (= ET 10:00-11:30 EDT, 拆分跨日 part 1) | Mode 7 | `intraday_preflight.py --market us` | `intraday_postflight.py --market us` |
| 美股盘中盯盘-overnight | **00:00-03:30 HKT 次日** DOW 2-6 (= ET 12:00-15:30 EDT, 拆分跨日 part 2) | Mode 7 | 同上 | 同上 |
| 美股收盘报告 | **04:00 HKT 次日** 工作日 DOW 2-6 (= 16:00 ET EDT, 同上) | Mode 6 | `report_preflight.py --market us --phase close` | `report_postflight.py --market us --phase close` |

所有 harness preflight/postflight 都在 `scripts/harness/`。Mode 6 / brief 的 postflight 会在 pass/warn 时
自动跑 `scripts/data/build_dashboard.py` 刷新 `assets/data/dashboard.json` 并一起 commit，保证 Pages 同步。

cron prompt 已精简成"按 skill 的 harness 4-step 跑"+ 自包含 fallback 指令，改格式时**只改 SKILL.md 里的 Mode 段**，payload 不重复 SKILL 细节（例外：Step 2.5 sidecar 必须在 payload 里点名——2026-06-04 重写 payload 时漏了它，status_banner 断供 6 天，LLM 只跟 payload 的步骤编号走）。

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

底层数据 `~/.openclaw/cron/runs/{jobId}.jsonl`；`runId` 以 `manual:` 开头是手动 trigger，
其余空 runId 是 cron daemon 自动调度。脚本本体 `scripts/data/cron_runs.py`。

### 已废弃（不作为调用入口，但作为参考代码可读）
> 这些脚本**不要直接调起来跑**当主路径，但里面的 URL、header、fallback 思路、解析片段在调试或场景超出现役脚本时仍有参考价值。
- `scripts/legacy/stock_analyzer.py` — 被 `scripts/data/analyze_us_stocks.py` + `analyze_hk_stocks.py` 取代；早期 fallback 顺序的来源（`check_portfolio.sh` 仍引用）
- **完全删掉** (2026-05-16 大扫除)：`monday_signal.py` (含硬编码 key)、`api_retry_wrapper.py`、`baidu_search_wrapper.py`、`deep_analysis.py`、`final_analysis.py`、`find_opportunities.py`、`hk_ai_monitor.py`、`multi_agent_stock_analysis.py`、`price_alert_monitor.py`、`TradingAgents/` 整目录
- **完全删掉** (2026-07-04 清理)：`scripts/legacy/{hk_monitor,hk_open_monitor,hk_stock_fetcher,portfolio_monitor,portfolio_table,portfolio_visualization}.py`（无代码/cron 引用的死参考）、`scripts/data/brief_fallback_send.py`（被 `gh_action_brief_fallback.py` 取代）

---
