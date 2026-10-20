---
name: daily-deep-brief
description: kcn 每个工作日 08:03 HKT 跑一次的盘前全 swarm 深度分析。harness 化：`clawock brief preflight` 计算并编译 typed decision packet，LLM 只写 plan 与受限 judgment（纯文本判断，不写版式），`clawock brief postflight` 校验后由 `brief_render` 渲染报告与微信卡、生成 Pages projection、commit 并自动投递微信。**输出**：结构化 plan、受限 judgment JSON，harness 渲染的 markdown 报告与紧凑微信卡。**只在每日 8 点 cron 触发时使用；手动深度分析仍走 portfolio-swarm-review。**
---

# Daily Deep Brief (08:03 HKT, weekday)

8 点这个时点：HK 开盘前 ~90 分钟，US 已收盘 ~4 小时。盘前是 deep think 最好的窗口 —
有完整夜间消息面，没有盘中执行压力。

## Harness 架构（不可越权）

```
┌──────────────────────┐   ┌────────────────┐   ┌──────────────────────────┐
│ clawock brief preflight │──►│ LLM (你 / Rick) │──►│ clawock brief postflight  │
│   (确定性 + 幂等)      │   │ (只写判断/反方) │   │ 校验 → 渲染 → 投递        │
└──────────────────────┘   └────────────────┘   └──────────────────────────┘
   指标/因子/风险/evidence     查 packet summary     校验 plan+judgment，
   编译 typed packet           写 plan + judgment    brief_render 出 md+微信卡，
                               (纯文本，不写版式)    Pages 只读稳定 projection
```

**为什么这样分**：之前完全交给 LLM，模型可能漏快照、漏 HHI、漏 FX、漏 retrospective。
确定性步骤交给脚本（一定执行，无遗漏）；LLM 只做"分析综合"这个不能脚本化的部分。

## 🔒 Exec 铁律：退出码就是整回合的判据

**每一条 `exec` 的退出码会被当成整个回合的成败。** 一条中途的非零退出会让 cron 把
**已经做完并已投递**的一轮判成 `error`（2026-08-18：简报全部产出、`wechat_sent: true`、
commit+push 都成了，但一条读「可能不存在的文件」的 exec 非零退出，整轮仍被记成红）。

规则正文只有一份：本回合任务消息里的「Exec 契约」（源文件
`config/cron-payloads/_exec-contract.md`，简报、报告、盘中共用）。本 skill 不另写一套，
两句话的要点：

- **探测**（读可选文件、`ls`/`grep`/`head`/`test`）给那一条探测自己兜底 `|| true`。
- **业务步骤**（preflight / postflight）的结果必须原样可见：不接管道、不补 `|| true` /
  `; true`，只允许 `; echo "EXIT=$?"`。preflight 退 2 就是失败，不是「今天还没产出」。

配套的窄规则见 Step 5 的「送达确认铁律」（#558）：那条禁的是 postflight 之后再去读
marker 确认送达。

## 6-step 流程（严格按顺序）

### Step 1: 跑 preflight（一行命令搞定所有确定性活）

```bash
clawock brief preflight
```

**行情失败闸**：US 或 HK 刷新失败时，preflight 退出 1，并把本日 context 与
manifest 换成 `price_refresh_failed` 的失败代（无持仓数字、无 decision packet）。
看到该状态立即结束本轮，不写 plan/judgment，不调用 postflight；修复行情后重跑
preflight。fallback 会拒绝生成，postflight 也会阻止发布。其他资料采集警告仍按
本次 context 的 `issues` 逐项披露。

这一步内部做了：

1. `clawock analyze-us` — US 价格刷新（7-route fallback + RSI/MA）
2. `clawock analyze-hk` — HK 价格刷新（Tencent 主源 + Eastmoney 全量独立对账/兜底 → stooq → yfinance + 恒指 + 信号）
3. `clawock fx --json` — USDHKD 实时汇率（Frankfurter → exchangerate.host → Yahoo）
4. `cp portfolio.json memory/snapshots/{date}.json` — 每日快照（longitudinal 基础设施）
   - **为什么**：`portfolio.json` 是滚动覆盖的 ground truth，每次刷价就丢前一刻状态。
     有 snapshot 历史才能做 Rolling P&L 曲线 / Alpha vs benchmark / Drawdown 分析 / Position 变化追溯。
   - ⚠️ **不可补做** — 每过一天少一份永远拿不回来的数据。
5. **HHI / Top2 集中度算法**（HK + US leg 分开）
6. **SEC EDGAR fundamentals** — 从当天 `portfolio.json` 动态筛选 `shares > 0` 的 US 持仓；跳过 `is_leveraged_etf=true` 或被名称启发式识别为杠杆 ETF 的标的，其余单股逐一跑 `clawock filings`
   - 杠杆 ETF 检测启发式（name 关键词）：'倍', 'Direxion', 'T-Rex', 'Defiance', 'ProShares',
     '2X Long', '3X Long', 'Daily Target'
   - 不在文档硬编码 ticker；实际名单以当天持仓和上述动态过滤结果为准
7. **Retrospective**：读 prior v2 plan，对每个 decision 按 strategy 检查 condition 是否触发、模拟 benefit 与 confidence calibration

输出分三层：

- `memory/.tmp/brief-context-{date}.json` —— 完整、不可裁剪的审计事实；供 postflight 校验，**不要整份 cat 进模型上下文**。
- `memory/.tmp/brief-context-{date}/manifest.json` + `core.json` + feature bundles —— 同一 `generation_id` 下的模型输入边界。manifest 记录路径、hash、字段、逐 section 大小和预算。
- manifest 的 `tools.decision_packet` —— harness 编译的 typed 决策边界；证据 ID、算术和授权边界由代码拥有；技术分类、量化评级与候选是登记策略的意见。

### Step 2: 只读 decision packet summary（唯一常驻输入）

#### 谁决定什么（#2842，先读这一节）

你负责假设、证据取舍、要不要动、动多少、在哪动、什么情况下认错。代码负责事实、算术、现金/库存/整手、义务和已有授权。登记过的规则（两族证据、三种技术形态、催化分级、左侧观察、证伪不证实、突破不追高等）是**一份参考策略的意见**：默认可以照做，证据让你得出不同结论时可以不照做。

一条决策会被分三路检查，三路结果互不冒充：

| 检查 | 例子 | 后果 |
|---|---|---|
| 事实（`FACT_*`） | 引用不存在的事件或计算回执、声称一个没人观测到的价格、把未来的数据当今天的 | 打回，必须改 |
| 可行性与授权（`FEAS_*` / `AUTH_*`） | 超过现金或持股、不是整手、已有未成交加仓、硬止损义务未履行、超限的票加仓、杠杆产品加仓、风控买腿没有处方 | 打回这条动作；观点可以保留在散文里 |
| 策略异议（`STRAT_*`） | 入场位不是登记形态、没有已升级事件就卖、超过登记策略的单批股数、提名了规则没提名的候选 | **不打回**。harness 把异议记在这条决策上，并印在卡片和页面的「与登记策略不同」里 |

每只票的 `constraints.open_actions` 是可以写的动作（第二路的边界），`closed_actions` 写明每个关着的动作为什么关；`allowed_actions` 是登记策略会做的动作。写 `open_actions` 里、`allowed_actions` 外的动作是合法的，那就是一条策略异议。**没有任何环节会把你的提案改成系统更喜欢的样子**，所以偏离规则时把理由写清楚：这条决策之后按它自己的假设被复盘。

持仓外的票也可以提。`summary.proposal_universe` 列出本地存有日线、因此事后能被结算的未持有标的（价格是所标日期的收盘或当日报价，港股带整手）。对它们可以写 `watch` 或 `add_only_on_trigger`；买入提案会带上「尚未过建仓前研究闸」的标注——它是一条可评估的提案，不是下单许可，kcn 决定是否走 entry-gate。不在这张表里的票无法结算，写不进 plan，想法写在散文里并在 `▎待补` 提出把它加入 registry。

当 packet 某票出现 `technical.setups` 并考虑加仓时，先读
[`references/technical-playbooks.md`](references/technical-playbooks.md)。该
reference 的三种技术 staged setup 和 packet 编译出的 `alpha_confirmation` 是登记策略
给出的入场；引用其中一个时触发、失效、批次以本次 packet 为准。你也可以提出自己的入场
（见 Step 4 B「自定入场的加仓」），那会被标成不对应登记形态。`alpha_confirmation` 不是
第四种技术 alpha：量化横截面/同业残差负责 price-relative 选名，新闻 surprise
或 attention acceleration 提供独立的 point-in-time information family，技术价位
只安排未来 1–5 个本地交易日的执行。`add_authority.tier` 和 `max_add_shares` 是这套
策略自己的评级和单批上限，措辞改不了它们；你的提案可以不同，但要在 `hypothesis` 里
说明依据，而不是声称规则给了更高的 tier。

`quant.left_side` 是左侧分批的**观察档**（kcn 2026-09-27，`mode: observe`）：它不在
`technical.setups` 里，登记策略不据此授权加仓。你若认为左侧分批今天成立，可以按
「自定入场的加仓」提出，并写明它是左侧、首档和失效在哪。
加仓侧可以写一行「左侧观察：首档 `rungs[0]`、失效 `invalidation_price` / MA200
`trend_floor`」，`gate` 非空时写明被哪条闸挡住（`thesis_not_intact` / `negative_information`
/ `peer_laggard` / `leveraged_excluded`）；数字照抄，不自己推后两档。

**证据族现在有三个(#1086)**：`price_relative`(因子/同业残差)、
`point_in_time_information`(一手披露)、**`technical_breakout`**(收盘站上前 20 日高
且 z < `early_no_chase_zscore`)。第三族是 #856 回测里**唯一四周期全绿**的形态
(H20 55.9% avg +16.25%；港股 H20 59.4% avg +38.7%)，此前只喂给盘中消息、
对决策没有任何权重。

登记策略的三条判据：**门槛仍是两族**(突破单独不获该策略提名；自定提案走 `open_actions`)；突破**不算 validated**
(validated 仍要两侧都有 `usable_for_decisions` 的证据)；因此**杠杆腿不会被价格形态
提拔**，`leveraged_requires_validated_evidence` 照旧。授权成立时
`add_authority.technical_reasons` 会写明是哪一次突破——**引用它，不要自己重算价位**。

`quant.early_trend.observed=true` 是 harness 已发现的提前布局候选：必须让 Bull 写最强的
可证伪提前布局论点，让 Bear 写 priced-in/拥挤/来源质量反驳，Judge 再给
`candidate|wait|reject`。规则提名的票 Judge 可以保留、等待或否决；规则没提名（`observed=false`、
tier 为 `none`）而你认为值得的票也可以给 `candidate`，页面会标出这是与登记策略不同的提名。优先核对 `primary_event_ids`；只有新闻转载时必须把
`needs_primary_evidence` 原样保留，不能冒充一手催化。

```bash
/root/.local/bin/clawock tool decision_packet_summary \
  --workspace /root/.openclaw/workspace \
  --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json
```

summary 的 `stock_discovery` 是独立于持仓/peer-map 的持仓外研究队列。它只有
`needs_entry_gate`、`allowed=false` 的候选，不提供建仓授权。所有候选取值相同的字段
（来源 `evidence`、`missing_evidence`、`next_action` 等）只在 `candidate_shared` 写一次，
对每个候选都成立；`candidates` 各行只列自己不同的字段。简报和投递卡由 harness
固定展示；只有同时进入 `proposal_universe` 的票才可写 add 提案，检查该票 `authorization`：`entry_gate_cleared` 表示已读取并验证研究闸；`entry_gate_required` 仍是待研究提案，不能说已获建仓授权。`proposal_availability=unavailable` 的票不得写买单。可说明下一步研究哪个行业、要核什么
一手披露。`snapshot_metrics` 不是实时价格，`observed_at=null` 必须保留「时点未核」。
先用 `quote_request` 经 `clawock fetch-peers` 核验报价，再遵循 entry-gate 的人工研究
流程；不要用 `analyze-us TICKER` 查新票（该命令当前只刷新持仓）。候选源失败写
「Nasdaq 未取到」，不能解释为「没有机会」。港股跨板块发现、analyst 一致预期尚缺。

summary 包含 book/concentration、每票 deterministic status、技术/因子可用性、风险计数、allowed actions 与 evidence IDs。它不要求模型加载原始持仓交易流水或整张因子表。
每票的整手、单批上限、仓位空间只在 `constraints` 里印一次（`--section execution` 有完整尺寸明细）；`row_notes` 里的说明对每一行同名字段都成立。持仓多到 summary 装不下时，harness 会把参考明细收进逐票查询，顶层 `folded` 写明收起了哪一段、用哪个 `section` 查——要用到时按它逐票查，不要当成该票没有这段。

需要分析某票时才查该票；需要单一维度时必须带 `--section`：

```bash
/root/.local/bin/clawock tool decision_packet_query \
  --workspace /root/.openclaw/workspace \
  --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json \
  --arg ticker=00100 --arg section=technical
```

可选 section：`facts|technical|thesis|execution|quant|sentiment|history|information|evidence|risk|status|constraints`。

**实时消息面**：summary 每票的 `live` 是 preflight 刚抓的实时公告/新闻（HKEXnews、SEC 全文检索、Google 新闻、Yahoo，上次收盘以来）前两条 cite，全部条目在 `--section information` 的 `information.live`；引用照抄 cite（含发布时间与「上次收盘后」/「上次收盘前旧闻」，SEC 全文检索只有提交日、「时刻未知」）。summary 顶层 `live_information.<hk|us>.degraded` 非空＝该源没取到，简报里写「X 未取到」，不许写成没有消息。实时条目是消息面证据，不是加仓授权。一次查询硬上限 24 KiB，并同时校验 manifest hash 与 generation。正常分析禁止 `cat brief-context-{date}.json`，也禁止为了省一次查询而整份读 core/research/market bundle。

> **为什么走 `clawock tool`**：工具注册表是这套上下文协议唯一机器可读的定义（`clawock tool --list` 直接吐 JSON schema），而 24 KiB 预算是在注册表里强制的。协议实现随 `clawock` wheel 安装；workspace 只提供本次生成的数据，不再提供可执行 Python 源码。输出含 `_meta.generation_id` 代次钉扎。

### Step 2.5: 按消费者 lazy-load bundles

bundle 是审计深钻，不是默认模型输入。只有 packet 没有提供某个报告必须字段时才加载；每个 bundle 最多一次，紧挨消费者读取。

```bash
# 风险情景 / 解套数学使用前
/root/.local/bin/clawock tool context_bundle --workspace /root/.openclaw/workspace --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json --arg bundle=risk_detail
# EDGAR / 同行明细确需原始研究记录时
/root/.local/bin/clawock tool context_bundle --workspace /root/.openclaw/workspace --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json --arg bundle=research
# 需要查看事件图完整 provenance 时（action 权限仍以 packet constraints 为准）
/root/.local/bin/clawock tool context_bundle --workspace /root/.openclaw/workspace --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json --arg bundle=evidence
# 需要市场级而非 per-ticker 的宏观/名人记录时
/root/.local/bin/clawock tool context_bundle --workspace /root/.openclaw/workspace --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json --arg bundle=market
# Retrospective / Decision v2 校准段使用前
/root/.local/bin/clawock tool context_bundle --workspace /root/.openclaw/workspace --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json --arg bundle=calibration
```

bundle 路由：

- `risk_detail`: `breakeven_math`, `risk_metrics`
- `research`: `quant_signals`, `cross_sectional_factor`, `peer_residual`, `t0_setups`, `us_fundamentals`, `peer_scan` 及对应 review；`strategy_scores` 是策略实验室每个策略按**已登记参数**给各持仓的分数与排名，连同实验室对该策略的结论（`standing`）。它只是参考读数：`live_permission` 恒为 false，不是加仓、减仓或尺寸的依据；`status` 不是 `ok` 时写明未取到，不要当成没有信号
- `evidence`: `catalysts`, `news_evidence_graph`
- `market`: `macro`, `sentiment`, `influencer`, `em_news`, `watch_list`
- `calibration`: `retrospective`, `decision_metrics`, `reflections`

`market.watch_list`（#556）：非持仓 AI 观察池（智谱 02513 / 迅策 03317 等）的**价格面观察**——仅当突破/接近突破/5d 大涨时才有行。写「新机会」节时读取它，但**观察池本身不产生 add 授权**；同名标的若在 `proposal_universe` 中，可按其边界写可评估提案，否则先补报价与 registry。

manifest 若出现 `extras`，表示新 feature 被隔离而没有偷长常驻 core；只有下面明确要求消费该字段时才读。任一 bundle 的 `_meta.generation_id` 与 manifest 不同，立即停止，不得把不同 preflight run 的事实拼在一起。

### Step 3: Swarm 分析（你的创造性工作）

按下面这个 3-tier 流程做分析。所有数字只能从本次 generation 的 packet 查询、确有必要时加载的 bundle、或本次运行内 `clawock tool compute` / `observations` 的返回取；风险分类和 action bounds 引用 harness 结果。packet 给的技术指标和因子分数是固定窗口下的一种算法，你可以用 `compute` 换窗口、换比较对象或定义新的量，但不心算。

#### Required reads

本 cron 是 isolated 运行：上下文里已注入 AGENTS.md / SOUL.md / TOOLS.md / IDENTITY.md / USER.md，
**不注入 MEMORY.md**（直聊才注入）。已注入的不要重读，另外读：

1. 本 skill 的数据/数字/投递规则与本次 packet — isolated cron 不读主会话 `MEMORY.md`；其中的具体教训保留在主会话，cron 约束在本 skill 和 postflight gate 生效
2. `portfolio.json` — 持仓 ground truth（preflight 已刷过价）
3. `memory/{昨天 YYYY-MM-DD}-pre-open.md` 如果存在 — 上次 thesis 和 next-session plan
4. `INVESTMENT_SOP.md` — 启动顺序参考

`context.research_surface` 同样只读，但**必须被消费**：
- `reviews_due` 非空 → 在简报里点名该票 + 披露日期，并说明下一步走 `earnings-review` skill（不要在简报里现编财报数字）。
- `overdue_commitments` 非空 → 写成管理层可信度的负面证据，引用 `commitment_id` 与逾期天数。
- `ungated_positions` 非空 → 明确写「该仓位没有过建仓前研究闸」，这是流程事实不是行情判断。
- `errors` 非空 → 当作数据完整性问题优先报，不要继续引用失效 artifact 里的任何数字。
这四类都不要求你去修 artifact；简报只负责让它们不再无声。

当前持仓 thesis 只读 `context.thesis_registry`，daily brief 不在每天晨报里重写 canonical baseline。`status=unknown` 只表示缺基线，不得靠模型记忆或昨天文案补造历史；需要变更时必须走 registry validator/drift evaluator，并为每个 improved/weakened 维度附本次新增 evidence ID。

#### Regime detection（先跑，定调）

| Regime | 触发 | sizing 含义 |
|---|---|---|
| Trending up | 指数 ADX > 25, MA20 > MA50, RSI 50-70 | 杠杆可持，反弹时只看过热点（RSI > 75）减 |
| Trending down | 指数 ADX > 25, MA20 < MA50, 连续低低 | 杠杆 decay 加速，preferred cash，不加 |
| Range-bound | ADX < 20, RSI 在 50 附近震荡 | T-only，fade extremes |
| Volatile / regime change | 高方差，MA 矛盾，sentiment 混乱 | 缩规模、放宽止损、等清晰 |

**两个市场分开判**（kcn book 是港股 + 美股 mismatch 是常态）：
- US: 用 QQQ / SOX 走势
- HK: 用 ^HSTECH / 恒指

#### Tier 1 — 4 个分析师角度（独立思考、合并成一张大表）

| 票 | Market | Fundamentals | Sentiment | Cross-Market |
|---|---|---|---|---|
| {ticker} | 距成本 / RSI / MA stance / 1 行评级 | EDGAR latest period 或 ETF underlying | 散户温度 / news 异动 | 跟随 / 背离 |

这张表由 harness 渲染：Market 列取自 packet，其余三列是你写的每票 `fundamentals`、`sentiment_read`、`cross_market`（纯文本）。

- Fundamentals 优先用 EDGAR（preflight 已抓），其次 web search peer/历史 P/E
- Sentiment：US 看 r/wallstreetbets + Tavily；HK 看雪球 + 富途 + 南向资金
- Cross-Market：纳指→恒科链路当日是否工作；US 隔夜 vs HK 即将开盘

#### 🔭 投资哲学多棱镜（借鉴 UZI-Skill 的投资人广度，蒸馏成 6 个哲学透镜）

对**最重仓 + 最有争议的 2-3 个持仓**（不是全部，省 token 但 kcn token 充足可放宽到 4-5 个），各用下面 6 个透镜扫 1 行——目的是**用多视角逼出盲点**，不是凑 66 个角色扮演的戏：

| 透镜 | 问的问题（一行） |
|---|---|
| 💰 价值 (Graham/Buffett) | 现价 vs 内在价值/护城河？跌了是便宜还是变质？ |
| 🚀 成长 (Fisher/Wood) | 营收/TAM 拐点还在吗？故事兑现到哪步？ |
| 📈 动量/趋势 | 价在 200 日线哪侧？资金在进还是出？ |
| 🔬 逆向 (Burry/contrarian) | 共识是什么？哪里可能 priced-in/拥挤？反方最强论点？ |
| 🌍 宏观 (Dalio) | regime/利率/流动性对它是顺风还是逆风？ |
| 🧮 量化 | quant_signals 表里的因子状态（**只引用，不心算**）？ |

**铁律**：①透镜是**信息覆盖**（LLM 强项，喂给 Tier 2/3），**不是额外的投票** —— 它们不改变检查方式：事实和可行性照查，登记策略的异议照记。②透镜**分歧本身是信号**：6 个里若价值说买、动量说卖，写明这个张力，别假装统一。③别为每个持仓都跑全套（token 与噪音权衡），抓关键票。

#### ⚡ 板块全景（必跑 — context.json 不覆盖）

每日 Tier 1 后必做一段板块横向扫描，目标回答："你持仓在板块里**领涨/落后/中位**？归因是什么？"

- 板块来源是动态的：读 `memory/peer-map.json`，**每个 active ticker 的 `theme` 字段就是它的板块名**（如 "HK AI 大模型" / "HK 科技指数 2x leveraged (HSTECH 标的)" / "商业航天"）。持仓变了，板块自动跟变 — 不要在 SKILL.md / 报告里写死任何特定 ticker
- 对每个去重后的 theme 跑一次 `clawock web-search` —— 它**同时**问 DeepSeek 搜索和 Tavily，两个源并列、各自一节输出、各自标状态（不是主备，一个源失败不影响另一个源的结果）。两边限额各算各的：**Tavily** 免费档 1000 credits/月全局共享，本 skill 每天只 1 次、按去重后的 theme 数搜（通常 ≤10 次/天），别对同一 theme 重复搜，**必须带 `--bucket brief`**（走本 skill 的月度配额 300；不带会落 `research` 桶）；**DeepSeek** 没有 credits 预算，只有账号级 5 QPS（本机统一限速），同行/催化/叙事想多查可以再跑 `--providers deepseek`：
  - HK 板块 → `clawock web-search "今日 HK {theme} 涨幅榜 板块异动" --days 2 --bucket brief`
  - US 板块 → `clawock web-search "{sector ETF 如 SOXX/QQQ/ARK} 今日成分涨跌" --days 2 --bucket brief`
  - 某个源返回 `unavailable`（Tavily 额度用尽/DeepSeek 限速或余额）时 exit 0，**别当报错**；用另一个源和当前会话内置搜索，并写明哪个源没取到。两源都没取到才是"未检索"，不是"无消息"
- 每个板块输出：Top 3-5 涨幅 + 你持仓票在榜单中的位置（领涨/落后/中位）
- **归因句必带**：落后是因为(a) 利好时点（盘后才公布）/ (b) 早盘异常抛压 / (c) β 错配 / (d) 个股逻辑滞后？
- 结论写进 `judgment.narrative.sector_read`（纯文本，引 ≥3 个具体涨跌幅 + 1 个明确归因）；报告里的板块表由 harness 从 `context.peer_scan` 渲染，逐票那句判断写在该票的 `peer_read`
- ⚠️ **持仓自己的数字** (RSI/MA/PnL) 仍然从 core 取，板块这段只 search 板块/同行公开行情
- **同时落盘到** `memory/.tmp/sector-scan-{date}.json`（build_dashboard 会读，让 GH Pages dashboard 同步显示）。schema：
  ```json
  {
    "generated_at": "{ISO8601}",
    "date": "{YYYY-MM-DD}",
    "sectors": [
      {
        "theme": "HK AI 大模型",
        "tickers_in_book": ["00100"],
        "top_movers": [
          {"ticker": "06651", "name": "五一视界", "pct": 27.6, "catalyst": "具身智能数据平台"},
          {"ticker": "00992", "name": "联想集团", "pct": 15.0, "catalyst": "AI 营收翻倍"}
        ],
        "self": [
          {"ticker": "00100", "pct": 0.07, "rank_text": "落后", "attribution": "Token Pay 盘后才公布"}
        ]
      }
    ],
    "narrative": "今天港股 AI 板块全面爆发，主角不是 MINIMAX 而是..."
  }
  ```
  - 缺失/解析失败 dashboard 容错（market_context 退回 portfolio.json 的 {}），不影响 brief 投递

#### Tier 2 — Bull vs Bear（必须有真分歧）

两段，各 80-120 字。Bull 用 Tier 1 数据组装"持有 + 加仓"案；Bear 用 Tier 1 数据组装"减仓 + 砍仓"案。**至少在 1 个仓位上观点不同** — 完全一致说明辩论失败。

引用：每方至少引 2 个具体 Tier 1 数据点（不是 vibes）。

**Devil's advocate（#1101）**：Bear 除组装"减仓 + 砍仓"案外，必须**点名攻击当前最强共识**——即 Tier 1 表里最被看好的票 / 最强势的多头论点，并写明攻击的是哪个结论。不许只挑软柿子；若确实无强共识，明说"无强共识，攻击次强"并给出理由。目的：压制群体思维与锚定，别让辩论顺着第一个观点滑下去。

#### Tier 3 — 3 个 Risk Voice + Judge

| Voice | 立场 | 必须做的 |
|---|---|---|
| Aggressive | 抓 upside | 引用 Bull 最强点；指出 Conservative 错过了什么 |
| Conservative | 保本 derisk | 引用 Bear 最强点；指出 Aggressive 低估的尾部 |
| Neutral | 拍中线 | **对每个争议票必须拍一边**，"看情况"是失败答 |

**Judge** 权重规则：
- kcn 风险偏好 = **激进**（USER.md），Aggressive 默认略多权重
- **但** trending down regime 启动时 Conservative 权重 +1 档
- 数据 stale 任何一段 → 涉及票 confidence -10pp
- **视角轮换（#1101）**：三位风险官的首位表态权每 4 个交易日轮换（Aggressive → Conservative → Neutral → 循环），当日首位 voice 写进 `judgment.narrative.risk_voice_first`（harness 据此排序）。轮换只改表态顺序与框架设定，**不改** kcn 激进偏好的权重规则。

输出策略级 decision。**同一股票同一天允许多条决策**，例如 `core_position` 继续持有，同时 `intraday_t` 做日内 T；两者不能互相覆盖。

| action | 含义 |
|---|---|
| `cut` | thesis 破，挂卖单 |
| `trim_on_rebound` | thesis 弱化，等强势 |
| `hold_and_watch` | thesis 完好，无操作 |
| `t_only` | 不留隔夜信念，fade 极值 |
| `add_only_on_trigger` | 明确触发条件后加仓 |

每条 decision：ticker + `strategy_id` + action + 1 行具体理由 + 1 行触发条件。

**每个 decision 必须带 `driven_by`**——这个策略决策主要由哪个数据源驱动（写进 v2 ledger，按 episode 计算 edge）：

| driven_by | 含义 |
|---|---|
| `technical` | 价格/MA/RSI/缺口/量价(默认值；纯图表驱动归这里) |
| `catalyst` | 硬事件：财报/指引/SEC/EDGAR/M&A/产品发布(catalysts + 新闻里的硬催化) |
| `sentiment` | 软情绪：Reddit 热度 / Google News 情绪 / 散户温度 |
| `influencer` | Trump 原帖 / Musk·段永平·洪灏·Burry·Pelosi 报道 / ARK 日度调仓 / Serenity |
| `macro` | VIX/利率/DXY/指数 regime |
| `peer` | 相对强弱 / 板块轮动(同行扫描驱动) |
| `risk_rule` | 组合上限、杠杆、β 等政策型再平衡 |

规则：**只填主导那一个**(不是把所有沾边的都列上)。若是技术面为主、消息面只是佐证 → 填 `technical`。这个字段决定我们能不能回答"消息面值不值得听",所以要诚实归因,别把图表驱动的 call 贴成 catalyst 来给自己加分。

#### 📊 driven_by / strategy 的动态 edge（REQUIRED）

只读 `context.decision_metrics.by_driver` 与 `by_strategy`，禁止把 README 或旧报告里的点时数字当当前事实。比较 `n_episodes`、`avg_benefit_pct` 和 `cluster_ci95`：n 小或 CI 跨 0 时只能说“方向性”，不能声称显著。`risk_rule` 是政策执行，不当作择时信号夸奖。

#### 🎚️ 分层 confidence 校准与 sizing（REQUIRED）

原始 `confidence` 只保留为作者当时判断的审计字段，不是胜率。`context.decision_metrics.hierarchical_calibration.current_group_calibrators` 是这本账自己的战绩：每个 `action + driver + condition + regime` 组的校准概率、CI、`edge_supported` 和 `signal_size_multiplier`，由严格按 `plan_date` 前向更新的 beta-binomial 校准器产生，稀疏小组收缩到更宽层级。

- **匹配由 postflight 做，不用你做**：每条主动决策写完后，系统按它自己的四个字段查表，把命中的那一行盖在该决策的 `calibration` 字段上（没有命中 = 该组证据不足，照此标注）。不要在 plan 里自己写 `calibration`，也不要手工换算倍数。
- **这张表是事实，不是尺寸公式**（kcn 2026-10-10）。股数由你定，上限是持股（`max_sell_shares`）和现金与集中度留出的空间（`position_room_shares`）；`max_add_shares` 是登记策略的单批建议，超过它会记一条异议：战绩说「这类 call 过去没跑赢」时，你可以缩小、可以照做、也可以认为今天不同而加码——在 `rationale` 里说出你怎么看这条战绩，尤其是逆着它下注的时候。它之后和结果一起被复盘，这就是你改进自己的材料。
- 表里只装 `evidence_sufficient=true` 的行；省略了多少、分别因为什么，看同级的 `current_group_calibrator_count` / `current_group_calibrators_omitted` / `omitted_abstain_reasons`。表变短说明证据变薄，不是数据丢了。不要拿相邻小组的点估计冒充本组，也不要把缺证据说成有 edge。
- 组合硬闸的 `risk_rebalance + risk_rule` 是政策执行，不是预测；校准战绩不能用来否决硬闸要求的动作。

#### 🌡️ 牛 / 熊 / 震荡 regime（REQUIRED，保留）

Bull/Bear 是决策框架的一部分，不能因升级账本而删除：

- Tier 2 仍必须分别写 Bull case 与 Bear case，并且至少在一个持仓或一个策略上形成真分歧。
- 当前 regime 仍由 `context.macro.regime` 和可用的市场趋势数据判断为 `risk_on` / `neutral` / `risk_off`；报告必须写判断依据，数据 stale 时明确降置信度。
- `risk_on`：`core_position` 默认让利润奔跑；没有证伪催化时不要因短线波动反复 cut。`intraday_t` 与 `risk_rebalance` 可独立存在，不能覆盖 core thesis。
- `risk_off`：提高防御权重，杠杆与集中风险优先由 `risk_rebalance` 处理；`tactical_entry` 需要更强的价格/事件触发。
- `neutral`：按各 strategy 自己的 condition 执行，不把同股不同时间尺度压成一个动作。
- 复盘时按 `strategy_id` 分层看牛熊适应性；在 v2 尚无足够 regime episode 样本前，保留定性判断并注明样本不足，绝不引用旧 v1 的静态百分比冒充当前结果。

这意味着“牛市 core 持有 + 同日 intraday T”“熊市 core 未证伪 + risk_rebalance 降杠杆”都可以同时成立；它们是不同策略，不是自相矛盾。

#### 🚦 仓位/杠杆硬闸(REQUIRED — 优先级高于 driven_by 与 regime guard)

**回撤复盘的最大教训:亏不是因为"没听 LLM",是因为组合构造**(US β≈4.4、73% 杠杆 ETF、HK 85% 单因子)。任何一个 driven_by 面都没提前叫出来——这不是信号问题,是**风控纪律层缺失**。所以在所有 driven_by/regime 逻辑之上,先过一道仓位硬闸。

preflight 已算好,直接读 `context.risk_guardrail`:
- `breaches[]` — 每条 = 一个超限的硬闸(single_name / factor_concentration / leveraged_exposure / beta),带 `detail` + 现成 `action`(含具体减仓金额)。
- `hard_stop_watch[]` — 杠杆 ETF 浮亏跌破 −18% 的硬止损触发。
- `directive` — 本次总指令；`caps` — 当前阈值（2026-10-11 kcn：集中与杠杆 ETF 敞口不设上限。单名超过 35% 只进 `concentration_reviews`，杠杆与否都不算 breach；单名、相关 cluster、杠杆 ETF 占比上限都是整段 100%，杠杆 ETF 占比仍按港股制度乘数收紧；US β 6.0；杠杆止损 −18%）。持仓策略带 `forbid_reduce_advice` 的票（现为 `infinite_ammo_dca`）不出硬止损和 `regime_delever` 行。Top2 仅展示，不再冒充同因子。
- `context.risk_discipline.records[]`（core，常驻）— 同一 breach 的持久状态：`breach_id`、严重度、`age_days`、首次/最后变化、required reduction、acknowledgement、限时 override、execution evidence；`adaptive.recent_choices` 是最近几次 stand/reissue（完整理由留在账本）。每日重新生成的 plan 不是状态账本。

硬性规则:
- **强制与回应分两类**,看每条风险行的 `risk[].enforcement`(#2839):
  - `forced`(杠杆硬止损、`regime_delever`):规则自己给了去处(`required_reduction.swap_to`),必须在 Judge 段落出对应动作(cut,或 regime 的 trim/cut),不准"观望"。**唯一例外**是下面「长期不执行的建议」里 `adaptive.may_stand=true` 的那几条,以及 durable override 生效的。
  - `respond`(`single_name` / `leveraged_exposure` / `factor_concentration` / `beta` 四类上限):规则只说要减多少、没说钱去哪,所以**不强制卖**。每条都要回应:减仓(trim/cut),或 `hold_and_watch` 并在 rationale 写明今天为什么不减、什么情况下会减。不许不提,也不许只写一句「继续观察」。**超限期间该票加仓关闭**,持有不等于可以加。postflight 把这次选择记进风险账本。
  - 卖出不是默认答案。比较减仓后持有现金与换仓的机会成本；现金也可以是有理由的选择。强制义务只核应减数量，不强迫同时写买腿。引用 `risk_rule` 换仓买腿时，仍须遵守指定目标与配对金额。
- 每条 open 记录必须引用 `breach_id + age_days + acknowledgement/execution 状态`；未确认的老 breach 要明确升级，不得每天当新提醒重写。
- 当天 plan 内的 `override.status=active` **不能**豁免硬闸。只有 durable ledger 里带非空 reason 且未过 TTL 的 `status=overridden` 才有效；创建例外必须由用户明确决定，可用 `/root/.local/bin/clawock risk override BREACH_ID --reason '...' --ttl-hours N`。确认已看见用 `risk ack ... --note '...'`，成交证据用 `risk confirm ... --evidence '...'`；这些命令只记账，绝不下单。
- 任何 critical/high breach 未关闭且未 durable override 时，禁止新增同一标的、杠杆或因子暴露。卖出不受阻；同一份 plan 中可证明净降 factor exposure 的 2x→1x 配对换仓不受阻。
- 这些减仓及其风控换仓买腿 **strategy_id=`risk_rebalance`、driven_by=`risk_rule`**（纪律性再平衡，不是择时预测），并在 rationale 注明组合政策依据。
- **risk_on 的 HOLD 是策略默认，不是动作禁令**：纪律性再平衡与自主的策略异议都按实际证据说明，不能只因 regime 标签否决。
- 登记策略通常优先削杠杆 ETF 来降 β；具体选择由模型比较敞口、机会成本与 thesis，使用风控处方时遵守该处方。
- **杠杆ETF解套口径(kcn 2026-06-11 定)**:杠杆 ETF 的 breach/hard_stop 动作 = **2x→1x 同因子换仓而非清仓**(映射在 `brief_preflight.LEV_1X_SWAP`:07226→03033、PLTU→PLTR、ROBN→HOOD、MSFU→MSFT)——敞口不变、反弹一点不踏空,但停掉日内重置 decay;`context.risk_guardrail.reentry_rule` 满足(🧭转 green,标的收复 200 线)才允许 1x→2x 换回。**现货(非杠杆)套牢 kcn 方针=持有等待合法**(现货等待免费,2x 等待收费),对现货超限的最低要求是"不补仓、借反弹分批",别反复催清仓。
- **换仓的买腿怎么写(#1075)**:2x→1x 是**一砍一买两条腿**,买腿由**风控规则**授权,不需要
  技术 setup。目标票的 `constraints.swap_mandate` 就是那份授权(`from_ticker` / `breach_id` /
  `max_value` / `currency`);此时它的 `allowed_actions` 会含 `add_only_on_trigger`,直接用,
  别因为它没有 setup 就退回 hold。三条硬约束:①只能买 mandate 指名的那一只 ②金额不超
  `max_value` ③**两条腿必须共享同一个 `decision_group_id`**(ledger 只按这个字段配对换仓;
  写成别的字段名会在归一化时丢掉),否则 postflight 拒收买腿、decision_audit 也会把它当成裸买。两腿股数必须为正整数，买腿满足目标票的 `lot_size` 整手。目标票自己也在 breach 时 mandate 为 `null`——那就是不许换过去。
- **目标没持有的处方同样可以写买腿**:packet 顶层 `swap_mandates` 列出全部处方,含 `target_held:false`
  的(例:RKLX→RKLB,RKLB 6/13 已清)。这些目标在 `tickers` 里没有行,在 `swap_targets.<票>` 里有:
  `facts.current_price`(连同 `price_basis`:`quote` 是今天取的报价,`last_close` 是最近一场收盘,
  `price_as_of` 是它的日期)、`constraints.lot_size` 与 `constraints.swap_mandate`。买腿写法与持有的
  目标完全一样(`add_only_on_trigger`、同一个 `decision_group_id`、金额不超 `max_value`、整手);
  `current_price` 为 null 时必须自己在 `condition.price` 写入场价,港股目标 `lot_size` 为 null 时这条
  买腿写不了,在本段说明「目标整手未取到」。`swap_targets` 里的票只能作为处方的买腿出现,
  不需要也不允许写 `ticker_judgments` 行。
- **standing 判词**:每条 breach 的 `risk[].standing`。`decision_overdue=true` 表示它已经站了
  ≥`threshold_days` 天而 execute / acknowledge / override **三个出口一个都没走过**。这时不要
  再写第 N 遍同样的提醒,写成一个要求:要么执行,要么用 `risk ack` 留痕"看见了、接受它继续开着",
  要么用 `risk override --reason` 记下**为什么决定不做**。实测 2026-08-26:三条 hard_stop 站了
  42 天、同一条砍单发了 136 次、执行 0 次,而 `override` 字段一次没用过——账本读起来像"没人看",
  真相是有人每天看、每天决定不做。
- **长期不执行的建议 —— 今天提不提，由你判断(2026-09-12 kcn)**:每条风险行带 `adaptive`。
  harness 已经从账本和成交记录算好了证据,你不用、也不许自己推断 kcn 想不想做:
  - `eligible=true` = 挂 ≥10 天 + kcn 明确没照做:`stance.stance=declined`(同期在别的票有成交,
    这几只一股没减)或 `contrary`(被要求减的时候反向买入,`buys_on_target` 次)。`silent`(最近
    没交易,可能不在)**不算**表态,不能让一条 breach 变成 eligible;已经 eligible 的不因此收回。
    同一条 breach 平掉后 30 天内再开算同一轮,天数和搁置资格延续。
  - `may_stand=true` → 今天由你选:**重提**(照常出 cut/trim)或**维持**(出 `hold_and_watch`,
    `strategy_id=risk_rebalance`、`driven_by=risk_rule`)。默认维持;**只有今天和上次重提时比
    有实质不同**才重提——跌穿关键位、新的一手催化、制度切换、临近事件(FOMC/财报)——
    并在 rationale 第一句写出「今天和 `last_reissued_on` 那天比,变了什么」。写不出来就维持。
  - 选**维持**时,rationale 不要再写第 N 遍「应该砍」。kcn 的做法已经摆在 `stance` 里
    (例:SPCH 是「无限子弹流继续摊本」):在他选的打法里给有用的话——这个仓位最该盯的位、
    什么情况下这套打法本身不成立。**加仓仍然冻结**,维持不等于可以加。
  - `must_reissue=true` → 按 `risk[].enforcement` 回应：`forced` 才要求 cut/trim；`respond` 仍可说明理由后持有，不因重提计时器变成强卖。rationale 引 `must_reason`
    (再深 10pp / 需减额 1.5 倍 / 严重度升级,或距上次重提满 28 天)。
  - 选择由 postflight 记进账本(`adaptive.stances`),你不写账本、不编 id。
- 若 `breach_count=0` → 本段写"✅ 仓位硬闸无触发",照常决策。
- **解套/回本数字只准引用 `context.breakeven_math`**(preflight 已算好:每只浮亏持仓回本所需涨幅、2x 的横盘 decay ≈σ²/12 每月、半年窗含 drag 等效标的涨幅),禁止自己心算或编造。解读纪律见其 `note`:直线涨→2x 回本更快;横盘→2x 每月白付 decay;再跌→2x 双倍挨打——换 1x 买的是后两种情景的保护,不是回本速度,别说反。
- **技术面数值引用 `context.quant_signals` 中 `status=fresh` 的行，或本次 compute 的带日期回执**(每只持仓的趋势/动量/RSI/zscore20/吊灯止损线/vol_target_weight,杠杆 ETF 按标的算)；`stale/missing/retired` 行只用于披露数据缺口，禁止据此形成判断，也禁止自创"看图"结论。**因子话语权由 `context.quant_signal_review` 决定**(信号每日留痕 vs T+1/T+5 前瞻收益自动对账):必须公示 `n_events/n_dates/n_tickers`;`usable=false` 或聚类 CI 跨 50% 说明这条规则的前瞻对账不支持它，引用时必须写明；它不妨碍你使用同一组观测形成自己的判断。`decision_direction=reverse` 仅在反向 CI 整体低于 50% 时成立，禁止因 raw hit_rate<50% 自动反向。T+0 牌面的评级同理：`sample_sufficient=true AND edge_supported=true` 之外的评级是未获对账支持的规则意见，引用时写明；样本够多但 Wilson CI 不支持原方向仍是 `usable=false`，不得据此自动反向交易。`driven_by=technical` 的整体战绩一律读取 `context.decision_metrics.by_driver.technical` 的实时计算值，禁止引用固定百分比。这是自迭代环——哪个因子可信,数据说了算,每天自动更新。
- **跨截面因子读 `context.cross_sectional_factor`**。这是同行/1x 标的的行业中性研究层。`activation.usable_for_decisions` 说的是**那个预注册 composite 的前瞻验证有没有通过**，不是其中每个测量值能不能用：单项测量（动量、相对强度、波动、回撤、质量）是核实过的观测，可以进入你的判断；composite 分数和排名是一种登记过的加权意见。为 false 时，引用 composite 或排名必须同句写明「该组合打分未通过前瞻验证」，不得把 retrospective CI 说成 prospective 证据，也不得把它写成已验证的优势。
- **同行残差读 `context.peer_residual`**。leader continuation、laggard avoidance、mean reversion 三条规则各自的 `rule_activation.<rule>.usable_for_decisions` 说的是那条规则的样本够不够，不得互相借样本。残差本身是测量值，可以用；规则未激活时引用它的触发要写明「该规则样本未达标」，由你判断这次是否仍然成立并给出理由。港股 peer 只能来自人工 `peer-map.json`，禁止补写或调用自动 HK 同行发现。
- **规则产出与观测分开读（#2843）**：packet 的 `judgment_contract.rule_outputs` 列出每个 section 里哪些字段是登记规则的结论（`technical.tag` / `setups`、composite、`add_authority`、`status.label` 等）。它们如实记录了规则说了什么，但不是市场事实：可以采纳，可以不同意，不同意时写明依据。规则没有点名的观测不因此不能用。
- **需要 packet 里没有的量，就让系统算，不要心算**：

  ```bash
  # 你定义的特征：窗口、比较对象、公式都由你选；返回数值和回执（receipt_id、as_of、读了哪些日线）
  /root/.local/bin/clawock tool compute --workspace /root/.openclaw/workspace --arg 'expression=zscore(close("RKLX") / close("RKLB"), 20)'
  # 规则结论底下的原始观测：日线 / 因子逐项测量 / 全部事件（含未升级的）
  /root/.local/bin/clawock tool observations --workspace /root/.openclaw/workspace --arg ticker=RKLB --arg kind=factors
  ```

  `compute` 可用函数见 `clawock tool --list`（`close/open/high/low`、`sma`、`ema`、`ret`、`vol`、`zscore`、`atr`、`atr_pct`、`rsi`、`range_pos`、`drawdown`、`beta`、`corr`、`highest`、`lowest`、`last`、`lag`，序列之间可加减乘除），ticker 写成带引号的字符串，持仓外的 registry 标的同样可算。结果的数值原样引用，并在该句写出它是什么（「RKLX/RKLB 比值的 20 日 z 值 -0.74」）；postflight 认本次运行内算出的回执。回执只证明输入存在、没读 `as_of` 之后的数据、算术可重放，**不证明你的假设成立**。日线从 2025-12 起存，窗口不够会直接报「insufficient history」，照实写，不换个说法补一个数。

> `driven_by` 如实记录主导证据；风险行区分强制义务与回应义务。超限不自动等于卖出，观点和减仓选择不能从阈值直接推出。

#### ⚖️ 消息面权重：硬催化 vs 软情绪（登记策略的默认做法）

本节和下一节「证伪不证实」是登记策略对消息的处理方式，来自牛市里反复 churn 的教训。默认照做。你有具体证据认为这次不同时可以不照做：把依据写进 `hypothesis`，把认错条件写进 `thesis_invalidation`，harness 会在这条决策上标出它偏离了哪条规则。**不能做的是另外两件事**：引用不存在或对不上票的事件（事实错误），以及为了躲标注而改 `driven_by`。

登记资讯策略更重视一手硬催化，对标题情绪、热度与名人言论采取保守权重。这是待检验的策略，不是事实层对动作的许可表：

| 类别 | 例子 | 登记策略的意见 |
|---|---|---|
| 硬催化 | 财报/指引、监管文件、合同、明确政策落地 | 可作为主要驱动，仍要核对原文、时点与价格反应 |
| 软情绪 | 标题情绪、热度、无落地的名人言论 | 通常只作佐证；是否足以改变动作、权重与信心由模型说明 |

- `actionable_escalation=true` 是资讯策略的升级结论。引用未升级的真实事件也可提出主动动作，并保留策略异议；`evidence_event_id` 必须真实且属于该票。
- 重复摘要不等于独立证据，过期事件不可冒充新消息。`positive/confirming` 是证据方向，不自动规定 hold。
- `tavily_resolution_queue` 每条带 `command`（`clawock web-search … --bucket brief`，DeepSeek 与 Tavily 并发）；Tavily credits 只花在队列里的事件上，DeepSeek 不受此限，其他事件也可 `--providers deepseek` 补查。结果的可信度、与原事件的关系及是否改变判断由模型解释，不把搜索成功当成交易许可。
- 不再规定软情绪只能调整 confidence ±10pp，也不规定只有硬催化能翻转动作。采用情绪、名人或机构调仓线索时，说明机制、来源局限与认错条件；ARK 的交易是别人的交易，不能冒充公司事件。
- 按真正主导证据填写 `driven_by`，不为迎合登记策略改标签。自定主动提案用 `hypothesis` 说明为什么值得做。
- **前瞻事件的日期只能引用 `context.catalysts`，禁止推测。** 财报/FOMC/宏观在 `earnings`/`fomc`/`macro_events`；公司级预定事件（港股通生效日、解禁日、mainnet 上线、指数调整生效日）在 **`scheduled_events`**（真源 `memory/scheduled_catalysts.json`，手工维护）。
  - `date_confidence=confirmed` → 可直接写该日期；`estimated` → 写日期但必须标「预计」；**`date` 为 `null`（`unconfirmed`）→ 只能写「生效日未确认」，不准用「下周一」「下个月」「9 月」这类自己推出来的说法**。
  - `scheduled_events` 里没有的公司级预定事件 → **当作日期未知处理**，同时在 `▎待补` 提示把它加进 `memory/scheduled_catalysts.json`，别在正文里编一个。
  - 为什么是铁律：2026-08-06 的简报对同一个 MiniMax 港股通事件给出了**三个互相矛盾的日期**（「下周一生效」/「next month」/「9 月生效」），而正文正在拿这个日期决定要不要 trim。没有结构化真源时，模型每天重猜且没有任何东西会红。

#### 🛡️ 消息面证伪不证实（登记策略的默认做法，牛市最关键）

登记策略偏向让已有趋势继续，担心利好引发反复买卖的成本。模型仍须比较继续持有、减仓、加仓的证据与机会成本；正面消息不必然已在价，负面消息也不必然值得卖。

进入决策的新闻标记 `confirming`（印证当前 thesis）或 `disconfirming`（挑战 thesis），方便复盘。标签描述证据关系，不决定可写的动作。若判断利好、估值或情绪足以支持动作，保留真实归因并写假设与失效条件；不要改成 `technical` 或 `risk_rule` 来避开异议。纪律性动作只有在确实依据风险规则时才标 `risk_rule`。

#### Strategy frame 示例 — Judge 写明主导机制

让 Judge 明示哪个 strategy frame 在驱动每个 action，便于事后检验。下面 8 个是示例，也可以写自己的简短名称（最多保留三个标签，长论证写在 judge / method）：

| Frame | 触发条件举例 |
|---|---|
| `momentum` | MA 多头排列 / 量价齐升 / 新高 + 成交放量 |
| `mean_reversion` | RSI > 75 / < 25 / 偏离布林带 +2σ |
| `breakout` | 突破前高 / 关键阻力位 + 放量确认 |
| `relative_strength` | 跑赢/输 benchmark > 3pp（peer 涨自己跌也归此） |
| `earnings_setup` | 财报前后 5d / 预期 vs 实际 surprise |
| `sentiment_shift` | F&G 拐点 / 新闻情绪 5d 翻转 / 异常 short interest |
| `technical_breakdown` | 跌破 200MA / 跳空缺口 / 头肩顶 |
| `sector_rotation` | 同板块 peer 强自己弱（或反之） |

格式：

```
▎Judge — strategy frames

| Ticker | Action | Frame | Detail |
|---|---|---|---|
| SOXL | trim_on_rebound | technical_breakdown + relative_strength | 跌破 200MA + 跑输 NVDA -8pp |
| 00100 | hold_and_watch | sentiment_shift | F&G 从 fear 转 neutral |
| RKLB | cut | mean_reversion | RSI 78 + 浮+82% |
```

说明具体机制与证据，不用空泛的“综合判断”代替论证；定性证据可以成立，不为填表编造数值。

`frames` 是模型自定的文本标签，归一化保留新名称；`driven_by` 与 `strategy_id` 仍分别记录证据来源和账本策略，标签不能替代这些字段。

纪律型减仓如实说明政策依据，不必硬套技术机制；`frames` 可省略，也可用自定名称表达真实机制。不要为了覆盖率编造观点。

#### Confidence calls

每个主要 action 给 0-100% 信心 + 1 行简单理由：

| 区间 | 校准 |
|---|---|
| 80-100% | 4 个 analyst 全部同向，Bull/Bear 强点收敛，数据新鲜，regime 清晰 |
| 60-79% | 大部分同向，1 个 analyst 异议，regime 清晰 |
| 40-59% | analyst 分裂，regime 混乱，或 1 段数据 stale |
| 20-39% | 信号冲突，疑似 regime change，多段数据 stale |
| < 20% | 不要按这个 read 行动；等清晰 |

#### 报告各段：harness 印数据，你只写判断字段

下面这些段落的表格、读数、标题和顺序都由 harness 从 context 渲染（Step 4 A）。你写的只是
右列的 judgment 字段：纯文本，不画表，不写 `▎`，字数上限见 Step 4 C。字段留空，发布出去的
报告就空一段。

| 报告段 | harness 印什么 | 你写什么 |
|---|---|---|
| 昨日 plan 兑现度 | `context.retrospective` 逐条兑现表 | 教训并入 `narrative.calibration_read` |
| 同行扫描 | `context.peer_scan`：上一场收盘、最强同行、差距 | 每票 `peer_read` |
| 大盘速读 | `context.macro` 读数；页眉印 regime 标签 | `narrative.macro_read`、`narrative.regime_read` |
| 社交舆情 | `context.sentiment.tickers` 的提及数、新闻、近 N 日涨跌 | 每票 `sentiment_read` |
| 名人异动/政策风向 | `context.influencer` 全段 | 无专门字段；在别的段落引用时按下面的口径 |
| 决策校准 | `decision_metrics` 校准表 | `narrative.calibration_read` |
| 下一时段 | — | `narrative.next_session` |

#### 同行扫描：每票 `peer_read`

一句判断，按题材与自己的方向四选一起头：
- 题材+ 自己+ → "alpha 抓住了"
- 题材+ 自己- → "考虑切换：peer 比我强"
- 题材- 自己- → "持有合理，等题材轮回"
- 题材- 自己+ → "稀有，珍惜"

出现「考虑切换」→ Tier 3 Judge 给 rotation trigger（例："00100 反弹至 800 减 20 股，换入 0020 商汤"）。

#### 大盘速读：`macro_read` 与 `regime_read`

`macro_read` 不超过 5 句，每句一个指标 + 它对**当前持仓**意味什么（不是教科书定义）。Fed 最新发布
与利率无关（如人事任命）时不提。

- `context.macro` 为空 = preflight 判过期（超过 36h，或指数收盘落后最近一场已收盘 session）或缺失：`macro_read` 只写一句"⚠️ 宏观快照过期，本段不印读数"，不引用任何指数读数；postflight 不 fail

**🧭 Regime guard（REQUIRED）**：`context.macro.regime` 给出 `label`(risk_on/neutral/risk_off)+ `reasons`。
页眉由 harness 印 label；`regime_read` 写 reasons 拼成的一句 → 该 regime 下的决策默认。据 regime 收敛主动操作：
- **risk_on** → core_position 默认 HOLD；择时 cut/trim 要说明证据与机会成本，偏离登记策略照收照档。`risk_rebalance` 是独立策略，可因组合政策在 risk_on 中减杠杆，不与 core thesis 混为一谈。
- **neutral** → 正常按 frame 判断,无额外封顶。
- **risk_off** → 防御优先,cut/trim 门槛放宽(可信度提高),add 需更强触发;杠杆仓位优先减。
- regime 缺失(null,数据 stale)→ 写"regime 未知,主动操作按常规谨慎"并跳过封顶。

#### 社交舆情：每票 `sentiment_read`

`context.sentiment.tickers` 只含有信号的票（0 mention + 0 news 的已剔掉）。
- **price-in 判断必做**：近 N 日涨跌取自 `recent_move`（`px_pct` over `n_sessions`，可能为 null=无快照）。利好 + 该票近期已大涨 → 多半"已在价"，追/不减都行但别当新理由出手；利好 + 没动 → 才有"未反应"的可操作空间；利空 + 已大跌 = 部分消化，利空 + 没跌 = 风险未释放要警惕
- 新闻只抽 2-3 个动词/名词短语，不复制全标题
- 判断必须连到**你今天对这个票的具体 strategy/action**（一致 / 矛盾要点出来）
- 可标 `[confirming]` 或 `[disconfirming]` 说明它与 thesis 的关系；两者都不限制动作，异议按「谁决定什么」记账
- 该票 news_top + reddit_top 命中负面关键词（`miss/SEC/probe/fraud/lawsuit/downgrade/halt/recall/short report`）时，在它的 `sentiment_read` 里点名是哪个
- sentiment 数据 age_hours > 36：写"⚠️ sentiment 数据 stale"，不据此下判断

#### 名人异动/政策风向：引用口径

这一段由 harness 从 `context.influencer` 全部印出（Trump 原帖 + Musk/段永平/洪灏/Burry/Pelosi 的港美媒体报道 +
ARK 日度调仓 + Serenity 选股帖，LLM 已筛市场相关性并交叉匹配过持仓）。你在辩论、判断或下一时段里引用这些条目时：
- 优先级 **撞持仓 > 新机会 > 板块相关**；撞持仓的条目要连到该持仓今天的 action
- 新机会是 kcn 没持有但被点名/推荐的票——选股线索，点出 stance 和是否值得进 watchlist；stance=attack/sell 是**规避/做空**信号，不是买入信号
- Musk / 段永平 / 洪灏 / Burry / Pelosi 条目是"新闻代理"(二手)，可信度低于 Trump 原帖；Pelosi 的成交发生在 30-45 天前、新闻点是**披露**本身，别写成"今天买入"
- ARK(Cathie Wood) 是机构日度成交记录：`买入`= 加仓、`卖出`= 减仓，**不是**看空/抨击；周末与港股假期看到的是上一个美股交易日的动作
- Serenity 来自 Substack(一手但低频)，多为微盘/小票选股 idea：当线索看，**别当买入指令**，需自查基本面/一手证据(见 [[serenity-skill]])
- `source_status` 有 `failed` 的来源是没取到，不能写成该作者没有动向；age_hours > 36 或 counts.total=0 时不引用

#### 决策校准：`calibration_read`

calibration bundle 的 `decision_metrics` 是 v2 唯一口径：只结算**条件实际触发**的决策；同一 `ticker + strategy_id` 的连续同类决策合并为一个 episode，只取一次代表样本，避免每日重复建议放大样本量。校准表由 harness 印；`calibration_read` 写你从表里读出的结论：
- 主动决策 n、平均 benefit、date-cluster CI；主动口径信心校准对 `brier_baseline_loo` 的比较
- 按 strategy / action / driven_by 点出最强与最弱各一项
- 执行状态：**要动手的**与**不用动的**两条腿分开写，执行率不等于建议质量。两条腿各自的 `stranded` **必须同句写出来**（「另有 N 条永远验不了，不在分母」）——那是窗口早已关闭、`_detect_followed` 每次重试都答 unknown 的行，标的从没进过 holdings，被丢掉的样本偏向「没执行」，所以裸报的执行率系统性偏高
- 昨日 plan 兑现度的教训 1-2 句：什么 trigger 设过紧/松；什么 thesis 站住/破；哪个 confidence 区间过自信。trigger 未触发的机会成本可能为正（错过 alpha）或负（躲过损失）

规则：
- `calibration.active.n < 8` 或主动 n 缺失：明确写样本未填满，只作方向性参考。
- 主动 `cluster_ci95` 跨 0：不许声称有稳定 edge。
- **Brier 禁止裸报**。`0.295` 单独写会被读成「接近 0，还行」。只准写成对 `brier_baseline_loo`（闭眼总报基准率的留一法常数预测）的比较。`brier_beats_baseline=false` 时说「信心值校准不合格」或「过度自信」，**不许说「信心值没有信息量」**——Brier 分解里 resolution 仍 >0，是 reliability 把它吃掉了，说「没信息量」是过度指控。
- **禁止报「听 AI 赚了多少钱」类金额**。`decision_money_impact` 已于 2026-07-15 撤下且**不再写入 dashboard.json**：它把从没执行过的 call 也算进去。重建对照账本前，任何「多赚/少赚 X 元」都是编的。
- **胜率必须带 coverage**。`coverage_active.episodes_unresolved` 是判不了的 episode 数（休市/需人工核实/标的无交易）。只报胜率不报这个数=把难题藏进分母外。
- **禁止拿 active 胜率和 passive 胜率横比**。两者是不同样本池（不同标的/日期/暴露），相减不测量任何东西——「主动跑赢/跑输躺平」这类话一律不许写。
- confidence 必须参考同 strategy/action 的 episode 战绩；样本小则收敛到中性，不得因同一股票连续多日重复 call 而虚增信心。
- 同一天同一股票可以有多个 strategy；分别写、分别触发、分别评估，禁止压成一条综合 action。
- `event` / `manual` 条件若无可验证触发证据，状态为 `not_evaluable`，不进入胜率和 Brier。
- `execution` 与 `evaluation` 分离：建议是否有利和 kcn 是否执行是两个问题，报告时不得混写。

#### 决策记忆 (reflections — REQUIRED if `context.reflections` 非空)

`context.reflections[ticker]` 是每个持仓的历史同类决策战绩(`bucket_history` 如 "清×9 胜3" / `recent` / `lesson`)。**给某标的下主动 call 前必须先看它的 reflection**:
- 若该票 `bucket_history` 显示你**反复做某动作且多半错**(如 ROBN "清×9 胜3")→ 这次别再机械重复,要么换论据要么降级为 hold,并在 rationale 里引"过去 N 次清 ROBN 错 M 次"。
- `win_rate < 0.5` 的票 → 主动 call 需要比平时更强的新证据才出手。

#### 下一时段：`narrative.next_session`（可交易，不是观察清单）

**决策优先(decision-first)**:先用 `reflections` + `decision_metrics` 为每个持仓按 strategy 定 action + condition + confidence，**再**写叙事论证决策。决策是主角，叙事是理由。宁可 1-3 个高确信主动策略，其余 core hold，也不要 8 个摊薄的逐票评级。

每条一个字符串：`{时点 + 时区}: {具体观察 / 触发}`，不加序号（harness 编号）。包含：
- HK 开盘前 09:00 HKT 查什么消息
- HK 开盘后 09:30 HKT 关注哪个票什么价位
- US 盘前（09:30 ET 之前）查什么
- US 开盘后 09:30 ET 关注什么
- Book-level metric 红线（例：港股浮亏到 X% 触发 forced derisk）

### Step 4: 写输出文件（B plan / C judgment / D insights —— A 报告与 E 微信卡由 harness 渲染）

#### A. 报告与微信卡：**你不写，harness 渲染**

`memory/{YYYY-MM-DD}-pre-open.md` 与 `memory/.tmp/brief-card-{YYYY-MM-DD}.txt`
由 `clawock.harness.brief_render` 从**本次 context + 你的 judgment + 校验后的 plan**
渲染，postflight 自动跑，不需要你调用。

**不要写这两个文件。** 你手写的稿子会在 postflight 里被渲染结果覆盖——它不会
进产品，只会浪费一轮 token。

为什么这么分（2026-08-31，kcn 定）：报告过去由模型逐行手写，于是①版式每天重新
发明一遍，同一张表昨天七列今天六列；②该留在辩论段的推演渗进表格里，读者要在一堆
过程文字里找"09:30 到底做什么"。现在**模型只出想法，harness 只出版式**：标题层级、
表格、排序、数字格式、段落顺序全部在代码里，每天同一个位置放同一件事。

因此：

- 你写的每一段判断都通过 **B（plan）** 和 **C（judgment）** 进入报告，别处不进。
- judgment 的文字字段**必须是纯文本**：不许出现 `|`、`#`、`**`、` ``` `、`▎`、
  行首 `-`/`*`/`1.`/`>`。这不是文风要求——渲染器正在画那张表，你的竖线会落进单元格里
  把那一行撑成多一列。postflight 会直接判非法并指出是哪个字段。
- 事实、指标、风控闸、集中度、回本数学、同行涨跌、宏观读数、校准表全部由 harness
  从 context 取；**你不需要把它们抄进 judgment**，抄了也不会被用。
- 正文由渲染器排版，不设写作目标长度；≥40KB 可读正文会提示超长。避免重复论述，
  不为凑长度扩写，也不在 postflight 后裁文。

本地想看渲染结果（不写盘）：

```bash
clawock brief render --dry-run
```

#### B. 结构化 plan → `memory/{YYYY-MM-DD}-plan.json`

postflight 严格 schema 校验：

book 的两腿与 `fx_rate_usdhkd` 从 core 原样抄入；两种合计由宿主统一计算，postflight 会覆盖模型手算值并校验，兜底卡也重新计算。不要把 US 腿当两币合计。

```json
{
  "schema_version": 2,
  "date": "2026-05-18",
  "context_generation_id": "照抄 manifest.generation_id",
  "fx_rate_usdhkd": 7.8315,
  "fx_source": "Frankfurter",
  "regime": {"us": "trending-up", "hk": "trending-down"},
  "book": {
    "usd_total_pnl": -117.28,
    "hkd_total_pnl": -918.44,
    "hk_leg_hkd": -4936.0,
    "us_leg_usd": 513.0
  },
  "decisions": [
    {
      "strategy_id": "risk_rebalance",
      "thesis_id": "reduce-leveraged-beta",
      "ticker": "ROBN",
      "action": "cut",
      "condition": {"type": "open", "price": null, "description": "周一开盘任意价"},
      "size": {"pct": 50, "shares": 20},
      "confidence": 0.82,
      "expected_move_pct": -6.5,
      "driven_by": "risk_rule",
      "regime": "risk_off",
      "contested": true,
      "rationale": "降低杠杆 beta；这是组合政策型再平衡，不是预测",
      "thesis_invalidation": "若 crypto rev 环比转正 / DAU 回升 → 论点失效，停止减仓",
      "debate": {
        "bull": "crypto rev 若回暖，减到 50% 会踏空反弹",
        "bear": "杠杆 beta 在 risk_off 下放大回撤，DAU 连续两季下滑无止跌迹象",
        "attacked_consensus": "攻击的是「AI 板块整体还有一波」这条最强共识",
        "frames": ["technical_breakdown", "relative_strength"],
        "judge": "纪律优先：政策型减仓不等预测兑现",
        "evidence_ids": ["risk:leveraged_exposure:US", "quant:ROBN:dist_ma200_pct"]
      }
    },
    {
      "strategy_id": "intraday_t",
      "thesis_id": "robn-intraday-mean-reversion",
      "ticker": "ROBN",
      "action": "t_only",
      "condition": {"type": "price_above", "price": 16.2, "description": "冲高缩量时做 T"},
      "size": {"pct": 15, "shares": 6},
      "confidence": 0.61,
      "driven_by": "technical",
      "evidence_event_id": null,
      "regime": "neutral",
      "contested": false,
      "rationale": "与 core/risk_rebalance 分开的日内策略",
      "hypothesis": "冲高到 16.2 上方时买盘衰竭，日内回落到 VWAP 的概率高于继续上冲",
      "method": "近 20 日日内区间位置 + 冲高当日成交缩量的对照",
      "forecast": {"event": "触发后当日收盘低于 16.2", "probability": 0.58, "horizon_sessions": 1},
      "alternatives": [{"option": "hold_and_watch", "why_not": "不做 T 则杠杆腿的日内波动白付"}]
    }
  ],
  "watch_levels": {
    "hstech_breakdown": 4800,
    "soxl_breakdown_pct": -4,
    "book_force_derisk_usd": -300
  }
}
```

合法 enum：
- `strategy_id` ∈ {`core_position`, `risk_rebalance`, `intraday_t`, `event_trade`, `tactical_entry`}；迁移历史才允许 `legacy_unknown`
- `context_generation_id`：必填，逐字符照抄本次 `manifest.generation_id`；postflight 会递归检查 plan 内所有 `*generation_id`，跨代引用直接 fail。
- 🗣 `rationale` 与 `condition.description` **会原样进入当天之后每一份开盘/午盘/收盘报告和盘中盯盘的上下文**，下游照抄就推到 kcn 微信。所以这两个字段同样不写 `harness`/`preflight`/`postflight`/`packet`/`sidecar`：不要把登记策略偏好写成风控禁令；说明真实限制或自己的判断。postflight 会以 advisory 标出。
- 每条 `action` 必须在该票的 `constraints.open_actions` 里（持仓外的票看 `swap_targets` / `proposal_universe` 那一行）；不在的动作 `closed_actions` 写了原因，改不了。在 `open_actions` 里而不在 `allowed_actions` 里的动作可以写，会被记成策略异议。卖出腿的 `size.shares` 是正整数且不得超过 `max_sell_shares`；`risk[].kind=hard_stop`（非 `may_stand`）的 cut 是整仓：只写一条 cut 时 `size.shares` 可以留空，postflight 按该行 `required_reduction.minimum_shares` 填；自己写股数（含拆成几条不同条件的腿）则合计要达到它。cap 类 breach（`enforcement=respond`）不强制卖出：`minimum_value` 是到上限的总距离，减不减、分几批由你判断，`constraints.respond_to_breach_ids` 非空的票必须有一条带理由的决策。同一条腿的全部加仓金额合计不得超过 `portfolio.cash_available` 里该腿的现金。
- `action` ∈ {`cut`, `trim_on_rebound`, `hold_and_watch`, `t_only`, `add_only_on_trigger`, `add_on_breakout`, `watch`}
- `condition.type` ∈ {`open`, `price_above`, `price_below`, `index_breakdown`, `event`, `manual`}
- `driven_by` ∈ {`technical`, `catalyst`, `sentiment`, `influencer`, `macro`, `peer`, `risk_rule`}（每个 decision 必填）
- `evidence_event_id`：`driven_by=catalyst` 时必填，必须精确匹配该票 packet `evidence` 里的一个真实事件；对不上任何事件是事实错误，直接打回。事件是否 `actionable_escalation=true` 是资讯策略对它的评级：主动 call 引用未升级的真实事件可以写，会被记成「所引事件未被资讯策略升级」。`driven_by` 不是 `catalyst` 的 decision 填 `null`。
  - ⚠️ 被动决策若归因 `catalyst` 就**必须**给出真实 `event_id`，不能填 `null` —— 归因得可核。给不出具体事件，就说明它其实不是 catalyst 驱动，改用 `technical`/`risk_rule` 等如实标注。**不要为了过闸而改标 `driven_by`**：这个字段直接决定 `by_driver` 胜率归属（主动和被动都进桶），洗标签就是在污染自己的 edge 统计。
- `regime` ∈ {`risk_on`, `neutral`, `risk_off`}（每个 decision 必填；按本报告已判定的当前 regime 留痕，迁移旧数据才允许 `unknown`）
- `confidence` ∈ [0.0, 1.0]
- `size.shares`（整数，**主动 call（`cut`/`trim_on_rebound`/`t_only`/`add_only_on_trigger`/`add_on_breakout`）必填**；`hold_and_watch`/`watch` 不需要)：股数是这条 call 日后唯一能被折算成钱的凭据。面板上那条金额曲线已撤（见上条铁律），但**重建一套可信对照账本必须有股数，当天没填就永远补不回来**。宁可给保守估数也别留空。填**你真的会动的股数**,不是仓位上限。
- **引用登记形态的加仓**（含 alpha_confirmation）：填写 packet setup 的 `technical_setup_id`、`technical_campaign_id`、`invalidation_price`、`condition.valid_for_sessions` 与 `tranche_number=next_tranche_number`。`technical_setup_id` 必须是本次 packet 里真有的 setup（写一个不存在的是事实错误）；入场、失效或批次与它不同时照实写，会被标成「与所引的登记形态不同」。`alpha_confirmation` 的 `driven_by` 应按真正主导证据写 `peer`/`catalyst`/`sentiment`，不能因为技术只负责 timing 就洗成 `technical`。
- **自定入场的加仓**（不引用任何登记形态）：`technical_setup_id` 留空，必须写 `hypothesis`（这笔在赌什么）和 `invalidation_price`（价格到哪说明错了），`condition` 写你选的触发。它会带上「入场位由本计划自定」等异议标注，这是如实记录，不是错误。
- 两类加仓共同的硬边界：`size.shares` 是正整数，港股是 `lot_size` 的整手倍数，不超过 `position_room_shares`；该票有未关闭的风险 breach、是每日重置杠杆产品且没有 validated 证据、或已有未成交的 add 时，加仓是关着的（见 `closed_actions`）。
- `simulated_entry_price`（选填）只能是 packet 给的该票现价或你自己的 `condition.price`；写别的数等于声称了一个没人观测到的价格，会被打回。
- 风控配对换仓的 add 按上文「换仓的买腿怎么写」执行；不套用技术加仓的 trace 字段，不填不存在的 setup/campaign/invalidation/tranche。
- **提案字段**（主动 call 应填；它们让这条决策之后能按自己的方法被复盘，#2842/#2844）：
  - `hypothesis`（≤400 字）：你认为什么成立、为什么它现在重要。不是 `rationale` 的复述：`rationale` 说做什么，`hypothesis` 说你相信什么。
  - `method`（≤240 字）：你怎么得出来的——用了哪些观测、哪个窗口、哪种比较。自由文本，不需要是菜单里的词；同一种方法尽量用同样的写法，系统按这段文字给方法编号，之后按编号统计它的结果。
  - `forecast`：`{"event": "第 5 个交易日收在 11.5 上方", "metric": "close_above", "level": 11.5, "probability": 0.55, "horizon_sessions": 5}`。一个到期能判对错的陈述。没有把握就不填，不要编概率。
  - `alternatives`（≤3 条）：`[{"option": "hold_and_watch", "why_not": "…"}]`，你权衡过而没选的做法，包括「不动」和换成别的标的。
  - `tool_receipts`：本次运行里 `clawock tool compute` 返回的 `receipt_id` 列表（形如 `cr-…`）。只引真的算过的：不存在的回执、重放不出来的回执、`as_of` 晚于今天的回执都是事实错误。
  - `policy_review` 由 harness 写，你不写；写了会被替换。
- `contested` ∈ {`true`, `false`}（每个 decision 必填）：Tier 2 的 Bull 与 Bear 是否真的在该策略上分歧。
- `debate`（object，主动 call 应填，`hold_and_watch`/`watch` 选填）：**把已经发生的辩论落成可核对的结构**（#1117）。Bull/Bear/devil's advocate/Judge frame 这四件事你本来就在 markdown 里写，但读者只能看到结论，无法核对反方是否真的存在——「我们辩过」在没有记录之前只是一句自述。字段：
  - `bull` / `bear`：这条 decision 上双方最强的一句话（各 ≤600 字符，超出截断）。`bear` 是这块的重点：赢的那面本来就在 `rationale` 里。
  - `attacked_consensus`：本轮 devil's advocate（见 § Tier 2 铁律）点名攻击的那条最强共识。与该票无关时可省略，别为了填而编。
  - `frames`：最多三个简短文本标签，可以沿用上述示例或自定。字段不要求技术机制；没有贴切标签可省略，论证写进 `judge` / `method`。
  - `judge`：Judge 的合成判词一句话（不是 Bull/Bear 的复述）。
  - `evidence_ids`（≤6 条，选填）：这场辩论**站在**哪几条 context 证据上（#1141）。只认三个能被解析的命名空间，postflight 逐条对着本次 context 核，**核不上的直接丢掉并记一条 degradation**（不会让流水线变红，但会被数出来）：
    - `news:…` —— **照抄那一条事件的 `evidence_id` 字段**。`context.news_evidence_graph.events` 每一行都自带一条，形如 `news:evt_3ffdc891b1dd9eb52b84`；你不需要拼，也不要拼。
      - 2026-09-10 这里被拼成了 `news:00100-humain-m3-2026-09-04` 和 `news:02208-h1-report-2026-09-08`——`<票>-<主题>-<日期>`，一个人会取的名字，而真 id 是一串不透明的 `evt_` 十六进制。**不透明的 token 只能抄，抄不了就别引。**跟下面 `risk:` 同一条纪律。
    - `risk:…` —— **照抄那一行的 `evidence_id` 字段**。`context.risk_guardrail` 的 breach / hard_stop_watch / concentration_review 每一行都自带一条，形如 `risk:single_name_review:00100`；你不需要拼，也不要拼。
      - 这条规则以前是一段语法（命名空间 + `<type>` 全集 + ticker 形还是 leg 形 + 「别自己起名」），2026-09-08 仍然被拼成 `risk:single_name:00100` 去指一行 `type` 是 `single_name_review` 的记录——票是对的，名字取了另一行合法拥有的那一半。所以现在只有一条：**那一行写着什么就抄什么**。
      - 想引整条腿的闸（`leveraged_exposure`、`beta` 这种 `ticker` 为 null 的行）同理，它的 `evidence_id` 已经是 `:<leg>` 形。
      - resolver 另外接受**那一行所在 list 的键名**作为同一行的别名（`risk:hard_stop_watch:RKLX` == `risk:leveraged_hard_stop:RKLX`），**仅限该 list 里所有行 type 相同时**——`breaches` 装着四种 type，拿它当名字说不清指的是哪一行，照样被丢。这是给「抄了外层键名」兜底的，不是第二种写法：**照抄 `evidence_id` 仍然是唯一该做的事。**
    - `quant:<ticker>:<field>` —— `context.quant_signals.rows[<ticker>]` 上一个非空字段（如 `quant:SPCH:dist_ma200_pct`）。**只有 `rows` 里真有的 ticker 能引**：杠杆 ETF 通常没有自己的行（07226 没有，它的底层 HSTECH 有），要引就引你真正读的那一行
    **没有可引的证据就不填**，别为了填而造 id：造出来的引用比不引更糟，它看起来像证据。portable workflow lane 早就要求每个 case 带 `evidence_ids`（`workflows/validators.py`），这里是把同一条纪律接到日报这条 lane 上。
  - **自定 frame 原样保留**；空或非文本标签会丢弃并计 `debate_frames_invalid`。不合规的 `evidence_ids` 被丢弃并计 `debate_citation_unresolved`，不伪造引用。文本与标签数量仍有长度预算；`action`、`condition`、`strategy_id` 等执行字段写错仍须修正。整块为空时按未写计入 `debate_coverage`。
- `expected_move_pct`（number，选填，带符号，单位 %）：**这条 decision 预期这只票走多远**（#1159）。`confidence` 说的是「多有把握」，`invalidation_price` 说的是「论点在哪死」，**没有一个字段说「走多远」**——所以「方向对、幅度错了四倍」这句话这本账本目前对自己讲不出来。填了之后按 t1 对 `underlying_return_t1_pct` 打分（这只票自己的收益，不是 `benefit_t1_pct` 那个相对不动的反事实）。
  - 是**预测**不是目标价，也不是止损距离：写 `-8` 表示「我预期它跌 8%」。`0` 是合法且可打分的预测（「预期它不动」），和不填不是一回事。
  - |值| > 100 会被丢弃（打字过滤，不是风控），丢弃不会让流水线变红。
  - **没有把握就不要填**：这条和 `debate.evidence_ids` 同一条纪律——编一个数比不填更糟，它看起来像预测。覆盖率发布在 dashboard 的 `magnitude_metrics.coverage_pct`，必填与否以后对着这条序列谈。
- `thesis_invalidation`（string，主动 cut/trim/add 写明；hold 可选）：什么可观察的证据会推翻这条决策？可写价格结构、基本面、事件或假设机制失效，不限定为硬催化，也不要求失效先发生才能提出动作。
- `thesis_id` 必须沿用 `context.thesis_registry.theses.<ticker>.thesis_id`（resolved 时）；registry 为 `unknown` 时保留已有 decision ID，不得新造一个“看起来像历史”的 canonical thesis。`context.retrospective.decisions[].thesis_ref` 是只读解析结果。

**condition.type 详解**（决定 retrospective 怎么算触发）：

| 值 | 含义 | 模拟触发逻辑 |
|---|---|---|
| `open` | 开盘任意价 | 永远触发（trigger_price 一般 null） |
| `price_above` | 价格突破上方 | `day_high >= trigger_price` |
| `price_below` | 价格跌破下方 | `day_low <= trigger_price` |
| `index_breakdown` | 指数破位 | trigger_condition 字段说明哪个指数 + 哪个值 |
| `event` | 事件型（财报/公告） | 有结构化证据才触发，否则 not_evaluable |
| `manual` | 完全靠人判断 | 无结构化证据则 not_evaluable |

禁止输出顶层 `actions`。postflight 会生成稳定的 `decision_id` / `episode_id` 并写入 `memory/decisions.jsonl`。**不要自己写这两个字段**（也不要从昨天的 plan 抄）：写了也会被丢弃重算 —— 它们是台账的键，由台账按规则判定是否延续同一 episode。同股同日的不同 strategy 必须保留为不同 decision；同策略连续同 action 才可归入同一 episode。

#### C. 受限判断 overlay → `memory/.tmp/brief-judgment-{YYYY-MM-DD}.json`

先生成模板，再只回填观点字段：

```bash
/root/.local/bin/clawock tool decision_packet_judgment_template \
  --workspace /root/.openclaw/workspace \
  --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json
```

**schema v3（2026-08-31）**：这份文件现在同时是 Pages projection 的判断层
**和整篇报告的文字来源**——Tier 2/3、板块解读、大盘解读、校准解读、下一时段计划
都从这里渲染。写漏一个字段，就是发布出去的报告里空一段。

顶层只允许 `schema_version/context_generation_id/portfolio_assessment/
portfolio_counterargument/narrative/ticker_judgments`。

每票只允许（前九个字段照旧，后四个是 Tier 1 那张表里 harness 算不出来的格）：

```json
{
  "ticker": "00100",
  "verdict": "bullish|neutral|bearish|mixed",
  "confidence": 0.62,
  "disposition": "candidate|wait|reject",
  "assessment": "你的评价",
  "counterargument": "最强反方",
  "rationale": "为何在冲突信号中这样判断（只写 plan rationale 里没有的：历史战绩、反方为何不成立；≤2 句）",
  "falsifier": "什么事实会推翻当前候选/等待判断",
  "next_evidence": "下一步要找的一手披露或价格确认",
  "fundamentals": "Tier 1 · 基本面格：EDGAR/财报/ETF 标的口径",
  "cross_market": "Tier 1 · 跨市场格：跟随还是背离",
  "sentiment_read": "Tier 1 · 情绪格：这条消息面的性质、权重与局限（硬催化/软情绪）",
  "peer_read": "同行扫描那一行的判断：领先/落后说明什么"
}
```

逐票的 `assessment`、`counterargument`、`next_evidence` 会印进今日动作。
行动行的信心来自 plan；若逐票 judgment 信心不同，报告会并列点明差异。
同一判断应使用同一个数；若同票有不同动作/判断对象，在理由中解释差别。

**`rationale` 不许复述 plan。** 报告里「今日动作 · 信心与判定」是一票一块：plan 的 `rationale`
印在「理由」，这里的 `rationale` 印在「判定」，和前者逐句相同的会被 harness 删掉（`brief_render._unsaid`）。
换个说法把同样的事实再写一遍删不掉，只会让简报变长：2026-09-11 两处加起来 12.5KB，简报 44KB 越过
40KB 极端线。这里写 plan 没说的——`bucket_history` 战绩、为什么反方不成立、信心为什么是这个数——
没有就一句话。

`narrative`（整篇报告的辩论层，全部必填）：

```json
{
  "regime_read": "Header 那行 regime 的解读",
  "bull": "Tier 2 多头案（引 ≥2 个具体数据点）",
  "bear": "Tier 2 空头案（同上）",
  "devils_advocate": "点名攻击当前最强共识",
  "attacked_consensus": "被攻击的那条共识，一句话",
  "risk_voice_first": "aggressive|conservative|neutral（今日首位表态，4 个交易日轮换）",
  "aggressive": "Tier 3 · 抓 upside",
  "conservative": "Tier 3 · 保本 derisk",
  "neutral": "Tier 3 · 对每个争议票拍一边",
  "sector_read": "板块全景的归因结论",
  "macro_read": "大盘速读的一句判断",
  "calibration_read": "Decision v2 校准表怎么读",
  "next_session": ["下一时段第 1 步", "第 2 步"],
  "data_holes": ["还缺什么数据（可空数组）"]
}
```

三条硬规则：

1. **纯文本**。任何字段出现 `|`、`#`、`**`、` ``` `、`▎` 或行首 `-`/`*`/`1.`/`>`
   都会被 postflight 判非法并点名字段——版式是 harness 的活（见 A 节）。
2. **不写事实**。禁止加入价格、RSI、MA、因子分、股数、action、evidence 内容；
   harness 已经从 context 把它们渲染进表里，你重复一遍只会有对不上的风险。
3. `risk_voice_first` 只决定三位风险官的**表态顺序**，不改 kcn 激进偏好的权重规则。

postflight 严格校验后才把这些文字并入 `assets/data/brief_projection.json`；
overlay 缺失/非法时 Pages 仍发布 deterministic rows，只把 `judgment_status` 标为
missing/invalid——但报告的辩论段会因此空着，所以这不是"可选项"。

#### D. LLM 复盘 sidecar → `memory/.tmp/insights-{YYYY-MM-DD}.json`

build_dashboard 会读它，让 dashboard 上 **行为复盘 / 唱反调 Pre-mortem / 隐藏集中度** 三张卡同步刷新（缺失/解析失败容错，卡自动隐藏，不影响 brief 投递）。这是 dashboard 上唯一由你（LLM）写的"对决策本身的反思"层 —— 数字算不出来、只有你能写。

**铁律（accuracy）**：所有数字只能引本次 manifest 所属的 `core.json` / 已加载 bundle 里**真实出现过的** win_rate / Brier / 仓位权重 / HHI / pnl%。完整 audit 只用于 postflight 交叉校验，不能靠整份 cat 绕过预算。**绝不编造 context 里没有的具体美元金额或未发生的交易**。宁可不写一条，也不要编数字。

```json
{
  "generated_at": "{ISO8601}",
  "behavioral_review": {
    "verdict": "一句话总评 ≤40字，点出最核心的行为问题",
    "points": [
      {"text": "具体行为偏差，必引 context 里的真实数字，≤55字", "tag": "edge|bias|warning"}
    ]
  },
  "bear_cases": [
    {"ticker": "代码", "thesis": "空头论点 ≤55字", "falsifier": "什么数据/价位证明这空头错 ≤35字", "watch": "盯哪个位/事件 ≤25字"}
  ],
  "hidden_concentration": {
    "headline": "一句话点穿名义分散下的真实集中 ≤40字",
    "factor": "主导因子名（如 AI/半导体高 beta）",
    "basis": "market_value | lookthrough",
    "exposure_pct": 88,
    "detail": "哪些持仓同因子联动 + 风险 ≤70字"
  }
}
```

内容要求：
- **behavioral_review.points 4-5 条**，覆盖：① `decision_metrics.by_driver`；② `by_strategy`；③ `by_condition`；④ active episode 的 cluster CI；⑤ execution 与 advice 是否出现偏差。`tag`：edge=正面发现 / bias=认知偏差 / warning=要警惕。
- **bear_cases 2-3 个**，选**最重仓或最高杠杆**的持仓（看 context 仓位权重 + leveraged_etf）。
- **hidden_concentration**：识别表面分散实际同因子。先选一个口径写进 `basis`，全卡只用这一个口径的数字：`market_value` = `sector_exposure` 的市值占比；`lookthrough` = `lookthrough_exposure` 的 `factors`/`sectors` 的 `gross_pct`（杠杆产品按名义倍数计）。`exposure_pct` 不是估算：取**同一条腿**里你点名的那几个桶的占比之和（可四舍五入到整数），`detail` 里每个百分数都必须是该口径的某个桶、几个桶之和、单只持仓权重或 `leveraged_etf` 的占比。发布端按 `basis` 逐个核对，对不上或缺 `basis` 整张卡不发布；风险贡献、有效下注数这类不在这两份投影里的数不要带百分号写进这张卡。
- 全部中文，口吻直接、像私人交易教练，指出问题不安慰。

#### E. 微信卡：harness 渲染，不用你写

`memory/.tmp/brief-card-{YYYY-MM-DD}.txt` 与报告一起由 `brief_render` 生成：
标题行 + 核心结论（取 `judgment.portfolio_assessment`）+ Book/HHI + 今日动作
（取 plan 的 decisions，含 driven_by 与 confidence）+ 触发位（plan 的
`watch_levels`）+ 完整报告链接。**别再手写这个文件**——写了会被覆盖。

想让卡上那句"核心结论"更准，改的是 `judgment.portfolio_assessment`，不是卡本身。
这句原样推到 kcn 微信，他看不到管线：不写 `harness`/`preflight`/`postflight`/`packet`/`sidecar`，
也不描述你在按什么指令或格式写（「9/9 preflight 仍 4 breach」→「今天仍有 4 条风控超限」）。
postflight 会以 advisory 标出。

### Step 5: 跑 postflight（验证 + commit + 自动投递微信）

```bash
clawock brief postflight
```

输出 JSON：
```json
{
  "status": "pass|warn|fail",
  "issues": [...],
  "wechat_prefix": "...",
  "wechat_sent": true,
  "commit_ok": true,
  "commit_msg": "committed"
}
```

- `pass` — 全部 OK，已 `git commit`
- `warn` — 有非 critical 实质问题或 ≥40KB 极端超长（≤4 个），已 commit 但标 `(validation warnings)`
- `fail` — 缺文件/JSON 解析错/critical 字段缺失，**不 commit**、**不投递**
- `wechat_sent` — postflight 自动投递结果（见下）

**status 不是逐条 issue 判的，别自己猜哪条是硬闸。** `fail` 只由 critical 关键词
（`缺失` / `解析失败` / `表格 #`）或 issues > 4 条触发；其余都是 warn，照样 commit + 投递。

**`fail` 才需要修：有 critical 就修点名的 critical；若只是 issues > 4，就只修到 ≤4 条。**
每次改完立刻重跑一次 postflight 拿新 status，到 warn/pass 就停。不要在一次 `fail` 之后
一路埋头修到自己认为"干净"为止 —— 解除 fail 后剩下的 issue 不阻塞交付。

**`warn` 和 `pass` 一样是终态（`commit_ok: true` 时）：已 commit、已尝试投递，不要为了变成 pass 再跑 postflight。**
重跑不会再投递（当天已有投递记录就跳过），只会多一次 commit + push + dashboard 重建，
报告正文也不会因此更好。具体到 warn 里的各条：

- 带 `(advisory)` 的提示（管线术语等）和正文超长：**不改文件、不重跑**，下次生成时注意。
- `wechat_sent: false`：同样**不重跑**、不手动发——重跑只会被投递幂等检查跳过。
- 唯一例外是 `projection_status: invalid`（issue 以 `judgment 未通过校验` 开头）：Pages 会丢掉整个
  判断层（见 C 节），值得修**一次**。先 `read` 当前 judgment，按 `projection_issues` 一次改完所有
  点名字段，其余字段原样保留（整份 `write` 时最容易把没点名的字段弄丢），再重跑一次 postflight。
  这一次之后不论结果如何都结束本轮。重跑改写了已投递的报告时，postflight 自己会在页面标题下加
  「投递后修订」说明并记一条 `content_revised_after_delivery`（不重发卡片）；不要自己写说明或补发。

> **2026-09-17 教训**：首轮 warn 已 commit；模型先按 judgment 超长重写整份 judgment，重跑后
> 发现重写时丢了一个 `peer_read`，又顺手改 plan 里的 advisory 术语再跑一次，三次 postflight
> 产生三个 commit。旧版「改完任何一条 issue 就重跑」没限定只对 `fail`，读起来像 warn 也要修到干净。

> **2026-07-27 教训**：旧规则把 35.8KB 和表格 critical 混在同一个 issues 列表里，模型误把
> 体量当硬闸，事后一路裁到 23.7KB，既浪费时间/tokens 又引入编辑错误。新规则把体量单独记录：
> 只保留 ≥40KB 可读正文的 `warn`；小于此值是 `within_budget`，不再有 28KB 目标或中间 advisory 档。
> 无论哪档都保留完整正文，绝不在 postflight 后硬截断。报告由 `brief_render` 渲染；这条闸留着是为了在渲染器或持仓规模变化时仍能报警。

### 投递（Step 5 postflight 内自动，你什么都不用做）

> **🔒 投递已解耦——你绝不要手动发微信、绝不调任何 message/send 工具、也不要把卡片当回复文本贴出来。**
>
> pass/warn 时 **`brief_postflight` 自己**会用 fresh-token 短连接把渲染出的
> `brief-card-{date}.txt` 投到 kcn 微信（cron 已设 `delivery=none`，这是唯一微信路径），
> 并同步 Telegram，把两路结果记到 `memory/.tmp/brief-sent-{date}.json`。
> `brief_watchdog`（08:36）在 Telegram marker 缺失/失败时补投 Telegram；微信只在回执明确记录发送失败时补发一次，其余情况不重发。
>
> **为什么这样改（2026-06-08）**：旧的 `delivery=announce` 在长 turn 末尾用 turn 起点抓的 token 投递，brief turn 恒 >160s（173–975s）→ token 必过期 → 静默丢、`delivered=true` 是假信号（见 memory: openclaw-wechat-longturn-token-expiry）。短命 message send 每次抓新 token，且独立于 turn 时长，kcn 实测可靠（同 intraday 架构）。
>
> **你的职责到 Step 5 跑完 postflight 为止**：产出 B/C/D 三个文件（plan / judgment / insights）+ 跑 postflight，报告与微信卡由 postflight 内的 `brief_render` 生成。看到 status 为 `pass`/`warn` 且 `commit_ok: true` 即大功告成（`wechat_sent` 为 false 也一样，不要手动补发），**立即结束本轮，不要再追加任何思考或内容**。
>
> **🔒 送达确认铁律（2026-08-15 起，#558）**：
> postflight **之后禁止**用 exec / list / show 去读 `memory/.tmp/` 下的 marker、claim、sent 文件"眼见为实"确认送达。
> 送达由 postflight 的 marker + watchdog 兜底负责，`wechat_sent: true` / postflight 输出里的投递摘要就是权威。
> 违例形态（2026-08-10~14 复发 ≥5 次）：`Exec failed: list files in memory/.tmp/report-sent-*.json` → 整回合被判 error → 该槽位投递缺口（#544）。**postflight 说送到了就是送到了，不要二次确认。**
>
> 这条是窄规则（只管 postflight 之后的送达确认）。**一般形式见文档开头的「Exec 铁律：退出码就是整回合的判据」** —— 2026-08-18 同一机制换个位置又发生了一次（Step 3 读昨日 notes，末尾 `head` 读到不存在的文件 exit 1，简报已投递却仍判红）。

## Style rules

- judgment 是纯文本：3+ 个数据点写成一句里的并列数字，表格由 harness 画
- ⚠️ stale 任何数据必前置标注
- 没有"小心地"、"建议关注"这种废话 — 拍 strategy/action，拍条件与价位
- 每个 claim 钉到具体 ticker + 数字，没有泛论
- Bull/Bear/Aggressive/Conservative 必须真的不同观点
- Judge 不重复 Bull/Bear，是合成不是复述
- **FX 换算永远显式标注 source + timestamp**（core 里已有）

## 集中度阈值表（解读 core 的 `concentration` 字段）

### 算法（preflight 已经算了，这里只是参考）

对每个 leg（HK / US 分开）：
1. weight = `current_value / leg_total_current_value`
2. **HHI** = Σ weight² （0-1，越高越集中）
3. **Top 2 concentration** = 最大两仓 weight 之和

### 阈值

| HHI | Top 2 | 状态 |
|---|---|---|
| < 0.15 | < 40% | 健康 ✅ |
| 0.15-0.25 | 40-60% | 偏集中，可接受 |
| 0.25-0.40 | 60-75% | 集中风险 ⚠️ |
| > 0.40 | > 75% | 危险集中，单一事件可炸 book 🔴 |

集中度段（每腿 HHI、Top2、verdict）由 harness 印在 book 部分。散文里谈集中度时引用
`concentration.{hk,us}.verdict` 与 Top2 数字，不自己重算（港股 book 双仓集中 86% 曾是
2026-05-16 之前简报漏报的盲点）。

## ⚠️ 货币铁律

港币 + 美元 **不能直接相加**。book 段的双币视角（真实总浮盈亏 USD/HKD 两个 view、两条腿各自换算）
由 harness 印；你在散文里写金额时同样只在同一币种内加减，换算时写明 `fx.rate`、`fx.source` 与 `fx.fetched_at`。

历史教训：2026-05-16 那次"合计 -4,423"直接把 -4936 HKD 和 +513 USD 相加 → 毫无意义。kcn 当场指出。

### 提前埋点与左侧分档

逐票检查 `quant.preposition` / `technical.setups` 的 `preposition_scale_in`，不要只找突破。
这是 kcn 授权的前瞻试验，不是已验证 alpha。可按给出的 `price_below`、失效位、campaign、
下一档编号和 `constraints.max_add_shares` 写 `add_only_on_trigger`；须写可证伪的 hypothesis
和 method，说明尺寸取自持仓比例×资讯倾斜，以及 `evidence_strength` 中支持/不支持的范围。
unknown 论点不冒充 intact；已有 damaged/broken 状态不自动洗白。两档成交后不因换日重置。
每个可用试验候选必须明确选择：写有尺寸的单，或在该票判断中说明本次不买的原因，
不能无声退回“等突破”。硬止损、制度降杠杆、现金、整手和未成交单闸优先。
持仓外研究同时考虑 sentiment、资讯事件、同业/因子与 entry-gate 的供应链机制；
没有数据就写缺口，不凭板块相同捏造上下游关系。
