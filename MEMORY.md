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

## Promoted From Short-Term Memory (2026-10-08)

<!-- openclaw-memory-promotion:memory:memory/2026-10-03-2214.md:14:17 -->
- 六张全过，我给了排序表让它别平均用力: | 图 | 接线 | 文字 | 风险 | |---|---|---|---| decision-pipeline | 58 | 117 | **最高**（你圈的 4 处）| information-flow | 29 | 90 | 高 | [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-03-2214.md:14-17]
<!-- openclaw-memory-promotion:memory:memory/2026-10-03-2214.md:18:21 -->
- 六张全过，我给了排序表让它别平均用力: architecture | 30 | 60 | 中 | harnesses | 42 | 65 | 中 | debate-flow | 17 | 40 | 中低 | product-architecture | 25 | 45 | 中低 | [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-03-2214.md:18-21]
<!-- openclaw-memory-promotion:memory:memory/2026-10-03-2214.md:23:23 -->
- 六张全过，我给了排序表让它别平均用力: **判据脚本必须一次跑全部六张**，输出每张各自的相交数 / 终点归属 / 最小间距 / 纵向节奏。而且要求它**复用 #2424 的 `measurements.json` 测量基础，只换判据**（从「距离」换成「相交 / 终点归属 / 扇出目标」），别从零重写。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-03-2214.md:23-23]
<!-- openclaw-memory-promotion:memory:memory/2026-10-03-2214.md:25:25 -->
- 六张全过，我给了排序表让它别平均用力: 一句我写进去了：**哪张本来就干净，如实报「零缺陷」并给判据输出，不要为了显得做了事去改。** [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-03-2214.md:25-25]

## Promoted From Short-Term Memory (2026-10-10)

<!-- openclaw-memory-promotion:memory:memory/2026-09-24-pre-open.md:49:58 -->
- **理由** 硬止损 -33.3% ≤ -18% 站 42 天 breach ledger 持续；HK 杠杆 ETF 27.7% > amber 25% cap 双闸并发。adaptive.may_stand=true stance=declined 42d 同期他处有成交 kcn 选保留敞口让 HSTECH 反弹修复；swap_mandate 03033 (max 18042 HKD) 仍 open 但 kcn 实际不触发（风险增仓冻结需 proven risk-reducing pair，03033 packet technical_setup_ids=[] 无 alpha_confirmation/oversold_reclaim 等技术 setup，schema 校验 add_only_on_trigger 必填 technical_setup_id 走不通，故 buy 腿不出现在 plan）。Breakeven 49.9% (1x 6m 含 drag 23.4%)，标的 HSTECH 现 4379 距 4669 高 -6.2%，反弹需 +6.6%。9/24 vs 9/15 last_reissued (9 天) 无实质变化：HK AI 9/23 智谱 -12% / MINIMAX -3.98% 板块回踩，HSI -1.01% / HSTECH -1.33%，07226 -2.61% 跟随。维持 3.0 反弹减仓窗口 **判定**... [score=0.883 recalls=5 avg=0.483 source=memory/2026-09-24-pre-open.md:49-58]
<!-- openclaw-memory-promotion:memory:memory/2026-07-27-pre-open.md:160:176 -->
- **MSFU 7/29 财报**：Bull 看 buying opportunity；Bear 看短期 selloff + FOMC 双重事件 - **RKLX swap 时机**：Bull 看纪律 swap 不等价位；Bear 看"再忍一天等 SPCX 解禁前后整个板块反弹" ## ▎Tier 3 — 3 个 Risk Voice + Judge ### Aggressive（抓 upside，risk-on 立场） **立场**：纪律 swap 是无条件动作；但 SKHY 加仓窗口在 7/30 后打开（不是今天）。MSFT 7/29 财报如果 capex 指引温和 = +MSFU 反弹 alpha 在。 - **会做的事**：① 5 个 swap（SPCH→SPCX 150 / RKLX→RKLB 10 / PLTU→PLTR 14 / MSFU→MSFT 20 / 07226→03033 1000）**全部 09:30 HKT/ET 开盘市价成交**；② 00100 trim 20 股借反弹（if high > 215）→ 03929 → 实际是把 00100 单名 39.54% → 36% 收窄 - **会忽略的风险**：7/29 FOMC 加息概率 37.9% — 因为本子已 50% 浮亏，再跌空间有限（hard cap -100%） ### Conservative（保本 derisk，risk-off 立场） **立场**：纪律 swap +... [score=0.869 recalls=5 avg=0.437 source=memory/2026-07-27-pre-open.md:160-176]
<!-- openclaw-memory-promotion:memory:memory/2026-10-05-1854.md:15:18 -->
- 其余风险: #2595 会让公开胜率在下一次结算时变动 19 行，这是修复本身。; #2560 的卡片今天仍不展示（当天的 sidecar 是旧契约写的），要等下一份盘前简报按新契约写出第一张；模型是否守约只能事后观察。; #2603 只改标题，已有的 25 个归档提交不回填。; 巡检还在运行，随时可能再开新 issue；0 是 CI 结束那一刻的读数。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-05-1854.md:15-18]
<!-- openclaw-memory-promotion:memory:memory/2026-10-05-1854.md:19:19 -->
- 其余风险: 本机导航已更新并记录了复核基线；live checkout 里三个未提交的 `assets/data` 文件是定时发布写的，没动。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-05-1854.md:19-19]
<!-- openclaw-memory-promotion:memory:memory/2026-10-05-pre-open.md:11:11 -->
- 盘前深度简报｜2026-10-05 周一 08:03 HKT: 两条腿走反了方向：美股上周五 risk-on 收在高位、航天这条线一天涨 9% 到 15%，港股却跌出 52 周低位、恒科只剩 4158。今天的主基调不是找新机会，是把 2x 敞口一层层剥掉：美股两笔 2x 敞口在反弹位全清，1x 由 SPCX 继续承担；港股 07226 先减两成回 25% 上限之内。做完之后组合里只剩一条 2x，而且港股那条留下了两个新问题：减两成会把 00100 推到约 59.4%、离 60% 的强制线只剩不到一个百分点；而 1x 承接腿今天落不了纸，卖出所得只能停在现金。真正没有解法的还是 00100 —— 它占港股段 55.6%、贡献全组合 54.7% 的风险份额，规则只授权持有。 [score=0.803 recalls=0 avg=0.620 source=memory/2026-10-05-pre-open.md:11-11]

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
