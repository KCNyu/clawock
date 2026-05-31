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
4. Web search only for what SEC EDGAR can't give: peer multiples, analyst consensus, qualitative thesis, sector context
5. Load `references/fundamental-analysis.md` for framework, `references/financial-metrics.md` for ratio definitions
6. Output: business overview, financial trends from XBRL, valuation vs peers/history, insider signal, key risks, fair value range

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
**When:** US 盘中盯盘 cron (`*/30 10-15 * * 1-5 America/New_York`，共 12 次/天，已错开 09:30/16:00 阶段性报告)，比 Mode 6 更轻量、更高频。

**Harness 4-step**：

#### Step 1: preflight
```bash
python3 /root/.openclaw/workspace/scripts/harness/intraday_preflight.py --market us
```
输出 `memory/.tmp/intraday-context-us-latest.json`，关键字段：`should_alert` + `alert_reasons`。

#### Step 2: 写报告
- 拷贝 `raw_wechat_block` 到消息开头（**verbatim — 不许改格式不许 trim**）
  - intraday 的 holdings 是 **markdown 表格**（7 列：代码/股/成本/现价/今日/浮%/浮$，右对齐数字。走 `scripts/data/_wechat_table.py` 的 visual-width-aware 渲染，去 $ 前缀 + 加 浮$ 金额列；RSI 在信号段不再占表头）
  - ⚠️ **表格的 3 类行（表头 / 分隔 `|:--|--:|...|` / 每条数据）每一字符 1:1 复制**，不要数列重写分隔行 — 5/21 后多次因 LLM 自己写分隔行少一段 `--:|` 导致渲染失败（postflight 会 fail）
  - **市值/浮盈/今日/已实现 已经是单行用 `|` 分隔的格式** — 不要拆 3 行
  - **`📉 亏损持仓 X/Y | 杠杆ETF敞口 N%` 必须保留**，不要省
- 加 `▎我的看法` 段：**至少 60 字（postflight 软下限），目标 2-3 行**
  - 若 `should_alert=true`，**必须**提 `anomalies` 中至少一个票
  - 必须包含：今天该看/该等/该减 + 引用至少 1 个具体数字（票现价 / 异动幅度 / 信号 / RSI）
  - ⚡ **板块全景鼓励 tavily-search**：板块名读 `memory/peer-map.json` 各 ticker 的 `theme` 字段（持仓变了自动跟变，不要写死任何 ticker），search 对应 sector ETF / 主题板块今日成分涨跌 + 你持仓位置 + 1 句归因；持仓自己的数字仍从 context.json
  - 禁止"无异动，观望"这种敷衍 1 句话
- ≤ 1200 字软上限 / ≤ 1500 字硬上限

#### Step 2.5: 写 dashboard 状态横幅 sidecar → `memory/.tmp/intraday-insights-{YYYY-MM-DD}.json`

build_dashboard 读它刷新 dashboard **顶部状态横幅** + **Today's Movers 每条归因**（缺失容错，横幅自动隐藏）。只输出文本，**绝不写任何 key**。schema：
```json
{
  "generated_at": "{ISO8601}",
  "status_banner": "一句话 ≤50字：regime + 今日盈亏主来源 + 最该盯的一件事（盯盘提醒口吻）",
  "movers": {"代码": "一行归因 ≤40字：催化 / 板块beta / 纯杠杆放大噪音 + 操作含义（追/不追/观望）"}
}
```
- `movers` 覆盖 context 里 `anomalies` / today_movers 的**每个**票；杠杆 ETF（ROBN/PLTU/MSFU/SOXL/TQQQ 等）要点明"杠杆放大"、区分标的真涨还是纯 beta。
- **只用 context.json 的真实数字**；不确定催化就写"无明确个股催化，纯 beta"，**不编造财报/新闻**。
- HK / US 两个 intraday 共写这一个 per-date 文件，build_dashboard 取最新 mtime（当前在盘的市场覆盖横幅）。

#### Step 3: postflight
```bash
python3 /root/.openclaw/workspace/scripts/harness/intraday_postflight.py --market us <<< "{报告}"
```
**不 git commit**（高频触发避免 commit log 刷屏）。

#### Step 4: 发 WeChat
拼 `wechat_prefix` + 报告，**无标题**。

**和 Mode 6 的区别**：单段 `▎我的看法` 取代三段；无 ▎风险提示；无 git commit；holdings 用 markdown 表格（Mode 6 briefing 仍 ASCII）。

### Mode 6 — WeChat Briefing (cron-driven, harness 化 ✨)
**When:** 美股开盘 / 美股收盘 两个 cron 走这个 mode。

**Harness 4-step**：

#### Step 1: 跑 preflight
```bash
python3 /root/.openclaw/workspace/scripts/harness/report_preflight.py --market us --phase {open|close}
```
跑 `scripts/data/analyze_us_stocks.py --wechat --md-table` + 抽信号 + 异动，输出 `memory/.tmp/report-context-us-{phase}-{date}.json`。

#### Step 2: 读 context，写报告
关键字段：
- `raw_wechat_block` — 脚本输出，**verbatim 拷贝到消息开头**。holdings 是 **markdown 表格** (7 列：代码/股/成本/现价/今日/浮%/浮$；2026-05-21 起 visual-width-aware 渲染走 `_wechat_table.py`，去 $ 前缀加 浮$ 金额列，mobile WeChat 不渲染表格但每行视觉宽度精确一致)。⚠️ **表头/分隔/数据三类行每字符 1:1 复制**，不要重写分隔行 — 列数必须一致，postflight 会 fail。
- `title` — 自动选好
- `signal_count` / `anomalies` — 用于分析段
- `needs_risk_section` — STOP+TRIM ≥ 2 时为 true
- `commit_msg` — postflight 用

报告结构（postflight 校验）：
```
{title}

{raw_wechat_block 原样}

▎情绪面
{Finnhub news + 纳指 tone → market direction；⚡ **板块全景鼓励 tavily-search**：板块名读 peer-map.json `theme`（持仓动态），search 对应 sector ETF / 主题成分今日 Top 5 + 你持仓位置 + 1 句归因}

▎技术面
{RSI / MA stance → overbought/oversold/breakout}

▎操作建议
{具体票 + 价位；如 needs_risk_section 加 ▎风险提示}
```

#### Step 3: 跑 postflight
```bash
python3 /root/.openclaw/workspace/scripts/harness/report_postflight.py --market us --phase {phase} <<< "{报告}"
```
pass/warn 自动 `git commit portfolio.json`。

#### Step 4: 发 WeChat（拼 wechat_prefix + 报告）

**Title template**（preflight 已生成）：
- 开盘 09:30 ET：`🌅 美股开盘快报｜{date} 21:30 CST`
- 收盘 16:00 ET：`🌙 美股收盘日报｜{date}`

**Hard rules:**
- ⚠️ data gaps must be stated explicitly, never fabricate (postflight 扫敷衍词)
- Do not use `message` tool; reply text directly (cron delivery wraps it)
- No simple number recitation — model must add interpretation
- 异动票 (anomalies) **必须在报告里提到** (postflight 强制)
- 报告长度 ≤ 1200 字软上限 / ≤ 1500 字硬上限

### Mode 5 — Sentiment Read
**When:** "市场情绪怎么样" / "推上怎么说 X" / "Reddit 怎么聊 X" / before a sizing decision

Sources, in order:
1. **Finnhub news (in script)** — `scripts/data/analyze_us_stocks.py {TICKER}` without `--no-news` already pulls last 7 days with keyword sentiment scoring. **This is the first source — read it before anything else.**
2. **Tavily (news + X)** — for trending discussions, analyst notes, X/Twitter sentiment:
   ```bash
   node /root/.openclaw/workspace/skills/tavily-search/scripts/search.mjs "{TICKER} stock sentiment" --topic news --days 3
   node /root/.openclaw/workspace/skills/tavily-search/scripts/search.mjs "{TICKER} reddit wallstreetbets"
   ```
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
