## Style rules

- judgment 用文字解释数据含义，必要的具体事实用引用表示，表格由 harness 画
- ⚠️ stale 任何数据必前置标注
- 没有"小心地"、"建议关注"这种废话 — 拍 strategy/action，拍条件与价位
- 每个事实引用指向具体标的、指标或来源行
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
和 method。判断试验能否成手，直接读该票的 `constraints.max_add_shares` 与 `constraints.lot_size`。
constraints 折叠时，先读同代摘要的 `preposition_limits`，缺项再查该票的 constraints。
持仓比例只是尺寸输入。上限已够一手仍选择观察，写投资判断的理由。说明尺寸取自持仓比例×资讯倾斜，以及 `evidence_strength` 中支持/不支持的范围。
unknown 论点不冒充 intact；已有 damaged/broken 状态不自动洗白。两档成交后不因换日重置。
每个可用试验候选必须明确选择：写有尺寸的单，或在该票判断中说明本次不买的原因，
不能无声退回“等突破”。硬止损、制度降杠杆、现金、整手和未成交单闸优先。
持仓外研究同时考虑 sentiment、资讯事件、同业/因子与 entry-gate 的供应链机制；
没有数据就写缺口，不凭板块相同捏造上下游关系。
