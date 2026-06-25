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

## Promoted From Short-Term Memory (2026-06-24)

<!-- openclaw-memory-promotion:memory:memory/2026-06-19-pre-open.md:8:8 -->
- 盘前深度简报 | 2026-06-19 周五 08:00 HKT: > ⚠️ **HK 端午节休市** — 港股 6/19 (今) 休一天, 6/22 (周一) 09:30 HKT 重启。本期 HK 动作目标 **6/22 09:30 HKT 开盘**; US 6/19 21:30 HKT 周五盘仍交易。**6/22 同时是 RKLB 入纳指 100 日** + 美股周一开盘, 双重事件叠加。 [score=0.812 recalls=0 avg=0.620 source=memory/2026-06-19-pre-open.md:8-8]

## Promoted From Short-Term Memory (2026-06-25)

<!-- openclaw-memory-promotion:memory:memory/2026-06-21-1717.md:17:17 -->
- Conversation Summary: assistant: 今晚美股**不开盘** —— 6月19日是 Juneteenth（六月节），美股年度休市日之一（NYSE/Nasdaq 自2022年起列入官方假期）。 [score=0.849 recalls=0 avg=0.620 source=memory/2026-06-21-1717.md:17-17]
<!-- openclaw-memory-promotion:memory:memory/2026-06-21-1717.md:13:16 -->
- Conversation Summary: user: 算了 指数什么时候进场 我还有现金可以加 user: 那spch呢 user: 17.31买入20股spch user: 今晚美股开盘吗 [score=0.820 recalls=0 avg=0.620 source=memory/2026-06-21-1717.md:13-16]
<!-- openclaw-memory-promotion:memory:memory/2026-06-21-1717.md:19:21 -->
- Conversation Summary: 下一个交易日是周一 6月22日（北京时间周二 21:30 开盘）。 user: 哈？周一晚上也不开盘吗 assistant: 抱歉我刚才说错了，纠正一下： [score=0.820 recalls=0 avg=0.620 source=memory/2026-06-21-1717.md:19-21]
<!-- openclaw-memory-promotion:memory:memory/2026-06-21-1717.md:23:24 -->
- Conversation Summary: 下一个交易日是**美股周一 6月22日**，对应**北京时间周一晚 21:30 开盘**（不是周二）—— ET 和北京时间相差12小时，美股周一开盘=北京周一晚上,不跨天到周二。 assistant: 📈 Rick 的 Nostr 主页(网页直接看，免登录): [score=0.820 recalls=0 avg=0.620 source=memory/2026-06-21-1717.md:23-24]
<!-- openclaw-memory-promotion:memory:memory/2026-06-21-1717.md:3:5 -->
- Session: 2026-06-21 17:17:40 GMT+8: **Session Key**: agent:main:openclaw-weixin:direct:o9cq80-hgtrum-oss8knmdotlvzi@im.wechat; **Session ID**: 3195efb5-983a-40bb-a629-66fc73d4eb17; **Source**: openclaw-weixin [score=0.820 recalls=0 avg=0.620 source=memory/2026-06-21-1717.md:3-5]
<!-- openclaw-memory-promotion:memory:memory/2026-06-21-1717.md:9:12 -->
- Conversation Summary: user: 还在扩大吧 今天亏多少 user: 你算下今天亏多少 user: 昨天只看美股盈利多少呀 看看是不是今天都还回去了 user: 昨天我怎么记得涨了不少呀 robn你不能把我之前的盈利算进去 [score=0.820 recalls=0 avg=0.620 source=memory/2026-06-21-1717.md:9-12]
<!-- openclaw-memory-promotion:memory:memory/2026-06-22-pre-open.md:157:157 -->
- ▎Confidence 校准: self_calibration：Brier 30d = **0.234**（marginal）。`advice_track_record`（T+1，n=188 全样本不分 followed）：active 主动信号 win_rate **56%**（avg conf 56%，overconfidence_gap -0.01，基本校准）；passive_holds win_rate 62%。**vs hold-baseline：LLM 60% vs hold 55% → alpha +5.3pp（跑赢持有）**，但标注"单一 regime，需熊市/震荡样本确认"。⚠️ 高信心档(≥0.75) win_rate 仅 33%，overconfidence_gap +0.42——本简报所有主动 call 均压在 0.45-0.55 区间，不冒进。cut bucket 历史样本 n=1（30d 窗口太小不可靠），但 reflections 显示 07226 减仓历史 9 次 7 胜(78%)、PLTU 清仓历史 10 次仅 3 胜(30%，弱)——PLTU 这次定为规则强制换仓而非主动判断 thesis，confidence 已压到 0.50 而非更高。 [score=0.815 recalls=0 avg=0.620 source=memory/2026-06-22-pre-open.md:157-157]

## Promoted From Short-Term Memory (2026-06-26)

<!-- openclaw-memory-promotion:memory:memory/2026-06-22-pre-open.md:18:21 -->
- ▎仓位明细: | 代码 | 股 | 成本 | 现价 | 今日 | 浮% | 浮$ | |---|---|---|---|---|---|---| | 00100 | 60 | 822.83 | 497.6 | +12.33% | -39.53% | -19,513.80 | | 02208 | 400 | 14.084 | 10.88 | +0.37% | -22.75% | -1,281.60 | [score=0.858 recalls=0 avg=0.620 source=memory/2026-06-22-pre-open.md:18-21]
<!-- openclaw-memory-promotion:memory:memory/2026-06-22-pre-open.md:22:24 -->
- ▎仓位明细: | 03032 | 200 | 5.405 | 4.584 | -1.63% | -15.19% | -164.20 | | 07226 | 6200 | 4.3632 | 3.324 | -2.81% | -23.82% | -6,443.04 | | 03033 | 1000 | 5.14 | 4.512 | -1.18% | -12.22% | -628.00 | [score=0.858 recalls=0 avg=0.620 source=memory/2026-06-22-pre-open.md:22-24]
<!-- openclaw-memory-promotion:memory:memory/2026-06-22-pre-open.md:2:3 -->
- layout: default title: 盘前深度简报 · 2026-06-22 [score=0.828 recalls=0 avg=0.620 source=memory/2026-06-22-pre-open.md:2-3]
<!-- openclaw-memory-promotion:memory:memory/2026-06-22-pre-open.md:28:31 -->
- ▎仓位明细: | 代码 | 股 | 成本 | 现价 | 今日 | 浮% | 浮$ | |---|---|---|---|---|---|---| | CRCL | 2 | 87.00 | 80.23 | +0.00% | -7.78% | -13.54 | | PLTU | 14 | 40.96 | 31.36 | +0.00% | -23.43% | -134.36 | [score=0.820 recalls=0 avg=0.620 source=memory/2026-06-22-pre-open.md:28-31]
<!-- openclaw-memory-promotion:memory:memory/2026-06-22-pre-open.md:32:35 -->
- ▎仓位明细: | RKLX | 10 | 49.69 | 52.45 | +0.00% | +5.55% | +27.60 | | ROBN | 20 | 23.58 | 35.70 | +0.00% | +51.38% | +242.35 | | SPCH | 60 | 20.13 | 18.97 | +0.00% | -5.76% | -69.60 | | MSFU | 20 | 29.13 | 23.21 | +0.00% | -20.32% | -118.40 | [score=0.820 recalls=0 avg=0.620 source=memory/2026-06-22-pre-open.md:32-35]
<!-- openclaw-memory-promotion:memory:memory/2026-06-22-pre-open.md:8:10 -->
- Header — 盘前深度简报｜2026-06-22（周一）08:00 HKT: **Regime**：HK = trending-down(amber，HSTECH距200日线-15.6%，趋势OFF，20日波动30%<50%上限) ｜ US = trending-down(amber，但US休市中，上一交易日2026-06-19收盘数据) **FX (USDHKD)** = 7.8388 (Frankfurter) **Book（双视角，HKD+USD不可直接相加）**：USD-base 合计浮亏 -$3,641.83 ｜ HKD-base 合计浮亏 -28,547.61 HKD ｜ HK leg 60,245.6 HKD（浮亏-28,030.64 HKD）｜ US leg $3,440.4（浮亏-$65.95） [score=0.820 recalls=0 avg=0.620 source=memory/2026-06-22-pre-open.md:8-10]
