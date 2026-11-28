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

盘前 cron 在第一轮并行读取本指引并调用 preflight。preflight 按简报的 HKT 日期检查两市，
返回 `market_closed` 时直接结束。

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

### Step 3: Swarm 分析

[分析前读取分工、证据和风险约束](references/swarm.md)

[写判断前读取写作、集中度与货币规则](references/style.md)

### Step 4: 写 plan、judgment 和 insights

[写文件前读取输出协议和字段口径](references/plan-schema.md)

完整写入三份 JSON 草稿。报告 Markdown 和微信卡由 postflight 渲染。

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

**`fail` 才需要修**：按 `issues` 一次修正本次阻断项。保留已通过的字段，
用 `write` 完整覆盖需要修的文件，再运行一次正式 postflight。
如果仍返回 `fail`，用最终状态和剩余问题结束本轮，由既有 watchdog 接管。

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
> `brief-card-{date}.txt` 及当天风险待复查队列组成卡片，投到 kcn 微信（cron 已设 `delivery=none`），
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
