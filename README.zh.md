<div align="center">

<img src="assets/logo-mark.svg" alt="clawock 标志" width="58">

# clawock

### 多个 LLM Agent 分析一个**真实港股 + 美股组合**，风控由代码执行。

[![Dashboard](https://img.shields.io/github/deployments/KCNyu/clawock/github-pages?label=DASHBOARD&style=flat-square&logo=githubpages&logoColor=white&labelColor=252b35&color=4b91c8)](https://kcnyu.github.io/clawock/)
[![CI](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=CI&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![License](https://img.shields.io/badge/LICENSE-MIT-aab5bf?style=flat-square&labelColor=252b35)](LICENSE)

[**🎯 实时仪表盘**](https://kcnyu.github.io/clawock/) · [**📅 每日简报**](https://kcnyu.github.io/clawock/briefs.html) · [**它怎么跑的 ↓**](#-60-秒看懂)

[**English**](README.md) · **简体中文**

<br>

<a href="https://kcnyu.github.io/clawock/">
  <img src="assets/social-card.png" alt="clawock — 会给自己打分的自主 AI 投研台" width="820">
</a>

<sub>真实持仓 · 真实盈亏 · 每周刷新</sub>

<br>

<a href="https://kcnyu.github.io/clawock/"><img src="assets/dashboard.gif" alt="clawock 仪表盘循环六个标签页" width="300"></a>

<sub>总览 · 持仓 · 风控 · 信号 · 计划 · <b>诚实</b>。界面变化时更新。</sub>

<br><br>

**多 Agent 股票分析** &nbsp;·&nbsp; **代码风控硬闸** &nbsp;·&nbsp; **公开自评战绩** &nbsp;·&nbsp; **真实港股 + 美股组合**

</div>

---

> **一句话** —— 多个 LLM Agent 分析一个真实港股 + 美股组合；Python 执行风控、结算每条判断并发布未经人工修改的战绩。主动建议至今没显出优势。

## 🎰 60 秒看懂

clawock 是一套接入真实券商组合的自主多 Agent LLM 系统，港股与美股分账运行。

每个交易日，系统会：

- 🌅 定时运行简报、港美市场报告和盘中监控，
- 📥 抓最新价格、汇率、波动率、财报日历、宏观(VIX/DXY/10Y)、Reddit + 新闻舆情,甚至 **Trump/Musk 的市场异动**,
- 🧠 将标准化上下文交给多 Agent 分析与辩论流程，
- 🛡️ 由 Python 执行风控、schema 和账本校验，
- 📲 将简报发送到**微信**，
- 🌐 更新**公开仪表盘**。

## 🪞 它按策略 episode 打分，不拿每日重复 call 凑样本

每份简报提交 v2 `plan.json`。同一股票可以同时存在多个策略，例如长期 `core_position`、日内 `intraday_t` 与组合层 `risk_rebalance`；不同时间尺度同日结论不同是正常的，不再被压成一条综合动作。

唯一权威账本是 `memory/decisions.jsonl`。每条决策都有稳定 ID、策略、条件、仓位、置信度、驱动源、执行状态和评估状态。触发与结算走 `memory/bars/` 里**未复权的逐日行情**（单一 canonical 行情源，非交易所直连），按各自市场的交易日历计算——未收盘的 session 永远不参与打分。跳空穿过触发价的按开盘价成交，不按触发价：假装能在跳空前的价位成交，等于白送一段收益。休市、需人工核实、或标的当日无交易的，标为无法评分并公示条数，而不是悄悄从分母里消失。同一策略/动作的连续重申合并成一个 episode，因此连续五天写 hold 不会伪造五个样本——把触发价重锚到股价已经跑到的位置，仍然是重申，不是新的 call。一个 episode 的成绩取其内部已结算 call 的**平均值**，而不是推选其中某一条——做过多次 call 的 episode 经常自己跟自己矛盾，让首条或末条代表全组，能仅凭这个选择就把主动 call 胜率推过 50% 线。

Reflect 仪表盘展示：

- 累计 episode 胜率对 50% 方向命中线；
- 嘴上说的把握 vs 实际胜率，并与「留一法常数预测」对照 —— 这是信心值想有意义必须先跨过的门槛；
- 按日期聚类的 bootstrap 区间，避免把同日 call 当独立证据；
- 执行率拆成「要动手的」和「不用动的」两类分别统计 —— 因为「照做 HOLD」＝坐着没动，会机械性抬高综合执行率。仪表盘分别渲染实时的主动、被动和综合数值。

**这份战绩只量择时——现在是字面意义上的择时。** 单事件诊断回答「触发价比同日收盘执行好或差多少」：同票、同日、同方向、同股数严格配对，再报告 median bps 与按 date × ticker 聚类的 paired CI。它刻意不画累计金额曲线。

### 🧪 Shadow Portfolio · Policy Replay（政策模拟）

它回答更宽的反事实问题。两本 cash + inventory 账本从同一个 seed 沿时间重放：一本跟随全部已触发的主动建议，另一本买入后持有；两者都按 canonical 收盘计价，累计差记为**模拟 timing alpha**。现金与库存约束会挡掉重复建议卖同一批仓位的双计。Drill 卡片显眼标注**模拟 · 非实盘**，公开 `fill_counts.real_trade`——因为绝大多数建议并没有真实执行——USD 与 HKD 分账、绝不裸加，同时披露未复权日线带来的基线偏差。数据来自 sidecar `assets/data/shadow_portfolio.json`；这是政策模拟，不是实盘「听 AI 多赚多少」。

风控硬闸和 HOLD 纪律不在这两项择时诊断里，而在这个组合上恰恰是它们在真正干活 —— `assets/data/guardrail_history.jsonl` 持续积累证据。

LLM 只提交决策，不能写入或修改评估结果；ID、触发、分组和指标由 Python 流程按已记录的数据机械计算。这个隔离防止模型自评，但**不保证行情输入、触发判断或指标口径正确**；当前战绩仅作诊断，不作收益证明。

<p align="center"><img src="assets/shadow-backtest.png" alt="decision v2：累计 episode 胜率对 50% 方向命中参考线" width="760"></p>

<sub>累计 episode 胜率，50% 为方向命中参考线；只是方向判断的命中率，不代表收益。v1 历史已迁入 v2 episode 账本；由 GitHub Actions 每周刷新。</sub>

---

## 🎯 决策规则

每条判断都使用相同的归因、风控闸与策略分桶规则。

**1. 归因优先 —— 而且 edge 动态计算。** 每条决策标注唯一主导源；当前样本数、平均 benefit、胜率和日期聚类区间全部来自 `decision_metrics.by_driver`，README 不再写死某个时点的命中率。

**2. 硬催化 vs 软情绪。** 软情绪(Reddit、氛围、一条推)只能微调*置信度*数字,**永远翻不动操作分桶**。只有有日期的硬催化才能。

**3. 证伪,不证实。** risk-on 行情里默认 `HOLD`。一条*印证*利好的消息**不触发买入**;模型得先过一道证伪检查 + 一道"是不是已经 price in 了?"(近 5 日涨跌)测试。

**4. 信心被硬风控闸封顶。** 不管多笃定:单票 ≤35%、Top-2 ≤70%、杠杆 ETF 腿 ≤50%、组合 β ≤3.0、止损 −18%。仓位由结构约束,不由情绪。

**5. 杠杆按 regime 拨档,不择时。** 一个"200 日趋势 × 波动率"的刻度盘给杠杆 ETF 上限一个乘子(×1 / ×0.5 / ×0)。背后的回测教训:alpha 在*在错的 regime 里降杠杆*,不在抄顶。

**6. 量化信号必须挣到话语权。** 一层因子(双均线、12-1 动量、RSI-14、z-score、ATR 吊灯止损、波动目标仓位)在 Python 里跑 —— 但**每个因子在清过 n≥20 并证明命中率之前,禁止进入决策**。没证过的因子只展示、绝不照做。

所有东西最终落进一条或多条带明确条件的策略决策。同股的 `core_position`、`risk_rebalance`、`intraday_t`、`event_trade`、`tactical_entry` 可以并存，并在各自 episode 中结算。

---

## 🗣️ 多 Agent 决策台

08:00 深度简报使用结构化**多智能体辩论**，借鉴 [TradingAgents](https://github.com/TauricResearch/TradingAgents)，并针对港股与美股分账组合调整：

- **Tier 1 —— 4 个分析师视角。** 基本面 / 技术面 / 情绪面 / 板块轮动各自读取*同一份* `context.json` 并合并；每个观点都必须引用数字上下文。
- **Tier 2 —— Bull vs Bear。** 两个研究员组装对立的案子(持有/加仓 vs 减仓/砍仓),各自至少引 2 个具体的 Tier-1 数据点。硬规则:**至少要在 1 个仓位上真分歧** —— 一致同意 = 辩论失败,直接作废。
- **Tier 3 —— 3 个风险声音 + 一个 Judge。** Aggressive、Conservative、Neutral 各自争自己那一方;一个 **Judge** 给它们称重、点名每个决策由哪个 strategy frame 驱动,把争论收敛成带条件的策略决策。

至少一个持仓必须得到实质性的反方意见。Judge 将辩论结果写入 `plan.json`，并在下一交易日进入评分流程。

---

## 📅 每日运行时间表

```
03:00  🌙  记忆「做梦」—— 把昨天的教训提升进长期笔记
08:00  📊  每日深度简报 —— 多层分析 + 一个裁判模型,推送到微信
09:30  🇭🇰  港股开盘 → 10:00–11:30 / 14:00–15:30 盘中 → 12:00 午盘 → 16:00 收盘
09:30 ET 🇺🇸  美股开盘 → 拆分盘中盯盘 → 16:00 ET 收盘
            ↑ 每次成功完成的 reporting postflight 都会发布仪表盘语义变化
远端   🛰️  盘前宏观 / 舆情 / 影响力扫描 + 美股开盘前新闻摘要
每周   🧪  归档 / 健康检查 / 周复盘 / 视觉刷新
```

港股时间为 HKT；美股按 ET 表示，对应 HKT cron 会随纽约冬夏令时自动切换。精确生成表见 [CRON_SCHEDULES.md](CRON_SCHEDULES.md)。**节假日 + 周末闸**会跳过休市时段。

---

## 🏗️ 系统架构

Clawock 将概率性判断与确定性控制分开：Agent 分析组合并提出决策；Python 负责价格、风险上限、账本身份、结算、评分和发布。

![clawock 架构 —— Python 构建已对账的市场上下文，多 Agent LLM 进行辩论，代码记录决策，公开战绩表闭环评分](assets/architecture.svg)

上层路径将已对账的市场状态转成版本化决策；下层闭环使用 canonical bars 结算并评分，再将结果送回下一份简报。Watchdog、对账、投递兜底和安全发布均在模型之外运行。

---

## 🛡️ 可靠性控制

系统完整性由三层控制：

<table>
<tr><td width="33%" valign="top">

**1. Harness 模式**

每个**市场报告类** job 都是 `preflight(Python)→ LLM → postflight(Python)`。确定性的活 —— 价格、FX、HHI、信号计数 —— 100% 在代码里跑。LLM 只负责写*观点*。忘了 FX、漏了快照、跳过 >3% 异动 → postflight 抓出来并给报告打标记。算账函数有**单元测试**;**pre-push 闸会拒绝发布违反资金守恒的组合账本**。它挡的是账本自相矛盾,不保证行情口径正确。

</td><td width="33%" valign="top">

**2. 自学习闭环**

今天的 `plan.json` → 明天被打分。战绩表将置信度校准与实际结果送回下一份简报。

</td><td width="33%" valign="top">

**3. 纵深防御**

四层重叠保障 —— OpenClaw 跑主任务；GitHub Action 可接管缺失的晨间简报；系统 crontab watchdog 把确认漏投镜像到 Telegram；健康 workflow 把调度/数据漂移显性化。它不承诺多通道同时故障时仍必达，但单个 LLM stall 不再静默。

</td></tr>
</table>

**代码强制 fail-closed：**

- 组合风险算不出时，风险卡显示 **「⚠️ 算不出」**，绝不显示绿色「✅ 无」。
- 09:05 简报判官校验 `plan.json` 有效性；文件仅仅存在，不算有效计划。
- off-host 简报兜底按完整结构化 section 裁剪并发布 manifest；必需账本缺失时产出零动作，不拿残缺上下文临场发挥。

<details>
<summary><b>🔧 引擎盖下面</b> —— 运行时、写入协调与完整性闸门</summary>

<br>

**模型。** 交互式聊天当前跑 Claude；无人值守市场任务 pin **`MiniMax-M3`**。provider 凭证和 runtime fallback 策略在公开仓库之外，可独立变化而不改 harness。远端 LLM workflow 通过 Anthropic Messages 直调 MiniMax M3，并在可选 Xiaomi key 仍有效时退到 MiMo。仓库不存任何 provider key。

**写入对账。** dashboard 构建一次产出三份派生文件：`dashboard.json`、`decision_audit.json`、`shadow_portfolio.json`；cron 守护进程、远端 workflow、系统 crontab publisher、临时 session 都可能更新 `master`。所有权规则是：**隔离 scan sidecar 写者，并串行化同一 host 上的 dashboard builder。**

- **前端直接读 scan 子文件。** `macro / sentiment / influencer_feed / us_news_digest / em_news` 不再被嵌进 `dashboard.json`,`index.html` 加载时各自 fetch。于是一个 GitHub Action 永远只提交它*自己*那个互不相交的子文件 —— 这些写者不可能冲突,而且一次 scan 的 commit 一落地就立刻上页面,无需任何重建。(GH Actions 之间仍靠 `concurrency: group: data-write` 串行。)
- **三份 dashboard 构建产物共用一份 ownership 契约和同一把 host 锁。** 本地 harness postflight 和 flock 守护的 `publish_dashboard.sh` crontab 共用 host 上的 `/tmp/dashboard_publish.lock`，因此这些 host 内重建不会交错。所有 builder 都调用同一个语义 diff helper：纯构建时间变化会还原，任一生成文件出现真实变化就一起进入精确 staging pathspec。off-host `brief-fallback` 也复用同一 helper，但同名锁只存在于 GitHub runner 本地，无法与 host 上的锁互斥。
- **调度也有可校验契约。** runtime 真值来自 `openclaw cron list --json`;[`config/cron-schedules.json`](config/cron-schedules.json) 同时驱动[生成调度表](CRON_SCHEDULES.md)、DST 自动同步、payload/watchdog 检查和 CI health。Mode 7 会发布逐 slot heartbeat，不再是不可追踪的黑箱。
- **所有人都经 `safe_push.sh` push** —— rebase 重试、遇真冲突 abort(不死循环);提交进来的冲突标记会在 **push hook 被拒**,坏掉的 `dashboard.json` 永远到不了 Pages。
- **组合数字在门口就被闸住。** `portfolio.json` —— 唯一真值源 —— 写入走 advisory `flock` + 锁内重读再覆盖(`mutate_json`,原子 `os.replace`),根治 load-modify-write 竞态。**pre-push hook 会拦下任何账本违反资金守恒恒等式的 push**(`TCV = Σ 市值`、`现金 = 基线 + 成交 + 存取款`、`成本 = 移动加权`),所以没对账的改动到不了 Pages —— 而这些纯派生函数由 CI 里的 `pytest` 套件钉死。

</details>

---

## 📐 代码强制的「铁律」

以下约束由 `postflight` 强制执行：

- **🪙 FX —— HKD 和 USD 绝不直接相加。** 总额永远以两种口径展示,并盖上汇率 + 时间戳(`USDHKD = 7.83,来源 Frankfurter,<ts>`)。两种货币裸加是个毫无意义的数。
- **🔢 手填值 fat-finger 闸。** 少数手敲的值(现金余额、黄金定投对账)带笔误检测:现金较上一快照跳变 ≥5×、或黄金隐含均价偏离 NAV,会在静默污染总资产前被标出来。
- **📊 集中度 —— 每条腿单独算 HHI。** `HHI = Σ wᵢ²`,外加 Top-2 权重。分档:`<0.15` ✅ · `0.15–0.25` 🟡 · `0.25–0.40` 🟠 · `>0.40` 🔴。逐腿计算,绝不混算。
- **🎲 杠杆 ETF —— 看标的本身。** 名字带杠杆标记(`倍`、`Direxion`、`T-Rex`、`ProShares`、`2X/3X Long`……)的标的直接跳过基本面 —— 对每日重置的 2×/3× 产品,基本面是噪音;改用一个**杠杆刻度盘**(200 日趋势 × 波动率)来限制允许的杠杆上限。
- **💵 回报口径 —— 峰值净本金。** 回报 % 用 `true_principal` = 现金流账本里的峰值净投入,*不是* `cost − realized`。一笔已实现盈利会缩小 `cost − realized`、虚抬回报;账本口径不动。

---

## 🧬 技术栈与数据源

[Claude Code](https://claude.com/claude-code) · [openclaw](https://openclaw.com)(cron 守护进程)· [ECharts 5.5](https://echarts.apache.org/) · Jekyll + GitHub Pages · Python 3.11 · 纯静态前端

**公开数据** 腾讯 · stooq · yfinance · Frankfurter · SEC EDGAR · Finnhub · Nasdaq · 东财 · Polygon · Alpha Vantage · Reddit JSON · Google News RSS · Trump Truth Social feed

<sub>消息层为**双语**：Finnhub + Google News 覆盖美股，东财公司新闻 + 7×24 快讯覆盖港股。信息收集保持广度，决策层保持约束。</sub>

<details>
<summary><b>📊 数据工具包 — 8 层 26 端点，含每源本机可达性</b></summary>

<br>

Fetcher 优先使用有文档的公开端点，并在可用时采用**多源降级**；抓空会保留旧值，不整片覆盖。各数据源的条款和访问要求仍然适用。**可达**列来自服务器 IP 实测：✅ 稳定 · 🟡 flaky/限流 · 🔴 本机不可用。

| 层 | 端点 | 主数据源 |
|---|:---:|---|
| 1 · 行情 | 5 | 腾讯 gtimg · Yahoo v8 · 东财基金 |
| 2 · 基本面/申报 | 2 | SEC EDGAR · 东财 datacenter |
| 3 · 资金面 | 1 | 东财 push2his |
| 4 · 消息面 | 3 | 东财 · Finnhub · Google News |
| 5 · 宏观/情绪 | 4 | Yahoo · Reddit · Truth Social |
| 6 · 量化与风险 | 4 | 确定性计算 + 外部行情历史 |
| 7 · 汇率/校验 | 2 | Frankfurter · 本地不变量 |
| 8 · 回测/自省 | 5 | 本地快照 + 日线 |

- **1 · 行情** — `fetch_us_stocks` 美股实时价·多provider链 ✅ · `analyze_us_stocks` 美股刷新+RSI ✅ · `analyze_hk_stocks` 港股实时+HSI/HSTECH+新闻+信号 ✅ · `fetch_benchmark_history` SPY/HSI/HSTECH 日线 ✅ · `fetch_gold_dca` 黄金定投 000217 净值 ✅
- **2 · 基本面** — `fetch_us_filings` 10-K/10-Q·Form4·13F·XBRL(SEC) ✅ · `fetch_fundamentals_em` 美/港财报三表+关键指标 ✅
- **3 · 资金面** — `fetch_fundflow_em` 日级主力/超大/大/中/小单净流入 🟡
- **4 · 消息面** — `fetch_em_news` 港股个股中文新闻+7×24快讯 ✅ · `gh_action_news_digest` 美股持仓新闻→可执行要点 ✅ · `fetch_catalysts` 未来14天财报/事件 🟡
- **5 · 宏观/情绪** — `fetch_macro` VIX+宏观速读 ✅ · `fetch_sentiment` Reddit 情绪 🟡 · `fetch_influencer_feed` Trump/Musk 言论 🟡 · `fetch_peers` 同业现价+5日P&L ✅
- **6 · 量化与风险**(对外部行情历史做确定性计算，不含 LLM 判断) — `compute_quant_signals` 双均线/动量/RSI/ATR/vol-target ✅ · `compute_regime` 杠杆刻度盘(200DMA+波动带) ✅ · `compute_t0_setups` T+0牌面评级+追高检测 ✅ · `portfolio_risk_metrics` β/Cov-Var/回撤/集中度 ✅
- **7 · 汇率/校验** — `fetch_fx` USDHKD 3路fallback ✅ · `preflight_integrity` 钱守恒硬闸(TCV/PNL/FX/cash) ✅
- **8 · 回测/自省** — `decision_v2` episode 回测 · `backtest_hstech_regime` · `backtest_us_leverage` · `backtest_combined_regime` · `quant_signal_review` + `t0_setup_review` ✅

**请求节流** — 所有现役东财调用统一走 `_em_http.em_get()`：进程内串行（≥1s + 抖动）、单 `Session` 复用、有限重试后返回 `None`。运行抓取器或再分发内容前，请阅读[第三方数据与服务条款](THIRD_PARTY_DATA.md)。完整逐文件目录见 [`scripts/data/README.md`](scripts/data/README.md)。

</details>

<details>
<summary><b>📂 仓库结构</b></summary>

<br>

```
clawock/
├─ index.html  briefs.md                    ← Pages 着陆页
├─ assets/data/        由 harness + GH Actions 生成,绝不手改
│   ├─ dashboard.json  risk.json  catalysts.json
│   ├─ macro.json  sentiment.json  influencer_feed.json  us_news_digest.json  ← scan 子文件,前端直接 fetch
│   ├─ quant_signals.json  quant_signal_review.json     ← 因子战绩表
│   ├─ t0_setups.json  t0_setup_review.json             ← 盘中牌面战绩表
│   └─ guardrail_history.jsonl                          ← 每份简报里风控闸拦下了什么(2026-07-15 起积累)
├─ portfolio.json                           ← 唯一真值源(原子写入)
├─ tests/                                    ← decision-v2 + 资金守恒回归闸
├─ MEMORY.md  DREAMS.md                      ← 铁律 + 每夜「做梦」提升
├─ memory/
│   ├─ {date}-pre-open.md  {date}-plan.json  ← 简报输出 + 结构化计划
│   ├─ decisions.jsonl                       ← v2 决策/episode 权威账本
│   └─ snapshots/{date}.json
├─ scripts/
│   ├─ data/      抓取器 · build_dashboard.py · risk/quant/regime/t0 计算 · safe_push.sh
│   └─ harness/   {brief,report,intraday}_{pre,post}flight.py · 看门狗
└─ skills/{name}/SKILL.md
```

</details>

---

## ⚠️ 免责声明

本仓库包含**真实交易持仓**。它是一份个人记录和可移植工作区，不是投资建议、推荐或自动跟单系统。公开战绩未经人工修改，主动判断至今没显出优势；所有数字都可能在你阅读时已经过期。

## 📄 许可与第三方数据

原创代码采用 [MIT License](LICENSE)。改编的第三方代码继续保留原许可证与署名，见 [NOTICE](NOTICE) 和 [`THIRD_PARTY_LICENSES/`](THIRD_PARTY_LICENSES/)。第三方行情、新闻、社交帖子、申报文件、商标与 API 访问权不随 MIT 再授权；详见[第三方数据与服务](THIRD_PARTY_DATA.md)。本项目不是自动跟单服务。

---

<div align="center">

### ⭐ 关注这场实时实验

[**🎯 实时仪表盘**](https://kcnyu.github.io/clawock/) &nbsp;·&nbsp; [**📅 每日简报**](https://kcnyu.github.io/clawock/briefs.html) &nbsp;·&nbsp; [**English**](README.md)

<sub>由 <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> 与 Rick 构建维护 · 2026</sub>

</div>
