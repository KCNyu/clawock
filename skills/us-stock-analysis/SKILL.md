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

### Mode 7 — Intraday Check-in (cron-driven, every 30 min, harness 化 ✨)
**When:** US 盘中由 evening + overnight 两个 HKT cron 拼接，比 Mode 6 更轻量、更高频。
精确 EDT/EST 表达式只读 `config/cron-schedules.json` / 生成的 `docs/operations/cron-schedules.md`；
每日 DST 同步器会同时调整 live cron 与 watchdog。隔夜始终最晚 02:30 HKT，给 03:00
dreaming 留独占窗口，所以 EST 季比 EDT 季少两个 slot。

**Harness 4-step**：

#### Step 1: preflight
```bash
clawock intraday preflight --market us
```
输出 `memory/.tmp/intraday-context-us-latest.json`，并把**同一份 JSON** 打到 stdout（含 `context_id` —— Step 3 要原样回传）。关键字段：`should_alert` + `alert_reasons`，另有 `peer_scan`（本腿持仓的板块+同业涨跌，已排序）和 `plan_context`（08:00 简报为本腿定下、尚未成交的决策）。
- `active_information_candidates` — 框架已完成一手披露扫描、底层去重、`candidate|wait|reject` 与探索上限计算；这里只消费结构化结果，不在 skill 里重算阈值、方向或股数。三态都不是下单授权。
- `mover_thesis` — **只对本轮异动票**的 thesis 只读快照：`state`、`triggered`/`watch` 红线（含 severity 与 required_action）、下次 review trigger；最新一次 entry gate 判 `reject` 也会标出来。没有基线就是 `unknown`，不许靠记忆补。**这是归因语境不是催化剂**：红线解释「这个跌为什么要紧、当初说好要怎么做」，但能不能动手仍由 catalyst-gate 决定（软消息/情绪不构成主动操作依据）。
- `mover_news` — **只对本轮异动票**、有限预算抓回来的「刚发生了什么」：`tier=primary` 是交易所/监管一手文件（港股=港交所公告，美股=SEC filing，带 `age_minutes`），`tier=supporting` 是券商研报/媒体/7×24 快讯。**只有 primary 才可能构成硬催化**（仍要过 catalyst-gate）；supporting 只能当色彩，不能作为主动操作依据。
  - `known_catalysts` 是当天 08:00 brief 已核过、且只按本轮异动票裁剪的结构化催化。它回答「此前已知什么」，`mover_news` 回答「这个分钟窗口新发生什么」；两者不能混为一谈，也不因此扩大新闻窗口。
  - `status=no_recent_filing` 是**明确的空**：写「窗口内无一手公告」，不要改口编一个理由；`status=degraded` 说明源没抓到，同样如实写。
  - 用法铁律：异动票必须给出归因或明写「无法归因」。**不要把 `mover_news` 整块抄进报告**——最多引 1–2 条最相关的标题+时间。
  - 一手文件都没有、而异动又很大时，才允许用**内置 web search** 补一次（禁止 Tavily：盘中不烧额度）。
  - 三级分流（`config/filing-triage.json`）：`signal=interrupt`（8-K/13D/配售/盈警/停牌/业绩…）才可能算硬催化；`context` 只作背景；`noise`（Form 3/4/144/13G、翌日披露报表、月报表、法律意见书）**直接不进上下文**，只留 `suppressed_noise` 计数。没见过的标题一律 `context`，不会被悄悄丢掉。
  - 基金看穿：2x 单票 ETF 查的是**它跟踪的公司**（`target.kind=look_through`，如 PLTU→PLTR）；指数/板块基金没有发行人，直接标 `index_fund_no_issuer`，不会假装「公司没公告」。
  - `halts`（仅美股，每 slot 一次共享请求）：持仓或其标的被停牌时给出 `reason_code`（LULD 的 `LUDP` 最常打到 2x ETF）与复牌时间；港股停牌走公告（已在 triage 里判 interrupt）。

若 `delivery_mode=unchanged_receipt`：和上一次实际送达相比，风险档位、异动档位、盘中 setup、未成交计划和一级披露均无语义变化。**不要生成散文、不要写 prose/sidecar**，直接运行 `clawock intraday postflight --market us --context-id {context_id}`。harness 会发送带行情覆盖和一级源检查状态的一行回执；每档仍然可见，不是跳过。成功后输出 `wechat_prefix` + `raw_wechat_block` 并结束。下面 Step 2–2.5 只适用于 `delivery_mode=full_delta`。

#### Step 2: 只写 `▎我的看法` 散文（数据块归 harness）
- ❌ **不要抄 `raw_wechat_block`，不要重画那张表** —— postflight 在发送时自己把它拼在你的散文前面。
  你抄一遍只会引入排版误差：2026-07-28 00:30 就因为一格多打了一个空格，整段分析被丢掉只发了数据块。
  数据块里的市值/持仓表/亏损持仓行**已经在消息里了**，你的输出从 `▎我的看法` 开始。
- 你交付的就是这一段：**至少 60 字（postflight 软下限），目标 2-3 行**
  - 若 `anomalies` 非空，**必须**提其中至少一个票；主动一级信息本身也会令 `should_alert=true`，此时不能虚构一个价格异动。
  - `active_information_candidates.candidates` 非空时，至少写最相关一条：Bull 只陈述一手细节及预期传导，Bear 检查是否已 price-in/方向是否仍未知，Judge 照抄 harness 的 `candidate|wait|reject`、falsifier 与 next evidence；只能降级，不能自行补方向、价格、股数或授权。`degraded_issuers` 必须说“一级源降级”，不能说“没有消息”。
  - 📈 **加仓侧读数(`add_side_reads.rows` 非空时必写 1 行)**:harness 已经把异动、机会雷达
    (接近 20 日高)、早期趋势三条 lane 连同 thesis 红线和未了结的纪律动作 join 成
    `candidate|wait|reject`。**照抄 `verdict` + `why` + `needs`,数字照抄 `evidence`**
    (`move_pct` / `pct_from_high` / `prior_20d_high`),写成
    「{票} {verdict}:{why} → {needs}」。多条就写最急的 1-2 条(rows 已按 candidate→reject→wait
    排序)。纪律铁律不变:**三态都不是下单授权**,不许自行补方向、价格、股数;
    软消息/情绪只能停在 `wait`,只有一手披露才可能促成 `candidate`;
    `reject` 说明有纪律动作没走完,这时不要把它写成「可以加仓」。
  - **异动归因（`should_alert=true` 时必写，占 1 行）**：从 `mover_news.tickers[票].items` 里挑 **`signal=interrupt`** 的第一条，写成
    「{票} {幅度}% ← {标题要点}（{age_minutes} 分钟前 / {source_class}）」。多只异动票就各写一行，最多 3 行。
    - `halts` 里有这只票 → **先写停牌**（`reason_code` + 复牌时间），它比任何标题都能解释一次跳动。
    - 只有 `context` 没有 `interrupt` → 写「无一手催化，{context 标题}仅作背景」。
    - `status=no_recent_filing` → 先查 `known_catalysts[票]`：有则写「窗口内无新公告；沿用今早已知催化：{detail}（{source}）」；没有才写「窗口内无新公告，且无已知催化，暂无法归因」。`index_fund_no_issuer` → 写「指数基金无发行人公告，看成分/板块」。
    - `status=degraded` → 写「催化源未取到」，别把它说成「没有消息」。
    - 引用**至多两条**、每条一行；`suppressed_noise` / `more_interrupts` 只是计数，不要写进报告。
  - 必须包含：今天该看/该等/该减 + 引用至少 1 个具体数字（票现价 / 异动幅度 / 信号 / RSI）
  - 📋 **计划对账（`plan_context` 非空时必写 1 行）**：08:00 定下、还没成交的决策就在 `plan_context.open[]` 里——**不要再去 `cat` plan.json 或 decisions.jsonl**（2026-07-27 10:05 那样手刨 6 次还把 swap 股数说错，issue #119/#120）。写「{票} {action} {shares} 股仍挂着 / 已成交」，股数**照抄 `shares` 字段**；`driven_by=risk_rule` 的纪律动作不许被改写成「等回踩再做」；`carried_over>0` 要点名往日挂单。
  - 🔢 **数字铁律**：金额/股数一律**照抄 context**，不换算不心算；**别在 `▎我的看法` 里重述持仓股数或市值**（数据块里已经有了，但 `plan_context.open[].shares` 这种「本单动多少股」是要写的）；前瞻性数字要么给算式要么不写。postflight 的 `check_numeric_claims` 会把 context 里没有的数字和自相矛盾的区间标成 warn（issue #120）。
  - ⚡ **板块全景**：数据**已由 preflight 备好**在 context.json 的 `peer_scan` 里（每个 active ticker 一项：`theme` 板块名、`listed_peers` 已按今日涨幅降序、含 `pct_1d`/`pct_5d`、`divergence_signal`、`self_pct_1d`）。**直接引用它,不要自己去读 peer-map.json、也不要自己调 `clawock fetch-peers`**；给对应主题成分今日 Top 5 + 你持仓位置 + 1 句归因;`peer_scan` 为空或缺项时才回退 web search。若某条带 `name_mismatch`,以 feed 名为准并在报告里提一句。持仓自己的数字仍从 context.json。板块行情**优先用内置 web search**；`tavily-search` 仅在**开盘/收盘报告**或盘中真事件时才用，且必带 `--bucket report`/`--bucket intraday`（见 Mode 5 的 Budget rule）——盘中每 30 分钟的常规盯盘**不要**烧 Tavily
  - 禁止"无异动，观望"这种敷衍 1 句话
- 不设字数目标；postflight 只有一道防复读死循环的天花板：>5000 warn，>6000 fail（算的是拼装后的整条消息）

#### Step 2.5: 写 dashboard 状态横幅 sidecar

**规范见 `skills/_shared/intraday-status-sidecar.md`**（hk/us 共用单一来源）—— 写 `memory/.tmp/intraday-insights-{date}.json`（status_banner + 每个异动票 movers 归因，只文本无 key）。
- 本市场杠杆 ETF：**ROBN/PLTU/MSFU/SOXL/TQQQ** 等（2x 标的），归因要点明"杠杆放大"、区分标的真涨还是纯 beta。

#### Step 3: postflight（先写文件，再调用 —— 禁用 heredoc / here-string 重定向）
**必须两步、按顺序**：先用文件写入工具把 Step 2 的散文写到
`memory/.tmp/intraday-prose-us.md`，确认写入成功后再调用（命令写成一行）：
```bash
clawock intraday postflight --market us --context-id {Step 1 的 context_id} --text-file /root/.openclaw/workspace/memory/.tmp/intraday-prose-us.md
```
`--context-id` 必须是 Step 1 打印的那个：不匹配说明 context 已被换代（散文和数据不同代），
postflight 拒绝拼装、只发数据块。

❌ **不要用 here-string / heredoc 重定向把散文塞进 stdin** —— 内容含 emoji、`$` 和换行，
shell 引号极脆；2026-07-23 10:00 就因为模型漏喂 stdin，postflight 读到空串后吐出
4 条"报告写错了"的假 issue，run 被标红（实际重试后投递正常）。
postflight 现在把空输入/旧文件单独判成 `status: input_error`（不是 `fail`），并要求
文件 20 分钟内更新过 —— **忘了重写文件就会被拒**，不会把上一个 slot 的旧散文重发。

⏱ **看到 SIGTERM / exec 超时 ≠ 报告没发出去，别原样再跑一遍。** exec 的 overall-timeout
只杀命令外壳，postflight 子进程还在继续跑，通常微信早发出去了。先读
`memory/.tmp/intraday-sent-us.json`：`ts` 是本 slot 的、且有 `sent_ok` / `tg_ok`
就是已投递。（2026-08-13 09:30 港股开盘那次双发的机制，#508；postflight 现在有发送前
claim 会挡住第二次真发，但那一跑仍然是白跑。）

校验段标记 + 长度 + 异动票提及（都只校验你写的那段，不校验拼进来的数据块）。
**不提交 `portfolio.json`**；若 dashboard 有语义变化，postflight 会重建并提交
`assets/data/dashboard.json`。每个 slot 的完成/投递状态另写 heartbeat，由 single
publisher 发布。

#### Step 4: 输出报告（仅存档；微信已由 postflight 主发，禁用 message 工具）
微信投递已在 **Step 3 的 `intraday_postflight` 用 fresh-token 短连接发出**（cron `--no-deliver`，不 announce）——唯一路径。拼 `wechat_prefix` + 你的散文，**无标题**，作为**本回合最终文本回复**直接输出（仅存档）。
- ❌ **禁止调用 `message`/send 工具** — postflight 已发，手动再调会**双发**；`intraday_watchdog` 只在 Telegram marker 缺失/失败时补投 Telegram，不重发微信。整轮只输出一次，发完即停。

**和 Mode 6 的区别**：单段 `▎我的看法` 取代三段；无 ▎风险提示；不提交
`portfolio.json`（但会发布 dashboard 语义变化 + slot heartbeat）；holdings 用 markdown 表格。
**相同点**：两者都是散文模式 —— 数据块由 postflight 拼装，你只写分析。

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

用 stdout 里的字段：`signal_count` / `anomalies` / `index_direction` / `needs_risk_section` / `peer_scan` / `plan_context`（08:00 简报还没执行完的决策，见下）/ `mover_news`（异动票的一手催化）/ `mover_thesis`（异动票的 thesis 与红线）（板块 + 同业 Top 5 今日/5日涨跌 + 背离信号，板块全景段直接用它）；`raw_wechat_block` 是给你参考数字用的，**不要抄进散文**。

⚠️ **`plan_context` 对账（非空时 ▎操作建议 必写，写在该段最前）**：里面是 08:00 简报为本腿定下、**还没成交**的决策（`open[]`：`ticker`/`action`/`shares`/`pct`/`condition`/`confidence`/`driven_by`/`rationale`，外加 `exec_mode` 当日执行方式、`carried_over` 有几条是往日挂到今天的）。
- **不许给同一只票提相反的建议**。`driven_by=risk_rule` 的是**纪律动作不是择时**——给它加「等回踩 / 等反弹 / 等站稳」这类条件就是推翻简报（issue #119）。要推翻必须明写理由和新证据。
- `exec_mode.today_override` 说了 MOO 就不许改写成限价单口径。
- 股数/比例**照抄 `shares`/`pct`，不许换算也不许心算**；`carried_over>0` 时点一句「{n} 条昨日挂单仍未成交」。
- `plan_context` 为 `{}` 说明今天本腿没有未完成决策，按正常写，不要编一个计划出来。
- `plan_context` 里带 `error` 字段说明**计划没读出来，不是今天没有计划**（issue #136）。此时必须在 ▎操作建议 开头写一行「今日计划未取到（{error}），以下建议未与 08:00 简报对账」，并且**不许**顺势断言「今天没有未完成决策」。
- 可选键（#605/#609）：`overridden_by_user` = 用户已 override 的 risk_rule 砍单（已隐藏并结案，**不要再提「该砍未砍」**）；`reinvest_candidates` = 砍/trim 的弹药去向候选（仅当 `open[]` 真有 cut/trim 时出现；是观察不是授权，配对话术照抄候选 ticker 与 trigger，不许虚构「砍 X 的弹药」当 `open[]` 里没有 X）。

🔢 **数字铁律（postflight 会查，见 `check_numeric_claims`）**：散文里出现的每个金额/股数**必须是 context 里已有的数字**，照抄不换算。
- **禁止重述持仓股数、持仓市值、浮盈金额** —— 这些 postflight 已经拼在消息开头了，重述一遍只会多一次说错的机会（2026-07-27 就把 6200 股的仓位写成 1000 股）。**例外且仅此一个**：`plan_context.open[].shares` 是「这一单要动多少股」，照抄它是被要求的；被禁的是「这只票我持有多少股」。两者不是一回事——07226 持仓 6200 股、当日 swap 单 1000 股，同一天同一只票。
- 前瞻性数字（「再跌 2% 会亏多少」）要么**别写**，要么写出算式让人能验；拍一个量级出来是 2026-07-27「再伤 1.5-2 万 HK$」（真实约 1 千）那条 issue #120 的原型。
- 区间必须真实存在：`+0.3~-0.4%` 这种正负打架的区间是编的，postflight 会直接标出来。


▎情绪面 里的**异动归因**（`anomalies` 非空时必写，最多 2 行，写在该段最前）：
- 每只异动票一行：「{票} {幅度}% ← {mover_news 里 signal=interrupt 的标题要点}（{age_minutes} 分钟前 / {source_class}）」。
- `halts` 命中该票 → 先写停牌（`reason_code` + 复牌时间）。
- `mover_thesis` 里该票有 `triggered`/`watch` 红线 → 追一句「触及红线：{required_action}」——**这是归因语境，不是操作许可**，能不能动手仍由 catalyst-gate 与风控契约决定。
- 没有 interrupt：`no_recent_filing` 先查 `known_catalysts[票]`；有则写「窗口内无新公告；沿用今早已知催化：…」，没有才写「窗口内无新公告，且无已知催化，暂无法归因」；`index_fund_no_issuer` 写「指数基金无发行人公告，看成分/板块」；`degraded` 写「催化源未取到」（**不等于「没有消息」**）。一律不许编理由。
- 空间不够时**先砍板块全景的细节，不砍归因**——一次异动没解释，比少列两个同业更贵。

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

⏱ **看到 SIGTERM / exec 超时 ≠ 报告没发出去，别原样再跑一遍。** exec 的 overall-timeout 只杀命令外壳，postflight 子进程还在继续跑，通常微信早发出去了。先读 `memory/.tmp/report-sent-us-{phase}-{今天}.json`：有 `sent_ok` / `tg_ok` 就是已投递，直接把它当 Step 3 的结果输出。（2026-08-13 09:30 港股开盘就是这么让微信收到两条的，#508。postflight 现在有发送前 claim 会挡住第二次真发，输出里会写 `send_claim`，但那一跑仍然是白跑。）

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
- `../tavily-search/SKILL.md` — primary web search tool for news/sentiment/research (do not let the model improvise with Yahoo/Google scraping)
- `portfolio-swarm-review` skill — deep bull/bear/judge debate framework (analysts → researchers → risk debators → trader), inspired by TauricResearch/TradingAgents design; use when single-shot analysis isn't enough
