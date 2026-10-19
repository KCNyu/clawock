# 盘中回转研究服务契约

实现状态：`intraday-reversion` 已挂 `plugins`，未挂 `live`。提供独立的五分钟
完整场次回放；没有订单、持仓、实盘计划、投递或策略登记副作用。
[研究报告](../research/intraday-strategies.md)说明读过的开源实现、取舍和费率来源。

## 服务与调用

实现：`strategies/plugins/intraday_reversion.py`，`inject=('costs',)`，
`apply` 提供 `intraday_reversion`，方法 `replay(packet) -> dict`。
`decision/intraday_reversion.py` 是只转发的 facade；调用方显式传 research kernel。
现有 module facade 绑定的是 live kernel，因此这里**不**调用 `facade.install`，
避免为了复用门面而给研究服务 live 权限。替换 row 后 facade 跟随所挂服务。
卸载 row 后调用失败，不偷偷用硬编码 fallback。

```bash
clawock strategy-lab list
clawock strategy-lab intraday-replay /path/to/session.json
```

JSON 必填：`market`（hk/us）、`ticker`、`session`（当地 YYYY-MM-DD）、
`research_allowed: true`、`forbid_reduce_advice: false`、`shares`、`base_shares`、
`lot_size`（正整数）、`bars`（从 session 第一根至最后一根，`end` 为带时区的
ISO 时间，含 open/high/low/close）。OHLC 为未复权的同场次可执行价格，且
必须使用已完成的五分钟根；不是取样时刻的 partial bar。示意头部：

```json
{"market":"us","ticker":"RESEARCH_ONLY","session":"2026-10-16",
 "research_allowed":true,"forbid_reduce_advice":false,
 "shares":10,"base_shares":100,"lot_size":1,
 "bars":[{"end":"2026-10-16T09:35:00-04:00","open":100,"high":101,"low":99,"close":100}]}
```

上面的单根例子因历史不足而拒绝；完整美股场次需 78 根，港股需 66 根。
时间校验换算到 Asia/Hong_Kong 或 America/New_York，09:35 首根、16:00 尾根；
港股 12:00→13:05 允许午休，其余必须相隔五分钟。重复、倒序、缺根、跨场次、
非有限／布尔价格、坏 OHLC 拒绝。早收市、停牌和特殊场次目前拒绝，不冒充完整
session。调用方需提供真实交易日及来源，回放本身不做行情供应商认证。

row 的 config 默认如下，改变参数是研究配置改动，不是 live 授权：

| 键 | 默认 | 含义 |
|---|---:|---|
| window | 20 | 前 N 根完成收盘，不含当前信号根 |
| deviations | 2.0 | 超过均值加标准差倍数才研究卖出 |
| cost_multiple | 2.0 | 预期回归价差金额严格大于两腿费用的此倍数；不得小于 1 |
| min_net_bps | 10.0 | 扣两腿费用后，相对卖出本金至少此 bps |
| max_base_fraction | 0.1 | 回转股数不超过底仓此比例；只是研究安全默认 |

实现以一次完整场次为边界，每票最多一次回转。已完成信号根只提出条件，下一根
开盘重新检查价格仍高于冻结均值且净成本门槛通过才模拟卖出；不假装能在前一根
收盘成交。止损价 = 卖出价 +（卖出价 − 冻结均值）。后续有不利开盘跳空，按开盘
买回；同根 high/low 同时碰两线按止损先；目标缺口向下只给冻结目标价、不赠送
额外利润。始终买回相同股数，末根未触线则按收盘回补。收盘和开盘均是带点差
扣费的模拟成交，不保证真实挂单可成交；study 的 `execution` 约束现已覆盖现金／购买力和成交量检查；
熔断、盘口队列仍不能从 OHLC 证实。本研究不把做 T 当成无风险降低成本。

输出 `status` 为 refused/no_trade/replayed；均有 `live_permission:false`、参数、
输入 SHA256、完整成本模型、`evidence_grade:conditional_replay_not_walk_forward`。
成功交易带信号时间、成交所在 bar、目标／止损、退出原因、两腿费用分解、
`net_pnl` 与信号激活时的预计净 bps。`net_pnl` 是相对一直保留同样底仓的回转
现金增量，不是整本账户或底仓涨跌；币种随 market，不相加。无交易不是零风险
的业绩证据，完整样本仍应保留在分母里。JSON 发到 stdout，不写 lab 的日线 ledger。

`costs.fill` 复用唯一 `costs.trade_cost`，传方向／ticker／股数；最低佣金、税费、
豁免、点差都逐腿结算。rank portfolio 没有尺寸，以 config 中显式参考本金和参考
股价、买卖较高一侧估算；这是粗粒度门槛，不是做 T 证据。`method_evaluation`
逐 call 扣费再按 episode 平均；缺本金用显式参考票，缺股数用参考股价。
`shadow` 按实例配置的市场／币种映射费率并传实际模拟方向和股数；未覆盖币种的净曲线为不可用，不套港美费用也不算零成本；`method_trials` 通过 dataclass 完整冻结成本配置，
旧 trial 缺新字段仍用旧模型，不追溯注入当前免佣和税表。

## SPCH 冲突与实盘待决项

`infinite_ammo_dca.forbid_reduce_advice` 保持不变。缺政策值或为 true 时，本研究
回放也拒绝，不能用 LLM 的解释替代授权。输入的 research_allowed 只表达离线研究
范围，不能从用户任意 JSON 认定账户授权；当前没有实盘动作消费者，只有历史研究卡。

可判定的后续方案：由 kcn 明确白名单逐 ticker 授权；默认排除所有禁止减仓策略，
已授权票再受回转比例上限、单日次数、现金和整手约束。建议保留 10% 底仓、每天
一次作为研究起点，日内净亏损触限后停止新回转；具体阈值以未来净样本外结果
提案。**SPCH 不在可授权例外里**，除非 kcn 单独明确改变其打法；本 PR 不做取舍。
需要定的四项：真实标的白名单、5 分钟／更短周期、先美股还是港美分组研究、
LLM 在 live 中的角色。可先合本研究实现和成本纠正，不必等上述决策；需要批准
的行为均未实现／未启用。

## 已落地的后续工作

三种研究服务、模型候选/回执协议、净 walk-forward、成交和额度约束、盘中研究卡
现已实现，见[工作流与命令](../architecture/intraday-research-workflow.md)。本页保留
首个回归内核契约。新 `execution` 字段由 study 强制提供；不提供时仍是早期条件
回放，不能冒充具备成交约束的 walk-forward。

当前 `config/intraday-research-status.json` 已使用 Massive/Polygon 的未复权 SPY
五分钟历史线，取代免费复权短样本的空指标回执。研究和衍生结论公开范围依据
owner 本次明确授权；`license_evidence` 如实记录为 owner 授权陈述，并非抓取的
供应商许可证文件，也不宣称已独立核验账户档位或交易所再分发权。原始数据及
授权文件保留在私有目录，仓库只保存衍生研究回执及输入摘要。

冻结窗口 2026-04-01 至 2026-10-16 共 138 个交易日，全部取得，每场 78 根，
没有缺失日期。训练 60 场后，样本外 78 场，末折为 18 场；相对训练 60 +
最低样本外 60 = 120 场，窗口只有 18 场余量。这是长度余量，不能抵消缺日：
当前完整性判据仍要求窗口内无缺日。下次长度不够时先扩 `start`，还是调整
`minimum_oos`，由 kcn 决定，本次没有变更冻结协议或样本闸。

成本沿用显式保守情景：美股点差 4 bps、每腿承担一半；账户佣金仅在共享月度
50 万 HKD 额度内为零，月初使用量假设为零，USD/HKD 固定 7.8（压力记账假设，
非观测汇率），逐腿按当前监管费率快照反事实扣费。四个压力臂仍为双倍点差、
延迟一根、每腿额外 2 bps 未知费用、正常 TAF；未降低费率或删除压力臂。
没有账户发票，不能将这些数称为实际全部费用。

模型逐折仅看当折训练回执，冻结选择后才提取下一折，完成四折模型比较；这是
当前模型的回顾研究，并非历史预测。净结果及各压力臂见状态文件 `metrics`，
负值原样保留；没有通过历史候选判据，仍为 `insufficient_or_failed`。
前瞻验证未开始，`live_permission:false`，未更改 live/SPCH 或交易授权。
