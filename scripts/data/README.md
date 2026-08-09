<div align="center">

# 📊 stock-data

**clawock 的多市场行情数据工具包 — 美股 · 港股 · 黄金**

*行情 · 基本面 · 资金面 · 消息面 · 宏观情绪 · 量化因子 · 汇率校验 · 回测自省*

</div>

---

## 定位

clawock 是**美股 + 港股 + 黄金定投**的实盘组合。工具包遵循三条规则：

- **Provider-aware** — 优先使用有文档的公开端点；需要认证的来源遵守其认证和使用条款。
- **多源降级** — 关键路径都是 provider chain，主源挂了自动落下一个，抓空保留旧值不整片覆盖。
- **可达性实测** — 下表 `可达` 列来自当前服务器：✅ 稳定 · 🟡 flaky/限流 · 🔴 本机不可用。

---

## 架构总览

| # | 层 | 端点 | 主数据源 |
|---|---|---|---|
| 1 | 行情 Market | 5 | 腾讯 gtimg · Yahoo v8 · 东财基金 |
| 2 | 基本面/申报 Fundamentals | 2 | SEC EDGAR · 东财 datacenter |
| 3 | 资金面 Capital Flow | 1 | 东财 push2his |
| 4 | 消息面 News | 3 | 东财 · Finnhub · Google News |
| 5 | 宏观/情绪 Macro & Sentiment | 4 | Yahoo · Reddit · TruthSocial |
| 6 | 量化与风险 Quant & Risk | 4 | 确定性计算 + 外部行情历史 |
| 7 | 汇率/校验 FX & Integrity | 2 | Frankfurter · 本地不变量 |
| 8 | 回测/自省 Backtest & Calibration | 5 | 本地历史快照 + 日线 |

---

## Layer 1 · 行情 Market Data

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `fetch_us_stocks.py` | 美股活跃持仓实时价 · 多 provider 链 | 多源 | ✅ |
| `analyze_us_stocks.py` | 美股组合刷新 + RSI | Yahoo v8 chart | ✅ |
| `analyze_hk_stocks.py` | 港股实时价 + HSI/HSTECH 指数 + 新闻 + 信号 | 腾讯 qt.gtimg.cn | ✅ |
| `fetch_benchmark_history.py` | SPY / HSI / HSTECH 日线历史(基准叠加) | 腾讯 kline / Yahoo | ✅ |
| `fetch_gold_dca.py` | 黄金定投 000217 净值 + Au99.99/伦敦金回本映射 | 东财 lsjz / 上金所 / 腾讯 XAU / Frankfurter | ✅ |

## Layer 2 · 基本面/申报 Fundamentals & Filings

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `clawock filings` | 10-K/10-Q 段落 · Form 4 内部人 · 13F 机构 · XBRL 关键财务 | SEC EDGAR | ✅ |
| `clawock fundamentals` | 美/港财报三表 + 关键指标(中文科目) | 东财 datacenter | ✅ |

## Layer 3 · 资金面 Capital Flow

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `clawock fundflow` | 日级主力/超大/大/中/小单净流入 + 主力净占比 | 东财 push2his | 🟡 |

## Layer 4 · 消息面 News

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `clawock em-news` | 港股个股中文新闻(催化级, 带日期) + 7x24 快讯 | 东财 search / newsapi | ✅ |
| `gh_action_news_digest.py` | 美股持仓新闻蒸馏为可执行要点 | Finnhub + Google News | ✅ |
| `clawock catalysts` | 未来 14 天财报/事件日历 | Finnhub earnings | 🟡 |
| `news_evidence_graph.py` | 公告/SEC/新闻/日历去重事件图；来源、新颖度、到期与价量/同行确认硬闸 | 元数据/标题 + 本地行情 | ✅ |

## Layer 5 · 宏观/情绪 Macro & Sentiment

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `fetch_macro.py` | VIX + 宏观情绪速读 | Yahoo v8 | ✅ |
| `fetch_sentiment.py` | 活跃持仓社交情绪扫描 | Reddit WSB/stocks/investing | 🟡 |
| `fetch_influencer_feed.py` | Trump / Musk 市场级言论 | TruthSocial feed / GNews | 🟡 |
| `clawock fetch-peers` | 同业股现价 + 5 日 P&L | 多源(同行情链) | ✅ |

## Layer 6 · 量化与风险 Quant & Risk · 确定性计算 + 外部行情输入

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `clawock quant` | 双均线 / 动量 / RSI / ATR / vol-target(杠杆 ETF 按标的) | 派生 | ✅ |
| `clawock regime` | 杠杆刻度盘: 200DMA 趋势 + 20d 波动带 | 派生 | ✅ |
| `clawock t0` | T+0 牌面评级 + 追高检测 | 派生 | ✅ |
| `clawock cross-factor` | 同行/1x 标的行业中性排名、杠杆 decay 对比（激活闸前仅研究） | 腾讯 qfq + SEC XBRL | ✅ |
| `clawock peer-residual` | 人工同行篮子等权/流动性权重残差、breadth/dispersion/leadership（HK 禁自动发现） | 腾讯 qfq + peer-map | ✅ |

## Layer 7 · 汇率/校验 FX & Integrity

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `preflight_integrity.py` | 数据不变量硬闸: TCV / PNL / FX / cash 对账 | 本地 | ✅ |
| `src/clawock/bar_checks.py` | bar/quote **判据唯一真源**:结构不可能(fatal) vs 可疑(flag,含 o==h==l==c 退化区间)、同源区间越界、gap-safe 收益(停牌不填 0)。策略仍由各 fetcher 自己定 | 纯本地(无 I/O) | ✅ |
| `src/clawock/research_provenance.py` | 研究报告 Decimal 计算、两源数字溯源与 fail-closed 准出（tolerance 上限 5%，算式异常也只输出结构化 fail） | 结构化 manifest + 本地确定性校验 | ✅ |
| `src/clawock/thesis_registry.py` | 持久 thesis schema/validator、证据驱动 drift（红线触发/解除对称要证据）与 decision link 解析；`clawock thesis` 操作 | `memory/theses/*.json` + 本地确定性校验 | ✅ |
| `src/clawock/earnings_review.py` | 一手财报复盘:来源分级、盈利质量数学、管理层承诺账本、provenance 准出与 thesis 证据交接；`clawock earnings` 操作 | `memory/earnings/*/*.json` + 本地确定性校验 | ✅ |
| `workflow_health.py` | 排程 GitHub Actions 周度健康:连续失败计数 + **静默停跑**检测(节奏从 workflow 文件里读) | `gh run list` + `.github/workflows/*.yml` | ✅ |
| `src/clawock/instrument_registry.py` | 工具标的**唯一真源**:杠杆倍数、underlying 看穿(`look_through`/`issuer_for` — 基金→发行人、指数基金→无发行人)、canonical bar manifest | `config/instruments.json` | ✅ |
| `src/clawock/entry_gate.py` | 建仓前研究闸:信息分级与投资质量分离、确定性硬否决(行业例外写进配置)、pass/reject/gray 判定与深研路由；`clawock entry-gate` 操作 | `memory/entry-gates/*.json` + `config/entry-gate-vetoes.json` | ✅ |

## Layer 8 · 回测/自省 Backtest & Calibration

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `src/clawock/claim_provenance.py` | 回测结论必须引用 run card，且卡里仍要含这个数字；扫描面由工作区 `config/claim-provenance.json` 声明 | `memory/backtests/*.json` | ✅ |
| `build_evidence.py` | 生成 `evidence.md`「测了什么、什么没通过」：数字全部读自产物，判定区分**未通过 / 尚不可判 / 通过** | 派生 | ✅ |
| `src/clawock/run_card.py` | 每次回测留证：输入序列身份(source/窗口/bar 数/摘要) + 参数 + 代码哈希 + 指标 JSON；`clawock run-card` 复查。落 `memory/backtests/` | 纯本地 | ✅ |
| `backtest_hstech_regime.py` | 恒科 regime 去杠杆回测(2021→今) | 腾讯 kline | ✅ |
| `backtest_us_leverage.py` | 美股 2x ETF regime 回测 | 日线模拟 | ✅ |
| `backtest_combined_regime.py` | 全组合 regime vs buy&hold vs 全 1x（MA/vol 在各代理**原生交易日**上算，不用 union 日历填充值） | 因子代理历史 | ✅ |
| `validate_regime_dial.py` | 杠杆刻度盘样本外验证：walk-forward + 环形位移置换检验 + 阈值敏感面；建模的是**生产 tier 映射**(1.0/0.5/0.0)而非 2x→cash | 腾讯 kline | ✅ |
| `src/clawock/decision_v2.py` | 安装包拥有的 strategy episode 结算、coverage、严格前向分层 confidence 校准、方向命中审计 | workspace decisions ledger + canonical bars | ✅ |
| `src/clawock/risk_discipline.py` | 持久 breach 账本、确认/限时 override、成交证据与同风险增仓冻结；`clawock risk` 操作 | guardrail + portfolio trades | ✅ |
| `clawock quant-review` · `clawock t0-review` | 因子 / 牌面 edge 自检(T+1/T+5 命中率) | 本地留痕 | ✅ |
| `clawock cross-factor` | 预注册 walk-forward + date×ticker 双向聚类 CI；存活偏差未消除即禁止入决策 | 本地留痕 + 调整后日线 | ✅ |
| `clawock peer-residual` | leader 延续 / laggard 规避 / 均值回归分规则 prospective 聚类校准 | 本地留痕 + 人工 taxonomy | ✅ |
| `news_evidence_graph.py` | 重复新闻衰减、事件到期与 catalyst actionable 权限审计 | 本地留痕 + 预注册 policy | ✅ |

---

## 🛡️ 请求节流与降级

**东财统一出口 `_em_http.em_get()`** — 所有现役东财调用（行情、基金、基本面、资金流与新闻 fetcher）统一经过节流器：

- **进程内串行** — 相邻请求间隔 ≥ `EM_MIN_INTERVAL`(默认 1.0s), 线程锁保护;
- **请求抖动** — 每次额外 0..`EM_JITTER`(默认 0.5s)，分散突发请求;
- **Session 复用** — 单 `requests.Session`，复用 TCP/TLS 降低连接开销;
- **重试 + 优雅降级** — 3 次重试耗尽返回 `None`, 调用方一律降级为空 `[]`, 永不抛。

**多源 fallback 链** — 行情、FX 等关键路径主源挂了自动落下一个;多 series fetcher 抓空**保留旧值**不整片覆盖(避免限流丢线)。

运行抓取器或再分发生成内容前，请阅读仓库根目录的
[`docs/legal/third-party-data.md`](../../docs/legal/third-party-data.md) 与 [`NOTICE`](../../NOTICE)。

---

<div align="center">
<sub>数据脚本清单见本目录 · 路由/fallback 链见仓库根 <code>TOOLS.md</code> · 铁律见 <code>MEMORY.md</code></sub>
</div>
