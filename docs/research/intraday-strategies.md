# 盘中策略：开源依据与适配结论

这里记录 research 插件的选型依据，不授予交易权限。研究对象是港股／美股的
已有底仓日内回转；无底仓卖空、融资、期权和跨币种套利不在实现范围。
`intraday-reversion` 是首个可独立卸载的研究服务，设计与运行方式见
[盘中研究契约](../design/intraday-strategy-research.md)。没有真实分钟数据的
walk-forward 成绩，不能据此声称策略赚钱或进入 live。

## 读过的开源实现

以下链接固定到实际阅读的提交；不是从搜索摘要拼出的公式。第三方实现只作为
方法依据，没有复制源码或引入依赖。指标实现不等于已证明的交易策略。

| 候选 | 读到的实现与逻辑 | 适用市场及前提 | 失效场景 | 本仓库适配与取舍 |
|---|---|---|---|---|
| Bollinger 底仓回转（首个实现） | [Backtrader BollingerBands](https://github.com/mementum/backtrader/blob/2571371f2c21c70a0cc52147fda226a9acb92932/backtrader/indicators/bollinger.py)：SMA ± 标准差倍数，默认 20/2，另有 %B | 通用；已有可卖底仓、可回购现金、报价连续、价格有回归倾向 | 单边上涨导致卖飞；新闻跳空；波动扩张；止损与目标同根不可排序；流动性不足 | 只需 OHLC，可先完成因果回放与费用闭环。独立实现统计公式；改为前 20 根完成收盘（不含信号根），下一根开盘模拟卖出，冻结均值为买回目标。不是完整复刻 Backtrader，也不宣称“上轨必回落” |
| Session VWAP 回归（research 已实现） | [Lean VolumeWeightedAveragePriceIndicator](https://github.com/QuantConnect/Lean/blob/0a0c012ae900bc26b20c09e1346fe057679b2c99/Indicators/VolumeWeightedAveragePriceIndicator.cs)：按 volume 加权的滚动窗口，价格是 **OHLC4**，并非 HLC3 | 港美通用；需要可靠分钟成交量、明确 session 重置与交易阶段 | 趋势日的 VWAP 不是支撑／阻力保证；量缺失、拆股、午休与集合竞价混用；收盘量激增 | 独立服务 `intraday_vwap` 已实现 session 累积和成交量加权离散度，明确不同于上游滚动窗。现有 daily-bars 不提供分钟量，不能把日线或等权均价当 VWAP |
| Donchian / 开盘区间突破（research 部分已实现） | [Lean DonchianChannel](https://github.com/QuantConnect/Lean/blob/ed551458f5f91bedd1409fe5dd8df373f1f1d8ca/Indicators/DonchianChannel.cs)：最高 high、最低 low 的滚动通道；源码自身更新含当前根 | 港美通用；趋势延续、足够成交、非停牌；必须用前一完成通道判断突破 | 震荡反复假突破、开盘跳空、价差扩张、新闻反转 | 服务 `intraday_breakout` 已实现前窗向下通道突破，使用底仓而非新增卖空，与均值回归作为研究对照。开盘 30 分钟固定区间不在本底仓回转实现范围，不是 Lean 原算法的直接移植 |
| RSI + Bollinger 直接移植（不选） | [Freqtrade BbandRsi](https://github.com/freqtrade/freqtrade-strategies/blob/7f91ff52bb664423ae673092a6a18d76c50c2c29/user_data/strategies/berlinguyinca/BbandRsi.py)：1h，RSI14 <30 且 close < HLC3 的 20/2 下轨入场；RSI >70 出场；另有 ROI/stoploss | 原生态偏加密币的连续交易与 long-entry；港美需要 session、底仓与整手约束 | 不能保证当日买回／卖出；下跌趋势多次抄底；默认止损和收益目标不适合直接当日回转 | 研究其多条件过滤，但不搬原参数或收益宣传。仓库已有 RSI 策略，不新增重复数值算子 |

Backtrader 文件是 GPL-3.0-or-later，Lean 文件是 Apache-2.0；本实现没有复制代码。
若以后 vendoring，应逐文件核对仓库许可证、notice 和依赖许可证，不能把公开仓库
等同于可无条件复制。Freqtrade 示例只作阅读依据，未引入代码。

## 成本先决定机会集

`config/cost-model.json` 现在区分三种证据：

- **账户事实**：kcn 2026-10-18 自述，港美共享每月 500,000 HKD 等值成交免佣。
  佣金和最低佣金为零只在额度内成立。没有账单、额度消耗、兑换口径、超额费率；
  `usage_verified: false`，不是无限免佣，也不是程序替账户批准额度。
- **查证的费率**：逐项保留来源和生效日期。是交易所／监管／清算的收费，向零售
  账户无加价转嫁仍是模拟假设，不是已经看过 kcn 的账单。
- **假设**：HK/US 全点差 12/4 bps、每腿支付 `spread_share=0.5`；impact off；
  缺尺寸时的参考本金及参考股价。平台费、汇兑、融资和未校准冲击没有伪装成零。

费率来源（已阅读原文）：

| 项目 | 生效日期与费率 | 来源 |
|---|---|---|
| HK 印花税 | 2023-11-17 起每边 0.1%，每笔向上取整至 HKD 1；豁免证券不收 | [HKEX 证券交易费用](https://www.hkex.com.hk/Services/Rules-and-Forms-and-Fees/Fees/Securities-(Hong-Kong)/Trading/Transaction?sc_lang=en) |
| SFC / AFRC / 交易费 | 2014-11-01 / 2022-01-01 / 2023-01-01 起：0.0027% / 0.00015% / 0.00565%，各自取最近仙位 | 同上 |
| CCASS | **2025-06-30 起 0.0042%，无最低／最高收费** | [HKSCC LSD/019/2025 原通告及附录](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/HKSCC/2025/019_25_HKSCC_OP_stock-settlement-fee-restructure_e.pdf)；[HKEX 解释](https://www.hkex.com.hk/News/Market-Communications/2025/250221news?sc_lang=en) |
| US SEC Section 31 | 2026-04-04 起卖出额每百万 USD 20.60（0.206 bps） | [FINRA 2026-03-17 通知](https://www.finra.org/rules-guidance/notices/information-notice-20260317) |
| US FINRA TAF | 常规 2026 年每卖出股 USD 0.000195，最高 9.79；**2026-10-01 至 12-31 暂停征收** | [常规费率表](https://www.finra.org/rules-guidance/rule-filings/sr-finra-2024-019/fee-adjustment-schedule)；[即时生效暂停文件](https://www.finra.org/rules-guidance/rule-filings/sr-finra-2026-021) |

CCASS 旧制 0.002%、最低 2、最高 100 仍有可配置公式和测试，不能当当前收费。
即使按旧制，HKD 10,000 的 HKD 2 是 **2 bps**，HKD 50,000 是 **0.4 bps**；
到 HKD 100,000 才是比例费 0.2 bps。原线索的 20/4 bps 高了十倍。
因此不能据此制造“现在必须大仓位做 T”的门槛。真正的小额成本跳跃仍有印花税
整元进位，以及任何未来核实的券商最低收费。

[HKEX 豁免表](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Trading/Securities/Stamp-Duty-Reporting-and-Payment/Securities-exempt-from-stamp-duty/secstpduty.xlsx)
按类别列出 ETF 和 L&I 免税，不是每只 ETF 都逐行出现。配置保存本次文件 SHA256。
研究示例选择 **02800（Tracker Fund）**，由
[HKEX 2015 公告](https://www.hkex.com.hk/News/Market-Communications/2015/150204news?sc_lang=en)
逐名确认其 ETF 身份与 2015-02-13 生效豁免。代码只对显式核验过的 ticker 豁免，
不因代码前缀或模型称其为 ETF 就免税。07226 等 L&I 应逐名核验身份再登记；本次
没有把它们加入候选白名单，也不从类别豁免猜每只票的身份。

### 可复算的费用算例，非业绩

两腿金额暂按相等，US 按每腿 100 股、每股 100 USD；当前 tariff snapshot、额度内
免佣、上述固定点差、US 监管转嫁向上取分；没有实际收益或市场报价：

| 每腿金额 | 股票类型 | 两腿总费用 | 往返占本金 |
|---|---|---:|---:|
| HKD 10,000 | 港股应税普通股 | HKD 34.56 | 34.56 bps |
| HKD 10,000 | 已核验免税 ETF 02800 | HKD 14.56 | 14.56 bps |
| USD 10,000 | 美股，TAF 暂停期间 | USD 4.21 | 4.21 bps |
| USD 10,000 | 美股，常规 2026 TAF 情景 | USD 4.23 | 4.23 bps |

港股普通股约为美股费用门槛的 8.2 倍；免税 ETF 约 3.5 倍，不能把两者混称港股。
有点差假设不等于已证明成交；停止使用本 snapshot 前须更新 TAF 到期规则。
新插件按**两腿各自的金额**收费，并要求预计价差金额大于总费用的 2 倍、扣费后
至少 10 bps（研究起点，非优化结果）。以等额近似，最低价差门槛为上述费用的
两倍与“费用 + 10 bps”两者较大值：普通股 69.12、ETF 29.12、美股 14.21 bps。
“当日振幅很大”不够：必须是信号当下可定义的均值距离，不能拿事后全天高低点
差当可赚的钱；买不回时仍按止损或收盘回补，所有失败也扣两腿费用。

## 研究顺序与限制

优先用流动性可核验的美股既有底仓做分钟数据研究，再以已核验豁免的港股 ETF
对照，普通港股另组，分别统计净结果、币种、点差与样本覆盖；这不是实盘选股。
band、VWAP 与向下突破均为独立可卸载的 research 服务。策略／标的选择
必须在测试窗口前冻结，不能看完美股成绩后删除差的港股样本。

当前闭环已扩展为许可/数据口径检查 → 冻结研究 manifest → research 服务 →
因果成交与费用回放 → 净 walk-forward/模型回执 → 历史研究卡，见
[工作流及复现命令](../architecture/intraday-research-workflow.md)。免费真实样本只有
十个场次且为复权价格，已输出拒绝回执；更长历史的研究权限仍缺证据，所以
没有合格净收益结果或实证“最优”参数。前瞻观察尚未开始。单元测试的合成走势
不当成实证，也不将已有日线 rank IC 用作日内回转的证据。
