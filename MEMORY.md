# MEMORY.md - Rick's Long-Term Memory

## 用户偏好

### 持仓分析风格
- **直接分析当前持仓**：用 `portfolio.json` 成本 vs 实时价计算盈亏
- 忽略 `trades` 字段的历史操作，focus 当前仓位
- 简洁直接，不交代背景
- **风险偏好：激进型**，可用现金约 15万人民币（≈$20,500 USD）
- **重点：港股**（持仓、节奏、机会），美股作为补充观察
- 表格优先，能用结构化展示就不用大段文字
- **仓位策略：2026-07-08起偏好集中，不散着玩**——见 [feedback_position_concentration.md](memory/feedback_position_concentration.md)

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
- **Vibe-Research 数据源审计（2026-07-11）**：kcn 让学 github.com/simonlin1212/Vibe-Research（A股40端点 + 美港18端点）。结论=**其可达的源我们已全覆盖且多数更优**——① 美股基本面它用 Yahoo quoteSummary，我们用 `fetch_us_filings.py`（SEC EDGAR XBRL，零 auth 政府源，已接进 brief_preflight）+ `fetch_fundamentals_em.py`（东财 GMAININDICATOR/三表，US+HK，实测 200 可达）双保险，比它稳；② β 它拉 Yahoo 单股发布值，我们 `portfolio_risk_metrics.py` 用真实收益率算组合级 Cov/Var vs SPX/HSI（>3.0 硬闸），更严谨；③ 美港资金流我们有 `fetch_fundflow_em.py`。**唯一真缺口=analyst 一致预期（目标价/评级/升降级历史），是 Yahoo quoteSummary 独家 → 本机实测 429（连 crumb 端点都限），建了也不可靠 → 暂不建**。副产：`cls_telegraph()`（财联社快讯）已 404 下线别再试；它东财全系用 `em_get()` 串行≥1s+随机0.1-0.5s 抖动，比我们粗暴 sleep 好，将来 fetcher 防封可抄这个抖动策略

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
- 美股：ET 09:30-16:00；对应北京时间随 EDT/EST 自动切换，禁止写死 21:30~04:00
- 判断美股阶段优先用 ET；精确 HKT cron 见自动生成的 `CRON_SCHEDULES.md`
- 北京时间 16:02 = 港股刚收盘

---

## 关键市场联动
- 油价↓（地缘缓和）↔ 加密/科技涨
- CRCL：GENIUS Act 稳定币法案推进，相对独立于大盘
- 港股核心驱动：恒科指数方向 + 个股逻辑（00100 AI、02208 风电政策）

---

## OpenClaw CLI 注意事项

### OpenClaw 调度状态
- 6.1 后 cron runtime state 在 SQLite，旧 `~/.openclaw/cron/jobs.json` 是迁移 fallback，不能当真值。
- 查 cron / dreaming → `openclaw cron list --json`；跨调度源看 HKT 时间线 → `./check_crons.sh --timeline`。
- CI 不能访问本机 SQLite，读取 `config/cron-schedules.json`；它同时驱动 DST 同步、payload/watchdog 校验和 `CRON_SCHEDULES.md`，host system check 会对比 live CLI + crontab。
- 查 gateway → `curl http://127.0.0.1:18789/health`。

### ⚠️ brief 投递铁律 — WeChat 只发紧凑卡 + 链接，**绝不贴完整 brief 全文**
- **brief cron Step 4 写紧凑卡，Step 5 postflight 主发**：卡片只含核心结论 + Book + ≤3 动作 + 触发位 + 当日全文链接；LLM 最终回复仅留痕，不调 message 工具。
- **绝不把 pre-open.md 全文(~14-17KB)糊进微信。** 完整 brief 照常写进 pre-open.md → commit → dashboard/briefs 页看（深度不变，全文不裁）。
- **教训：2026-05-31** 让 mimo 把完整 brief 作为最终消息吐出 → **复读死循环**（"Now let me output the WeChat message…"复读几十遍被当回复发出，kcn 收到一屏垃圾），2 次实测都犯。**根因=mimo 在长输出上 commit 不下来**，不是 size 也不是措辞；**短卡片 = 物理上不会 loop**（已验证干净投递）。`delivered=true` 对 brief 不可信（同 report stub 坑）。
- **兜底**：`scripts/harness/brief_watchdog.py`（系统 crontab 08:30 HKT 工作日）读取 postflight delivery marker；Telegram 已成功则不动，marker 缺失/失败才补投 Telegram。它不再重发 WeChat，也不靠截断的 run summary 猜成败。
- WeChat 通道正常（手动 `openclaw message send` 即时送达）；冷会话静默丢弃见 cold-session 坑（本次不是）。
- briefs 页 7 列表格在 mobile 横向滚动（`_layouts/default.html` @media≤600px：table display:block+overflow-x:auto），不撑破布局。

---

## 持仓数据
- **单一来源：`portfolio.json`**，不在此维护副本
- ticker 列表：`memory/current-portfolio-summary.md`（提高检索命中）

## Promoted From Short-Term Memory (2026-07-14)

<!-- openclaw-memory-promotion:memory:memory/2026-07-09-pre-open.md:32:35 -->
- Book 总览: | **HK leg 合计** | **HK$87,570** | | | US 持仓 | $2,971 | 6 只活跃仓 | | US 现金 | $504 | 几乎耗尽 | | **US leg 合计** | **$3,475** | | [score=0.843 recalls=0 avg=0.620 source=memory/2026-07-09-pre-open.md:32-35]

## Promoted From Short-Term Memory (2026-07-18)

<!-- openclaw-memory-promotion:memory:memory/2026-07-13-pre-open.md:11:14 -->
- Header: **FX** USDHKD = 7.84 (Frankfurter) **Regime** HK: 🟡 AMBER_LEV（HSTECH -12.1% vs MA200，趋势OFF，vol 33%<50%，lev cap ×0.5）| US: 🔴 RED（SPCH/SPCX 5DMA 以下 -3.9%，lev 降杠杆） **Book** USD ~$13,601 | HK leg 80,367 HKD (持仓 58,170 + 现金 22,197) | US leg ~$3,350 USD (持仓 3,016 + 现金 335) **HHI** HK: 0.362 ⚠️ 集中风险 (Top2 83.1% = 00100 46.2% + 07226 37.0%) | US: 0.278 ⚠️ (Top2 62.5% = SPCH 46.9% + MSFU 15.6%) [score=0.803 recalls=0 avg=0.620 source=memory/2026-07-13-pre-open.md:11-14]
<!-- openclaw-memory-promotion:memory:memory/2026-07-13-pre-open.md:15:16 -->
- Header: **Breaches** ⛔ 8 仓位硬闸 + 🛑 5 杠杆止损触发（今日全部必须落地） **Today** HK OPEN · US CLOSED（周末休市，US动作押今晚 21:30 HKT） [score=0.803 recalls=0 avg=0.620 source=memory/2026-07-13-pre-open.md:15-16]
<!-- openclaw-memory-promotion:memory:memory/2026-07-13-pre-open.md:2:4 -->
- layout: default title: 盘前深度简报 · 2026-07-13 description: "clawock 盘前深度简报 2026-07-13：港股 + 美股真实持仓的多空辩论、量化因子、风控硬闸与 AI 自评战绩（诚实公开，承认主动操作跑输躺平）。" [score=0.803 recalls=0 avg=0.620 source=memory/2026-07-13-pre-open.md:2-4]
<!-- openclaw-memory-promotion:memory:memory/2026-07-13-pre-open.md:22:25 -->
- Retrospective（对照 2026-07-10 plan）: | Ticker | 计划 | 触发? | 是否执行 | 模拟P&L | |--------|------|-------|---------|---------| | 07226 | cut → 换 03033 | ✅ | ❌ 未执行 | +347 HKD（若3.524开执行） | | PLTU | cut → 换 PLTR | ✅ | ❌ 未执行 | 0 USD | [score=0.803 recalls=0 avg=0.620 source=memory/2026-07-13-pre-open.md:22-25]
<!-- openclaw-memory-promotion:memory:memory/2026-07-13-pre-open.md:26:28 -->
- Retrospective（对照 2026-07-10 plan）: | RKLX | cut → 换 RKLB | ✅ | ❌ 未执行 | 0 USD | | MSFU | cut → 换 MSFT | ✅ | ❌ 未执行 | 0 USD | | SPCH | cut → 换 SPCX | ✅ | ❌ 未执行 | 0 USD | [score=0.803 recalls=0 avg=0.620 source=memory/2026-07-13-pre-open.md:26-28]
<!-- openclaw-memory-promotion:memory:memory/2026-07-13-pre-open.md:30:30 -->
- Retrospective（对照 2026-07-10 plan）: **5 plans fired, 0 executed。连续第二日未落地。** 高置信度历史胜率 75%，但所有触发动作均为纪律规则——今日必须无条件执行，不再是选择。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-07-13-pre-open.md:30-30]

## Promoted From Short-Term Memory (2026-07-19)

<!-- openclaw-memory-promotion:memory:memory/2026-07-14-pre-open.md:17:17 -->
- Header: **今日主基调**：纪律换仓日 + CPI前夜静默模式。00100连续三日崩盘，解禁抛压未竭；4只杠杆ETF硬止损全员触发多日未执行；明日Jun CPI(7/15 20:30 HKT)是本周最关键催化。今日首要任务是执行已触发的规则性动作，减少alpha决策，等CPI方向再定US加/减节奏。 [score=0.815 recalls=0 avg=0.620 source=memory/2026-07-14-pre-open.md:17-17]
<!-- openclaw-memory-promotion:memory:memory/2026-07-14-pre-open.md:19:19 -->
- Header: **Book 总览**（资产视角）: [score=0.815 recalls=0 avg=0.620 source=memory/2026-07-14-pre-open.md:19-19]
<!-- openclaw-memory-promotion:memory:memory/2026-07-14-pre-open.md:2:4 -->
- layout: default title: 盘前深度简报 · 2026-07-14 description: "clawock 盘前深度简报 2026-07-14：港股 + 美股真实持仓的多空辩论、量化因子、风控硬闸与 AI 自评战绩（诚实公开，承认主动操作跑输躺平）。" [score=0.815 recalls=0 avg=0.620 source=memory/2026-07-14-pre-open.md:2-4]
<!-- openclaw-memory-promotion:memory:memory/2026-07-14-pre-open.md:21:24 -->
- Header: | 维度 | 金额 | |---|---| | **HK leg 合计** | 74,976 HKD（市值52,779 + 现金22,197）| | **US leg 合计** | 3,208 USD（市值2,971 + 现金237）| [score=0.815 recalls=0 avg=0.620 source=memory/2026-07-14-pre-open.md:21-24]
<!-- openclaw-memory-promotion:memory:memory/2026-07-14-pre-open.md:25:28 -->
- Header: | **组合总计（USD base）** | **~12,773 USD** | | **组合总计（HKD base）** | **~100,131 HKD** | | HK 未实现P&L | -47,897 HKD（-47.6%）| | US 未实现P&L | -1,453 USD（-32.8%）| [score=0.815 recalls=0 avg=0.620 source=memory/2026-07-14-pre-open.md:25-28]
<!-- openclaw-memory-promotion:memory:memory/2026-07-14-pre-open.md:9:11 -->
- 盘前深度简报 | 2026-07-14 周二: **生成时间**: 08:00 HKT | **USDHKD**: 7.8386 (Frankfurter) **HK开盘**: 09:30 HKT（距今约90分钟）| **US下次开盘**: 21:30 HKT **模型自校准**: Brier=0.259(marginal), LLM vs Hold +7pp alpha, 高置信过度自信 +18pp [score=0.815 recalls=0 avg=0.620 source=memory/2026-07-14-pre-open.md:9-11]
