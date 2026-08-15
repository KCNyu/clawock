<div align="center">

<h1><img src="site/assets/logo-lockup.svg" alt="clawock" height="48"></h1>

### AI 争辩。代码结算。连亏损都摆在明面上。

Agent-native 投资决策工作流引擎。外部 Agent 负责思考,clawock 负责让每个决策可验证、可结算、可复盘。一个真实港美股投研台正在用它运行,全程公开。

[![Dashboard](https://img.shields.io/github/deployments/KCNyu/clawock/github-pages?label=DASHBOARD&style=flat-square&logo=githubpages&logoColor=white&labelColor=252b35&color=4b91c8)](https://kcnyu.github.io/clawock/)
[![Tests](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=TESTS&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![Dashboard Data](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/dashboard-artifact-gate.yml?label=DATA&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/dashboard-artifact-gate.yml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fkcnyu.github.io%2Fclawock%2Fassets%2Fdata%2Fcoverage.json&style=flat-square&logo=python&logoColor=white&labelColor=252b35)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![License](https://img.shields.io/badge/LICENSE-MIT-aab5bf?style=flat-square&labelColor=252b35)](LICENSE)

[**实时仪表盘**](https://kcnyu.github.io/clawock/) &nbsp;·&nbsp; [**每日简报**](https://kcnyu.github.io/clawock/briefs.html) &nbsp;·&nbsp; [**证据与反证**](https://kcnyu.github.io/clawock/evidence.html) &nbsp;·&nbsp; [**English**](README.md)

<br>

<a href="https://kcnyu.github.io/clawock/">
  <img src="site/assets/social-card.png" alt="clawock —— 装进任意外部 Agent 的可迁移投资决策工作流,并由真实港美股投研台持续验证" width="820">
</a>

<sub><i>“市场不在乎模型有多自信。”</i></sub>

<a href="https://kcnyu.github.io/clawock/"><img src="site/assets/dashboard.gif" alt="clawock 仪表盘循环切换各标签页" width="300"></a>

<sub>真实持仓、真实盈亏、公开打分。预览图每周刷新;实时仪表盘随交易日更新。</sub>

</div>

---

## 这是什么

给 AI Agent 用的投资决策工作流引擎。Claude Code、Codex、OpenClaw 或任何外部运行时负责模型调用、对话、记忆、工具;clawock 负责把一次投资决策变成一份**带证据、带反方、带结算、带战绩**的记录。

**模型提议,Python 结算,战绩公开。** 价格、风控上限、账本、盈亏结算全部由代码独立完成,模型永远不能给自己打分——所以这份公开战绩连亏损都收着,包括「主动判断至今没跑赢买入持有」。它不是跟单服务,不替你下单;执行始终在账户所有者手里。

它发布在 PyPI:`pip install clawock`,在自己账本上跑,不需要这个仓库。

## 快速开始

前置要求:Python ≥ 3.11,一个能读写文件的 Agent(任何 runtime 都行,模型调用留在你自己的环境里)。

```bash
python -m pip install clawock
clawock workflow install investment-decision --workspace ./my-decision
clawock init ./my-decision --workflow investment-decision
clawock run prepare --workspace ./my-decision
```

`run prepare` 产出一份带上下文指纹的请求文件,交给你的 Agent 写出 `decision.json`,`run publish` 负责校验(证据、反方、资金与汇率对账)并给出生成回执。不想先接模型?`examples/minimal-run` 无模型完整跑通 `init → prepare → publish`(被 CI 执行,不会烂掉):

```bash
bash examples/minimal-run/run.sh
```

## 核心卖点

| 卖点 | 人话 |
|---|---|
| **Agent-native** | 不重造 Agent。模型、记忆、工具循环全在外部 runtime,clawock 只安装决策契约,跨 runtime 可迁移 |
| **确定性结算** | LLM 提议,Python 结算。模型写不了、改不了自己的战绩 |
| **公开自评** | 一个真实港美股账户,每一条结果都公开打分,亏损在内,「没跑赢买入持有」也写在页面上 |
| **有界改进** | 结算结果只能提议有边界的参数改动,不能暗改策略 |
| **证据强制** | 每个论点必须有反方;每次加仓必须量化证据 × 时点信息两族同时成立 |
| **账本守恒** | 每次发布前检查资金守恒,现金/持仓/盈亏不平就什么都不发 |

## 防作弊机制

- **模型不能给自己打分**:决策由 Python 按基准行情、各市场自己的交易日历结算
- **一个论点只算一次**:同一论点的重复喊单收敛为一个案例(episode),连喊五天「持有」不会变出五个样本
- **因子要过样本外检验**:因子优势的 bootstrap 区间必须整体落在 50% 一侧才能进决策;截面层预注册,回溯结果永远不能把它打开
- **风控上限每次简报都查**:单票 ≤35%、Top-2 ≤70%、杠杆 ETF ≤50%、组合 β ≤3.0、−18% 止损;每条违规有持久化记录
- **软情绪不能单独翻转交易**:一条推文只能微调置信度,硬负面催化才可触发防守动作

## 它已经在跑

这套系统每天 08:00 产出深度简报(多 Agent 辩论:四视角分析师 + 多空研究员 + 三位风险官 + 一位裁判归因),盘中每 30 分钟盯盘,收盘结算,推送到微信,并刷新公开仪表盘。港股按 HKT、美股按 ET,cron 随纽约夏令时自动切换;节假日闸门跳过休市场次。

[**实时仪表盘**](https://kcnyu.github.io/clawock/) · [**每日简报**](https://kcnyu.github.io/clawock/briefs.html) · [**证据与反证**](https://kcnyu.github.io/clawock/evidence.html) · [**排程表**](docs/operations/cron-schedules.md)

## 术语速查

| 术语 | 一句话 |
|---|---|
| Agent-native | 为 AI Agent 设计,装进现有 runtime,而不是再造一个 Agent |
| 确定性结算 | 由 Python 代码结算,LLM 无法改写结果 |
| 多智能体辩论 | 多空对立论点 + 裁判点名策略框架,一致同意读作警示 |
| 护栏 / 硬闸 | 风控上限由代码执行,不靠模型自觉 |
| 样本外验证 | 因子先通过检验,才能影响决策;预注册防回溯作弊 |
| 审计链 | 证据 → 反方 → 决策 → 执行 → 结果,一条 lineage 到底 |
| 有界改进 | 结果只能提议参数调整,不能重写策略 |
| 影子组合 | 模拟回放同一时间线,对比「跟单建议」与「买入持有」 |

## 底层是怎么组织的

<details>
<summary><b>信息层:8 层 40 个模块,港股美股双语覆盖</b></summary>

<br>

| 层 | 模块 | 主要来源 |
|---|:---:|---|
| 1 · 行情 | 7 | 腾讯 · Yahoo · 东财 · Polygon |
| 2 · 基本面/申报 | 3 | SEC EDGAR · 东财 datacenter · 港交所 |
| 3 · 资金面 | 1 | 东财 push2his |
| 4 · 消息面与催化剂(双语) | 5 | 东财 · Finnhub · Google News · 交易所公告 |
| 5 · 宏观/情绪 | 3 | Yahoo · Reddit · CNN · 社交 feed |
| 6 · 量化与风险 | 8 | 对价格历史做确定性计算 |
| 7 · 账本/汇率校验 | 6 | Frankfurter · 对账账本 · 本地不变量 |
| 8 · 回测/自省 | 7 | 本地快照 + 基准行情 |

每次运行只拿自己能用得上的块:preflight(Python)组装上下文 → 模型读文件 → postflight(Python)校验发布。抓取层优雅降级:东财统一走节流网关,报价/汇率多源兜底,抓空保留旧值。哪个模块属于哪一层由 [`config/information-layers.json`](config/information-layers.json) 声明,CI 对着它核对,模块搬了家数字不会留在原地。完整命令与 provider 目录见[命令参考](docs/reference/commands.md)。

</details>

<details>
<summary><b>打分与回测的硬规则</b></summary>

<br>

<p align="center"><img src="site/assets/shadow-backtest.png" alt="累计案例胜率对 50% 方向命中基线" width="760"></p>

<sub>累计案例胜率对 50% 方向命中基线 —— 衡量方向对了多少次,不是赚了多少;买入持有对比在持仓页的影子组合里。每周刷新。</sub>

- 触发与标记来自单一基准供应商的逐日不复权行情;未完成场次永不打分,缺口按开盘价成交
- 置信度只保留为审计字段;严格前向的 beta-binomial 分层模型,稀疏小组向宽层先验收缩
- 择时单独计价:只问触发成交比当日收盘好或差多少,从不画累计金额曲线
- 影子组合(模拟,非实盘):两本现金+库存账重放同一时间线,一本跟主动建议、一本买入持有
- 杠杆刻度盘样本外打分,择时能力对照环形位移原假设;当前结论:不可与随机区分,页面如实写着
- 页面从产物生成,不能与产物脱节;引用回测数字必须指向仍含该数字的运行卡,CI 两条都查

</details>

<details>
<summary><b>架构与写入协调</b></summary>

<br>

![clawock 产品架构 —— 外部运行时拥有模型、对话、记忆与工具;包提供可迁移工作流、认证上下文、确定性对账、评估和有边界改进](site/assets/product-architecture.svg)

![KCNyu live desk 架构 —— Python 构建对账后的市场上下文,OpenClaw Agent 辩论交易,clawock 契约把关决策,公开战绩闭环](site/assets/architecture.svg)

![clawock 的多 Agent 辩论 —— 一份证据包喂给四种分析师视角;两名研究员建立多空对立论点并记录分歧点;三种风险声音与一位裁判点名策略框架,收敛成 plan.json,进入下一场的打分环](site/assets/debate-flow.svg)

- 仪表盘产物整体发布到数据面(data plane);前端直接读扫描旁路文件(sidecar),写者互不冲突
- 所有写入走 `ops/publish/safe_push.sh`:rebase 重试、真冲突中止,冲突标记在 push hook 被拒
- `portfolio.json` 是唯一真源:advisory 文件锁 + 原子替换,pre-push hook 拦下账目不平的 push
- 模型选择属于外部 runtime,仓库不存任何供应商密钥
- 仓库结构、排程契约等细节见[项目文档](docs/README.md)

</details>

## 研究入口

| 问题 | 入口 | 复用范围 |
|---|---|---|
| 分析一家美股公司 | [`us-stock-analysis`](skills/us-stock-analysis/SKILL.md) | 可随 clawock 工作区复用 |
| 分析一家港股公司 | [`hk-stock-analysis`](skills/hk-stock-analysis/SKILL.md) | 可随 clawock 工作区复用 |
| 检查当前组合 | [`portfolio-risk-review`](skills/portfolio-risk-review/SKILL.md) / [`portfolio-swarm-review`](skills/portfolio-swarm-review/SKILL.md) | 依赖已配置的真实组合 |
| 复盘一个已披露的报告期 | [`earnings-review`](skills/earnings-review/SKILL.md) | 可复用,产物落 `memory/earnings/` |
| 判断新标的值不值得深研 | [`entry-gate`](skills/entry-gate/SKILL.md) | 可复用,产物落 `memory/entry-gates/` |

入口单向串联:建仓前研究闸 → 一手财报证据 → 规范论点 → 决策/风控/结算回路,每步写版本化产物,后一步永远无法用文案重推前一步。

## 许可与免责

本仓库包含**真实交易持仓**,是个人记录与可携带工作区——**不是投资建议、不是推荐、也不是跟单系统**。结算规则与方法学变更都在代码里版本化,任何一条结果都不是人工挑选的;主动判断至今没显出优势,你读到时每个数字都可能已经过时。

原创代码 [MIT](LICENSE);改编第三方代码保留原许可与署名,见 [NOTICE](NOTICE) 与 [`THIRD_PARTY_LICENSES/`](THIRD_PARTY_LICENSES/)。行情、新闻、社交内容与 API 访问**不**被 MIT 重新授权,见[第三方数据与服务](docs/legal/third-party-data.md)。

用 [Claude Code](https://claude.com/claude-code)、[openclaw](https://openclaw.com) cron 守护进程、Jekyll + GitHub Pages 与 Python 构建。

<div align="center">
<br>

**[实时仪表盘](https://kcnyu.github.io/clawock/)** &nbsp;·&nbsp; **[每日简报](https://kcnyu.github.io/clawock/briefs.html)** &nbsp;·&nbsp; **[English](README.md)**

<sub>由 <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> 与 Rick 构建维护 · 2026</sub>

</div>
