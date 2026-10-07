# MEMORY.md - Rick's Long-Term Memory

直聊主会话注入本文件；isolated cron 不注入。只放规则、偏好和长期结论。持仓、ticker 列表、
金额只在 `portfolio.json`，这里不留副本。

## 用户偏好

- 分析当前持仓：用 `portfolio.json` 的成本对实时价算盈亏，不用历史操作代替当前仓位。
- 简洁直接，不交代背景。表格优先。
- 风险偏好激进。可用现金读 `portfolio.json`。
- 重点是港股（持仓、节奏、机会），美股作补充观察。
- 仓位偏好集中：资金归拢到少数大仓位，不摊成一堆小票。
- 加仓：突破加仓成立，深跌抄底不成立（8 个月 28 票非重叠回测的结论）。

### SPCH 无限子弹流

SPCH 持续加仓摊本，直到 SPCX 正股出现实质性反弹，或解禁落地。

- 按 DCA 记账：每次加仓正常记录并 commit。盯盘报告不喊砍，不重复风险提示。
- 只在两个条件上升级为 P0：SPCH 单日跌幅 >15%；SPCX 正股单周跌幅 >25%。
  阈值在 `config/intraday-strategy-policies.json`。
- 升级后的动作是摆数学，问一次是否继续，不劝阻。
- 累计加仓金额不是触发条件，不因投入超过某个数额报警。

### 投资问题工作流

问到持仓、portfolio、美股、港股、加仓或减仓，先读 `portfolio.json`（`shares > 0` 活跃，
`== 0` 已清仓），再按 `INVESTMENT_SOP.md` 走。

### 委派 coding agent

kcn 让我把事情交给 coding agent 时，我是传话的，不替他作主。

- 他的原话逐字放进 brief，作为唯一需求来源。不改写、不摘要、不扩写。
- 我查到的事实线索、我的猜测、我的建议，各自单列并写明「不是 kcn 的指令」，
  不混进原话，也不写成他的口吻。worker 可以不采纳。
- 他没说的范围、处置标准、优先级和禁令，不由我补。派之前发现 brief 里多出一串
  他没提过的约束，先停下，把「原话 / 事实线索 / 我的建议」分开再发。
- 需要他本人取舍的事，在给他的回复里直接问，不预设方向让 worker 照着做。
- 他点名谁就派谁（claudecode、Codex、OpenCode）。默认 agent 只在他没点名时用。

---

## 数据规则（本文件是唯一权威）

每次问持仓、股价、盈亏，先实时抓取，再回答。

### 1. 不用缓存价

- 不用 `portfolio.json` 的 `current_price` 算盈亏，它是上次更新的旧数据。
- 先跑 `clawock analyze-us` / `clawock analyze-hk`。fallback 链见
  `docs/reference/tool-operations.md` § 数据源清单。
- 所有源都失败时明确说「数据获取失败，以下为旧数据」，不静默使用旧数据。
- 抓取成功后更新 `portfolio.json` 并 commit。

### 2. FX：HKD 与 USD 不直接相加

- 港股 book 用 HKD，美股 book 用 USD。
- book 级数字给 USD-base 和 HKD-base 两个视角，标明 rate、source、fetched_at。
- 换算用 `clawock fx --json`。

### 3. 已知数据坑

- `00100 MINIMAX` 只有 Tencent 一个源。Tencent 失败必须明说。
- `today_change` 字段可直接信任：前收由 Polygon `/prev` 独立拉取，另有 dp% 反推兜底。
- 美股盘后（20:00 ET 之后）抓取时，Nasdaq 杠杆 ETF 报价可能错位一日：现价停在前一日、
  前收变成当日收盘，`today_change` 反号。识别方法：活跃美股全部 `open==high==low==current`。
  处理：隔几小时重抓；不要据此下涨跌结论。
- 新浪美股接口境外 403，不试。
- 财联社快讯接口已下线，不试。
- analyst 一致预期（目标价、评级、升降级）没有可靠源：Yahoo quoteSummary 在本机被限流。
  回答里说明缺这项，不编。
- 美股基本面用 `clawock filings`（SEC EDGAR）和 `clawock fundamentals`；资金流用
  `clawock fundflow`；组合 β 用 `clawock portfolio-risk`。

### 4. 数字与断言

- 成本基准只认 `portfolio.json` 的 `holdings[].cost`（实际买入价）。浮盈和浮盈百分比以它
  为基准。不用 IPO 参考价、上市首日价、前收或现价冒充成本。
- 当日盈亏按行情交易日的前收与当日成交计算，唯一实现是 `portfolio/math.day_pnl`
  （owner 见 `docs/architecture/harness.md`）。不用成本或 IPO 参考价代替前收。
- 「新高 / 历史最高 / 历史低位 / 突破 / 接近前高」这类断言，先核 `memory/snapshots/` 和
  `portfolio.json` 的真实数字再写。不确定就写「待核」。
- 每个关键数字能指出来源 file:field（成本→holdings，前收→Polygon `/prev`，
  市值→total_current_value）。指不出来源的数字不报。

---

## 取数：先用命令，再考虑 curl

- 默认走 `clawock analyze-us` / `clawock analyze-hk` / `clawock us-quotes`。它们封装了
  provider 顺序、URL、Eastmoney 前缀、独立前收链和字段污染兜底。
- 命令不覆盖时（非持仓 ticker、指数成分、调试某一路 fallback）才 curl。先打开对应实现，
  看 URL、header、解析和 fallback 顺序，再写 curl。
- provider 与 fallback 只读已安装 package 的当前实现和 `TOOLS.md`。不按旧文件名恢复执行路径。

---

## 时区

精确调度以 `config/cron-schedules.json` 为准，`docs/operations/cron-schedules.md` 是生成视图。

- 港股：HKT 09:30-12:00 / 13:00-16:00（北京时间相同）。
- 美股：ET 09:30-16:00。对应北京时间随 EDT/EST 切换，不写死 21:30-04:00。
- 判断美股阶段用 ET。

---

## 关键市场联动

- 油价↓（地缘缓和）↔ 加密/科技涨
- CRCL：GENIUS Act 稳定币法案推进，相对独立于大盘
- 港股核心驱动：恒科指数方向 + 个股逻辑（00100 AI、02208 风电政策）

---

## OpenClaw 运维

- cron 运行状态在 SQLite。`~/.openclaw/cron/jobs.json` 是迁移 fallback，不是真值。
- 查 cron / dreaming：`openclaw cron list --json`。
- 跨调度源的 HKT 时间线：`bash ops/host/check_crons.sh --timeline`。
- 查 gateway：`curl http://127.0.0.1:18789/health`。
- cron contract 是 `config/cron-schedules.json`，它驱动 DST 同步、payload / watchdog 校验
  和生成的 `docs/operations/cron-schedules.md`。

### 简报投递：微信只发紧凑卡 + 链接

- 不把 `pre-open.md` 全文贴进微信。全文写进当日的 pre-open 简报文件，在 briefs 页看。
- brief cron 的模型只写受限 judgment；postflight 渲染紧凑卡并主发。卡片只含核心结论、
  Book、不超过 3 个动作、触发位和当日全文链接。模型的最终回复只留痕，不调 message 工具。
- brief 的 `delivered=true` 不可信，以 postflight 的 delivery marker 为准。
- 兜底是 `clawock-brief-watchdog`（档位见 `docs/operations/cron-schedules.md`）：Telegram
  已成功就不动；marker 缺失或失败才补投 Telegram；marker 明确记录微信失败时同档只补发一次。

---

## Promoted From Short-Term Memory

下面由 runtime 自动追加，是某天简报的片段。

- 其中的 book 总额、浮盈、FX、价格都是当天的，不是行情源。要数字就现抓
  （`clawock analyze-us` / `clawock analyze-hk` / `clawock fx`）。
- 只用来回忆当时的判断和理由。
- 自动晋升的片段在审阅前只是候选，score 高不等于已核实。审阅时保留可跨日期复用的具体
  教训；删掉 front matter、HTML、当日价格和仓位动作。相同来源的候选不算独立证据。

## Promoted From Short-Term Memory (2026-10-06)

<!-- openclaw-memory-promotion:memory:memory/2026-10-02-pre-open.md:23:23 -->
- 今日动作 · 信心与判定: <div class="brief-entries" markdown="1"> [score=0.815 recalls=0 avg=0.620 source=memory/2026-10-02-pre-open.md:23-23]
<!-- openclaw-memory-promotion:memory:memory/2026-10-01-pre-open.md:23:23 -->
- 今日动作 · 信心与判定: <div class="brief-entries" markdown="1"> [score=0.804 recalls=0 avg=0.620 source=memory/2026-10-01-pre-open.md:23-23]
<!-- openclaw-memory-promotion:memory:memory/2026-10-01-pre-open.md:11:11 -->
- 盘前深度简报｜2026-10-01 周四 08:03 HKT: 港股今天休市，港股数字停在 9 月 30 日收盘；美股则用一场星舰入轨任务把最好的一天给了我们最大的那笔敞口。今晚基调只有一句：这不是一个该加仓的组合，是一个该把决策权收回来的组合。九成账面亏损不是选股问题而是仓位结构问题——港股段 57.79% 压在 00100，美股段 86.11% 压在 SPCH，两段 HHI 分别是 0.421 和 0.748。四条仓位硬闸加两条杠杆硬止损同时亮着，其中两条已站 49 天和 78 天而账本上一次执行、一次确认、一次豁免都没有。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-01-pre-open.md:11-11]
<!-- openclaw-memory-promotion:memory:memory/2026-10-01-pre-open.md:13:13 -->
- 盘前深度简报｜2026-10-01 周四 08:03 HKT: **反方**：最强反方会说：四条硬闸全在恒科与纳指同向下跌的那三周生成，现在恐惧贪婪 31.6、波动率只有 16，从没见过这么干净的反弹窗口；SPCH 今天涨 2.24% 领涨全组合，此时砍仓就是把最好的消息卖在最低价。它有一半对——今天确实不该砍。但它混淆了两件事：星舰成功是印证型消息，按纪律从来不能成为减仓理由；反过来我要减的从来不是这个故事，而是 3501 美元账户里 3015 美元是同一只 2x 杠杆 ETF。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-01-pre-open.md:13-13]
<!-- openclaw-memory-promotion:memory:memory/2026-10-01-pre-open.md:19:19 -->
- 今天做什么: <div class="brief-card" markdown="1"> [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-01-pre-open.md:19-19]
<!-- openclaw-memory-promotion:memory:memory/2026-10-01-pre-open.md:2:4 -->
- layout: default title: 盘前深度简报｜2026-10-01 周四 08:03 HKT description: "clawock 盘前深度简报 2026-10-01：港股 + 美股真实持仓的多空辩论、量化因子、风控硬闸与决策校准。" [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-01-pre-open.md:2-4]
<!-- openclaw-memory-promotion:memory:memory/2026-10-01-pre-open.md:9:9 -->
- 盘前深度简报｜2026-10-01 周四 08:03 HKT: <div class="brief-card brief-lede" markdown="1"> [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-01-pre-open.md:9-9]

## Promoted From Short-Term Memory (2026-10-07)

<!-- openclaw-memory-promotion:memory:memory/2026-10-02-pre-open.md:11:11 -->
- 盘前深度简报｜2026-10-02 周五 08:03 HKT: 今天不是预测日，是执行日。港股段 57.8% 押在 MINIMAX 单一标的上、美股段 85.6% 押在 SPCH 2x 上，两条腿同时危险集中，而今晚 20:30 有非农。唯一有实质变化的不是行情而是账：SPCH 浮亏重新击穿硬止损线，允许动作从反弹减仓收窄为直接清掉换成 1x。MINIMAX 昨天涨 3.65% 领涨港股 AI，但中期报告刚在盘后披露，今天是它第一次被定价，先看再动。维持 07226 与 RKLX 现有打法，不重发第 N 遍。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-02-pre-open.md:11-11]
<!-- openclaw-memory-promotion:memory:memory/2026-10-02-pre-open.md:13:13 -->
- 盘前深度简报｜2026-10-02 周五 08:03 HKT: **反方**：反过来看，今天唯一确定要做的动作，是把一笔在正股反弹里刚刚走强的 2x 敞口清掉，而这件事的动机不是价格而是账上的规则；同一天账户刚因为拒绝对同一条敞口执行了 79 天而把敞口买得更大。星舰成功、正股月涨 4.1%，在一个上升叙事里执行纪律性削减，很可能是减在情绪最好的一天。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-02-pre-open.md:13-13]
<!-- openclaw-memory-promotion:memory:memory/2026-10-02-pre-open.md:19:19 -->
- 今天做什么: <div class="brief-card" markdown="1"> [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-02-pre-open.md:19-19]
<!-- openclaw-memory-promotion:memory:memory/2026-10-02-pre-open.md:2:4 -->
- layout: default title: 盘前深度简报｜2026-10-02 周五 08:03 HKT description: "clawock 盘前深度简报 2026-10-02：港股 + 美股真实持仓的多空辩论、量化因子、风控硬闸与决策校准。" [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-02-pre-open.md:2-4]
<!-- openclaw-memory-promotion:memory:memory/2026-10-02-pre-open.md:9:9 -->
- 盘前深度简报｜2026-10-02 周五 08:03 HKT: <div class="brief-card brief-lede" markdown="1"> [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-02-pre-open.md:9-9]

## Promoted From Short-Term Memory (2026-10-08)

<!-- openclaw-memory-promotion:memory:memory/2026-10-03-2214.md:14:17 -->
- 六张全过，我给了排序表让它别平均用力: | 图 | 接线 | 文字 | 风险 | |---|---|---|---| decision-pipeline | 58 | 117 | **最高**（你圈的 4 处）| information-flow | 29 | 90 | 高 | [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-03-2214.md:14-17]
<!-- openclaw-memory-promotion:memory:memory/2026-10-03-2214.md:18:21 -->
- 六张全过，我给了排序表让它别平均用力: architecture | 30 | 60 | 中 | harnesses | 42 | 65 | 中 | debate-flow | 17 | 40 | 中低 | product-architecture | 25 | 45 | 中低 | [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-03-2214.md:18-21]
<!-- openclaw-memory-promotion:memory:memory/2026-10-03-2214.md:23:23 -->
- 六张全过，我给了排序表让它别平均用力: **判据脚本必须一次跑全部六张**，输出每张各自的相交数 / 终点归属 / 最小间距 / 纵向节奏。而且要求它**复用 #2424 的 `measurements.json` 测量基础，只换判据**（从「距离」换成「相交 / 终点归属 / 扇出目标」），别从零重写。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-03-2214.md:23-23]
<!-- openclaw-memory-promotion:memory:memory/2026-10-03-2214.md:25:25 -->
- 六张全过，我给了排序表让它别平均用力: 一句我写进去了：**哪张本来就干净，如实报「零缺陷」并给判据输出，不要为了显得做了事去改。** [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-03-2214.md:25-25]
