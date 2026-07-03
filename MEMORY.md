# MEMORY.md - Rick's Long-Term Memory

## 用户偏好

### 持仓分析风格
- **直接分析当前持仓**：用 `portfolio.json` 成本 vs 实时价计算盈亏
- 忽略 `trades` 字段的历史操作，focus 当前仓位
- 简洁直接，不交代背景
- **风险偏好：激进型**，可用现金约 15万人民币（≈$20,500 USD）
- **重点：港股**（持仓、节奏、机会），美股作为补充观察
- 表格优先，能用结构化展示就不用大段文字

### 投资问题工作流
凡是问到 `持仓` / `portfolio` / `美股` / `港股` / `加仓/减仓`，按顺序读：
1. `portfolio.json`（权威持仓）
2. `memory/current-portfolio-summary.md`（ticker 列表）
3. 最近 1-3 篇 `memory/YYYY-MM-DD.md`
4. 工作流细节见 `INVESTMENT_SOP.md`

---

## ⚠️ 数据规则（铁律 — 本文件是唯一权威）

**每次问持仓/股价/盈亏，先实时抓取，再回答。**

### 1. 不用缓存价
- **禁止用 portfolio.json 的 `current_price` 计算盈亏** — 那是上次更新的旧数据
- 必须先跑 `scripts/data/analyze_{us,hk}_stocks.py`（fallback 链详情见 `TOOLS.md` § 数据源清单）
- 所有源均失败 → 明确说"数据获取失败，以下为旧数据"，**禁止静默使用**
- 数据成功后 → 更新 `portfolio.json` + git commit
- 教训：2026-05-11 用缓存价 RKLB 写成 $110 vs 实时 $118，盈利 +$790 错写成 +$550

### 2. FX 铁律 — HKD + USD 不能直接相加
- 港股 book 用 HKD，美股 book 用 USD — **绝不直接相加**
- 所有 book-level 数字必须**双视角**：USD-base + HKD-base，显式标注 rate / source / fetched_at
- 工具：`python3 scripts/data/fetch_fx.py --json` （3 路 fallback，4h 缓存）
- 教训：2026-05-16 deep brief 把 -4936 HKD + +513 USD = -4423 直接相加 → 数字毫无意义

### 3. 已知数据坑
- **00100 MINIMAX 只有 Tencent 一个源**，新 IPO 其他源没数据；Tencent 失败必须明说
- 收盘后 live-quote API 会把 `PreviousClose` 更新为当日收盘价，导致 `today_change = 0`；脚本已修（Polygon `/prev` 独立拉前收 + dp% 反推兜底），`today_change` 字段可直接信任
- **盘后 closed fetch（20:00+ ET）撞 Nasdaq 杠杆 ETF 报价坑**：`lastSalePrice` 停在前一日旧价、`PreviousClose` 反装当日真实收盘 → 价格错位一日 + `today_change` 反号（2026-05-29 MSFU/PLTU 被记成大跌实为大涨）。识别：活跃美股全部 `open==high==low==current` 退化报价。修法见 `memory/openclaw-us-postclose-stale-price-swap.md`（重抓自愈 + Nasdaq netChange 补 today_change + refresh_today_snapshot）
- 新浪美股接口境外 403，跳过不试

### 4. 数字与断言铁律（钱相关，kcn 反复当场抓错 → 列为硬闸）
- **成本基准只认 `portfolio.json` holdings[].cost（实际买入价）**：浮盈/浮%/今日盈亏/盈亏金额一律以它为基准。**绝不**用 IPO 参考价/上市首日价/前收/现价冒充成本。教训：SPCX 用 IPO 参考价当 prev_close 算出错误 `today_change +135`，kcn 当场抓。
- **状态断言先核实数再说，禁编造**："新高/历史最高/历史低位/XX 区域/突破/接近前高"这类话**必须先核 `memory/snapshots/` + `portfolio.json` 真实数字**才能下；不许凭记忆、语感或新闻语气脑补。不确定就写"待核"，别给一个听起来对的假断言。教训：RKLB「新高区域」纯属编造被 kcn 抓。
- **每个关键数字能指出来源 file:field**（成本→holdings、前收→Polygon `/prev`、市值→total_current_value…）；报数字时心里先过一遍来源，报不出来源的数字不报。

---

## 脚本与降级 curl 的关系

**默认走脚本**（`scripts/data/analyze_us_stocks.py` / `scripts/data/analyze_hk_stocks.py` / `scripts/data/fetch_us_stocks.py`），它们封装了 provider 顺序、URL pattern、Eastmoney 前缀、prev_close 独立链、各种字段污染兜底——这些是反复踩坑攒下来的，能用就别绕。

**脚本不覆盖时可以 curl，但要先学再 curl：**
- 场景：查非持仓 ticker / 指数成分 / 突发数据源切换 / 调试 fallback 某一路
- 步骤：先 grep / 打开相关脚本，看里面的 URL、header、解析片段、fallback 顺序，再决定 curl 怎么写
- 即使是 `TOOLS.md` 标"已废弃"的脚本（`scripts/legacy/stock_analyzer.py` / `scripts/legacy/hk_stock_fetcher.py` / `hk_monitor*.py` 等），**作为参考代码仍然可以读**，里面有早期 fallback 思路和被淘汰原因的线索
- 永远跳过：新浪美股接口（境外 403）

**Why:** "瞎拉数据"是只看官方文档闭眼写 curl，会重新踩 PreviousClose 污染、Eastmoney 前缀、Sina 境外 403、yfinance 限速这些坑；"自主退化"是脚本里已经写明白的东西先学完，curl 只用来填脚本没覆盖的边缘场景。

---

## 时区
- 港股：HKT 09:30-12:00 / 13:00-16:00（北京时间同）
- 美股：ET 09:30-16:00（北京时间 21:30 ~ 次日 04:00）
- 北京时间 21:39 = 美股刚开盘，不是收盘
- 北京时间 16:02 = 港股刚收盘

---

## 关键市场联动
- 油价↓（地缘缓和）↔ 加密/科技涨
- CRCL：GENIUS Act 稳定币法案推进，相对独立于大盘
- 港股核心驱动：恒科指数方向 + 个股逻辑（00100 AI、02208 风电政策）

---

## OpenClaw CLI 注意事项

### `openclaw cron` / `gateway status` 等子命令会卡死
- **原因**：通过 WebSocket RPC 连接 gateway(:18789)，在 agent exec 沙箱里无法完成 auth 握手
- **解决**：
  - 查 cron → 直接读 `~/.openclaw/cron/jobs.json`
  - 查 gateway → `curl http://127.0.0.1:18789/health`
  - 查 dreaming → `jobs.json` 里找 `managed-by=memory-core`

### ⚠️ brief 投递铁律 — WeChat 只发紧凑卡 + 链接，**绝不贴完整 brief 全文**
- **brief cron Step 6：只输出 ≤1.5KB 紧凑卡**（核心结论 + Book + ≤3 动作 + 触发位 + 当日全文链接 `https://kcnyu.github.io/clawock/memory/{date}-pre-open.html`），**一次性整段输出即结束**，不调 message 工具、不中途插"让我构造/输出"元叙述。
- **绝不把 pre-open.md 全文(~14-17KB)糊进微信。** 完整 brief 照常写进 pre-open.md → commit → dashboard/briefs 页看（深度不变，全文不裁）。
- **教训：2026-05-31** 让 mimo 把完整 brief 作为最终消息吐出 → **复读死循环**（"Now let me output the WeChat message…"复读几十遍被当回复发出，kcn 收到一屏垃圾），2 次实测都犯。**根因=mimo 在长输出上 commit 不下来**，不是 size 也不是措辞；**短卡片 = 物理上不会 loop**（已验证干净投递）。`delivered=true` 对 brief 不可信（同 report stub 坑）。
- **兜底**：`scripts/harness/brief_watchdog.py`（系统 crontab 08:30 HKT 工作日）——**只用 `transcript_loop_score(sessionId) ≥ 5`（mimo 复读循环签名）判失败**，不再对 run summary 做 marker 匹配（summary 是截断元叙述，marker 匹配每天假阳性）；命中即补发**紧凑卡**(plan.json 的 book+动作)+全文链接（LLM-free，dedupe）。crontab 行必须走 `/bin/bash -lc 'cd <ws> && …'`（裸 `python3` 拿不到 login PATH → openclaw 找不到 node → 补发失败，2026-06-01 修）。
- WeChat 通道正常（手动 `openclaw message send` 即时送达）；冷会话静默丢弃见 cold-session 坑（本次不是）。
- briefs 页 7 列表格在 mobile 横向滚动（`_layouts/default.html` @media≤600px：table display:block+overflow-x:auto），不撑破布局。

---

## 持仓数据
- **单一来源：`portfolio.json`**，不在此维护副本
- ticker 列表：`memory/current-portfolio-summary.md`（提高检索命中）

## Promoted From Short-Term Memory (2026-07-02)

<!-- openclaw-memory-promotion:memory:memory/2026-06-29-pre-open.md:97:97 -->
- Confidence Calls: **自校准（30天）**：Brier=0.2495（marginal）。T+1 vs hold baseline：LLM 56% vs 42% → alpha+14pp（跑赢空仓基线）。⚠️ high-conf(≥0.75) 历史胜率=0%——本简报所有 confidence 已压在 0.50-0.55，不虚高。 [score=0.815 recalls=0 avg=0.620 source=memory/2026-06-29-pre-open.md:97-97]

## Promoted From Short-Term Memory (2026-07-03)

<!-- openclaw-memory-promotion:memory:memory/2026-06-29-pre-open.md:12:15 -->
- Header — Book: | | USD-base | HKD-base | |---|---|---| | HK leg 总值 | $6,659 | HK$52,221.6 | | US leg 总值 | $3,050 | HK$23,918 | [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-29-pre-open.md:12-15]
<!-- openclaw-memory-promotion:memory:memory/2026-06-29-pre-open.md:16:19 -->
- Header — Book: | **合计** | **$9,709** | **HK$76,140** | | HK leg P&L | — | **-HK$36,055** | | US leg P&L | **-$1,037** | — | | **Book 合计 P&L** | **-$5,635** | **-HK$44,190** | [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-29-pre-open.md:16-19]
<!-- openclaw-memory-promotion:memory:memory/2026-06-29-pre-open.md:2:3 -->
- layout: default title: 盘前深度简报 · 2026-06-29 [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-29-pre-open.md:2-3]
<!-- openclaw-memory-promotion:memory:memory/2026-06-29-pre-open.md:21:21 -->
- Header — Book: ⚠️ HKD 与 USD 不可直接相加，以上双视角分列。 [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-29-pre-open.md:21-21]
<!-- openclaw-memory-promotion:memory:memory/2026-06-29-pre-open.md:23:23 -->
- Header — Book: **Concentration（HHI）** [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-29-pre-open.md:23-23]
<!-- openclaw-memory-promotion:memory:memory/2026-06-29-pre-open.md:8:8 -->
- 盘前深度简报 | 2026-06-29 周一 08:00 HKT: USDHKD = 7.8421（Frankfurter）｜HK 09:30 开盘前 90 分钟，US 周五 04:00 收盘后 ~4 小时（**今日美股休市**，US calendar=CLOSED — 6/29 周一 US 实际无交易日，本简报 US 段为周五收盘后延续分析，非新交易日） [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-29-pre-open.md:8-8]
<!-- openclaw-memory-promotion:memory:memory/2026-06-30-pre-open.md:121:121 -->
- Confidence Calls: | cut/换仓 | 0.55 | 连续6天触发，昨日模拟SPCH-92.5USD/RKLX-35.5USD，换仓时机争议较大但纪律不可绕过 | [score=0.815 recalls=0 avg=0.620 source=memory/2026-06-30-pre-open.md:121-121]
<!-- openclaw-memory-promotion:memory:memory/2026-06-30-pre-open.md:123:123 -->
- Confidence Calls: **Retrospective (2026-06-29 plan):** [score=0.815 recalls=0 avg=0.620 source=memory/2026-06-30-pre-open.md:123-123]

## Promoted From Short-Term Memory (2026-07-04)

<!-- openclaw-memory-promotion:memory:memory/2026-06-30-pre-open.md:12:15 -->
- Header — Book: | | USD-base | HKD-base | |---|---|---| | HK leg 总值 | $7,414 | HK$58,169 | | US leg 总值 | $3,668 | HK$28,764 | [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-30-pre-open.md:12-15]
<!-- openclaw-memory-promotion:memory:memory/2026-06-30-pre-open.md:16:19 -->
- Header — Book: | **合计** | **$11,082** | **HK$86,933** | | HK leg P&L | — | **-HK$34,704** | | US leg P&L | **-$692** | — | | **Book 合计 P&L** | **-$5,118** | **-HK$40,133** | [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-30-pre-open.md:16-19]
<!-- openclaw-memory-promotion:memory:memory/2026-06-30-pre-open.md:2:3 -->
- layout: default title: 盘前深度简报 · 2026-06-30 [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-30-pre-open.md:2-3]
<!-- openclaw-memory-promotion:memory:memory/2026-06-30-pre-open.md:21:21 -->
- Header — Book: ⚠️ HKD 与 USD 不可直接相加，以上双视角分列。 [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-30-pre-open.md:21-21]
<!-- openclaw-memory-promotion:memory:memory/2026-06-30-pre-open.md:23:23 -->
- Header — Book: **Concentration（HHI）** [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-30-pre-open.md:23-23]
<!-- openclaw-memory-promotion:memory:memory/2026-06-30-pre-open.md:8:8 -->
- 盘前深度简报 | 2026-06-30 周二 08:00 HKT: USDHKD = 7.8423（Frankfurter）｜HK 09:30 开盘前 90 分钟，US 昨收 04:00 后 ~4 小时 [score=0.806 recalls=0 avg=0.620 source=memory/2026-06-30-pre-open.md:8-8]
