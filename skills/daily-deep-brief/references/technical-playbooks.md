# 港美股双向技术战法与执行边界

这些是登记策略的参考形态，用于比较与复盘；模型可在 `open_actions` 内提出自定入场，不要求先匹配形态。现金、库存、整手和已有授权边界仍由 packet 校验。

## 研究来源与可迁移机制

| 来源 | 本次核验的最新提交 | 借用机制 | 不照搬项 |
|---|---:|---|---|
| freqtrade/freqtrade | 2026-08-12 | 限制补仓次数、初仓预留后续 tranche、未完成订单时不重复补、补后重算成本与止损 | 加密货币 24×7、秒级轮询和示例参数 |
| QuantConnect/Lean | 2026-08-12 | 信号/仓位/止损分离；ATR 越高单次仓位越小；订单单位和交易时区进入执行层 | 默认美股经纪商模型不能代表港股整手 |
| microsoft/qlib | 2026-07-23 | 从信号生成目标仓位，再以换手上限从当前仓位靠近；执行层处理不可交易状态 | A 股涨跌停和交易单位假设 |
| PyPortfolio/PyPortfolioOpt | 2026-07-07 | 用相关性聚类识别真实风险集群；风险按 cluster 而非 ticker 数衡量 | HRP/CVaR 目标权重不覆盖用户的主动集中偏好 |

仓库活跃不代表算法是新发明；以上日期只证明实现仍在维护。趋势、突破、RSI、ATR 本身是经典机制。

## 三种技术 setup + 一种 alpha 执行确认

1. `trend_pullback`：多头趋势成立，当日触及并收复 MA20，收阳且高于前收。第一次加一小批，失效线为 MA50/ATR/吊灯线中更严格的有效线；最多两批。
2. `confirmed_breakout`：收盘突破此前 20 日高，1 个月动量为正且吊灯止损未破。第一次只加小批；跌回 MA20/吊灯线即失效；最多两批。
3. `oversold_reclaim`：前一日 RSI≤35 且 20 日 z≤−1，次日收复前一日高点。它是登记策略用于降低均价的 setup，只加一批 5%，跌破此前 5 日低点失效。

`alpha_confirmation` 只能由 packet 生成，模型不能自己创建。它先要求两个独立
family：factor/peer residual 合并为 `price_relative`，新闻方向 surprise 或相对自身
历史的 attention acceleration 为 `point_in_time_information`；随后技术层只在未来
1–5 个本地交易日等突破确认，跳空按开盘成交，同日同时触发 entry 与 invalidation
按失效处理。warming-up exploration 每 ticker/policy 只采一批 2.5%；不足一股/一手
时，只有该最小单位仍低于市场账 3% 硬上限才可补成一单位，否则输出零。validated
才能多批，杠杆 ETF 不允许 exploration。

`left_scale_in`（左侧分批，kcn 2026-09-26/27）现在是**观察档，不是 setup**：收盘低于前
20 日高 ≥2 ATR、仍在 MA200 上方的非杠杆持仓，packet 在 `quant.left_side` 给出档位、失效价、
MA200 底线和闸门状态，但不进 `technical.setups`、不给股数。原因是价格规则本身不跑赢一直
持有、并入右侧只增加同一批风险（证据与待 kcn 拍板的开闸条件见
`docs/architecture/harness.md` § Left side (observe mode)）。不得把它写成摊低成本的授权。

`亏损`、`比成本低`、`今天翻红`、`利好新闻`都不是 setup。它们本身不构成登记 setup；自主提案须说明机制与失效条件。

## 分批与集中

- 非杠杆高确信 core 可集中。35–60% 是 review band，不强制卖；超过 60% 须回应但不强卖，加仓仍受仓位授权约束。
- 2×/3× 日内重置产品继续执行严格上限，永不走均值回归补仓；需要保留敞口时走 2×→1×。
- 每个 setup 必须给 entry、invalidation、单批股数、目标最大权重和剩余批次数。登记策略建议一次一批；模型可提出不同尺寸并留下策略异议，拆单不能重复使用现金或仓位空间。
- 同一 ticker 可同时有 `core_position=hold` 与 `tactical_entry=add`；不得将 tactical add 改写成 core 无限摊平。

## 港股执行

- `lot_size` 来自当次 Tencent HK quote 的 board-lot 字段。主动加仓至少一手且只能为整手倍数；缺失时禁加，不猜一手为多少股。
- 触发价必须考虑 09:30–12:00、13:00–16:00 HKT 与午休；午间价格不是可连续成交的信号。
- 停牌、开盘跳过触发价或单手金额超过剩余授权资金时不追单，转下一次 review。

## 美股执行

- 当前账本只支持整数股，即使经纪商可能支持碎股，plan 也不得写碎股。
- 常规触发按 09:30–16:00 ET 正常时段；盘前/盘后跳空只作为重新定价条件，不自动视为已按触发价成交。
- 新上市、薄成交或隔夜 gap 高的票缩小 tranche；有未完成订单时不生成重复加仓。

## 生成纪律

可引用 packet 的真实 `technical.setups`，也可不引用形态而自定触发价。引用形态但改变入场、失效或批次时如实记录差异；自定入场写 `hypothesis` 与 `invalidation_price`。股数遵守现金、整手和 `position_room_shares`，超过 `max_add_shares` 只是登记策略异议。登记形态不存在时不要伪造 ID，也不必因此退回 hold/watch。
