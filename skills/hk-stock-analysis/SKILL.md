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

交互问题（Modes 1-5）的共同前提两市场共用一份：先 read `../_shared/interactive-mode-reads.md`；下面按市场列出本轮要读的路径。

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
2. **Eastmoney HK** `push2.eastmoney.com/.../ulist.np/get` (secid prefix 116) — requested for **every ticker** as an independent batch, even when Tencent succeeded. When both succeed, prefer Tencent but compare `c` and `pc`; divergence >1% is persisted as holding `quote_divergence`, disclosed in `data_source`, and surfaced as an integrity `QUOTE_DIVERGENCE` WARN (also printed on stdout); a fresh quote clears the prior verdict when no divergence is reported. When Tencent misses, Eastmoney is the first fallback.
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

### Mode 7 — 盘中盯盘（cron，每 30 分钟）

本节只是路由。Mode 7 正文两市场共用一份：`skills/_shared/intraday-mode7.md`；cron 任务（`config/cron-payloads/intraday.md`，market=hk）第一轮直接 `read` 那份正文和 `skills/_shared/intraday-status-sidecar.md`，不读本文件。盘中规则只改那一份，这里不复述；人工对话里被问到盘中盯盘规则时也去读它。

### Mode 6 — 定时市场报告

港股开盘、午盘、午后和收盘共用。对应市场怎么看，见 `../_shared/report-analysis-hk.md`；写法见 `../_shared/report-prose-rules.md`。定时执行、投递和故障恢复按 `config/cron-payloads/report.md`。

#### Step 1: 跑 preflight

手工运行用 `clawock report preflight --market hk --phase {open|mid|pm|close}` 并保留同代 `context_id`。

#### Step 2: 只写分析散文

按上面的分析和写作指针完成正文，保存到 Step 3 使用的文本路径。

#### Step 3: 跑 postflight

`clawock report postflight --market hk --phase {phase} --context-id <context_id> --text-file <正文路径>`。最终回执和等待方式见报告任务正文 Step 3–4。

### Mode 5 — Sentiment / 情绪面 Read
**When:** "市场怎么看 X" / "雪球怎么聊 00100" / "港股情绪" / before sizing

港股情绪面跟美股不同 — 主战场是中文社区（雪球/富途牛牛/同花顺论坛/微博），不在 Reddit/X。源使用顺序：

1. **Finnhub news（脚本带）** — `clawock analyze-hk {TICKER}` 默认拉 Finnhub 7 天新闻。港股覆盖比美股稀疏，但能拿到主要英文媒体（Reuters / Bloomberg / SCMP）
2. **中文 web 搜索：DeepSeek + Tavily** — `clawock web-search` 同时问两个源，各自一节、各自标状态（并列的两个源，不是主备）。限额各算各的：
   - **DeepSeek**：无 credits 预算，账号级 5 QPS（本机统一限速），盘中也可随时用：`clawock web-search "{中文公司名} 港股 最新" --providers deepseek --days 3`
   - **Tavily** ⚠️ 免费档 1000/月全局共享：只在**开盘/收盘报告**或盘中真事件(异常波动/停牌/财报预警/政策公告)时一起跑；Mode 7 cron 盘中盯盘的模型**不调** Tavily（harness 已检索，读 `anomaly_search`，见 Mode 7）。必带 `--bucket report`(开/收盘) 或 `--bucket intraday`(盘中事件)：
   ```bash
   clawock web-search "{TICKER} 港股 最新" --days 3 --bucket report
   clawock web-search "{中文公司名} 雪球 讨论" --bucket report
   ```
   某个源 exit 0 返回 unavailable 别当报错，写明哪个源没取到。雪球/富途/公众号是 JS 渲染或反爬页面，搜索只拿到索引摘要，正文仍要下面的 scrapling；拿不到就明说缺口。
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
5. **南向资金净流入** — 跟单只股没直接关系，但是港股大盘情绪的硬指标，`clawock web-search "南向资金 {date}" --providers deepseek` 搜

Output:
- **Sentiment score**: -1 (极度看空) 到 +1 (狂热)；明确标注跟价格的背离（"涨了但雪球普遍看空 = 空头未投降" 之类）
- **Key narratives**（2-3 条）：中文社区的核心叙事，跟英文媒体可能不同
- **南向资金 context**：当日净流入 / 近一周累计，作为情绪锚
- **Volume signal**：讨论帖数 vs 上周平均 — 升温 / 冷淡

**港股专属警示**：
- 中文社区"庄"、"洗盘"、"游资"等词高频出现 → 短线 sentiment，不要当基本面信号
- 老千股嫌疑标的（频繁配股 / 长期阴跌）在雪球往往有专门骂帖，这些是早期信号
- 00100 这种新 IPO 在雪球评论区流量大但样本偏，给情绪打分时降权

## 港股判断框架与数据陷阱

见 [港股定时报告分析准则](../_shared/report-analysis-hk.md)，用于报告和直接分析。直聊输出和工作流按对应 Mode。

## Examples

**User:** "00100 怎么样"
**Approach:** Mode 1 — `clawock analyze-hk 00100 --no-news`, 注意 Tencent 是唯一源, 失败要明说; 输出价 + PnL + 一句话判断

**User:** "恒科今天什么情况"
**Approach:** Mode 4 — 拉 ^HSTECH 走势, 加南向资金当日数据, 列出 03032/07226 等代表股表现, 一段大势判断

**User:** "02208 估值"
**Approach:** Mode 3 — 跑脚本, web 搜风电政策最新动向 + 同业 (龙源/中广核新能源) 对比, 给估值区间

## Shared output contract

For interactive technical, fundamental or full reports, use
`../_shared/stock-analysis-output.md` for evidence, units, uncertainty and output scope.

## Companion tools

- `../scrapling/SKILL.md` — 当 Tencent/Eastmoney/stooq/yfinance 全挂 或需要抓雪球/富途社区时
- `../tavily-search/SKILL.md` — 中文新闻 / 南向资金数据 / 政策搜索的可选配置入口；skill 名是 `tavily`，catalog/key 不可用或脚本返回 unavailable 时用当前会话可用搜索
- `/root/.openclaw/workspace/TradingAgents/` — 用户已克隆的 TauricResearch 多 agent 框架。深度分析需要 bull/bear debate 时可参考其 agent 角色设计
