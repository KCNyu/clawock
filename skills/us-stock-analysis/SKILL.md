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

For interactive questions (Modes 1-5). Direct chat already has `MEMORY.md` and `TOOLS.md`
injected — use them rather than rereading. Cron Modes 6/7 follow their payload instead:
isolated cron does not inject `MEMORY.md`, and what those runs must obey is in the payload,
the Mode section and the postflight gate.

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
2. Load `references/technical-analysis.md` for indicator interpretation
3. Output: trend (up/down/sideways), MA20/50 stance, RSI-14 reading (oversold <30, overbought >70), recent support/resistance from price action, one-line risk note

### Mode 3 — Fundamental Read
**When:** "Is X overvalued?" / "Analyze Y's business"
1. Run `clawock analyze-us {TICKER}` for fresh price baseline
2. Run `clawock filings {TICKER}` — pulls SEC EDGAR: latest 10-K/10-Q/8-K + 13 key XBRL concepts (revenue/net income/cash/EPS/assets/equity, 4 most recent periods). **Use this before web search** — primary source, structured, no scraping.
3. (Optional) `clawock filings {TICKER} --form4` if insider activity is material to thesis
4. (Optional 中文速查) `clawock fundamentals {TICKER} --indicators` — 东财 GMAININDICATOR 一次给齐 ROE/毛利率/净利率/资产负债率（比从 XBRL 自算比率快）；数字与 SEC 冲突时以 SEC 为准
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

### Mode 7 — 盘中盯盘（cron，每 30 分钟）

本节只是路由。Mode 7 正文两市场共用一份：`skills/_shared/intraday-mode7.md`；cron 任务（`config/cron-payloads/intraday.md`，market=us）第一轮直接 `read` 那份正文和 `skills/_shared/intraday-status-sidecar.md`，不读本文件。盘中规则只改那一份，这里不复述；人工对话里被问到盘中盯盘规则时也去读它。

### Mode 6 — WeChat Briefing (cron-driven, harness 化 ✨)
**When:** 美股开盘 / 美股收盘 两个 cron 走这个 mode。

**Harness 4-step**：

#### Step 1: 跑 preflight
```bash
clawock report preflight --market us --phase {open|close}
```
跑 `clawock analyze-us --wechat --md-table` + 抽信号 + 异动，写 context 文件，并把**同一份 JSON** 打到 stdout（含 `context_id`；末行是 `context_path:`）。若输出 `market_closed`，本回合到此结束。

#### Step 2: 只写分析散文

**你不写数据块、不写表格、不写标题** —— postflight 自己从 context 拼。2026-07-24 之前是让模型 verbatim 拷贝数据块，结果模型读错 context 就把一天前的数字发了出去；现在那条回路已经拆掉，数字在发送时刻直接取自 context 文件。

用 stdout 里的字段：`signal_count` / `anomalies` / `index_direction` / `needs_risk_section` / `peer_scan` / `plan_context`（盘前简报还没执行完的决策，见下）/ `mover_news`（异动票的一手催化）/ `mover_thesis`（异动票的 thesis 与红线）（板块 + 同业 Top 5 今日/5日涨跌 + 背离信号，板块全景段直接用它）/ `live_information`（每只持仓的实时公告与新闻：`summary.<票>` 每条照抄 `cite`，含发布时间与「盘中实时」/「开盘前旧闻」；`degraded` 里的源是没取到，写「X 未取到」，不等于没有消息）/ `quote_coverage`（`unrefreshed` 里的票本次没刷到行情，表里是上次的价与涨跌；`anomalies`/`plan_triggers` 里这些票带 `quote_fresh: false`）；`raw_wechat_block` 是给你参考数字用的，**不要抄进散文**。任何行情缺口按 `quote_coverage` 明说，不能把旧价说成本时段的数。

⚠️ **`plan_context` 对账（非空时 ▎操作建议 必写，写在该段最前）**：里面是 盘前简报为本腿定下、**还没成交**的决策（`open[]`：`ticker`/`action`/`shares`/`pct`/`condition`/`confidence`/`driven_by`/`rationale`，外加 `exec_mode` 当日执行方式、`carried_over` 有几条是往日挂到今天的）。
- **不许给同一只票提相反的建议**。`driven_by=risk_rule` 的是**纪律动作不是择时**——给它加「等回踩 / 等反弹 / 等站稳」这类条件就是推翻简报（issue #119）。要推翻必须明写理由和新证据。
- `exec_mode.today_override` 说了 MOO 就不许改写成限价单口径。
- 股数/比例**照抄 `shares`/`pct`，不许换算也不许心算**；`carried_over>0` 时点一句「{n} 条昨日挂单仍未成交」。
- `plan_context` 为 `{}` 说明今天本腿没有未完成决策，按正常写，不要编一个计划出来。
- `plan_context` 里带 `error` 字段说明**计划没读出来，不是今天没有计划**（issue #136）。此时必须在 ▎操作建议 开头写一行「今日计划未取到（{error}），以下建议未与 盘前简报对账」，并且**不许**顺势断言「今天没有未完成决策」。
- 可选键（#605/#609）：`overridden_by_user` = 用户已 override 的 risk_rule 砍单（已隐藏并结案，**不要再提「该砍未砍」**）；`reinvest_candidates` = 砍/trim 的弹药去向候选（仅当 `open[]` 真有 cut/trim 时出现；是观察不是授权，配对话术照抄候选 ticker 与 trigger，不许虚构「砍 X 的弹药」当 `open[]` 里没有 X）。

🔢 **数字铁律（postflight 会查，见 `check_numeric_claims`）**：散文里出现的每个金额/股数**必须是 context 里已有的数字**，照抄不换算。
- **禁止重述持仓股数、持仓市值、浮盈金额** —— 这些 postflight 已经拼在消息开头了，重述一遍只会多一次说错的机会（2026-07-27 就把 6200 股的仓位写成 1000 股）。**例外且仅此一个**：`plan_context.open[].shares` 是「这一单要动多少股」，照抄它是被要求的；被禁的是「这只票我持有多少股」。两者不是一回事——07226 持仓 6200 股、当日 swap 单 1000 股，同一天同一只票。
- 前瞻性数字（「再跌 2% 会亏多少」）要么**别写**，要么写出算式让人能验；拍一个量级出来是 2026-07-27「再伤 1.5-2 万 HK$」（真实约 1 千）那条 issue #120 的原型。
- 差值 / 倍数 / 距离可以算，但要把两个操作数写在同一句、结果前面（「SPCX $148.18 距前高 152.3 还有 2.8%」）；乘积写完整的「操作数 × 操作数 ≈ 结果」。postflight 只核算这种写出来的算术，心算只给结果仍会标出。
- 区间必须真实存在：`+0.3~-0.4%` 这种正负打架的区间是编的，postflight 会直接标出来。


▎情绪面 里的**异动归因**（`anomalies` 非空时必写，最多 2 行，写在该段最前）：
- 每只异动票一行：「{票} {幅度}% ← {mover_news 里 signal=interrupt 的标题要点}（{age_minutes} 分钟前 / {来源的中文说法}）」。`source_class` 只用来选说法，不照抄：`exchange_filing`/`hkexnews_filing`→交易所公告，`sec_filing`/`sec_filing_mirror`/`sec_fulltext`→SEC 文件，`finnhub_filing`→公司公告（Finnhub），`market_flash`→市场快讯，其余取值同样换成中文。
- `halts` 命中该票 → 先写停牌（停牌原因用中文说 + 复牌时间，`reason_code` 不照抄）。
- `mover_thesis` 里该票有 `triggered`/`watch` 红线 → 追一句「触及红线：{required_action}」——**这是归因语境，不是操作许可**，能不能动手仍由 catalyst-gate 与风控契约决定。
- 没有 interrupt：`no_recent_filing` 先查 `known_catalysts[票]`；有则写「窗口内无新公告；沿用今早已知催化：…」，没有才写「窗口内无新公告，且无已知催化，暂无法归因」；`index_fund_no_issuer` 写「指数基金无发行人公告，看成分/板块」；`degraded` 写「催化源未取到」（**不等于「没有消息」**）。一律不许编理由。
- 空间不够时**先砍板块全景的细节，不砍归因**——一次异动没解释，比少列两个同业更贵。

🗣 **读者只看得到这条微信，看不到管线**：三段里不写 `harness`/`preflight`/`postflight`/`packet`/`sidecar`/`context_id`，也不描述你在按什么指令、格式或步骤写；约束翻成交易语言（「packet 锁定的破位审议线」→「计划里的破位复核线」）。postflight 会以 advisory 标出。
context 的字段名与枚举值（任何带下划线的英文标识，如 `hold_and_watch`、`near_breakout`，以及 `verdict=wait` 这类「键=值」）一律不写进正文，翻成中文说法（`hold_and_watch`→持有观察）；postflight 会把它标成正文顶部的校验警告。

写这几段，**存成 `memory/.tmp/report-prose-us-{phase}.md`**：
```
▎情绪面
{Finnhub news + 纳指 tone → market direction；⚡ **板块全景**：用 peer_scan 写对应主题今日 Top 5 + 你持仓位置 + 1 句归因。行情优先内置 web search；tavily 仅开盘/收盘或真事件用，带 `--bucket report`，盘中常规盯盘不烧 Tavily}

▎技术面
{RSI / MA stance → overbought/oversold/breakout}

▎操作建议
{plan_context 非空时先写计划对账（哪条已成交/仍挂着 + 今天怎么执行），再写具体票 + 价位}

▎风险提示（仅当 needs_risk_section=true）
```

**长度由你自己判断**：不设字数目标，把该说的说完，不为凑数注水也不为省字砍内容。
必须写到的：`peer_scan` 的 Top 5、持仓在同行里的位置、今日/5 日涨跌和归因、异动归因、
计划对账、三段必需标记、证据，以及 `needs_risk_section=true` 时的风险提示。
自然要避免的是重复而不是长度——同一组合风险数字不要在技术面、操作建议和风险提示三段
重复；财报/lockup 日期只在最相关的一段写一次；情绪面的异动归因和同行对比不要在技术面复述。

#### Step 3: 跑 postflight
```bash
clawock report postflight --market us --phase {phase} --context-id {Step 1 的 context_id} --text-file /root/.openclaw/workspace/memory/.tmp/report-prose-us-{phase}.md
```
`--context-id` 必须是 Step 1 打印的那个：不匹配说明 context 已被换代（散文和数据不同代），postflight 拒绝拼装、只发数据块。散文文件超过 30 分钟没更新同样拒发（防重发上个 slot 的旧文本）。
pass/warn 自动刷新 snapshot/dashboard，提交 scoped 产物并经 `ops/publish/safe_push.sh` 推送。

⏱ **exec 超时 / SIGTERM 之后怎么收尾**：只按任务消息 Step 3 的规则走（源文件
`config/cron-payloads/report.md`，六个报告任务共用，本节不另写）。完成判据是 postflight 自己返回的
`status` + `commit_ok`；`report-sent-*` marker 只证明投递，不能据此收尾。

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
- 不设字数目标；拼装全文只有一道防复读死循环的天花板（>5000 warn，>6000 fail）

### Mode 5 — Sentiment Read
**When:** "市场情绪怎么样" / "推上怎么说 X" / "Reddit 怎么聊 X" / before a sizing decision

Sources, in order:
1. **Finnhub news (in script)** — `clawock analyze-us {TICKER}` without `--no-news` already pulls last 7 days with keyword sentiment scoring. **This is the first source — read it before anything else.**
2. **Tavily (news + X)** — for trending discussions, analyst notes, X/Twitter sentiment. ⚠️ **Budget rule** (免费档 1000 credits/月，全局共享): 本条只管人工对话与开盘/收盘报告；Mode 7 cron 盘中盯盘的模型**不调** Tavily（harness 已检索，读 `anomaly_search`，见 Mode 7）。人工对话里盘中**默认不调 Tavily**，用 Finnhub + Reddit JSON 就够；只有**开盘/收盘报告**、或盘中出现**真事件**(异常波动跑输基准 / 停牌 / 财报预警 / 监管公告 / 有大标题但价格无法解释)才用。调用必须带 `--bucket`：开盘/收盘用 `--bucket report`，盘中事件用 `--bucket intraday`(不带 bucket 会落 60/月的 default 桶很快被挡):
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
**Approach:** Mode 4 — full pipeline with references/report-template.md structure.

## Reference files (lazy-load)

- `references/technical-analysis.md` — indicator definitions, chart patterns, support/resistance methodology
- `references/fundamental-analysis.md` — business quality, financial health, valuation frameworks, red flags
- `references/financial-metrics.md` — every ratio formula needed for valuation work
- `references/report-template.md` — full-report skeleton for Mode 4

These are market-agnostic; `hk-stock-analysis` also references them.

## Companion tools

- `../scrapling/SKILL.md` — when all 7 script-internal fallbacks fail, or when Reddit/social needs comment-level depth past the public JSON
- `../tavily-search/SKILL.md` — optional configured search; skill 名是 `tavily`，catalog/key 不可用或脚本返回 unavailable 时用当前会话可用搜索
- `portfolio-swarm-review` skill — deep bull/bear/judge debate framework (analysts → researchers → risk debators → trader), inspired by TauricResearch/TradingAgents design; use when single-shot analysis isn't enough
