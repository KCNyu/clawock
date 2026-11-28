---
name: us-stock-analysis
description: Workspace-aware US stock analysis for kcn. Routes through `clawock analyze-us` / `clawock us-quotes` instead of generic web search, then layers fundamental/technical/news analysis on top. Use when user asks to analyze a US ticker (e.g. "analyze AAPL", "look at RKLB", "compare TSLA vs NVDA"), check earnings, run technicals, or write an investment report on a US name.
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

交互问题（Modes 1-5）的共同前提两市场共用一份：先 read `../_shared/interactive-mode-reads.md`；下面按市场列出本轮要读的路径。

In this order:
1. `/root/.openclaw/workspace/MEMORY.md` — data rules and traps (especially the "禁止用 portfolio.json 缓存价" rule)
2. `/root/.openclaw/workspace/TOOLS.md` — script paths, provider fallback chains, skill routing table
3. `/root/.openclaw/workspace/INVESTMENT_SOP.md` — standard startup sequence for investment questions
4. `/root/.openclaw/workspace/portfolio.json` — if the ticker is in the active book, cost basis and PnL matter

## Data source rule (non-negotiable)

**Default path — use the workspace script, not web search:**

```bash
# Full analysis: refreshes price + RSI-14 / MA20 / MA50 + Finnhub news + signal
/root/.local/bin/clawock analyze-us {TICKER}
/root/.local/bin/clawock analyze-us {TICKER} --no-news    # skip news (save Finnhub quota)

# Price-only refresh
/root/.local/bin/clawock us-quotes {TICKER}
```

The script internally runs the 7-route fallback (Nasdaq API → Eastmoney → Finnhub → Yahoo v8 → yfinance → Alpha Vantage → Polygon), pulls `prev_close` independently from Polygon's `/prev` endpoint (so `today_change` is trustworthy after close), and writes back to `portfolio.json` if the ticker is held. Bypassing it re-introduces every bug it was written to fix.

**Web search is only for:** earnings transcripts, SEC filings, analyst notes, sector news, peer fundamentals, qualitative thesis material — never primary price quotes.

**Forbidden:** Sina US quotes API (境外 403), raw Yahoo scraping when the script already covers it, reading `portfolio.json` cached `current_price` without first refreshing.

## Four analysis modes

Pick the smallest mode that answers the question. Default to **Quick Read** unless the user explicitly asks for deep analysis.

### Mode 1 — Quick Read (most common)
**When:** "What's RKLB at?" / "How's NVDA doing today?"
1. Run `clawock analyze-us {TICKER} --no-news` for price + RSI/MA/signal
2. If in active book, pull cost basis + PnL from `portfolio.json`
3. One short paragraph: price, today's move, RSI/MA stance, one-line verdict

### Mode 2 — Technical Read
**When:** "Is X oversold?" / "Where's resistance on Y?"
1. Run `clawock analyze-us {TICKER} --no-news`
2. Apply the shared output contract below; interpret only indicators actually returned
3. Output: trend (up/down/sideways), MA20/50 stance, RSI-14 reading (oversold <30, overbought >70), recent support/resistance from price action, one-line risk note

### Mode 3 — Fundamental Read
**When:** "Is X overvalued?" / "Analyze Y's business"
1. Run `clawock analyze-us {TICKER}` for fresh price baseline
2. Run `clawock filings {TICKER}` — pulls SEC EDGAR: latest 10-K/10-Q/8-K + 13 key XBRL concepts (revenue/net income/cash/EPS/assets/equity, 4 most recent periods). **Use this before web search** — primary source, structured, no scraping.
3. (Optional) `clawock filings {TICKER} --form4` if insider activity is material to thesis
4. (Optional 中文速查) `clawock fundamentals {TICKER} --indicators` — 东财 GMAININDICATOR 一次给齐 ROE/毛利率/净利率/资产负债率（比从 XBRL 自算比率快）；数字与 SEC 冲突时以 SEC 为准
5. Web search only for what SEC EDGAR can't give: peer multiples, analyst consensus, qualitative thesis, sector context
6. Apply the shared output contract below; verify reporting periods, units and valuation assumptions
7. Output: business overview, financial trends from XBRL, valuation vs peers/history, insider signal, key risks, fair value range

### Mode 4 — Full Report
**When:** "Give me a full report on X" / "Should I add X?"
1. Run script (Mode 1 baseline)
2. Do fundamentals (Mode 3)
3. Do technicals (Mode 2)
4. Do sentiment (Mode 5)
5. Web search for catalysts (next earnings date, upcoming product/regulatory events)
6. Use the shared output contract below; scale the report to the question
7. Output: executive summary + bull case + bear case + valuation + technical setup + sentiment read + risk + catalyst calendar + concrete entry/exit levels

### Mode 7 — 盘中盯盘（cron，每 30 分钟）

本节只是路由。Mode 7 正文两市场共用一份：`skills/_shared/intraday-mode7.md`；cron 任务（`config/cron-payloads/intraday.md`，market=us）第一轮直接 `read` 那份正文和 `skills/_shared/intraday-status-sidecar.md`，不读本文件。盘中规则只改那一份，这里不复述；人工对话里被问到盘中盯盘规则时也去读它。

### Mode 6 — 定时市场报告

美股开盘和收盘共用。对应市场怎么看，见 `../_shared/report-analysis-us.md`；写法见 `../_shared/report-prose-rules.md`。定时执行、投递和故障恢复按 `config/cron-payloads/report.md`。

#### Step 1: 跑 preflight

手工运行用 `clawock report preflight --market us --phase {open|close}` 并保留同代 `context_id`。

#### Step 2: 只写分析散文

按上面的分析和写作指针完成正文，保存到 Step 3 使用的文本路径。

#### Step 3: 跑 postflight

`clawock report postflight --market us --phase {phase} --context-id <context_id> --text-file <正文路径>`。最终回执和等待方式见报告任务正文 Step 3–4。

### Mode 5 — Sentiment Read
**When:** "市场情绪怎么样" / "推上怎么说 X" / "Reddit 怎么聊 X" / before a sizing decision

Sources, in order:
1. **Finnhub news (in script)** — `clawock analyze-us {TICKER}` without `--no-news` already pulls last 7 days with keyword sentiment scoring. **This is the first source — read it before anything else.**
2. **Web search: DeepSeek + Tavily (news + X)** — `clawock web-search` asks both at once; each answers under its own heading with its own status (parallel sources, not primary/backup). Each keeps its own limit:
   - **DeepSeek**: no credit budget, account-wide 5 QPS (gated on this host) — use it freely, intraday included: `clawock web-search "{TICKER} stock news" --providers deepseek --days 3`
   - **Tavily** ⚠️ 免费档 1000 credits/月全局共享: 只在**开盘/收盘报告**、或盘中**真事件**(异常波动跑输基准 / 停牌 / 财报预警 / 监管公告 / 有大标题但价格无法解释)时让它一起跑；Mode 7 cron 盘中盯盘的模型**不调** Tavily（harness 已检索，读 `anomaly_search`，见 Mode 7）。必须带 `--bucket`：开盘/收盘 `report`，盘中事件 `intraday`:
   ```bash
   clawock web-search "{TICKER} stock sentiment" --days 3 --bucket report
   clawock web-search "{TICKER} reddit wallstreetbets" --bucket report
   ```
   某个源 `unavailable`（Tavily 额度尽 / DeepSeek 限速）时 exit 0，别当报错；用另一个源的结果并写明哪个源没取到。
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
4. **scrapling fallback** — if Reddit JSON 429s or content needs comment-level depth, use `StealthyFetcher` (see `../scrapling/SKILL.md`). Same for X if web search misses.

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
- **Cite the data freshness.** End with "数据: clawock analyze-us {timestamp}" so the user knows price is live, not cached.
- **Flag stale data loudly.** If the script's fallback chain failed all 7 routes, lead with "⚠️ 数据获取失败，以下为旧缓存数据" before any analysis.

## Special handling — leverage ETFs

When the ticker is a leveraged ETF (SOXL, TQQQ, RKLX, MSFU, ROBN — anything with the `is_leveraged_etf=true` flag in `portfolio.json` or 2x/3x in the name):
- Always note decay risk for multi-day holding periods
- Verdicts must reference the underlying's direction, not just the ETF's chart
- 1-day RSI on these is noisy; weight MA20/50 stance higher

## Examples

**User:** "RKLB 怎么样"
**Approach:** Mode 1 — `clawock analyze-us RKLB --no-news`, read its position from portfolio.json, output table + one-line verdict.

**User:** "compare AAPL vs MSFT"
**Approach:** Comparison mode — script both, side-by-side table, paragraph verdict.

**User:** "Give me a deep report on PLTU"
**Approach:** Mode 4 — full pipeline with the shared output contract.

## Shared output contract

For interactive technical, fundamental or full reports, use
`../_shared/stock-analysis-output.md` for evidence, units, uncertainty and output scope.

## Companion tools

- `../scrapling/SKILL.md` — when all 7 script-internal fallbacks fail, or when Reddit/social needs comment-level depth past the public JSON
- `../tavily-search/SKILL.md` — optional configured search; skill 名是 `tavily`，catalog/key 不可用或脚本返回 unavailable 时用当前会话可用搜索
- `portfolio-swarm-review` skill — deep bull/bear/judge debate framework (analysts → researchers → risk debators → trader), inspired by TauricResearch/TradingAgents design; use when single-shot analysis isn't enough
