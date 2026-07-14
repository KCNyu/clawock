<div align="center">

# 📊 stock-data

**clawock 的多市场行情数据工具包 — 美股 · 港股 · 黄金**

![layers](https://img.shields.io/badge/架构-8层-blue)
![endpoints](https://img.shields.io/badge/端点-26-green)
![sources](https://img.shields.io/badge/数据源-10-orange)
![markets](https://img.shields.io/badge/市场-US·HK·Gold-purple)
![key](https://img.shields.io/badge/无key优先-✓-brightgreen)
![antiban](https://img.shields.io/badge/东财防封-em__get()-red)

*行情 / 基本面 / 资金面 / 消息面 / 宏观情绪 / 量化因子 / 汇率校验 / 回测自省 全覆盖 · 多源 fallback · 每源标注本机实测可达性*

</div>

---

## 定位

clawock 是**美股 + 港股 + 黄金定投**的实盘组合，工具包只做实盘真正用得到的数据，且每一条都在服务器 IP 上实测过可达性。设计三原则:

- **无 key 优先** — 能用公开端点绝不要 API key；需 key 的（Finnhub）都有免 key fallback。
- **多源降级** — 关键路径都是 provider chain，主源挂了自动落下一个，抓空保留旧值不整片覆盖。
- **诚实可达** — 下表 `可达` 列是本机实测：✅ 稳定 · 🟡 flaky/限流 · 🔴 本机被封（保留代码，换 IP 可用）。

---

## 架构总览

| # | 层 | 端点 | 主数据源 |
|---|---|---|---|
| 1 | 行情 Market | 5 | 腾讯 gtimg · Yahoo v8 · 东财基金 |
| 2 | 基本面/申报 Fundamentals | 2 | SEC EDGAR · 东财 datacenter |
| 3 | 资金面 Capital Flow | 1 | 东财 push2his |
| 4 | 消息面 News | 3 | 东财 · Finnhub · Google News |
| 5 | 宏观/情绪 Macro & Sentiment | 4 | Yahoo · Reddit · TruthSocial |
| 6 | 量化因子 Quant Signals | 4 | 派生(纯算术, 零外部依赖) |
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
| `fetch_gold_dca.py` | 黄金定投 000217 净值 + 定投指标 | 东财 lsjz / fundgz | ✅ |

## Layer 2 · 基本面/申报 Fundamentals & Filings

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `fetch_us_filings.py` | 10-K/10-Q 段落 · Form 4 内部人 · 13F 机构 · XBRL 关键财务 | SEC EDGAR | ✅ |
| `fetch_fundamentals_em.py` | 美/港财报三表 + 关键指标(中文科目) | 东财 datacenter | ✅ |

## Layer 3 · 资金面 Capital Flow

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `fetch_fundflow_em.py` | 日级主力/超大/大/中/小单净流入 + 主力净占比 | 东财 push2his | 🟡 |

## Layer 4 · 消息面 News

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `fetch_em_news.py` | 港股个股中文新闻(催化级, 带日期) + 7x24 快讯 | 东财 search / newsapi | ✅ |
| `gh_action_news_digest.py` | 美股持仓新闻蒸馏为可执行要点 | Finnhub + Google News | ✅ |
| `fetch_catalysts.py` | 未来 14 天财报/事件日历 | Finnhub earnings | 🟡 |

## Layer 5 · 宏观/情绪 Macro & Sentiment

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `fetch_macro.py` | VIX + 宏观情绪速读 | Yahoo v8 | ✅ |
| `fetch_sentiment.py` | 活跃持仓社交情绪扫描 | Reddit WSB/stocks/investing | 🟡 |
| `fetch_influencer_feed.py` | Trump / Musk 市场级言论 | TruthSocial feed / GNews | 🟡 |
| `fetch_peers.py` | 同业股现价 + 5 日 P&L | 多源(同行情链) | ✅ |

## Layer 6 · 量化因子 Quant Signals · 纯算术零外部依赖

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `compute_quant_signals.py` | 双均线 / 动量 / RSI / ATR / vol-target(杠杆 ETF 按标的) | 派生 | ✅ |
| `compute_regime.py` | 杠杆刻度盘: 200DMA 趋势 + 20d 波动带 | 派生 | ✅ |
| `compute_t0_setups.py` | T+0 牌面评级 + 追高检测 | 派生 | ✅ |
| `portfolio_risk_metrics.py` | β / Cov-Var / 回撤 / 集中度 | Yahoo 30d + 派生 | ✅ |

## Layer 7 · 汇率/校验 FX & Integrity

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `fetch_fx.py` | USDHKD 汇率 · 3 路 fallback | Frankfurter(ECB) → 备用 | ✅ |
| `preflight_integrity.py` | 数据不变量硬闸: TCV / PNL / FX / cash 对账 | 本地 | ✅ |

## Layer 8 · 回测/自省 Backtest & Calibration

| 端点 | 数据 | 源 | 可达 |
|---|---|---|:---:|
| `backtest_hstech_regime.py` | 恒科 regime 去杠杆回测(2021→今) | 腾讯 kline | ✅ |
| `backtest_us_leverage.py` | 美股 2x ETF regime 回测 | 日线模拟 | ✅ |
| `backtest_combined_regime.py` | 全组合 regime vs buy&hold vs 全 1x | 因子代理历史 | ✅ |
| `decision_v2.py` | strategy episode 结算、cluster CI、资金加权复合回测 | decisions ledger + snapshots | ✅ |
| `quant_signal_review.py` · `t0_setup_review.py` | 因子 / 牌面 edge 自检(T+1/T+5 命中率) | 本地留痕 | ✅ |

---

## 🛡️ 防封与降级

**东财统一出口 `_em_http.em_get()`** — 东财对同 IP 高频请求阶梯式惩罚(先 000 空响应, 后短时 ban)，所有东财调用(`_em_symbols` / `fetch_fundamentals_em` / `fetch_fundflow_em` / `fetch_em_news`)统一走它:

- **进程内串行** — 相邻请求间隔 ≥ `EM_MIN_INTERVAL`(默认 1.0s), 线程锁保护;
- **随机抖动** — 每次额外 0..`EM_JITTER`(默认 0.5s), 打散固定节律指纹;
- **Session 复用** — 单 `requests.Session`, 复用 TCP/TLS 降可疑度;
- **重试 + 优雅降级** — 3 次重试耗尽返回 `None`, 调用方一律降级为空 `[]`, 永不抛。

**多源 fallback 链** — 行情、FX 等关键路径主源挂了自动落下一个;多 series fetcher 抓空**保留旧值**不整片覆盖(避免限流丢线)。

---

<div align="center">
<sub>数据脚本清单见本目录 · 路由/fallback 链见仓库根 <code>TOOLS.md</code> · 铁律见 <code>MEMORY.md</code></sub>
</div>
