### Step 3: Swarm 分析（你的创造性工作）

## 目录

- [必读输入](#swarm-inputs)
- [市场判断](#swarm-regime)
- [分工与三层分析](#swarm-roles)
- [仓位与杠杆](#swarm-risk)
- [交给 harness 的判断](#swarm-judgment)

写任何给读者看的判断前，先读 `src/clawock/trading-prose.md`（workspace 根目录下）。适用于导语、逐票判断、板块与复盘侧卡，也适用于会被 DSH 决策轨迹引用的 plan 理由、正反方和证伪条件。逐票写清当时怎么想；有订单尺寸、条件价和信心字段时，理由不再列一遍。

按下面这个 3-tier 流程做分析。所有数字只能从本次 generation 的 packet 查询、确有必要时加载的 bundle、或本次运行内 `clawock tool compute` / `observations` 的返回取；风险分类和 action bounds 引用 harness 结果。packet 给的技术指标和因子分数是固定窗口下的一种算法，你可以用 `compute` 换窗口、换比较对象或定义新的量，但不心算。

<a id="swarm-inputs"></a>

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

<a id="swarm-regime"></a>

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

<a id="swarm-roles"></a>

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

#### ⚡ 板块全景

以本次 `peer_scan` 的 `listed_peers`、`auto_peers` 与 `self_pct_1d` 判断持仓相对强弱。表格的标的、涨跌与同业相对名次由程序从这份快照生成，默认按快照主题分组；外部搜索用于补归因。未入本代结构化输入的搜索信息可作为核查线索。

板块叙事写到 `judgment.narrative.sector_read`，简报和面板共用。逐票归因写到 `peer_read`。如需为面板补充逐票归因与同业催化，另写 `memory/.tmp/brief-sector-draft-{date}.json`，包含本代 `context_generation_id`、`attribution`（持仓代码到归因文字）和 `catalysts`（同业代码到催化文字）。`themes` 可选，按持仓代码填写专题名。同市场同场次的同名主题会合并展示。价位、涨跌、来源和时间用 Step 4 的事实引用。

#### Tier 2 — Bull vs Bear（必须有真分歧）

各写一段，讲到分歧在哪儿就够。Bull 用 Tier 1 数据组装"持有 + 加仓"案；Bear 用 Tier 1 数据组装"减仓 + 砍仓"案。**至少在 1 个仓位上观点不同** — 完全一致说明辩论失败。

双方各用本代可查的证据说明理由。表里已有的数字只在会改变分歧时引用。

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

<a id="swarm-risk"></a>

#### 🚦 仓位/杠杆硬闸(REQUIRED — 优先级高于 driven_by 与 regime guard)

**回撤复盘的最大教训:亏不是因为"没听 LLM",是因为组合构造**(US β≈4.4、73% 杠杆 ETF、HK 85% 单因子)。任何一个 driven_by 面都没提前叫出来——这不是信号问题,是**风控纪律层缺失**。所以在所有 driven_by/regime 逻辑之上,先过一道仓位硬闸。

preflight 已算好,直接读 `context.risk_guardrail`:
- `concentration_reviews[].trim_to_review_line` 是按当前价、卖出同时缩小持仓腿分母、整手向上取整的情景尺寸，不是卖出授权。「需卖 X 股」取复核线的卖出量，「卖后剩 Y 股」才是当前股数减 X；若同时写账面价和触发价，两种情景分别标出价格口径。`trim_inputs` 给出复算输入。不能把原占比按剩余股数等比缩放；不同触发价须重算该票剩余市值与腿总市值。简报的风控区会按计划情景渲染减仓后占比、达到复核线需卖的股数和卖后余量。导语和理由解释动作依据，可直接指向风控区。若数字对判断不可或缺，按同一价格情景明确写出卖出或剩余口径。
- `breaches[]` — 每条 = 一个超限的硬闸(single_name / factor_concentration / leveraged_exposure / beta),带 `detail` + 现成 `action`(含具体减仓金额)。`age_days` 是**连续多少份简报记录**仍带该闸（周末/假日缺行不计，不是日历天；触底时带 `age_capped=true`）。
- `hard_stop_watch[]` — 杠杆 ETF 浮亏跌破 −18% 的硬止损触发。
- `directive` — 本次总指令；`caps` — 当前阈值（2026-10-11 kcn：集中与杠杆 ETF 敞口不设上限。单名超过 35% 只进 `concentration_reviews`，杠杆与否都不算 breach；单名、相关 cluster、杠杆 ETF 占比上限都是整段 100%，杠杆 ETF 占比仍按港股制度乘数收紧；US β 6.0；杠杆止损 −18%）。持仓策略带 `forbid_reduce_advice` 的票（现为 `infinite_ammo_dca`）不出硬止损和 `regime_delever` 行。Top2 仅展示，不再冒充同因子。
- `context.risk_discipline.records[]`（core，常驻）— 同一 breach 的持久状态：`breach_id`、严重度、`age_days`（首次进入至今的**日历天**）、首次/最后变化、required reduction、acknowledgement、限时 override、execution evidence；`adaptive.recent_choices` 是最近几次 stand/reissue（完整理由留在账本）。每日重新生成的 plan 不是状态账本。

硬性规则:
- **强制与回应分两类**,看每条风险行的 `risk[].enforcement`(#2839):
  - `forced`(杠杆硬止损、`regime_delever`):规则自己给了去处(`required_reduction.swap_to`),必须在 Judge 段落出对应动作(cut,或 regime 的 trim/cut),不准"观望"。**唯一例外**是下面「长期不执行的建议」里 `adaptive.may_stand=true` 的那几条,以及 durable override 生效的。
  - `respond`(`single_name` / `leveraged_exposure` / `factor_concentration` / `beta` 四类上限):规则只说要减多少、没说钱去哪,所以**不强制卖**。每条都要回应:减仓(trim/cut),或 `hold_and_watch` 并在 rationale 写明今天为什么不减、什么情况下会减。不许不提,也不许只写一句「继续观察」。**超限期间该票加仓关闭**,持有不等于可以加。postflight 把这次选择记进风险账本。
  - 卖出不是默认答案。比较减仓后持有现金与换仓的机会成本；现金也可以是有理由的选择。强制义务只核应减数量，不强迫同时写买腿。引用 `risk_rule` 换仓买腿时，仍须遵守指定目标与配对金额。
- 逐条核对 open 记录的 `breach_id`、`age_days`、确认与成交状态。风控区由程序列编号和触发事实。正文说哪些状态或处置变了，未确认的老问题明确升级。只有挂了多久会影响处置时才引用天数，并注明是简报记录数还是日历天。
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
- **解套/回本数字只准引用 `context.breakeven_math`**(preflight 已算好:每只浮亏持仓回本所需涨幅、同票已测算的月衰减、半年窗含 drag 等效标的涨幅),禁止自己心算或编造。摘要合计只引用 `[[/ctx/breakeven_math/priced_chop_drag_sum_pct_per_month]]`，限已测算标的的算术和，不能当组合损耗。某票带 `vol_unavailable_reason` 时写「这只的衰减算不出来」。不要用其他票、其他场次或 compute 推导替代。同票衰减用对应行 `chop_drag_pct_per_month`。解读纪律见其 `note`:直线涨→2x 回本更快;横盘→2x 每月白付 decay;再跌→2x 双倍挨打——换 1x 买的是后两种情景的保护,不是回本速度,别说反。
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

<a id="swarm-judgment"></a>

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

写同业比较怎样改变了对这笔仓位的判断。先对齐市场场次，再考虑板块同涨同跌、公司自己的消息或杠杆放大。只要事实还分不清，就说要等什么。轮动建议仍要在 Judge 里给出可复查的触发条件。

#### 大盘速读：`macro_read` 与 `regime_read`

`macro_read` 不超过 5 句，围绕最影响当前持仓的一两个变化讲明白。Fed 最新发布
与利率无关（如人事任命）时不提。

- `context.macro` 为空 = preflight 判过期（超过 36h，或指数收盘落后最近一场已收盘 session）或缺失：`macro_read` 只写一句"⚠️ 宏观快照过期，本段不印读数"，不引用任何指数读数；postflight 不 fail

**🧭 Regime guard（REQUIRED）**：`context.macro.regime` 给出 `label`(risk_on/neutral/risk_off)+ `reasons`。
页眉由 harness 印 label；`regime_read` 写当下环境为什么改变你愿意承担的风险或交易节奏。据 regime 收敛主动操作：
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
- 说明主动决策的样本和不确定性怎样影响你对策略的信任；信心校准只与 `brier_baseline_loo` 比较
- 只挑会改变下一次做法的发现，用对应 strategy / action / driven_by 定位
- 执行状态：**要动手的**与**不用动的**两条腿分开写，执行率不等于建议质量。若在正文报执行率，必须同句交代该腿的 `stranded`（「另有 N 条永远验不了，不在分母」）——那是窗口早已关闭、`_detect_followed` 每次重试都答 unknown 的行，标的从没进过 holdings，被丢掉的样本偏向「没执行」，所以裸报的执行率系统性偏高
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
- 若该票的某个 action 桶样本很少(如 `n=1`/`n=2`)，先读同一 `reflection` 里的 `cross_ticker`：它给出**其他票**在同 action 桶的样本量与胜率(已剔除本票)，用来看这个动作在全账本上的基础率。它是基础率，不是本票的证据，不能拿它替代本票的 `bucket_history`。
- 若该票 `bucket_history` 显示你**反复做某动作且多半错**(如 ROBN "清×9 胜3")→ 这次别再机械重复,要么换论据要么降级为 hold,并在 rationale 说明这次与过去的错误有何不同。
- `win_rate < 0.5` 的票 → 主动 call 需要比平时更强的新证据才出手。

#### 下一时段：`narrative.next_session`（可交易，不是观察清单）

**决策优先(decision-first)**:先用 `reflections` + `decision_metrics` 为每个持仓按 strategy 定 action + condition + confidence，**再**写叙事论证决策。决策是主角，叙事是理由。宁可 1-3 个高确信主动策略，其余 core hold，也不要 8 个摊薄的逐票评级。

每条一个字符串：`{时点 + 时区}: {具体观察 / 触发}`，不加序号（harness 编号）。包含：
- HK 开盘前 09:00 HKT 查什么消息
- HK 开盘后 09:30 HKT 关注哪个票什么价位
- US 盘前（09:30 ET 之前）查什么
- US 开盘后 09:30 ET 关注什么
- Book-level metric 红线（例：港股浮亏到 X% 触发 forced derisk）
