---
name: hk-stock-analysis
description: Workspace-aware Hong Kong stock analysis for kcn. Routes through scripts/data/analyze_hk_stocks.py (Tencent primary + Eastmoney full-batch independent cross-check/fallback → stooq → yfinance) for price/技术指标/news, layered with HK-specific concepts — 南向资金, HSTECH 方向, 杠杆 ETF 衰减, 老千股警惕, T+0 无涨跌幅. Use when user asks about a HK ticker (e.g. "分析 00100", "07226 怎么样", "恒科今天"), HK book performance, or HK sector view.
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
python3 /root/.openclaw/workspace/scripts/data/analyze_hk_stocks.py {TICKER}
python3 /root/.openclaw/workspace/scripts/data/analyze_hk_stocks.py {TICKER} --no-news    # skip news
python3 /root/.openclaw/workspace/scripts/data/analyze_hk_stocks.py --no-fetch            # use cached, analysis only
```

**HK fallback chain (inside script):**
1. **Tencent** `qt.gtimg.cn/q=r_hk{CODE}` — primary; batch first, then single-code retry for misses
2. **Eastmoney HK** `push2.eastmoney.com/.../ulist.np/get` (secid prefix 116) — requested for **every ticker** as an independent batch, even when Tencent succeeded. When both succeed, prefer Tencent but compare `c` and `pc`; divergence >1% is stored in `_divergence` and warned on stdout. When Tencent misses, Eastmoney is the first fallback.
3. **stooq.com** CSV — only for tickers still unresolved; same-day OHLCV; **caveat**: new IPOs (e.g. 00100) not covered, `prev_close` approximated from `open`
4. **yfinance** — only for tickers still unresolved; frequently rate-limited, last-resort fallback

**Removed routes (do not retry):**
- ❌ AAStocks / 富途网页 — anti-scraping, not worth the fight; use Tencent

**基本面路由（行情之外，2026-06-14 接入）：** 港股财报/关键指标走东财 datacenter — `fetch_fundamentals_em.py`（datacenter-web + searchapi 子域实测稳定；行情链的 push2 由共享客户端独立尝试）。详见 Mode 3。⚠️ 资金流 `fetch_fundflow_em.py` 写好但 push2his 在本服务器 IP 被封，暂不可用。

**Critical trap — 00100 MINIMAX has only Tencent.** As a new IPO it has no stooq/yfinance coverage. If Tencent fails on 00100, say so explicitly before falling back — do not silently use yesterday's cache.

**Web search is only for:** company news, 南向资金 flows, sector policy, peer fundamentals, qualitative thesis — never primary quotes.

## Four analysis modes

### Mode 1 — Quick Read (most common)
**When:** "07226 怎么样" / "00100 今天表现"
1. Run `scripts/data/analyze_hk_stocks.py {TICKER} --no-news`
2. If in active book, pull cost/PnL from `portfolio.json`
3. Output: price, today's move, 恒科/恒指 baseline for context, one-line verdict

### Mode 2 — Technical Read
**When:** Trend / oversold / breakout questions
1. Run `scripts/data/analyze_hk_stocks.py {TICKER} --no-news`
2. Output: trend, RSI-14, MA20/50 stance, support/resistance from recent action, 量价配合 if visible

### Mode 3 — Fundamental + Macro Read
**When:** "00100 估值合理吗" / "金风的业绩"
1. Run script for fresh baseline
2. **本地基本面优先**（东财 datacenter, 中文科目, 无 key — 别再用 web search 抓财报）：
   - 关键指标: `python3 scripts/data/fetch_fundamentals_em.py {CODE} --indicators` → 近 4 期 ROE/EPS/毛利率/净利率/资产负债率/股息率
   - 三表科目: `python3 scripts/data/fetch_fundamentals_em.py {CODE} --statements income`（balance/cashflow 同理）
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
python3 /root/.openclaw/workspace/scripts/harness/intraday_preflight.py --market hk
```
跑 `scripts/data/analyze_hk_stocks.py --wechat --md-table` + 抽信号 + 异动，输出 `memory/.tmp/intraday-context-hk-latest.json`。
关键字段：`should_alert` (bool) + `alert_reasons` (异动票/STOP 计数等)。另有 `peer_scan`（本腿持仓的板块+同业涨跌，已排序）。

#### Step 2: 写报告
- 拷贝 `raw_wechat_block` 到消息开头（**verbatim — 不许改格式不许 trim**）
  - intraday 的 holdings 是 **markdown 表格**（7 列：代码/股/成本/现价/今日/浮%/浮$，右对齐数字。走 `scripts/data/_wechat_table.py` 的 visual-width-aware 渲染，去 HK$ 前缀 + 加 浮$ 金额列）
  - ⚠️ **表格的 3 类行（表头 / 分隔 `|:--|--:|...|` / 每条数据）每一字符 1:1 复制**，不要数列重写分隔行 — 5/21 后多次因 LLM 自己写分隔行少一段 `--:|` 导致渲染失败（postflight 会 fail）
  - **市值/浮盈/今日 已经是单行用 `|` 分隔的格式** — 不要拆 3 行
  - **`📉 亏损持仓 X/Y | 2x杠杆敞口 N%` 必须保留**，不要省
- 加 `▎我的看法` 段：**至少 60 字（postflight 软下限），目标 2-3 行**
  - 若 `should_alert=true`，**必须**提到 `anomalies` 里至少一个票
  - 必须包含：今天该看/该等/该减 + 引用至少 1 个具体数字（票现价 / 异动幅度 / 信号）
  - ⚡ **板块全景**：数据**已由 preflight 备好**在 context.json 的 `peer_scan` 里（每个 active ticker 一项：`theme` 板块名、`listed_peers` 已按今日涨幅降序、含 `pct_1d`/`pct_5d`、`divergence_signal`、`self_pct_1d`）。**直接引用它,不要自己去读 peer-map.json、也不要自己调 `fetch_peers.py`**；给板块今日 Top 5 + 你持仓在榜单里的位置 + 1 句归因;`peer_scan` 为空或缺项时才回退 web search。若某条带 `name_mismatch`,以 feed 名为准并在报告里提一句。持仓自己的数字仍从 context.json。板块行情**优先用内置 web search**；`tavily-search` 仅在**开盘/收盘报告**或盘中真事件时才用，且必带 `--bucket report`/`--bucket intraday`——盘中每 30 分钟的常规盯盘**不要**烧 Tavily（免费档 1000/月全局共享）
  - 禁止"无异动，观望"这种敷衍 1 句话
- 目标 ≤1200 字；>2000 字 postflight warn，>2500 字 fail

#### Step 2.5: 写 dashboard 状态横幅 sidecar

**规范见 `skills/_shared/intraday-status-sidecar.md`**（hk/us 共用单一来源）—— 写 `memory/.tmp/intraday-insights-{date}.json`（status_banner + 每个异动票 movers 归因，只文本无 key）。
- 本市场杠杆 ETF：**07226**（恒科 2x）等，归因要点明"杠杆放大"。

#### Step 3: 跑 postflight
```bash
python3 /root/.openclaw/workspace/scripts/harness/intraday_postflight.py --market hk <<< "{报告}"
```
校验段标记 + 长度 + 异动票提及。**不提交 `portfolio.json`**；若 dashboard
有语义变化，postflight 会重建并提交 `assets/data/dashboard.json`。每个 slot 的
完成/投递状态另写 heartbeat，由 single publisher 发布。

#### Step 4: 输出报告（仅存档；微信已由 postflight 主发，禁用 message 工具）
微信投递已在 **Step 3 的 `intraday_postflight` 用 fresh-token 短连接发出**（cron `--no-deliver`，不 announce）——唯一路径。拼 `wechat_prefix` + 报告，**无标题**（高频推送避免刷屏），作为**本回合最终文本回复**输出（仅存档）。**不要调 `message`/send 工具**（postflight 已发，再调会双发）；`intraday_watchdog` 只在 Telegram marker 缺失/失败时补投 Telegram，不重发微信。

**和 Mode 6 的区别**：单段 `▎我的看法` 取代三段；无 ▎风险提示；不提交
`portfolio.json`（但会发布 dashboard 语义变化 + slot heartbeat）；holdings 用 markdown 表格。

### Mode 6 — WeChat Briefing (cron-driven, harness 化 ✨)
**When:** 港股开盘/午盘/午后/收盘 4 个 cron job 全部走这个 mode。

**Harness 4-step**（preflight → LLM → postflight → wechat）：

#### Step 1: 跑 preflight
```bash
python3 /root/.openclaw/workspace/scripts/harness/report_preflight.py --market hk --phase {open|mid|pm|close}
```
内部跑 `scripts/data/analyze_hk_stocks.py --wechat`，抽信号 (WATCH/STOP/TRIM 计数) + 异动 (≥3% 涨跌) + 恒指/恒科方向，输出 `memory/.tmp/report-context-hk-{phase}-{date}.json`。

#### Step 2: 读 context，写报告
```bash
cat /root/.openclaw/workspace/memory/.tmp/report-context-hk-{phase}-$(date +%Y-%m-%d).json
```

context.json 关键字段：
- `raw_wechat_block` — 脚本数据块，**verbatim 拷贝到消息开头**。⚠️ 若含 markdown 表格（7 列 holdings），**表头/分隔/数据三类行每字符 1:1 复制**，不要重写分隔行 — 列数必须一致，postflight 会 fail。
- `title` — WeChat 标题（按 phase 自动选）
- `signal_count` / `anomalies` / `index_direction` — 用于写分析段
- `peer_scan` — 每持仓的板块 + 同业今日/5日涨跌(已排序)+ 背离信号,**板块全景段直接用它**
- `needs_risk_section` — STOP+TRIM ≥ 2 时为 true，必须加 ▎风险提示 段
- `commit_msg` — postflight 用

报告结构（postflight 会校验）：
```
{title}

{raw_wechat_block 原样}

▎情绪面
{Finnhub 新闻 + 恒指/恒科方向 → 大盘判断（2-3 行）；⚡ **板块全景**：读 context.json 的 `peer_scan`（已含 theme + 排好序的同业涨跌），今日板块 Top 5 + 你持仓位置 + 1 句归因。行情优先内置 web search；tavily 仅开盘/收盘或真事件用，带 `--bucket report`/`intraday`，盘中常规盯盘不烧 Tavily}

▎技术面
{结合 anomalies + signals → 超买/超卖/突破（2-3 行）}

▎操作建议
{具体票 + 价位；如 needs_risk_section 加 ▎风险提示}
```

#### Step 3: 跑 postflight
```bash
python3 /root/.openclaw/workspace/scripts/harness/report_postflight.py --market hk --phase {phase} <<< "{完整报告文本}"
```
返回 JSON 含 `status` (pass/warn/fail) + `wechat_prefix`。pass/warn 自动刷新
snapshot/dashboard，提交 scoped 产物并经 `safe_push.sh` 推送。

#### Step 4: 输出报告（仅存档；微信已由 postflight 主发，禁用 message 工具）
微信投递已在 **Step 3 的 `report_postflight` 用 fresh-token 短连接发出**——这是
**唯一微信路径**（cron 设 `--no-deliver`，不再 announce），同时会镜像 Telegram。
把 `wechat_prefix` 拼到完整报告前面作为**本回合最终文本回复**输出即可（仅留痕）。
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
- 目标 ≤1200 字；>2000 字 postflight warn，>2500 字 fail

### Mode 5 — Sentiment / 情绪面 Read
**When:** "市场怎么看 X" / "雪球怎么聊 00100" / "港股情绪" / before sizing

港股情绪面跟美股不同 — 主战场是中文社区（雪球/富途牛牛/同花顺论坛/微博），不在 Reddit/X。源使用顺序：

1. **Finnhub news（脚本带）** — `scripts/data/analyze_hk_stocks.py {TICKER}` 默认拉 Finnhub 7 天新闻。港股覆盖比美股稀疏，但能拿到主要英文媒体（Reuters / Bloomberg / SCMP）
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
**Approach:** Mode 1 — `scripts/data/analyze_hk_stocks.py 00100 --no-news`, 注意 Tencent 是唯一源, 失败要明说; 输出价 + PnL + 一句话判断

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
