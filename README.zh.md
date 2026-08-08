<div align="center">

<h1><img src="assets/logo-lockup.svg" alt="clawock" height="48"></h1>

### 把投资决策能力，装进任何 Agent。

证据优先的投资 workflow、确定性的资金对账、连接结果的评估，以及有边界的改进；不替代你的 Agent runtime。

[![Dashboard](https://img.shields.io/github/deployments/KCNyu/clawock/github-pages?label=LIVE%20PROOF&style=flat-square&logo=githubpages&logoColor=white&labelColor=252b35&color=4b91c8)](https://kcnyu.github.io/clawock/)
[![Tests](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=CONTRACTS&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![Dashboard Data](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/dashboard-artifact-gate.yml?label=DATA&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/dashboard-artifact-gate.yml)
[![License](https://img.shields.io/badge/LICENSE-MIT-aab5bf?style=flat-square&labelColor=252b35)](LICENSE)

[**快速开始**](#快速开始) · [**架构**](#架构) · [**OpenClaw adapter**](#openclaw-是第一个生产-adapter) · [**KCNyu 实盘证明**](https://kcnyu.github.io/clawock/) · [**English**](README.md)

</div>

## clawock 是什么

clawock 是一套**面向 Agent 的投资决策 workflow plugin kit，加上一层可验证
harness**。OpenClaw、Hermes、Claude Code、Codex 或其它能用工具的外部 runtime
负责模型调用、对话、记忆、规划、工具、权限和凭证；它们安装或调用 clawock，
让一条投资决策遵守可迁移、可检查的契约。

第一套 workflow 把证据变成有边界的决策，并继续保留决策之后的链路：

```text
支持证据 + 真正的反方证据
              │
              ▼
 thesis + 失效条件 ──► decision ──► execution / outcome
              │              │                │
              └──── 认证上下文 + 确定性资金/汇率对账 ────┘
                                                   │
                                                   ▼
                                      可审阅的改进提案
                                      └─ 接受 / 拒绝 / 回滚
```

它不是交易机器人、券商、模型路由器，也不是另一套 Agent 框架。clawock 不决定
调用哪个模型，也不执行交易。它负责把 workflow 和其中的金融真值迁移到不同
Agent 之间。

## 为什么需要这一层

Agent 擅长读模糊证据、形成观点，却不适合当算术、溯源以及「给自己打分」的
最终权威。券商能给交易记录，通用 observability 能记工具调用；但它们本身都
不会强制一条完整的投资决策闭环。

clawock 增加四个领域能力：

- **决策必须过反方。** 只有支持材料不够；产物必须包含真正的反方论点和明确的
  thesis 失效条件。
- **资金由代码结算。** 订单、币种、汇率时间戳、费用、现金和盈亏进入确定性
  校验，不是任模型重新解释的散文。
- **记录不会停在答案。** workflow 版本、认证输入、决策、执行和观察到的结果
  共用一条 lineage。
- **改进有边界。** 结果只能对声明过的证据/溯源参数提出改动；提案可审、可
  版本化、可回滚，不能悄悄改策略或外部 Agent。

## 安装状态

包已经能以非 editable wheel 的方式在仓库外运行。在
[#379](https://github.com/KCNyu/clawock/issues/379) 完成 trusted publishing 之前，
请从 GitHub 安装当前 pre-release：

```bash
python -m pip install "clawock @ git+https://github.com/KCNyu/clawock.git"
clawock --help
```

这里暂时不宣传 `pip install clawock`：PyPI 项目还没有发布。release workflow
会使用 PyPI trusted publishing，并先做隔离 index 安装 smoke，之后才改这段文案。

## 快速开始

下面用包内的 example artifact 做 smoke。它证明的是 workflow lifecycle，不冒充
clawock 自己调用过模型：

```bash
clawock workflow install investment-decision --workspace ./decision-demo
clawock init ./decision-demo --workflow investment-decision

request_path=$(clawock run prepare --workspace ./decision-demo \
  | python -c 'import json,sys; print(json.load(sys.stdin)["request_file"])')

cp ./decision-demo/.agents/skills/investment-decision/assets/decision.example.json \
  ./decision-demo/decision.json

clawock run publish \
  --workspace ./decision-demo \
  --request "$request_path" \
  --artifact decision.json=./decision-demo/decision.json
```

receipt 把认证 request、workflow 版本、通过校验的 artifact 和不可变 generation
目录关联起来。真实使用时，把 `cp` 那一行换成外部 Agent 读取同一个 request 与
已安装 skill 后产出 `decision.json`。

### 外部 Agent 契约

一个 adapter 不需要复制业务规则，只需要：

1. 运行 `clawock run prepare` 并读取输出的 request JSON；
2. 让 Agent 能看到已安装的 `investment-decision` skill；
3. 让 Agent 在不修改 request 的前提下写出 `decision.json`；
4. 用同一个 request 和 artifact 运行 `clawock run publish`。

clawock 校验输出并发布 receipt。只有 runtime 能调用模型、使用对话、记忆和工具。

## workflow 里有什么

`clawock workflow show investment-decision` 会打印包内契约。当前 1.1.0 包含：

- 标准 `SKILL.md`、runtime-neutral references 和 JSON Schemas；
- 认证过的上下文文件与 workflow certificate；
- 支持证据和反方证据要求；
- thesis、失效条件、有边界的动作、订单、币种与汇率字段；
- 确定性的 decision/outcome 校验；
- generation-pinned artifacts 与本地 publication receipts；
- 用于有边界改动的 evaluate、propose、review、apply、rollback 命令。

这套 workflow 不发明新的量化因子、catalyst、信号、买卖点或组合规则。它消费
用户现有策略与证据。

## 有边界的改进，不是自主改写自己

```text
decision + observed outcome
            │
            ▼
 clawock workflow evaluate
            │
            ▼
 与证据绑定的 proposal
            │
       审阅精确 diff
       ┌────┴────┐
     拒绝       接受 ──► apply ──► rollback record
```

只有声明过的 workflow 参数可以改变。apply 必须带已接受的 review record；
rollback 恢复旧参数。生产指令、Agent memory、模型 policy 与投资策略不会隐式变化。

## 架构

![clawock 产品架构 —— 外部 Agent runtime 拥有模型、对话、记忆与工具，clawock 包提供可迁移 workflow、认证上下文、确定性对账、评估和有边界改进](assets/product-architecture.svg)

```text
┌──────────────────────────────────────────────────────────────┐
│ 外部 Agent runtime                                          │
│ OpenClaw · Hermes · Claude Code · Codex · 其它               │
│ model · chat · memory · planning · tools · permissions       │
└───────────────────────────┬──────────────────────────────────┘
                            │ 安装 Skill / 调用 CLI + JSON
┌───────────────────────────▼──────────────────────────────────┐
│ clawock 产品（`src/clawock/`）                               │
│ workflows · 认证上下文 · artifact contracts                 │
│ 确定性校验/对账 · evaluation                                 │
│ generation receipts · proposal/review/rollback               │
└───────────────────────────┬──────────────────────────────────┘
                            │ adapter-owned I/O
┌───────────────────────────▼──────────────────────────────────┐
│ 用户实例                                                     │
│ strategy · evidence · ledger · schedules · delivery · UI     │
└──────────────────────────────────────────────────────────────┘

今天的 KCNyu 生产实例：
OpenClaw scheduler ─► KCNyu adapter ─► clawock contracts
                  └► 对账账本 ─► data plane ─► Pages
```

最下面一层不进 wheel。公开 KCNyu dashboard 是一个真实运行实例和证明面，不是
可复用产品本身。

### 仓库目录图

```text
src/clawock/        可安装产品、schemas、workflow pack、adapters
tests/              高价值不变量与 installed-wheel 契约
scripts/harness/    迁移中的 KCNyu lifecycle adapter
scripts/data/       已分类、尚未完成物理迁移的 product/instance inventory
scripts/ops/        主机与运维入口
config/             KCNyu 实例配置（产品 schemas 已迁出）
skills/             OpenClaw 实例 skills；runtime 路径暂时保持稳定
memory/             KCNyu 账本、结果、研究状态与 OpenClaw memory
assets/ + *.html    当前 Pages source 与生成的 dashboard surface
```

这张图诚实保留了尚未拆开的部分。最终的 product/instance/site/operations 分离在
[#381](https://github.com/KCNyu/clawock/issues/381) 追踪；在 prompt、memory、skills、
tools、cron 和 delivery 的等价性证明完成前，不会为了目录好看移动 OpenClaw 根
上下文文件。

## OpenClaw 是第一个生产 adapter

当前实例用 OpenClaw 承担正常聊天和 11 个 isolated scheduled jobs。clawock 分别
记录 interactive chat、isolated cron、heartbeat 和 bootstrap context profile，
包含 memory 与 skill discovery，而不是把五个 Markdown 当成全部上下文。

OpenClaw adapter 的 runtime path 可配置。包不会暗中缩小 OpenClaw 的工具集，
下面这些责任始终属于 OpenClaw：

- 正常对话历史和 startup context；
- `AGENTS.md`、`SOUL.md`、`TOOLS.md`、`IDENTITY.md`、`USER.md` 注入；
- `MEMORY.md`、日期 memory、索引与搜索；
- skill catalog discovery 和选定 `SKILL.md` 的加载；
- tool schemas、权限、heartbeat、bootstrap、cron 与 delivery。

参见 [adapter contract](docs/architecture/openclaw-adapter.md) 与
[`clawock context audit`](docs/architecture/harness.md)。真实 OpenClaw scheduler
canary 已经成功调用包内 workflow；完整市场定时任务切换仍在
[#380](https://github.com/KCNyu/clawock/issues/380) 中。

## KCNyu 实盘证明

[公开 dashboard](https://kcnyu.github.io/clawock/) 跑的是一个真实港股 + 美股组合
workflow。它的价值不是展示漂亮 demo，而是把决策、亏损、对账与结果历史一起
暴露出来。最终执行权仍由人持有。

<p align="center"><a href="https://kcnyu.github.io/clawock/"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/assets/dashboard.gif" alt="KCNyu clawock dashboard 循环展示真实运行证明" width="300"></a></p>

- [实时 dashboard](https://kcnyu.github.io/clawock/)
- [已发布简报](https://kcnyu.github.io/clawock/briefs.html)
- [证据与反证](https://kcnyu.github.io/clawock/evidence.html)
- [Cron contract](docs/operations/cron-schedules.md)
- [Product vs instance 分类](docs/reference/product-vs-instance.md)
- [KCNyu live-instance 架构](assets/architecture.svg)

实盘里的任何内容都不是投资建议、收益承诺、跟单服务，也不能证明 workflow
具有市场 edge。

## 当前边界：不夸大

已经实现并验证：

- 在源码仓库外从 wheel 运行 package-native `init`、workflow 安装/发现、
  `run prepare` 与 `run publish`；
- evidence/opposition/decision/outcome schemas 与确定性资金/汇率校验；
- 明确的 proposal review、apply 与 rollback；
- 可配置 OpenClaw runtime path 和一次真实 isolated-scheduler canary；
- 一套 fail-closed 发布的真实 portfolio/data/dashboard 实例。

在称为「已完整交付的独立 harness」之前还缺：

- 正式 TestPyPI/PyPI 发布和 public index 隔离安装；
- 由一套有文档的非 OpenClaw runtime 跑完同一条真实 workflow；
- 从 `scripts/harness` 抽出剩余 KCNyu compatibility phases；
- 物理上的 instance/site/operations 分离；
- OpenClaw 全部 market cron 切换与相邻版本 before/after context parity。

终极交付计划和证据要求见
[#378](https://github.com/KCNyu/clawock/issues/378)。

## 开发

```bash
git clone https://github.com/KCNyu/clawock.git
cd clawock
python -m pip install -e '.[test]'
python -m pytest -q tests/test_wheel_contains_the_package.py
```

项目刻意把 installed-wheel 行为、资金对账和真实 receipt 放在 decorative test
数量之前。参见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [SECURITY.md](SECURITY.md)。

## License 与风险

MIT License。见 [LICENSE](LICENSE)、[NOTICE](NOTICE)、
[第三方数据条款](docs/legal/third-party-data.md) 与
[third-party notices](THIRD_PARTY_LICENSES/README.md)。

clawock 是研究软件，不是投资建议。它不下单，也不保证准确率、可用性或收益。
任何真金白银的使用都应保留人工批准、券商侧控制与独立对账。
