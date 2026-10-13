# MEMORY.md - Rick's Long-Term Memory

直聊主会话注入本文件；isolated cron 不注入。只放规则、偏好和长期结论。持仓、ticker 列表、
金额只在 `portfolio.json`，这里不留副本。

## 用户偏好

- 分析当前持仓：用 `portfolio.json` 的成本对实时价算盈亏，不用历史操作代替当前仓位。
- 简洁直接，不交代背景。表格优先。
- 风险偏好激进。可用现金读 `portfolio.json`。
- 重点是港股（持仓、节奏、机会），美股作补充观察。
- 仓位偏好集中：资金归拢到少数大仓位，不摊成一堆小票。单票占满一个市场段也可以，杠杆 ETF 同样
  （2026-10-11）。不因占比高或杠杆占比高劝减；融资、借钱、保证金不在此列。
- 加仓：回测结论是突破加仓成立、深跌抄底不成立（8 个月 28 票非重叠）。kcn 实际是跌了加：
  2026-05-17 至 10-08 的 35 笔买入没有一笔是突破加仓。这是他的打法，不拿回测结论劝他改，
  也不把系统的突破触发当成他会执行的单。

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
- coding agent 额度随时变，派发前先查，不要信 MEMORY.md 里的旧记录：
  `cd /root/tools/agent-dispatch && node quota.mjs codex`（或 `claude`）。
  额度耗尽的 worker 会 `state=quota` 直接收尾且没有报告 —— 派发授权要一次写全
  （含合并/部署），别指望它第二轮补。大任务把 `--quota-resumes` 调高（默认 1 不够，
  一个 README 重构轮就烧掉 3 次重试）。
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

## Promoted From Short-Term Memory (2026-10-11)

<!-- openclaw-memory-promotion:memory:memory/2026-10-06-pre-open.md:11:11 -->
- 盘前深度简报｜2026-10-06 周二 08:03 HKT: 今天只有一笔该动手的：美股那个 2x 敞口占到整段 92.2%、单票占 87.93%，昨天正股一天涨 7.6% 把 2x 推到 5 日 +36.1%，是把重置层换成 1x 最好的价，砍掉的是衰减不是 SpaceX 这门生意。港股这边反过来，恒科在 200 日线下方 15.6%，2x 硬止损开了 54 天但减额门槛没跨过重新发起的线，维持；00100 在智谱靠产品级催化涨 6.15% 的日子里只涨 0.58%，落后的不是估值是它自己拿不出催化，所以持有观察、不加仓。今日基调是纪律优先：一条执行、六条按住，指数在高位而账户在低位。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-06-pre-open.md:11-11]
<!-- openclaw-memory-promotion:memory:memory/2026-10-06-pre-open.md:13:13 -->
- 盘前深度简报｜2026-10-06 周二 08:03 HKT: **反方**：最强反方是：把最热的一条腿在单日 +15% 的当天砍掉，等于把八天以来最好的一次兑现窗口让出去，而这笔减仓在账上已经开了 83 天、执行 0 次、对这只票的买入却有 13 次。回看历史，这只票过去三次减仓三次都对，说明砍在强头上确实是这套打法里赚钱的那一半。反方还指出两件被低估的事：一是 SpaceX 的三发连中与摩根士丹利的 300 美元目标价都在同一天确认，杀伤力和催化同源；二是砍掉 2x 只解决衰减，不解决 87.93% 的单名集中——真正的分散要等 1x 承接腿拿到授权，而这笔单子执行之后美股段会剩 187 美元现金和 1 股 SPCX，单名集中反而更极端。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-06-pre-open.md:13-13]
<!-- openclaw-memory-promotion:memory:memory/2026-10-06-pre-open.md:19:19 -->
- 今天做什么: <div class="brief-card" markdown="1"> [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-06-pre-open.md:19-19]
<!-- openclaw-memory-promotion:memory:memory/2026-10-06-pre-open.md:2:4 -->
- layout: default title: 盘前深度简报｜2026-10-06 周二 08:03 HKT description: "clawock 盘前深度简报 2026-10-06：港股 + 美股真实持仓的多空辩论、量化因子、风控硬闸与决策校准。" [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-06-pre-open.md:2-4]
<!-- openclaw-memory-promotion:memory:memory/2026-10-06-pre-open.md:23:23 -->
- 今日动作 · 信心与判定: <div class="brief-entries" markdown="1"> [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-06-pre-open.md:23-23]

## Promoted From Short-Term Memory (2026-10-12)

<!-- openclaw-memory-promotion:memory:memory/2026-10-06-pre-open.md:9:9 -->
- 盘前深度简报｜2026-10-06 周二 08:03 HKT: <div class="brief-card brief-lede" markdown="1"> [score=0.823 recalls=0 avg=0.620 source=memory/2026-10-06-pre-open.md:9-9]
<!-- openclaw-memory-promotion:memory:memory/2026-10-07-pre-open.md:23:23 -->
- 今日动作 · 信心与判定: <div class="brief-entries" markdown="1"> [score=0.805 recalls=0 avg=0.620 source=memory/2026-10-07-pre-open.md:23-23]
<!-- openclaw-memory-promotion:memory:memory/2026-10-07-pre-open.md:11:11 -->
- 盘前深度简报｜2026-10-07 周三 08:03 HKT: 指数在涨、持仓在跌：VIX 15.01 标普纳指同步收红，可组合里九成的票都压在 MA200 之下。今天把美股两笔纪律性减仓执行掉，SPCH 5 日涨 31.3% 之后还占美股段 87.8%，RKLX 浮亏 60.4% 卡在硬止损线上 84 天；港股端不加不减，2.55 是 07226 那条不能再等的线。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-07-pre-open.md:11-11]
<!-- openclaw-memory-promotion:memory:memory/2026-10-07-pre-open.md:13:13 -->
- 盘前深度简报｜2026-10-07 周三 08:03 HKT: **反方**：最强反方是「在反弹最猛的一天卖出最强的两只」：SpaceX 正股贴住 20 日高、5 日 15.2%，Rocket Lab 因为收购 5 日 7.69%，宏观是 VIX 15 的 risk_on，恒科也在从 MA200 下方 14.7% 的位置反弹。这些都是真的，所以今天这两笔的性质不是看空，是用这周最好的价格把 84 天没关掉的敞口表关掉。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-07-pre-open.md:13-13]
<!-- openclaw-memory-promotion:memory:memory/2026-10-07-pre-open.md:19:19 -->
- 今天做什么: <div class="brief-card" markdown="1"> [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-07-pre-open.md:19-19]
<!-- openclaw-memory-promotion:memory:memory/2026-10-07-pre-open.md:2:4 -->
- layout: default title: 盘前深度简报｜2026-10-07 周三 08:03 HKT description: "clawock 盘前深度简报 2026-10-07：港股 + 美股真实持仓的多空辩论、量化因子、风控硬闸与决策校准。" [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-07-pre-open.md:2-4]
<!-- openclaw-memory-promotion:memory:memory/2026-10-07-pre-open.md:9:9 -->
- 盘前深度简报｜2026-10-07 周三 08:03 HKT: <div class="brief-card brief-lede" markdown="1"> [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-07-pre-open.md:9-9]
<!-- openclaw-memory-promotion:memory:memory/2026-10-07.md:13:13 -->
- 派发后必须验证「真的送达」: 今天 09:37 那条要求 **40 分钟没生效**，我却在回复里说「已送达，正在续跑」。原因：runner 输出 `appended to running task ... (ok/DONE)`，`ok/DONE` 是**已结束**状态不是运行中；inbox 里那条消息从没被取走。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-07.md:13-13]
<!-- openclaw-memory-promotion:memory:memory/2026-10-07.md:15:15 -->
- 派发后必须验证「真的送达」: 验证方法：追加后确认 inbox 消息移入 `inbox/delivered/` 且 `APPENDS` 递增。**没验证就不要说已送达。** [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-07.md:15-15]
<!-- openclaw-memory-promotion:memory:memory/2026-10-07.md:19:22 -->
- 今天被我判断错、由 worker 推翻的（别重复）: | 我的说法 | 实际 | |---|---| | 没有 running icon（grep `@keyframes` 只有 2 个） | `animateMotion` 有 195 处，SMIL 不用 CSS | | icon 重复率 82% | 82% 是跨八图合并去重；**逐图 28.7%** | [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-07.md:19-22]

## Promoted From Short-Term Memory (2026-10-13)

<!-- openclaw-memory-promotion:memory:memory/2026-10-07-pre-open.md:478:507 -->
- | SPCX | hold_and_watch | core_position | — | 45% | pending | </div> <div class="brief-card" markdown="1"> ### 同行扫描 <div class="brief-entries" markdown="1"> - **00100** · 上一场收盘 +2.05% · 差距 -5.54pp <span class="entry-meta">HK AI 大模型 · 最强同行 02513 智谱 +7.59%</span> **判断** 落后。智谱涨 7.59%、00100 涨 2.05%，差 5.5 个百分点，归因是解禁砸量与消息落点不同，不是题材证伪；按同行扫描的判断模板，这属于题材强而自己弱，值得考虑切换但没有一条可执行的切换路径。 - **02208** · 上一场收盘 +0.17% · 差距 -3.35pp <span class="entry-meta">风电 · 最强同行 00916 龙源电力 +3.52%</span> **判断** 落后。龙源电力涨 3.52%、大唐新能源涨 1.50%、东方电气跌 0.33%，它只涨 0.17%，3.4 个百分点的差距归因是 beta 错配，题材与设备端都还没轮到她。 - **03032** · 上一场收盘 +1.05% · 差距 -0.12pp <span class="entry-meta">HK 科技指数... [score=0.819 recalls=5 avg=0.456 source=memory/2026-10-07-pre-open.md:478-507]
