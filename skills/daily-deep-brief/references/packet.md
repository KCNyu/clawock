### Step 2: 只读 decision packet summary（唯一常驻输入）

## 目录

- [数据与行动边界](#packet-owner)
- [按需加载](#packet-bundles)

<a id="packet-owner"></a>

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
`skills/daily-deep-brief/references/technical-playbooks.md`。该
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

如果 summary 已存为 `"$SUMMARY"`，可按下列命令查看各段大小。`to_entries[]` 的每一项有
`key` 和 `value`，进入 `.value` 后直接用当前值 `.`：

```bash
jq -r 'to_entries[] | .key as $key | .value |
  "\($key) \(if type == "object" then "\(length) keys"
    elif type == "array" then "\(length) items"
    else tostring | .[0:60] end)"' "$SUMMARY"
```

summary 的 `stock_discovery` 是独立于持仓/peer-map 的持仓外研究队列。它只有
`needs_entry_gate`、`allowed=false` 的候选，不提供建仓授权。所有候选取值相同的字段
（来源 `evidence`、`missing_evidence`、`next_action` 等）只在 `candidate_shared` 写一次，
对每个候选都成立；`candidates` 各行只列自己不同的字段。简报和投递卡由 harness
固定展示；只有同时进入 `proposal_universe` 的票才可写 add 提案，检查该票 `authorization`：`entry_gate_cleared` 表示已读取并验证研究闸；`entry_gate_required` 仍是待研究提案，不能说已获建仓授权。`proposal_availability=unavailable` 的票不得写买单。可说明下一步研究哪个行业、要核什么
一手披露。`snapshot_metrics` 不是实时价格，`observed_at=null` 必须保留「时点未核」。
先用 `quote_request` 经 `clawock fetch-peers` 核验报价，再遵循 entry-gate 的人工研究
流程；不要用 `analyze-us TICKER` 查新票（该命令当前只刷新持仓）。候选源失败写
「Nasdaq 未取到」，不能解释为「没有机会」。`stock_discovery.inbox` 是本机持久研究状态：
简报只突出当日新候选与到期复查，旧项的 `last_seen` 不是当前报价时间。
人工状态、理由和复查日期由 `clawock research-inbox list|set` 管理；重新发现不得重置状态。
已有 entry-gate 链接只用于研究交接，不授权交易。港股入口当前明确报告数据源采集与再分发授权缺口；
analyst 一致预期仍缺失。

持仓判断完成后，若还有时间，用 `clawock research-inbox weekly` 取本周交接，每档最多处理队首 1 票。
用交易所披露、监管申报或发行人原文核对论点及反证；拿不到一手证据则留待下一档。
用 `research-inbox set TICKER --market HK|US --status researching|deferred|rejected --reason '理由' --review-on YYYY-MM-DD --assessment FILE`
记录交接。临时 JSON 含 `thesis`、`counterevidence`、`primary_sources`（披露 URL 数组）、
`completed`（本轮研究是否完成）、`benchmark`（已核对可比市场基准则填 HK 的 HSI 或 US 的 SPY，
缺可结算日线则填 null）。研究时间不足时照常交付简报。允许全周没有推荐；此处不写授权档案。

summary 包含 book/concentration、每票 deterministic status、技术/因子可用性、风险计数、allowed actions 与 evidence IDs。它不要求模型加载原始持仓交易流水或整张因子表。
每票的整手、单批上限、仓位空间只在 `constraints` 里印一次（`--section execution` 有完整尺寸明细）；`row_notes` 里的说明对每一行同名字段都成立；`setup_shared` 按 `setup_id` 列出该 setup 在每一行都相同的字段（文案、授权、批次规则），每票 `technical.setups` 只留随票变化的价位与计数，读一条 setup 时把两处合起来读。持仓多到 summary 装不下时，harness 会把参考明细收进逐票查询，顶层 `folded` 写明收起了哪一段、用哪个 `section` 查——要用到时按它逐票查，不要当成该票没有这段。

需要分析某票时才查该票；需要单一维度时必须带 `--section`：

```bash
/root/.local/bin/clawock tool decision_packet_query \
  --workspace /root/.openclaw/workspace \
  --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json \
  --arg ticker=00100 --arg section=technical
```

可选 section：`facts|technical|thesis|execution|quant|sentiment|history|information|evidence|risk|status|constraints`。

**实时消息面**：summary 每票的 `live` 是 preflight 刚抓的实时公告/新闻（HKEXnews、SEC 全文检索、Google 新闻、Yahoo，上次收盘以来）前两条 cite，全部条目在 `--section information` 的 `information.live`；引用用同一资讯行的 `[[/packet/…|cite]]`（含发布时间与「上次收盘后」/「上次收盘前旧闻」，SEC 全文检索只有提交日、「时刻未知」）。summary 顶层 `live_information.<hk|us>.degraded` 非空＝该源没取到，简报里写「X 未取到」，不许写成没有消息。逐票判断解释真正有用的消息。分析师四格会按持仓从 `live_information` 同票记录填一条有出处的新闻；旧闻保留时效，没可用项会注明。实时条目是消息面证据，不是加仓授权。一次查询硬上限 24 KiB，并同时校验 manifest hash 与 generation。正常分析禁止 `cat brief-context-{date}.json`，也禁止为了省一次查询而整份读 core/research/market bundle。

> **为什么走 `clawock tool`**：工具注册表是这套上下文协议唯一机器可读的定义（`clawock tool --list` 直接吐 JSON schema），而 24 KiB 预算是在注册表里强制的。协议实现随 `clawock` wheel 安装；workspace 只提供本次生成的数据，不再提供可执行 Python 源码。输出含 `_meta.generation_id` 代次钉扎。

<a id="packet-bundles"></a>

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

如果确需检查保存在 `"$RESEARCH"` 的 quant 原始记录，`.quant_signals.rows` 是
按 ticker 键控的对象。用 `to_entries[]` 取 ticker 和行，单票用字符串键：

```bash
jq -r '.quant_signals.rows // {} | to_entries[] |
  "\(.key) | \(.value.status) | \(.value.tag // "") | RSI=\(.value.rsi14) | \(.value.row_as_of)"' "$RESEARCH"
jq --arg ticker 00100 '.quant_signals.rows[$ticker]' "$RESEARCH"
```

bundle 路由：

- `risk_detail`: `breakeven_math`, `risk_metrics`
- `research`: `quant_signals`, `cross_sectional_factor`, `peer_residual`, `t0_setups`, `us_fundamentals`, `peer_scan` 及对应 review；`strategy_scores` 是策略实验室每个策略按**已登记参数**给各持仓的分数与排名，连同实验室对该策略的结论（`standing`）。它只是参考读数：`live_permission` 恒为 false，不是加仓、减仓或尺寸的依据；`status` 不是 `ok` 时写明未取到，不要当成没有信号
- `evidence`: `catalysts`, `news_evidence_graph`
- `market`: `macro`, `sentiment`, `influencer`, `em_news`, `watch_list`
- `calibration`: `retrospective`, `decision_metrics`, `reflections`

预算裁剪：若 manifest / issues 点名 `watch_list`、`strategy_scores` 被省略，本次即无该输入，不能假定 decision packet 含有它。新机会节须说明观察池输入不可用，不得据此宣称没有机会或借其它数据冒充。`news_evidence_graph.summary_scope` 标明 summary 是全量图统计（包括未投影/预算裁掉的事件），当前可读数量以 `events` 数组为准。

`market.watch_list`（#556）：非持仓 AI 观察池（智谱 02513 / 迅策 03317 等）的**价格面观察**——仅当突破/接近突破/5d 大涨时才有行。写「新机会」节时读取它，但**观察池本身不产生 add 授权**；同名标的若在 `proposal_universe` 中，可按其边界写可评估提案，否则先补报价与 registry。

manifest 若出现 `extras`，表示新 feature 被隔离而没有偷长常驻 core；只有下面明确要求消费该字段时才读。任一 bundle 的 `_meta.generation_id` 与 manifest 不同，立即停止，不得把不同 preflight run 的事实拼在一起。
