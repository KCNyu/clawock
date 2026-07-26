---
name: us-stock-analysis
description: Workspace-aware US stock analysis for kcn. Routes through the local fetch pipeline (analyze_us_stocks.py / fetch_us_stocks.py) instead of generic web search, then layers fundamental/technical/news analysis on top. Use when user asks to analyze a US ticker (e.g. "analyze AAPL", "look at RKLB", "compare TSLA vs NVDA"), check earnings, run technicals, or write an investment report on a US name.
triggers:
  - "analyze {US ticker}"
  - "美股 {ticker}"
  - "look at AAPL/NVDA/..."
  - "compare X vs Y"
  - "stock report"
---

# US Stock Analysis

Workspace-native US stock analyst. Always uses kcn's local pipeline for price/RSI/MA/signal — uses web search only for news, peer data, fundamentals.

## Required reads before answering

In this order:
1. `/root/.openclaw/workspace/MEMORY.md` — data rules and traps (especially the "禁止用 portfolio.json 缓存价" rule)
2. `/root/.openclaw/workspace/TOOLS.md` — script paths, provider fallback chains, skill routing table
3. `/root/.openclaw/workspace/INVESTMENT_SOP.md` — standard startup sequence for investment questions
4. `/root/.openclaw/workspace/portfolio.json` — if the ticker is in the active book, cost basis and PnL matter

## Data source rule (non-negotiable)

**Default path — use the workspace script, not web search:**

```bash
# Full analysis: refreshes price + RSI-14 / MA20 / MA50 + Finnhub news + signal
python3 /root/.openclaw/workspace/scripts/data/analyze_us_stocks.py {TICKER}
python3 /root/.openclaw/workspace/scripts/data/analyze_us_stocks.py {TICKER} --no-news    # skip news (save Finnhub quota)

# Price-only refresh
python3 /root/.openclaw/workspace/scripts/data/fetch_us_stocks.py {TICKER}
```

The script internally runs the 7-route fallback (Nasdaq API → Eastmoney → Finnhub → Yahoo v8 → yfinance → Alpha Vantage → Polygon), pulls `prev_close` independently from Polygon's `/prev` endpoint (so `today_change` is trustworthy after close), and writes back to `portfolio.json` if the ticker is held. Bypassing it re-introduces every bug it was written to fix.

**Web search is only for:** earnings transcripts, SEC filings, analyst notes, sector news, peer fundamentals, qualitative thesis material — never primary price quotes.

**Forbidden:** Sina US quotes API (境外 403), raw Yahoo scraping when the script already covers it, reading `portfolio.json` cached `current_price` without first refreshing.

## Four analysis modes

Pick the smallest mode that answers the question. Default to **Quick Read** unless the user explicitly asks for deep analysis.

### Mode 1 — Quick Read (most common)
**When:** "What's RKLB at?" / "How's NVDA doing today?"
1. Run `scripts/data/analyze_us_stocks.py {TICKER} --no-news` for price + RSI/MA/signal
2. If in active book, pull cost basis + PnL from `portfolio.json`
3. One short paragraph: price, today's move, RSI/MA stance, one-line verdict

### Mode 2 — Technical Read
**When:** "Is X oversold?" / "Where's resistance on Y?"
1. Run `scripts/data/analyze_us_stocks.py {TICKER} --no-news`
2. Load `references/technical-analysis.md` for indicator interpretation
3. Output: trend (up/down/sideways), MA20/50 stance, RSI-14 reading (oversold <30, overbought >70), recent support/resistance from price action, one-line risk note

### Mode 3 — Fundamental Read
**When:** "Is X overvalued?" / "Analyze Y's business"
1. Run `scripts/data/analyze_us_stocks.py {TICKER}` for fresh price baseline
2. Run `python3 scripts/data/fetch_us_filings.py {TICKER}` — pulls SEC EDGAR: latest 10-K/10-Q/8-K + 13 key XBRL concepts (revenue/net income/cash/EPS/assets/equity, 4 most recent periods). **Use this before web search** — primary source, structured, no scraping.
3. (Optional) `python3 scripts/data/fetch_us_filings.py {TICKER} --form4` if insider activity is material to thesis
4. (Optional 中文速查) `python3 scripts/data/fetch_fundamentals_em.py {TICKER} --indicators` — 东财 GMAININDICATOR 一次给齐 ROE/毛利率/净利率/资产负债率（比从 XBRL 自算比率快）；数字与 SEC 冲突时以 SEC 为准
5. Web search only for what SEC EDGAR can't give: peer multiples, analyst consensus, qualitative thesis, sector context
6. Load `references/fundamental-analysis.md` for framework, `references/financial-metrics.md` for ratio definitions
7. Output: business overview, financial trends from XBRL, valuation vs peers/history, insider signal, key risks, fair value range

### Mode 4 — Full Report
**When:** "Give me a full report on X" / "Should I add X?"
1. Run script (Mode 1 baseline)
2. Do fundamentals (Mode 3)
3. Do technicals (Mode 2)
4. Do sentiment (Mode 5)
5. Web search for catalysts (next earnings date, upcoming product/regulatory events)
6. Load `references/report-template.md` for structure
7. Output: executive summary + bull case + bear case + valuation + technical setup + sentiment read + risk + catalyst calendar + concrete entry/exit levels

### Mode 7 — Intraday Check-in (cron-driven, every 30 min, harness 化 ✨)
**When:** US 盘中由 evening + overnight 两个 HKT cron 拼接，比 Mode 6 更轻量、更高频。
精确 EDT/EST 表达式只读 `config/cron-schedules.json` / 生成的 `docs/operations/cron-schedules.md`；
每日 DST 同步器会同时调整 live cron 与 watchdog。隔夜始终最晚 02:30 HKT，给 03:00
dreaming 留独占窗口，所以 EST 季比 EDT 季少两个 slot。

**Harness 4-step**：

#### Step 1: preflight
```bash
python3 /root/.openclaw/workspace/scripts/harness/intraday_preflight.py --market us
```
输出 `memory/.tmp/intraday-context-us-latest.json`，关键字段：`should_alert` + `alert_reasons`，另有 `peer_scan`（本腿持仓的板块+同业涨跌，已排序）。
- `mover_thesis` — **只对本轮异动票**的 thesis 只读快照：`state`、`triggered`/`watch` 红线（含 severity 与 required_action）、下次 review trigger；最新一次 entry gate 判 `reject` 也会标出来。没有基线就是 `unknown`，不许靠记忆补。**这是归因语境不是催化剂**：红线解释「这个跌为什么要紧、当初说好要怎么做」，但能不能动手仍由 catalyst-gate 决定（软消息/情绪不构成主动操作依据）。

#### Step 2: 写报告
- 拷贝 `raw_wechat_block` 到消息开头（**verbatim — 不许改格式不许 trim**）
  - intraday 的 holdings 是 **markdown 表格**（7 列：代码/股/成本/现价/今日/浮%/浮$，右对齐数字。走 `scripts/data/_wechat_table.py` 的 visual-width-aware 渲染，去 $ 前缀 + 加 浮$ 金额列；RSI 在信号段不再占表头）
  - ⚠️ **表格的 3 类行（表头 / 分隔 `|:--|--:|...|` / 每条数据）每一字符 1:1 复制**，不要数列重写分隔行 — 5/21 后多次因 LLM 自己写分隔行少一段 `--:|` 导致渲染失败（postflight 会 fail）
  - **市值/浮盈/今日/已实现 已经是单行用 `|` 分隔的格式** — 不要拆 3 行
  - **`📉 亏损持仓 X/Y | 杠杆ETF敞口 N%` 必须保留**，不要省
- 加 `▎我的看法` 段：**至少 60 字（postflight 软下限），目标 2-3 行**
  - 若 `should_alert=true`，**必须**提 `anomalies` 中至少一个票
  - 必须包含：今天该看/该等/该减 + 引用至少 1 个具体数字（票现价 / 异动幅度 / 信号 / RSI）
  - ⚡ **板块全景**：数据**已由 preflight 备好**在 context.json 的 `peer_scan` 里（每个 active ticker 一项：`theme` 板块名、`listed_peers` 已按今日涨幅降序、含 `pct_1d`/`pct_5d`、`divergence_signal`、`self_pct_1d`）。**直接引用它,不要自己去读 peer-map.json、也不要自己调 `fetch_peers.py`**；给对应主题成分今日 Top 5 + 你持仓位置 + 1 句归因;`peer_scan` 为空或缺项时才回退 web search。若某条带 `name_mismatch`,以 feed 名为准并在报告里提一句。持仓自己的数字仍从 context.json。板块行情**优先用内置 web search**；`tavily-search` 仅在**开盘/收盘报告**或盘中真事件时才用，且必带 `--bucket report`/`--bucket intraday`（见 Mode 5 的 Budget rule）——盘中每 30 分钟的常规盯盘**不要**烧 Tavily
  - 禁止"无异动，观望"这种敷衍 1 句话
- 目标 ≤2200 字；>3000 字 postflight warn，>3500 字 fail

#### Step 2.5: 写 dashboard 状态横幅 sidecar

**规范见 `skills/_shared/intraday-status-sidecar.md`**（hk/us 共用单一来源）—— 写 `memory/.tmp/intraday-insights-{date}.json`（status_banner + 每个异动票 movers 归因，只文本无 key）。
- 本市场杠杆 ETF：**ROBN/PLTU/MSFU/SOXL/TQQQ** 等（2x 标的），归因要点明"杠杆放大"、区分标的真涨还是纯 beta。

#### Step 3: postflight（先写文件，再调用 —— 禁用 heredoc/`<<<`）
**必须两步、按顺序**：先用文件写入工具把 Step 2 的报告原样写到
`memory/.tmp/intraday-report-us.md`，确认写入成功后再调用：
```bash
python3 /root/.openclaw/workspace/scripts/harness/intraday_postflight.py \
  --market us --text-file /root/.openclaw/workspace/memory/.tmp/intraday-report-us.md
```
❌ **不要用 `<<<` / heredoc 把报告塞进 stdin** —— 报告含 emoji、`$`、`|` 表格和换行，
shell 引号极脆；2026-07-23 10:00 就因为模型漏喂 stdin，postflight 读到空串后吐出
4 条"报告写错了"的假 issue，run 被标红（实际重试后投递正常）。
postflight 现在把空输入/旧文件单独判成 `status: input_error`（不是 `fail`），并要求
文件 20 分钟内更新过 —— **忘了重写文件就会被拒**，不会把上一个 slot 的旧报告重发。

**不提交 `portfolio.json`**；若 dashboard 有语义变化，postflight 会重建并提交
`assets/data/dashboard.json`。每个 slot 的完成/投递状态另写 heartbeat，由 single
publisher 发布。

#### Step 4: 输出报告（仅存档；微信已由 postflight 主发，禁用 message 工具）
微信投递已在 **Step 3 的 `intraday_postflight` 用 fresh-token 短连接发出**（cron `--no-deliver`，不 announce）——唯一路径。拼 `wechat_prefix` + 报告，**无标题**，作为**本回合最终文本回复**直接输出（仅存档）。
- ❌ **禁止调用 `message`/send 工具** — postflight 已发，手动再调会**双发**；`intraday_watchdog` 只在 Telegram marker 缺失/失败时补投 Telegram，不重发微信。整轮只输出一次，发完即停。

**和 Mode 6 的区别**：单段 `▎我的看法` 取代三段；无 ▎风险提示；不提交
`portfolio.json`（但会发布 dashboard 语义变化 + slot heartbeat）；holdings 用 markdown 表格。

### Mode 6 — WeChat Briefing (cron-driven, harness 化 ✨)
**When:** 美股开盘 / 美股收盘 两个 cron 走这个 mode。

**Harness 4-step**：

#### Step 1: 跑 preflight
```bash
python3 /root/.openclaw/workspace/scripts/harness/report_preflight.py --market us --phase {open|close}
```
跑 `scripts/data/analyze_us_stocks.py --wechat --md-table` + 抽信号 + 异动，写 context 文件，并把**同一份 JSON** 打到 stdout（含 `context_id`；末行是 `context_path:`）。若输出 `market_closed`，本回合到此结束。

#### Step 2: 只写分析散文

**你不写数据块、不写表格、不写标题** —— postflight 自己从 context 拼。2026-07-24 之前是让模型 verbatim 拷贝数据块，结果模型读错 context 就把一天前的数字发了出去；现在那条回路已经拆掉，数字在发送时刻直接取自 context 文件。

用 stdout 里的字段：`signal_count` / `anomalies` / `index_direction` / `needs_risk_section` / `peer_scan`（板块 + 同业 Top 5 今日/5日涨跌 + 背离信号，板块全景段直接用它）；`raw_wechat_block` 是给你参考数字用的，**不要抄进散文**。

写这几段，**存成 `memory/.tmp/report-prose-us-{phase}.md`**：
```
▎情绪面
{Finnhub news + 纳指 tone → market direction；⚡ **板块全景**：用 peer_scan 写对应主题今日 Top 5 + 你持仓位置 + 1 句归因。行情优先内置 web search；tavily 仅开盘/收盘或真事件用，带 `--bucket report`，盘中常规盯盘不烧 Tavily}

▎技术面
{RSI / MA stance → overbought/oversold/breakout}

▎操作建议
{具体票 + 价位}

▎风险提示（仅当 needs_risk_section=true）
```

#### Step 3: 跑 postflight
```bash
python3 /root/.openclaw/workspace/scripts/harness/report_postflight.py --market us --phase {phase} --context-id {Step 1 的 context_id} --text-file /root/.openclaw/workspace/memory/.tmp/report-prose-us-{phase}.md
```
`--context-id` 必须是 Step 1 打印的那个：不匹配说明 context 已被换代（散文和数据不同代），postflight 拒绝拼装、只发数据块。散文文件超过 30 分钟没更新同样拒发（防重发上个 slot 的旧文本）。
pass/warn 自动刷新 snapshot/dashboard，提交 scoped 产物并经 `safe_push.sh` 推送。

#### Step 4: 输出报告（仅存档；微信已由 postflight 主发，禁用 message 工具）

微信投递已在 **Step 3 的 `report_postflight` 用 fresh-token 短连接发出**——这是
**唯一微信路径**（cron 设 `--no-deliver`，不再 announce），同时会镜像 Telegram。
把 postflight 返回的 `status` + `issues` 作为**本回合最终文本回复**输出即可（仅留痕）。
**不要自己调 `message`/send 工具**；`report_watchdog` 只在 Telegram marker 缺失/失败时
补投 Telegram，不重发微信。

**Title template**（preflight 已生成）：
- 开盘 09:30 ET：`🌅 美股开盘快报｜{date} 09:30 ET`
- 收盘 16:00 ET：`🌙 美股收盘日报｜{date}`

**Hard rules:**
- ⚠️ data gaps must be stated explicitly, never fabricate (postflight 扫敷衍词)
- ❌ **禁止调用 `message`/send 工具发报告** — 微信由 Step 3 的 `report_postflight` 用 fresh-token 主发（cron `--no-deliver`，不 announce），手动再调 message 会**和 postflight 撞成双发**（2026-06-03 美股开盘连发两次的根因：模型在"已完成"叙述的同一 turn 又调了一次 send）。整轮只输出一次，发完即停；`report_watchdog` 只在 Telegram marker 缺失/失败时补投 Telegram，不重发微信。
- No simple number recitation — model must add interpretation
- 异动票 (anomalies) **必须在报告里提到** (postflight 强制)
- 目标 ≤2200 字；>3000 字 postflight warn，>3500 字 fail

### Mode 5 — Sentiment Read
**When:** "市场情绪怎么样" / "推上怎么说 X" / "Reddit 怎么聊 X" / before a sizing decision

Sources, in order:
1. **Finnhub news (in script)** — `scripts/data/analyze_us_stocks.py {TICKER}` without `--no-news` already pulls last 7 days with keyword sentiment scoring. **This is the first source — read it before anything else.**
2. **Tavily (news + X)** — for trending discussions, analyst notes, X/Twitter sentiment. ⚠️ **Budget rule** (免费档 1000 credits/月，全局共享): 盘中盯盘(每 30 分钟)**默认不调 Tavily**，用 Finnhub + Reddit JSON 就够；只有**开盘/收盘报告**、或盘中出现**真事件**(异常波动跑输基准 / 停牌 / 财报预警 / 监管公告 / 有大标题但价格无法解释)才用。调用必须带 `--bucket`：开盘/收盘用 `--bucket report`，盘中事件用 `--bucket intraday`(不带 bucket 会落 60/月的 default 桶很快被挡):
   ```bash
   node /root/.openclaw/workspace/skills/tavily-search/scripts/search.mjs "{TICKER} stock sentiment" --topic news --days 3 --bucket report
   node /root/.openclaw/workspace/skills/tavily-search/scripts/search.mjs "{TICKER} reddit wallstreetbets" --bucket report
   ```
   护栏是硬闸：额度用尽脚本返回 "Web search unavailable" 且 exit 0，别当报错，退回 Reddit/内置搜索。
3. **Reddit JSON (no auth needed)** — direct fetch:
   ```bash
   curl -sH "User-Agent: openclaw/1.0" \
     "https://www.reddit.com/r/wallstreetbets/search.json?q={TICKER}&restrict_sr=1&sort=new&limit=25" \
     | jq '.data.children[].data | {title, score, num_comments, created_utc}'
   curl -sH "User-Agent: openclaw/1.0" \
     "https://www.reddit.com/r/stocks/search.json?q={TICKER}&restrict_sr=1&sort=new&limit=15" \
     | jq '.data.children[].data | {title, score}'
   ```
   r/wallstreetbets is retail momentum; r/stocks is more measured. Both together give the retail temperature.
4. **scrapling fallback** — if Reddit JSON 429s or content needs comment-level depth, use `StealthyFetcher` (see `../scrapling/SKILL.md`). Same for X if Tavily misses.

Output:
- **Sentiment score**: -1 (extremely fearful) to +1 (euphoric); call out divergence from price action ("price up but Reddit fearful — short squeeze setup" or vice versa)
- **Key narratives** (2-3 bullets): what people are actually saying / focused on
- **Catalyst chatter**: earnings expectations, upcoming events, FUD threads
- **Volume signal**: ↑ post count vs prior week = topic heating up

## Comparison mode

For "X vs Y" requests:
1. Run script for both tickers
2. Build side-by-side metric table (price, today_change, RSI, MA50 stance, P/E, revenue growth, margins, market cap)
3. Verdict in one paragraph — which has the cleaner setup and why; don't hedge

## Output style (kcn-tuned)

The user is aggressive, table-first, and hates filler. Match that:

- **Direct verdicts.** "RKLB looks toppy at $118, RSI 73, would trim on strength" beats "RKLB shows signs of being overbought; consider monitoring."
- **Tables for any 3+ data points.** Price/PnL/RSI/MA/signal lives in a table, not prose.
- **No hedging boilerplate.** Skip "This is not financial advice" — the user knows, and `MEMORY.md` has the trading style on record.
- **Cite the data freshness.** End with "数据: scripts/data/analyze_us_stocks.py {timestamp}" so the user knows price is live, not cached.
- **Flag stale data loudly.** If the script's fallback chain failed all 7 routes, lead with "⚠️ 数据获取失败，以下为旧缓存数据" before any analysis.

## Special handling — leverage ETFs

When the ticker is a leveraged ETF (SOXL, TQQQ, RKLX, MSFU, ROBN — anything with the `is_leveraged_etf=true` flag in `portfolio.json` or 2x/3x in the name):
- Always note decay risk for multi-day holding periods
- Verdicts must reference the underlying's direction, not just the ETF's chart
- 1-day RSI on these is noisy; weight MA20/50 stance higher

## Examples

**User:** "RKLB 怎么样"
**Approach:** Mode 1 — `python3 scripts/data/analyze_us_stocks.py RKLB --no-news`, read its position from portfolio.json, output table + one-line verdict.

**User:** "compare AAPL vs MSFT"
**Approach:** Comparison mode — script both, side-by-side table, paragraph verdict.

**User:** "Give me a deep report on PLTU"
**Approach:** Mode 4 — full pipeline with references/report-template.md structure.

## Reference files (lazy-load)

- `references/technical-analysis.md` — indicator definitions, chart patterns, support/resistance methodology
- `references/fundamental-analysis.md` — business quality, financial health, valuation frameworks, red flags
- `references/financial-metrics.md` — every ratio formula needed for valuation work
- `references/report-template.md` — full-report skeleton for Mode 4

These are market-agnostic; `hk-stock-analysis` also references them.

## Companion tools

- `../scrapling/SKILL.md` — when all 7 script-internal fallbacks fail, or when Reddit/social needs comment-level depth past the public JSON
- `../tavily-search/SKILL.md` — primary web search tool for news/sentiment/research (do not let the model improvise with Yahoo/Google scraping)
- `portfolio-swarm-review` skill — deep bull/bear/judge debate framework (analysts → researchers → risk debators → trader), inspired by TauricResearch/TradingAgents design; use when single-shot analysis isn't enough
