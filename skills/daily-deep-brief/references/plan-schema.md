### Step 4: 写输出文件（B plan / C judgment / D insights —— A 报告与 E 微信卡由 harness 渲染）

## 目录

- [自动渲染](#output-render)
- [计划](#output-plan)
- [判断](#output-judgment)
- [复盘](#output-insights)

<a id="output-render"></a>

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
- judgment 的文字字段使用纯文本和下述事实引用。引用之外不写 `|`、`#`、`**`、` ``` `、`▎`、
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

#### 在散文中引用事实

计划的理由、条件描述、证伪条件、尺寸说明、辩论、判断和面板侧卡按需使用 `[[/ctx/字段/...]]`（同代 context 或 bundle）或 `[[/packet/字段/...]]`（decision packet）引用原字段。数组从零编号。写 **`[[/packet/tickers/00100/facts/session_change_pct]]`** 即可，程序填值与百分号。代码含数字时引用对应行的 `ticker` 字段。来源和时间引用明确字段，新闻用资讯行的 `[[/ctx/.../0|cite]]` 生成标题、来源和时间；状态用 `|status`，列表计数用 `|count`。调用 compute 后用 `[[/compute/回执ID/value_pct]]` 等引用返回字段。

计划每条理由还可用 `[[/decision/size/shares]]`、`[[/decision/condition/price]]`、`[[/decision/trim_at_trigger/post_trim_weight_pct]]`、`[[/decision/trim_at_mark/shares_to_review_line]]` 引用本条已登记的尺寸、条件和对应卖出情景。股数、百分比及带币种字段的单位随值渲染。散文中不手写数字、股数、金额、占比、来源或时间；缺字段时说明缺口。机器字段仍按 schema 写 JSON 数字，例如 `size.shares`、`condition.price`、`confidence`。

<a id="output-plan"></a>

#### B. 结构化 plan → `memory/.tmp/{YYYY-MM-DD}-plan-draft.json`

草稿沿用计划 schema；postflight 对账后写 `memory/{YYYY-MM-DD}-plan.json`。

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
- 🗣 `rationale` 与 `condition.description` **会原样进入当天之后每一份开盘/午盘/收盘报告和盘中盯盘的上下文**，下游照抄就推到 kcn 微信。所以这两个字段同样不写 `harness`/`preflight`/`postflight`/`packet`/`sidecar`：不要把登记策略偏好写成风控禁令；说明真实限制或自己的判断。postflight 将此类 advisory 留在校验结果里。
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

<a id="output-judgment"></a>

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

写逐票判断前先给每个字段分一件事：`assessment` 写本次变化，`counterargument` 写真正的反证，
`next_evidence` 写下一条可核对的观察。已有账本、风控或四格会印出的数据，只在改变动作、尺寸或触发条件时
引用到「今日动作」里。延续原判断的 `hold_and_watch` 用一句话交代维持依据（含未解除的风险），把具体触发与
证伪留在各自字段。主动动作保留解释和证伪所需的证据。

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

<a id="output-insights"></a>

#### D. LLM 复盘草稿 → `memory/.tmp/brief-insights-draft-{YYYY-MM-DD}.json`

build_dashboard 会读它，让 dashboard 上 **行为复盘 / 唱反调 Pre-mortem / 隐藏集中度** 三张卡同步刷新（缺失/解析失败容错，卡自动隐藏，不影响 brief 投递）。这是 dashboard 上唯一由你（LLM）写的"对决策本身的反思"层 —— 数字算不出来、只有你能写。

文字使用 Step 4 的事实引用。程序核定同代后生成供 dashboard 读取的侧卡，并从指定投资腿和分组计算集中度。

```json
{
  "context_generation_id": "{本代 ID}",
  "behavioral_review": {
    "verdict": "一句话总评 ≤40字，点出最核心的行为问题",
    "points": [
      {"text": "具体行为偏差，必要时引用证据，≤55字", "tag": "edge|bias|warning"}
    ]
  },
  "bear_cases": [
    {"ticker": "代码", "thesis": "空头论点 ≤55字", "falsifier": "什么数据/价位证明这空头错 ≤35字", "watch": "盯哪个位/事件 ≤25字"}
  ],
  "hidden_concentration": {
    "headline": "一句话点穿名义分散下的真实集中 ≤40字",
    "basis": "market_value | lookthrough",
    "leg": "hk | us",
    "family": "sectors | factors",
    "buckets": ["投影中的分组原名"],
    "detail": "哪些持仓同因子联动 + 风险 ≤70字"
  }
}
```

内容要求：
- **behavioral_review.points 4-5 条**，覆盖：① `decision_metrics.by_driver`；② `by_strategy`；③ `by_condition`；④ active episode 的 cluster CI；⑤ execution 与 advice 是否出现偏差。`tag`：edge=正面发现 / bias=认知偏差 / warning=要警惕。
- **bear_cases 2-3 个**，选**最重仓或最高杠杆**的持仓（看 context 仓位权重 + leveraged_etf）。
- **hidden_concentration**：`market_value` 选 `sectors`，`lookthrough` 可选 `factors` 或 `sectors`。在一条投资腿内以原名选择同一组分区中的分组，程序求和并渲染占比。
- 全部中文，口吻直接、像私人交易教练，指出问题不安慰。

#### E. 微信卡：harness 渲染，不用你写

`memory/.tmp/brief-card-{YYYY-MM-DD}.txt` 与报告一起由 `brief_render` 生成：
标题行 + 核心结论（取 `judgment.portfolio_assessment`）+ Book/HHI + 今日动作
（取 plan 的 decisions，含 driven_by 与 confidence）+ 触发位（plan 的
`watch_levels`）+ 完整报告链接。**别再手写这个文件**——写了会被覆盖。

想让卡上那句"核心结论"更准，改的是 `judgment.portfolio_assessment`，不是卡本身。
这句原样推到 kcn 微信，他看不到管线：不写 `harness`/`preflight`/`postflight`/`packet`/`sidecar`，
也不描述你在按什么指令或格式写（「9/9 preflight 仍 4 breach」→「今天仍有 4 条风控超限」）。
postflight 将此类 advisory 留在校验结果里。
