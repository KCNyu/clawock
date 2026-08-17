---
name: hk-stock-analysis
description: Workspace-aware Hong Kong stock analysis for kcn. Routes through clawock analyze-hk (Tencent primary + Eastmoney full-batch independent cross-check/fallback → stooq → yfinance) for price/技术指标/news, layered with HK-specific concepts — 南向资金, HSTECH 方向, 杠杆 ETF 衰减, 老千股警惕, T+0 无涨跌幅. Use when user asks about a HK ticker (e.g. "分析 00100", "07226 怎么样", "恒科今天"), HK book performance, or HK sector view.
triggers:
  - "分析 {5位港股代码}"
  - "港股 {ticker}"
  - "恒科 / 恒指 / HSTECH"
  - "南向资金"
  - "{ticker} 怎么样"
---

# HK Stock Analysis

Workspace-native Hong Kong stock analyst. Uses the local fetch pipeline for live price + 恒指/恒科 baseline, then layers HK-specific analysis.

## Required reads before answering

In this order:
1. `/root/.openclaw/workspace/MEMORY.md` — data rules, traps, 00100-only-Tencent warning
2. `/root/.openclaw/workspace/TOOLS.md` — HK fallback chain detail, skill routing
3. `/root/.openclaw/workspace/INVESTMENT_SOP.md` — standard startup sequence
4. `/root/.openclaw/workspace/portfolio.json` — if the ticker is in the active book

## Data source rule (non-negotiable)

**Default path — use the workspace script, not web search:**

```bash
# Full analysis: refreshes price + 恒指/恒科基准 + RSI/MA + Finnhub news + signal
/root/.local/bin/clawock analyze-hk {TICKER}
/root/.local/bin/clawock analyze-hk {TICKER} --no-news    # skip news
/root/.local/bin/clawock analyze-hk --no-fetch            # use cached, analysis only
```

**HK fallback chain (inside script):**
1. **Tencent** `qt.gtimg.cn/q=r_hk{CODE}` — primary; batch first, then single-code retry for misses
2. **Eastmoney HK** `push2.eastmoney.com/.../ulist.np/get` (secid prefix 116) — requested for **every ticker** as an independent batch, even when Tencent succeeded. When both succeed, prefer Tencent but compare `c` and `pc`; divergence >1% is stored in `_divergence` and warned on stdout. When Tencent misses, Eastmoney is the first fallback.
3. **stooq.com** CSV — only for tickers still unresolved; same-day OHLCV; **caveat**: new IPOs (e.g. 00100) not covered, `prev_close` approximated from `open`
4. **yfinance** — only for tickers still unresolved; frequently rate-limited, last-resort fallback

**Removed routes (do not retry):**
- ❌ AAStocks / 富途网页 — anti-scraping, not worth the fight; use Tencent

**基本面路由（行情之外，2026-06-14 接入）：** 港股财报/关键指标走东财 datacenter — `clawock fundamentals`（datacenter-web + searchapi 子域实测稳定；行情链的 push2 由共享客户端独立尝试）。详见 Mode 3。⚠️ 资金流 `clawock fundflow` 写好但 push2his 在本服务器 IP 被封，暂不可用。

**Critical trap — 00100 MINIMAX has only Tencent.** As a new IPO it has no stooq/yfinance coverage. If Tencent fails on 00100, say so explicitly before falling back — do not silently use yesterday's cache.

**Web search is only for:** company news, 南向资金 flows, sector policy, peer fundamentals, qualitative thesis — never primary quotes.

## Four analysis modes

### Mode 1 — Quick Read (most common)
**When:** "07226 怎么样" / "00100 今天表现"
1. Run `clawock analyze-hk {TICKER} --no-news`
2. If in active book, pull cost/PnL from `portfolio.json`
3. Output: price, today's move, 恒科/恒指 baseline for context, one-line verdict

### Mode 2 — Technical Read
**When:** Trend / oversold / breakout questions
1. Run `clawock analyze-hk {TICKER} --no-news`
2. Output: trend, RSI-14, MA20/50 stance, support/resistance from recent action, 量价配合 if visible

### Mode 3 — Fundamental + Macro Read
**When:** "00100 估值合理吗" / "金风的业绩"
1. Run script for fresh baseline
2. **本地基本面优先**（东财 datacenter, 中文科目, 无 key — 别再用 web search 抓财报）：
   - 关键指标: `clawock fundamentals {CODE} --indicators` → 近 4 期 ROE/EPS/毛利率/净利率/资产负债率/股息率
   - 三表科目: `clawock fundamentals {CODE} --statements income`（balance/cashflow 同理）
3. Web search 仅补: 行业政策, 同业定性对比, 最新业绩点评（数字以本地为准）
4. Layer in HK-specific macro: 南向资金近一周流向, 港元 HIBOR 走势, 恒科 vs 纳指相对强弱
5. Output: 基本面 + 估值 + 流动性环境 + 风险

### Mode 4 — Sector / Index Read
**When:** "恒科怎么样" / "港股 AI 板块"
1. Pull 恒指 / 恒科 from script's index baseline (script auto-includes ^HSI, ^HSTECH)
2. 南向资金 净流入/流出（web search 当日数据）
3. 板块代表股的相对强弱
4. Output: 大势研判 + 板块归因 + 个股带头/拖累

### Mode 7 — Intraday Check-in (cron-driven, every 30 min, harness 化 ✨)
**When:** 盘中盯盘 cron (`*/30 10-11,14-15 * * 1-5 Asia/Shanghai`，共 8 次/天，已错开 09:30/12:00/13:30/16:00 阶段性报告)，比 Mode 6 更轻量、更高频。

**Harness 4-step**：

#### Step 1: 跑 preflight
```bash
clawock intraday preflight --market hk
```
跑 `clawock analyze-hk --wechat --md-table` + 抽信号 + 异动，输出 `memory/.tmp/intraday-context-hk-latest.json`，并把**同一份 JSON** 打到 stdout（含 `context_id` —— Step 3 要原样回传）。
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
关键字段：`should_alert` (bool) + `alert_reasons` (异动票/STOP 计数等)。另有 `peer_scan`（本腿持仓的板块+同业涨跌，已排序）和 `plan_context`（08:00 简报为本腿定下、尚未成交的决策）。

若 `delivery_mode=unchanged_receipt`：和上一次实际送达相比，风险档位、异动档位、盘中 setup、未成交计划和一级披露均无语义变化。**不要生成散文、不要写 prose/sidecar**，直接运行 `clawock intraday postflight --market hk --context-id {context_id}`。harness 会发送带行情覆盖和一级源检查状态的一行回执；每档仍然可见，不是跳过。成功后输出 `wechat_prefix` + `raw_wechat_block` 并结束。下面 Step 2–2.5 只适用于 `delivery_mode=full_delta`。

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
  - 必须包含：今天该看/该等/该减 + 引用至少 1 个具体数字（票现价 / 异动幅度 / 信号）
  - 📋 **计划对账（`plan_context` 非空时必写 1 行）**：08:00 定下、还没成交的决策就在 `plan_context.open[]` 里——**不要再去 `cat` plan.json 或 decisions.jsonl**（2026-07-27 10:05 那样手刨 6 次还把 swap 股数说错，issue #119/#120）。写「{票} {action} {shares} 股仍挂着 / 已成交」，股数**照抄 `shares` 字段**；`driven_by=risk_rule` 的纪律动作不许被改写成「等回踩再做」；`carried_over>0` 要点名往日挂单。
  - 🔢 **数字铁律**：金额/股数一律**照抄 context**，不换算不心算；**别在 `▎我的看法` 里重述持仓股数或市值**（数据块里已经有了，但 `plan_context.open[].shares` 这种「本单动多少股」是要写的）；前瞻性数字要么给算式要么不写。postflight 的 `check_numeric_claims` 会把 context 里没有的数字和自相矛盾的区间标成 warn（issue #120）。
  - ⚡ **板块全景**：数据**已由 preflight 备好**在 context.json 的 `peer_scan` 里（每个 active ticker 一项：`theme` 板块名、`listed_peers` 已按今日涨幅降序、含 `pct_1d`/`pct_5d`、`divergence_signal`、`self_pct_1d`）。**直接引用它,不要自己去读 peer-map.json、也不要自己调 `clawock fetch-peers`**；给板块今日 Top 5 + 你持仓在榜单里的位置 + 1 句归因;`peer_scan` 为空或缺项时才回退 web search。若某条带 `name_mismatch`,以 feed 名为准并在报告里提一句。持仓自己的数字仍从 context.json。板块行情**优先用内置 web search**；`tavily-search` 仅在**开盘/收盘报告**或盘中真事件时才用，且必带 `--bucket report`/`--bucket intraday`——盘中每 30 分钟的常规盯盘**不要**烧 Tavily（免费档 1000/月全局共享）
  - 禁止"无异动，观望"这种敷衍 1 句话
- 不设字数目标；postflight 只有一道防复读死循环的天花板：>5000 warn，>6000 fail（算的是拼装后的整条消息）

#### Step 2.5: 写 dashboard 状态横幅 sidecar

**规范见 `skills/_shared/intraday-status-sidecar.md`**（hk/us 共用单一来源）—— 写 `memory/.tmp/intraday-insights-{date}.json`（status_banner + 每个异动票 movers 归因，只文本无 key）。
- 本市场杠杆 ETF：**07226**（恒科 2x）等，归因要点明"杠杆放大"。

#### Step 3: 跑 postflight（先写文件，再调用 —— 禁用 heredoc / here-string 重定向）
**必须两步、按顺序**：先用文件写入工具把 Step 2 的散文写到
`memory/.tmp/intraday-prose-hk.md`，确认写入成功后再调用（命令写成一行）：
```bash
clawock intraday postflight --market hk --context-id {Step 1 的 context_id} --text-file /root/.openclaw/workspace/memory/.tmp/intraday-prose-hk.md
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
`memory/.tmp/intraday-sent-hk.json`：`ts` 是本 slot 的、且有 `sent_ok` / `tg_ok`
就是已投递。（2026-08-13 09:30 港股开盘那次双发的机制，#508；postflight 现在有发送前
claim 会挡住第二次真发，但那一跑仍然是白跑。）

校验段标记 + 长度 + 异动票提及（都只校验你写的那段，不校验拼进来的数据块）。
**不提交 `portfolio.json`**；若 dashboard 有语义变化，postflight 会重建并提交
`assets/data/dashboard.json`。每个 slot 的完成/投递状态另写 heartbeat，由 single publisher 发布。

#### Step 4: 输出报告（仅存档；微信已由 postflight 主发，禁用 message 工具）
微信投递已在 **Step 3 的 `intraday_postflight` 用 fresh-token 短连接发出**（cron `--no-deliver`，不 announce）——唯一路径。拼 `wechat_prefix` + 你的散文，**无标题**（高频推送避免刷屏），作为**本回合最终文本回复**输出（仅存档）。**不要调 `message`/send 工具**（postflight 已发，再调会双发）；`intraday_watchdog` 只在 Telegram marker 缺失/失败时补投 Telegram，不重发微信。

**和 Mode 6 的区别**：单段 `▎我的看法` 取代三段；无 ▎风险提示；不提交
`portfolio.json`（但会发布 dashboard 语义变化 + slot heartbeat）；holdings 用 markdown 表格。
**相同点**：两者都是散文模式 —— 数据块由 postflight 拼装，你只写分析。

### Mode 6 — WeChat Briefing (cron-driven, harness 化 ✨)
**When:** 港股开盘/午盘/午后/收盘 4 个 cron job 全部走这个 mode。

**Harness 4-step**（preflight → 散文 → postflight 拼装+投递 → 存档）：

#### Step 1: 跑 preflight
```bash
clawock report preflight --market hk --phase {open|mid|pm|close}
```
内部跑 `clawock analyze-hk --wechat`，抽信号 (WATCH/STOP/TRIM 计数) + 异动 (≥3% 涨跌) + 恒指/恒科方向，写 context 文件，并把**同一份 JSON** 打到 stdout（含 `context_id`；末行是 `context_path:`）。若输出 `market_closed`，本回合到此结束。

#### Step 2: 只写分析散文

**你不写数据块、不写表格、不写标题** —— postflight 自己从 context 拼。2026-07-24 之前是让模型 verbatim 拷贝数据块，结果模型读错 context 就把一天前的数字发了出去；现在那条回路已经拆掉，数字在发送时刻直接取自 context 文件。

用 stdout 里的字段：`signal_count` / `anomalies` / `index_direction` / `needs_risk_section` / `peer_scan` / `plan_context`（08:00 简报还没执行完的决策，见下）/ `mover_news`（异动票的一手催化）/ `mover_thesis`（异动票的 thesis 与红线）（板块 + 同业 Top 5 今日/5日涨跌 + 背离信号，板块全景段直接用它）；`raw_wechat_block` 是给你参考数字用的，**不要抄进散文**。

⚠️ **`plan_context` 对账（非空时 ▎操作建议 必写，写在该段最前）**：里面是 08:00 简报为本腿定下、**还没成交**的决策（`open[]`：`ticker`/`action`/`shares`/`pct`/`condition`/`confidence`/`driven_by`/`rationale`，外加 `exec_mode` 当日执行方式、`carried_over` 有几条是往日挂到今天的）。
- **不许给同一只票提相反的建议**。`driven_by=risk_rule` 的是**纪律动作不是择时**——给它加「等回踩 / 等反弹 / 等站稳」这类条件就是推翻简报，2026-07-27 09:30 就这么把一条 4 重 breach 的 swap 写成了「回踩 -1% 再减」（issue #119）。要推翻必须明写理由和新证据。
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

写这几段，**存成 `memory/.tmp/report-prose-hk-{phase}.md`**：
```
▎情绪面
{Finnhub 新闻 + 恒指/恒科方向 → 大盘判断（2-3 行）；⚡ **板块全景**：用 peer_scan 写今日板块 Top 5 + 你持仓位置 + 1 句归因。行情优先内置 web search；tavily 仅开盘/收盘或真事件用，带 `--bucket report`，盘中常规盯盘不烧 Tavily}

▎技术面
{结合 anomalies + signals → 超买/超卖/突破（2-3 行）}

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
clawock report postflight --market hk --phase {phase} --context-id {Step 1 的 context_id} --text-file /root/.openclaw/workspace/memory/.tmp/report-prose-hk-{phase}.md
```
`--context-id` 必须是 Step 1 打印的那个：不匹配说明 context 已被换代（散文和数据不同代），postflight 拒绝拼装、只发数据块。散文文件超过 30 分钟没更新同样拒发。返回 JSON 含 `status` (pass/warn/fail)。pass/warn 自动拼装+发送+刷新 snapshot/dashboard，提交 scoped 产物并经 `ops/publish/safe_push.sh` 推送。

⏱ **看到 SIGTERM / exec 超时 ≠ 报告没发出去，别原样再跑一遍。** exec 的 overall-timeout 只杀命令外壳，postflight 子进程还在继续跑，通常微信早发出去了。先读 `memory/.tmp/report-sent-hk-{phase}-{今天}.json`：有 `sent_ok` / `tg_ok` 就是已投递，直接把它当 Step 3 的结果输出。（2026-08-13 09:30 港股开盘就是这么让微信收到两条的，#508。postflight 现在有发送前 claim 会挡住第二次真发，输出里会写 `send_claim`，但那一跑仍然是白跑。）

#### Step 4: 输出报告（仅存档；微信已由 postflight 主发，禁用 message 工具）
微信投递已在 **Step 3 的 `report_postflight` 用 fresh-token 短连接发出**——这是
**唯一微信路径**（cron 设 `--no-deliver`，不再 announce），同时会镜像 Telegram。
把 postflight 返回的 `status` + `issues` 作为**本回合最终文本回复**输出即可（仅留痕）。
**不要调 `message`/send 工具**；`report_watchdog` 只在 Telegram marker 缺失/失败时
补投 Telegram，不重发微信。

**标题模板**（preflight 已生成在 context.json，直接用）：
- 开盘 09:30 HKT：`📊 港股开盘快报｜{date} 09:30`
- 午盘 12:00 HKT：`☕ 港股午盘快报｜{date} 12:00`
- 午后 13:30 HKT：`🌤 港股午后快报｜{date} 13:30`
- 收盘 16:00 HKT：`🔔 港股收盘日报｜{date}`

**硬性规则**：
- ⚠️ 数据缺口必须明说，禁止编造（postflight 会扫敷衍词）
- **00100 MINIMAX 只有 Tencent 一个源**，失败必须明说"实时价获取失败"
- 不用 `message` 工具 — 微信由 Step 3 的 `report_postflight` fresh-token 主发（cron `--no-deliver`），手动再调会和 postflight 双发；本回合回复文本仅存档
- 不简单复述数字，必须做模型自己的解读
- 异动票（anomalies 字段）**必须在报告里被提到**（postflight 强制）
- 不设字数目标；拼装全文只有一道防复读死循环的天花板（>5000 warn，>6000 fail）

### Mode 5 — Sentiment / 情绪面 Read
**When:** "市场怎么看 X" / "雪球怎么聊 00100" / "港股情绪" / before sizing

港股情绪面跟美股不同 — 主战场是中文社区（雪球/富途牛牛/同花顺论坛/微博），不在 Reddit/X。源使用顺序：

1. **Finnhub news（脚本带）** — `clawock analyze-hk {TICKER}` 默认拉 Finnhub 7 天新闻。港股覆盖比美股稀疏，但能拿到主要英文媒体（Reuters / Bloomberg / SCMP）
2. **Tavily 中文搜索** — 主要的中文新闻聚合。⚠️ **Budget rule**(免费档 1000/月全局共享)：盘中每 30 分钟盯盘**默认不调**；仅**开盘/收盘报告**或盘中真事件(异常波动/停牌/财报预警/政策公告)才用，必带 `--bucket report`(开/收盘) 或 `--bucket intraday`(盘中事件)；额度尽时脚本 exit 0 返回 unavailable 别当报错：
   ```bash
   node /root/.openclaw/workspace/skills/tavily-search/scripts/search.mjs "{TICKER} 港股 最新" --topic news --days 3 --bucket report
   node /root/.openclaw/workspace/skills/tavily-search/scripts/search.mjs "{中文公司名} 雪球 讨论" --bucket report
   ```
3. **雪球 HK 评论区（scrapling）** — 港股零售情绪核心，5 位代码格式 `HK{TICKER}`：
   ```python
   from scrapling.fetchers import StealthyFetcher
   sp = StealthyFetcher.fetch(f"https://xueqiu.com/S/HK{TICKER}", headless=True)
   # 取最近讨论标题 + 多/空票数 + 评论热度
   ```
4. **富途牛牛社区** — 同样的中文零售情绪源：
   ```python
   sp = StealthyFetcher.fetch(f"https://www.futunn.com/stock/{TICKER}-HK", headless=True)
   ```
5. **南向资金净流入** — 跟单只股没直接关系，但是港股大盘情绪的硬指标，Tavily 搜"南向资金 {date}"

Output:
- **Sentiment score**: -1 (极度看空) 到 +1 (狂热)；明确标注跟价格的背离（"涨了但雪球普遍看空 = 空头未投降" 之类）
- **Key narratives**（2-3 条）：中文社区的核心叙事，跟英文媒体可能不同
- **南向资金 context**：当日净流入 / 近一周累计，作为情绪锚
- **Volume signal**：讨论帖数 vs 上周平均 — 升温 / 冷淡

**港股专属警示**：
- 中文社区"庄"、"洗盘"、"游资"等词高频出现 → 短线 sentiment，不要当基本面信号
- 老千股嫌疑标的（频繁配股 / 长期阴跌）在雪球往往有专门骂帖，这些是早期信号
- 00100 这种新 IPO 在雪球评论区流量大但样本偏，给情绪打分时降权

## HK-specific concepts to apply

| Concept | When to use | How to apply |
|---|---|---|
| **南向资金** | Tone-setting for HK sessions | 流入 → 内资定价权强 / 流出 → 外资抛压. Quote daily net figure when available. |
| **HIBOR / 港元汇率** | Liquidity environment | HIBOR 升 = 流动性收紧 = 港股估值压力, 尤其打击高估值科技股 |
| **恒科 vs 纳指联动** | 03032 / 07226 / 03033 / 09988 / 00700 etc. | 美股科技夜盘强 → 次日恒科开盘往往跟随；联动断裂时单独分析 |
| **T+0 + 无涨跌幅** | Risk sizing on all HK | 单日波动可远超 A 股. 杠杆 ETF（07226 2x）单日 ±5-10% 是常态 |
| **老千股警惕** | 任何新接触的小市值标的 | 频繁配股 / 1-供-N / 历史多次合股 / 股价长期阴跌 → 排除. 现役持仓不在此列 |
| **杠杆 ETF 衰减** | 07226 (2x恒科), 类似 SOXL/TQQQ | 震荡市衰减明显, 强趋势市才适合多日持有. 默认按短线对待 |

## Output style (kcn-tuned)

- **直接判断, 不绕弯.** "07226 RSI 76 短期太高, 反弹位减仓"  优于 "may be approaching overbought territory"
- **表格优先.** 3 个以上数据点必用表
- **数据时效必须标注.** 收盘后给数据要说"收盘价"; 盘中给要说"实时"
- **失败要明说.** Tencent 挂了 → "00100 取价失败, 以下基于昨日收盘"

## Critical reminders (从 workspace MEMORY 同步)

- 港股交易时段: HKT 09:30-12:00 / 13:00-16:00 (北京时间同)
- 北京时间 16:02 = 港股刚收盘 (不是 still trading)
- 00100 是新 IPO, 数据源单一; PLTU/RKLX 这类美股新 IPO 同理但有 Nasdaq 兜底
- 港股核心驱动 (per MEMORY.md): 恒科指数方向 + 个股逻辑 (00100 AI / 02208 风电政策)

## Examples

**User:** "00100 怎么样"
**Approach:** Mode 1 — `clawock analyze-hk 00100 --no-news`, 注意 Tencent 是唯一源, 失败要明说; 输出价 + PnL + 一句话判断

**User:** "恒科今天什么情况"
**Approach:** Mode 4 — 拉 ^HSTECH 走势, 加南向资金当日数据, 列出 03032/07226 等代表股表现, 一段大势判断

**User:** "02208 估值"
**Approach:** Mode 3 — 跑脚本, web 搜风电政策最新动向 + 同业 (龙源/中广核新能源) 对比, 给估值区间

## Reference files (lazy-load)

港股跟美股共享的市场无关教育内容，全部在 `../us-stock-analysis/references/`：
- `../us-stock-analysis/references/technical-analysis.md` — RSI / MACD / MA / 形态定义
- `../us-stock-analysis/references/fundamental-analysis.md` — 业务质量 / 财务健康度 / 估值框架
- `../us-stock-analysis/references/financial-metrics.md` — 比率公式
- `../us-stock-analysis/references/report-template.md` — Full Report 结构骨架

## Companion tools

- `../scrapling/SKILL.md` — 当 Tencent/Eastmoney/stooq/yfinance 全挂 或需要抓雪球/富途社区时
- `../tavily-search/SKILL.md` — 中文新闻 / 南向资金数据 / 政策搜索的首选 web 搜索
- `/root/.openclaw/workspace/TradingAgents/` — 用户已克隆的 TauricResearch 多 agent 框架。深度分析需要 bull/bear debate 时可参考其 agent 角色设计
