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
扣费的模拟成交，不保证真实挂单可成交；现金／购买力不足、熔断等必须由后续
执行模型补充。本研究不把做 T 当成无风险降低成本。

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
范围，不能从用户任意 JSON 认定账户授权；当前没有 live reader。

可判定的后续方案：由 kcn 明确白名单逐 ticker 授权；默认排除所有禁止减仓策略，
已授权票再受回转比例上限、单日次数、现金和整手约束。建议保留 10% 底仓、每天
一次作为研究起点，日内净亏损触限后停止新回转；具体阈值以未来净样本外结果
提案。**SPCH 不在可授权例外里**，除非 kcn 单独明确改变其打法；本 PR 不做取舍。
需要定的四项：真实标的白名单、5 分钟／更短周期、先美股还是港美分组研究、
LLM 在 live 中的角色。可先合本研究实现和成本纠正，不必等上述决策；需要批准
的行为均未实现／未启用。

## LLM 找更好的策略，而非扩大无证据权限

现有契约不是“模型只能写两行”。`intraday-agent.md` 已允许模型辨析 policy 与
observations，通过 `clawock tool compute` 选择公式、引用 harness 的计算回执。
模型不亲自算数、渲染数字块或发消息；harness 也不伪造判断。强化判断不需要
推翻这条契约。

在现有契约内的下一步方案（本次不改 prompt 或 production harness）：

1. 向模型提供带时间戳的点差、波动、趋势斜率、事件原文引用、数据缺口和三种
   策略的反事实回执。让它提出 regime 假说、选择回归／突破／不做、解释为什么
   今天回归不成立；保留否决和无交易，防止只展示“有操作”的输出。
2. 模型输出研究 manifest：候选服务、参数空间、机制理由、反例、所需数据、
   冻结日期、模型／prompt 标识。比如 band 的 window={12,20,30}、
   deviations={1.5,2,2.5}，成本门槛不低于代码底线。manifest 是建议，harness
   验证 schema／参数范围与政策，计算所有数字。不要让模型读测试窗口后改 grid。
3. 训练窗口按日期选参数或策略，测试窗口只读冻结结果；模型自己的策略选择也
   算一个待检验 arm，和固定 band、固定不做、简单 regime 规则同资本比较。
   保存完整输入、模型响应和不触发原因，不能只保存获胜策略。
4. 模型可选择表达重点：事件驱动趋势、成本太高、数据不足、已触发回补；引用
   回执而不是编造幅度和目标。拒绝未知 JSON 字段／虚构引用是 gate；反复出现
   的合规失败按既有原则升级为确定性 gate。

需要另行批准的契约变更：让模型自报未可回放的数值当事实；让模型写实际尺寸、
覆盖减仓禁令、改变硬闸、自动加入 live 或发消息。它们不因“找最优”而默认获得
许可。当前工作没有这些改动。

## 分层验证与“最优”的含义

`strategy-lab optimize` 现有优化器是日线横截面排名，首个盘中服务故意不注册
`StrategySpec.score`，所以不会被每日 record 自动拿日线评分，也不会渗入 live
`strategy_scores`。`intraday-replay` 是明确的研究入口，非优化器已经完工的宣称。

后续分钟级 walk-forward 应在离机环境／CI：至少 60 个完成训练 session、20 个
测试 session，逐窗只用之前已闭合回转拟合；最终累计至少 60 个样本外 session，
保留缺失／拒绝和无交易计数。按日 block bootstrap 净增量与相对保留底仓的 lift，
其置信区间下界须大于零；策略／参数／标的搜索计入多重选择，不能只重采样最后
获胜曲线。记录整手、费用 rounding、两腿成交、失败回补、延迟一根／点差翻倍／
常规 TAF／未知券商费用的压力结果。再冻结前瞻 shadow 观察，才讨论实盘。
这些是设计门槛，不是已经跑出的结果。50 万免佣还需真实月度计量及 FX；超额
费率未知则该情景拒绝给完整净绩效，不能假设继续免费。

目前没有经核验的分钟历史数据，故没有净 walk-forward 结果，没有“最优”的实证
结论。优先次序是净现金增量、尾部损失与基准差额，再看操作次数和呈现清晰度；
不是最大化触发数量。完整测试交给 CI，本机只运行定向边界测试。

## 展示方案（单独实现，不改本 PR 的盘中卡）

建议一个 research 明细而非盘中新增交易指令：

- 首行由模型选一个有依据的结论：“回归证据不足／成本不足／仅研究候选”；
  固定显著状态为“研究，不代表实盘授权”。
- harness 固定印同一币种的预计可回归幅度、两腿费用、预计净幅度，并画同一
  bps 尺度的横条；不把事后日高低范围画成可获取利润。
- 时间线由回执画“信号 → 次根模拟卖出 → 目标／止损／收盘买回”，底仓保留
  股数与回转股数分开，显示未完成回补和费用情景。模型选择展开哪条解释，不能
  隐藏净亏损、政策冲突或费用缺口。
- 展开项呈现来源、参数版本、额度条件、印花税身份、walk-forward 状态与拒绝
  理由。数据不足显示未知，不画成 0。真正 live 卡的尺寸／动作仍走既有 postflight。

展示有独立消费方和验证需求，不是策略服务返回字符串就能替代。因此本次交付
这个设计，未来以单独 PR 实现渲染和数字同源检查，便于回滚定位。
