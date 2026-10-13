<div align="center">

<h1><img src="site/assets/logo-lockup.svg" alt="clawock" height="48"></h1>

### AI 争辩。代码结算。连亏损都摆在明面上。

[![PyPI](https://img.shields.io/pypi/v/clawock?label=PYPI&style=flat-square&logo=pypi&logoColor=white&labelColor=252b35&color=4b91c8)](https://pypi.org/project/clawock/)
[![npm](https://img.shields.io/npm/v/clawock-dsh?label=NPM&style=flat-square&logo=npm&logoColor=white&labelColor=252b35&color=4b91c8)](https://www.npmjs.com/package/clawock-dsh)
[![Tests](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/ci.yml?label=TESTS&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/ci.yml)
[![线上数据校验](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/dashboard-artifact-gate.yml?label=DATA&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/dashboard-artifact-gate.yml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fkcnyu.github.io%2Fclawock%2Fassets%2Fdata%2Fcoverage.json&style=flat-square&logo=python&logoColor=white&labelColor=252b35)](https://github.com/KCNyu/clawock/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/LICENSE-MIT-aab5bf?style=flat-square&labelColor=252b35)](LICENSE)

[**实时仪表盘**](https://kcnyu.github.io/clawock/) &nbsp;·&nbsp; [**每日简报**](https://kcnyu.github.io/clawock/briefs.html) &nbsp;·&nbsp; [**证据与反证**](https://kcnyu.github.io/clawock/#reflect) &nbsp;·&nbsp; [**English**](README.md)

<a href="https://kcnyu.github.io/clawock/">
  <img src="site/assets/social-card.png" alt="clawock —— 装进任意外部 Agent 的可迁移投资决策工作流,并由真实港美股投研台持续验证" width="820">
</a>

<sub><i>“市场不在乎模型有多自信。”</i></sub>

<a href="https://kcnyu.github.io/clawock/"><img src="site/assets/dashboard.gif" alt="clawock 仪表盘循环切换各标签页" width="820"></a>

<a href="https://kcnyu.github.io/clawock/#drill"><picture><source media="(max-width: 700px)" srcset="site/assets/books-narrow.svg"><img src="site/assets/books.svg" width="820" alt="美股账本与港股账本并排:各自的回报率、该回报率所除的本金口径,以及各自币种下的逐日盈亏曲线;下方是混合口径的合并回报率"></picture></a>

| **<!-- CW_M:days -->148<!-- /CW_M:days -->** | **<!-- CW_M:rows -->1013<!-- /CW_M:rows -->** | **<!-- CW_M:settled -->166<!-- /CW_M:settled -->** | **47** | **5** | **0** |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 天,真实港美股账户实盘 | 条决策,账本全部公开 | 个案例由代码结算 | 8 层抓取与计算模块 | 种 Agent harness,同一份契约 | 条分数由模型给自己打 |

<sub>真实持仓、真实盈亏,亏损照样摆出来([原始决策记录](https://github.com/KCNyu/clawock/blob/master/memory/decisions.jsonl))。数字与图每周刷新;实时仪表盘随交易日更新。</sub>

</div>

## 你能得到什么

clawock 帮你的 AI Agent 分析港股或美股持仓、写出买卖计划。作者每天早上收到的计划会说明买、卖还是继续等，支持和反对的理由，以及哪些价位会改变建议。**下单的是你。** 之后，程序按行情核对这些判断，把结果留给 Agent 下次参考。

<p align="center"><img src="site/assets/rsi-loop.svg" width="1016" alt="clawock 全景：八个信息层经兜底路径进入；Python 对账并认证出一份上下文；Claude Code、Codex、OpenClaw、DeepSeek Harness 或你自己的 CLI 在同一份证据上写多空两方；代码复核集中度并执行配置中的风控边界、记下越线之后的处置并执行证据要求；计划送到你手里，下单由你；代码把每条判断结算为赢、输或无法打分；记录沿两个回路返回，一个经历史与只用更早日期的校准进入下一次判断，一个经有边界的提案与具名审查进入证据规则；在作者的主机上，巡检轮次、提报闸、后台 agent 与必需 CI 维护实盘自身的代码，在 DeepSeek Harness 里看得见"></p>

**这个循环，就是这里说的 RSI（Recursive Self-Improvement，递归自我改进）。** 作者的每日任务依赖已接好的数据源、定时运行配置和积累的决策历史。新用户需要接入自己的数据、设置排程，也可以先跑[单次示例](#五分钟跑起来)。保存以前的证据和结果，让 Agent 在下次判断前有据可查。**它不承诺收益。** 那些叫作者「动手」的建议，还没有证明自己比抛硬币强。

这一页用一次真实判断说明整个过程：2026-10-08 早上的金风科技（`02208`，港股）。计划是继续持有观察，站上 8.97 才加仓。到下一个交易日收盘，股价下跌，账本因此记为 `loss`：评的是继续持有的判断，没有假定按 8.97 买入。下面几节分别说明证据、计划和计分方式。

计划里的指标由[插件](#能算的都是插件结果能做什么不是)计算。策略可以[搜索更好的设置](#策略可以搜索自己的参数采纳是一次要-review-的改动)，但采纳前需要人工审核。[五分钟跑起来](#五分钟跑起来)。

## 能算的都是插件；结果能做什么不是

2026-10-08，作者持有 400 股金风科技（`02208`，港股），平均成本 14.084。下面是指标如何进入计划、判断如何得到评估的过程。插件负责计算指标，`config/strategy-plugins.json` 指定使用哪些模块及其设置。

1. **`factors` 插件用金风的每日行情计算指标。** 结果显示没有上升趋势，股价在 200 日均线下方 31.8%。
2. **模型结合指标和其他证据写出多空理由。** 多方：同业里只有金风给出可以执行的确认价，组合也缺少港股科技与 AI 以外的持仓。空方：趋势弱，组合已越过四条风控线，都不支持加仓。结论是先观察，在价格到达前记下触发条件。
3. **计划具体到可以被证明是错的。** 观察；五个交易日内站上 8.97 才动手；跌到 8.923 这个想法作废。信心 0.34。
4. **代码评估继续持有的判断。** 参考价 8.645，是计划发布后第一个能成交的价格。下一个交易日收盘比它低了 4.22%，因此结果记为 `loss`。这条记录没有假定按加仓触发价买入。
5. **判断和结果留在记录里。** 公开账本上的 `dec-6d9e8bdc8817` 会计入下一份简报读取的历史记录。

<p align="center"><img src="site/assets/strategy-plugins.svg" width="1016" alt="一次真实判断，2026-10-08 的金风，分五步。01：factors 这一行画成插在插座里的一个模块，旁边留着一个空插座给你自己的行；它算出一条读数：趋势关闭，价格在 200 日均线下方 31.8%。02：模型就这条读数写出多方与空方。03：落在纸上的计划：观察，五个交易日内站上 8.97 才动手，8.923 作废，信心 0.34，存在分歧。一条线标着「从这里往下不是行」。04：金风截至 2026-10-09 的八根日线，动手价与作废价横贯其上；代码取 2026-10-08 的开盘价 8.645 为参考价，按下一个收盘 8.28 计价，低 4.22%，判为亏损。05：账本里存下的那一条，dec-6d9e8bdc8817，结果 loss。没有任何行可以给自己的判断打分、挑一个更有利的参考价、把亏损改成别的结果，或者让它不上账。"></p>

**你可以替换第 1 步的插件。** 自己的插件可以换用另一条均线、观察期或数据源。第 4、5 步的结算和记账不由插件控制：插件不能给自己的判断打分、挑选参考价、改结果或把判断排除在账本之外。因此，不同策略可以按同一套计分规则比较。

接入自己的 Agent 时，你需要一个 skill、一个命令行工具和一套交换决策的 JSON 文件格式。模型、对话和工具仍归你的 Agent。

**插件必须说明输入和输出。** 结果进入决策前，插件必须声明数据来源、单位、观察期和缺数据时的处理方式，不能把昨天的结果当成今天的。

| 插件 | 计算什么 | 缺数据时 |
|---|---|---|
| `factors` | 用每日行情计算每只股票的趋势、动量、RSI、波动与离场价 | 该字段为空；日线不足 30 根时，不提供这只股票的计算结果 |
| `bar-signals` | 每个交易日里，一只股票的交易成本有多高、接下来可能动多大 | 留空，绝不写 0：「估不出来」不等于「交易成本低」 |
| `sentiment` | 七天内的 Reddit 提及数，以及点名公众人物的言论 | 整段省略，并写明扫描是缺失、过期还是读不了 |
| `morning-scans` | 宏观快照与中文资讯，并且是每个定时扫描文件的唯一读取处 | 同上：省略，并给出原因 |
| `strategy-scores` | 每个标的在每个研究策略当前设定下排第几；仅作参考 | 写明未取到及原因 |

**插件加载失败时，依赖它的任务会停下并报出插件名，其余任务照常运行。**

**你可以编写自己的插件。** 在配置文件里登记已安装的 Python 模块；接口与必填声明见[插件编写指南](docs/architecture/strategy-plugins.md#writing-a-plugin-outside-this-repository)。插件以你的权限运行，不在沙箱内，因此只安装你信任的模块。

**其他插件运行时，你可以添加、移除插件或修改设置。** 移除插件会暂停依赖它的插件，恢复后自动重启；修改设置会让该插件按新配置重启。这沿用了 [dsh](examples/dsh/README.md) 的插件设计。

<p align="center"><img src="site/assets/plugin-system.svg" width="1016" alt="整套插件系统，分七部分。01：无论哪个 Agent 在跑这张台子（Claude Code、Codex、OpenClaw、dsh 或任意 CLI），执行的都是 brief、report、intraday 和 strategy-lab 这几条命令。02：一个文件 strategy-plugins.json 列出全部的行：十三个现网行、七个研究行，每行是一个 id、一个模块和它的设置。03：宿主把每一行挂进一个插座；二十行全部按名字画出，研究行 bars 被从插座里拔了出来，另有一个空插座留给你自己的行。04：拔出 bars 会撤销它唯一的一次注册，声明过需要 bars 的 optimizer 行进入等待，其余五行从未停过；插回去，optimizer 自己重新启动。05：改一个设置，把 daily-bars 行的 adjustment 从 qfq 改成 raw，这一行停下并在新设置下重新启动。06：dsh 所基于的五个原语与它们在这里的名字并排：文件里的一行、fiber、provide 与 inject、effect、update。07：没有插座的东西：结算、账本和风控上限。"></p>

```bash
clawock strategy-lab list       # 插件、提供的服务和缺少的依赖
clawock strategy-lab sources    # 输入、单位、观察期和缺数据时的处理方式
```

[插件配置与权限边界](docs/architecture/strategy-plugins.md) · [编写自己的插件](docs/architecture/strategy-plugins.md#writing-a-plugin-outside-this-repository)。

## 任何 harness，同一套会积累的决策契约

假设你今天用 Claude Code，下个月换成 Codex。你不用从头再来，因为 clawock 从来就不在聊天窗口里。它是一个 skill（`investment-decision`）、一个命令行工具，加上工作区里的几个文件。只要 Agent 能读文件、写文件、跑命令，就能接着用：**Claude Code / Codex / OpenClaw / DeepSeek Harness / 你自己的脚本**。

属于 Agent 的东西还是它的：模型、对话、记忆、研究工具、你的凭证和权限。clawock 从不启动模型。它只在你的 Agent 周围做四件事：把输入固定下来，检查输出，过后给结果打分，把记录留住。

接入自己的 Agent 时，你会用到 `request.json`、`decision.json`、`outcome.json` 和 `evaluation.json`。作者的每日实盘另外写入 `plan.json` 和 `decisions.jsonl`。

| 文件 | 谁写的 | 里面是什么 |
|---|---|---|
| `request.json` | clawock，在你运行 `clawock run prepare` 时 | 这次判断用的材料，每份文档都带指纹，事后换不掉 |
| `decision.json` | 你的 Agent | 它的回答：看多的理由、看空的理由、动作，以及什么情况说明它错了 |
| `plan.json` | 作者的实盘，每天早上 | 同样的回答，但覆盖整个组合，每只持仓一条 |
| `decisions.jsonl` | 作者的实盘 | 公开账本：一次判断一行，代码结算后把结果补在这一行上 |
| `outcome.json` | 你，等观察期过了之后 | 你看到的价格，以及价格是从哪里来的 |
| `evaluation.json` | clawock，在你运行 `clawock workflow evaluate` 时 | 方向对不对。不是赚了多少钱 |

**写下一份计划前，Agent 可以回看以前怎么判断、结果怎样。** 模型本身没有变。文件保存证据、实际动作和结果；积累足够的评估记录后，作者的配置还会核对以前给出的信心有多可靠。换 Agent 时保留同一个工作区，就能继续使用这些历史。新工作区没有你的决策历史，需要逐次记录判断、等观察期结束后评估，才能积累起来。

<p align="center"><img src="site/assets/product-architecture.svg" width="1016" alt="clawock 产品架构 —— 外部运行时拥有模型、对话、记忆与工具;包提供可迁移工作流、认证上下文、确定性对账、评估和有边界改进"></p>

[通用调用与反馈协议](docs/architecture/runtime-protocol.md#evaluate-and-improve-without-owning-the-agent) · [工作流的改进边界](docs/architecture/harness.md#ownership).

## 信息进来：先有来源，再有观点

2026-10-08，08:03。早上的任务刚启动，还没有任何模型开始跑。Python 已经从腾讯取回了金风的日线，找过公司公告，也向 Google 新闻要了它的标题。回来四条。两条和金风毫无关系。另外两条是上一个收盘之前发的，于是被标成旧闻。一手财务披露没有取到。

简报在 `02208` 下面照实写了两行。一行说，一手财务披露「未取到」。另一行说：「这只票今天没有可用消息证据，所以它今天的判断完全来自价格与相对强弱。」

这一节的标题说的就是这条规矩：**先把来源收齐、标清楚，然后才轮到观点。** 落到实处是三个做法：

- **每个来源都有后备。** 行情先走腾讯或 Nasdaq，一家取不到就换下一家。公告来自 SEC 和港交所，资金流来自东财，另有中英文新闻、宏观数据和情绪。然后 Python 把你的账本、汇率和风险数字核对一遍。
- **旧闻不会被当成新消息。** 上一个收盘之前发布的内容，都标成旧闻。
- **没取到就写「未取到」，不写「没有消息」。** 港股的基础覆盖是齐的，但**研究广度落后美股**。

**你的 Agent 拿到的是一包文件。** 在作者的实盘上，`preflight` 写出这次判断必需的文件，外加 Agent 想多看时可以再打开的参考文件。金风那次判断到现在还带着它所用那包材料的编号 `c3f65a7beaebb24e`，谁都能查到它背后是哪一批资料。在你自己的 harness 里，`clawock run prepare` 写出 `request.json`：同样的一包材料，每份文档和整包各有一个 SHA-256 指纹，并记下它对应的工作流版本。

**指纹证明的是「用了哪些材料」，不证明新闻是真的。** 每条引用都带来源，以及发布时间或观察时间。数据源的密码和模型的 API key 留在你自己的运行时里，不进公开仓库。在你自己的 harness 里，Agent 还可以用它自己的研究工具补充证据，只要查得到出处。作者的定时任务只读 Python 装配好的文件。

**实盘完整信息流与投递路径**

<p align="center"><img src="site/assets/information-flow.svg" width="1016" alt="clawock 数据流 —— 8 个信息层经有序的多源兜底抓取;Python 对账并计算风险;盘前简报、时段报告与盘中巡检各自跑 preflight,只组装本次能用的块;模型只读这些文件、从不自己抓数据;Python postflight 校验后发布到 master、仪表盘轮询的 data-plane 分支,并投递微信与 Telegram;不调用 LLM 的 crontab watchdog 兜底送达"></p>

[信息层与来源目录](docs/how-the-desk-works.zh.md#信息层) · [认证协议](docs/architecture/runtime-protocol.md).

## 决策出来：多空同读一份证据

那天早上的问题很简单：金风现在该不该加仓？Agent 不能凭感觉回答。它必须先写看多的理由，再写最有力的反方理由，然后才能给出动作、触发价、信心数字，以及什么情况下它认错。多空两边读的是同一包文件。

作者的 08:03 简报设定：站上 8.97 才加仓，五个交易日内有效，失效价为 8.923。盘中卡片用最新行情核对触发条件。金风当天最高到 8.71，因此当天没有触发加仓。已有持仓的「继续持有」判断，仍按下面的口径单独计分。

**你拿到的是一份计划和一张回执。** 作者的实盘每天留下简报和 `plan.json`。在你自己的 harness 里，Agent 写出 `decision.json`，你运行 `clawock run publish`。这时 Python 检查四件事：每个论断都指向那包材料里的某份文档；有反方理由；写明了什么情况算判断错了；订单和汇率的算术对得上。四件都过，你拿到一张和那包材料绑定的回执。缺了反方理由，就拒绝发布。在作者的实盘上，对话里得出的结论用 `clawock record --source <harness>` 记进账本。不管走哪条路，下不下单由你决定。

<p align="center"><img src="site/assets/decision-card-example.png" width="640" alt="一张 clawock 决策回执:标的、各自引用证据的看多与看空理由、论点、失效条件、置信度与动作,以及已发布的 run id 和固定的证书"></p>

<sub>示例输出，不是真实结算。</sub>

**实盘完整多空辩论**

<p align="center"><img src="site/assets/debate-flow.svg" width="1016" alt="clawock 的多 Agent 辩论 —— 一份证据包喂给四种分析师视角;两名研究员建立多空对立论点并记录分歧点;三种风险声音与一位裁判点名策略框架,收敛成 plan.json,进入下一场的打分环"></p>

在作者的实盘上，这场辩论由几个角色分头完成：四位分析师，一多一空两位研究员，三位风险官，还有一位裁判；裁判要写明每条结论用的是哪套策略。这套辩论改编自 [TradingAgents](https://github.com/TauricResearch/TradingAgents)。在你自己的 harness 里，你现有的那一个 Agent 也要满足同样两条：读同一份证据，写出反方理由。

## 收盘后：结果回到下一次判断

对 2026-10-08 的金风记录，代码评的是「继续持有」这个判断在下一个交易日对不对。参考价取计划发布后第一个能成交的价格 8.645；下一个交易日收在 8.28，低了 4.22%，所以结果记为 `loss`。这条记录的动作是 `watch`，评估方式是 `passive_stance`，并注明 `fill_assumed: false`，没有假定按 8.97 的触发价买入。这里是持有判断的方向评分，不是一笔新交易的盈亏。

这个分数靠三条规矩才算数，每条背后都有一个真实的例子：

- **每天说同一句话，只算一次。** 从 2026-07-29 到 2026-10-08，简报对金风说了 45 次「持有观察」。它们归成一个结果（`ep-f31982c6d511`），不是 45 个。
- **打不了分的判断也留在账上。** 2026-10-01 的计划给金风设了触发价，但那天港股休市。记录 `dec-143614125e34` 的结果未定（`outcome: unknown`），评估状态是无法评估（`status: not_evaluable`），场次原因单独记录（`session_reason: market_closed`）。
- **你做了什么，和计划说了什么，分开记。** `clawock mark-followed` 给每条判断标上「跟了」或「没跟」，因为账户的成绩是模型的建议加上你自己的选择。

价格只认同一套标准日线，并且按各个市场自己的交易日历来读。

**下一次判断从这份记录开始。** 2026-10-12 的简报在「昨日兑现（2026-10-08 的 plan）」这张表里，又把金风这次判断印了一遍，旁边写着 `loss`。同一份简报里，裁判对金风写的是：不动，十天后有三季报，猜方向不如等公告。模型还会读到它以前给的信心数字到底准不准。这项核对只用更早日期的数据；例子太少时，就少信这个数字一点，或者干脆不给读数。判断错了的那一条，仍然连着它当时依据的证据，所以 Agent 可以回头复核昨天的理由，而不是每天把故事从头讲一遍。

**在自己的 harness 里评估判断时，** 等观察期结束，把价格和来源写入 `outcome.json`，再运行 `clawock workflow evaluate`，生成核对判断方向的 `evaluation.json`。它不计算实际成交的盈亏。

评估结果或被拒绝的发布，可以用来支持修改证据要求的提案。审核者的姓名和决定会留在记录里，通过后才能应用，也可以回滚。这个流程只允许调整所需证据条数、没有一手来源时的信心上限，不能修改策略、买卖规则或 skill 本身。审核和回滚步骤见[反馈协议](docs/architecture/runtime-protocol.md#evaluate-and-improve-without-owning-the-agent)。

<p align="center"><img src="site/assets/feedback-learning.svg" width="1016" alt="收盘之后：模型只提交一次判断，代码按各市场日历用基准日线核对触发，同一论点归为一个案例，结算为赢、输或无法打分并全部发布；实盘里执行、结算、历史与校准绕回下一份简报；换个 harness 时，观察到的结果可以触发有边界的提案，经具名审查接受或拒绝，应用时保留回滚记录"></p>

每条判断都按这套规则结算并公开：赢的、输的、无法评估的都保留，不在事后人为调整结果。

<p align="center"><img src="site/assets/shadow-backtest.png" alt="累计案例胜率对 50% 方向命中基线" width="760"></p>

<sub>累计案例胜率对 50% 方向命中基线:衡量方向对了多少次,不是赚了多少。每周刷新;实时数字在<a href="https://kcnyu.github.io/clawock/#drill">持仓页</a>。</sub>

读这些结果时，请留意四条限制：

- **量的是方向，不是钱。** 图表统计方向判断的命中率，不是收益。模型不能给自己打分，也不代表行情数据和计分定义一定正确。
- **主动建议尚未证明比抛硬币强。** 估计区间仍包含 50% 的信号不会进入决策；杠杆刻度盘的择时能力也无法与随机区分。两项结果都公开在 [Reflect](https://kcnyu.github.io/clawock/#reflect)。
- **影子组合是模拟，不是实盘。** 主要指标不含佣金和买卖价差，旁边另列按预设成本扣减的结果。两者都没有模拟大单对价格的影响。
- **账户成绩包含人的选择。** 由账户所有者决定是否跟随建议，每条判断分别记录已跟随、未跟随或未知。

有账本数据时，你可以复核计算。`clawock scorecard-provenance --check` 从 `memory/decisions.jsonl` 重算公开的主要指标，`clawock audit-resettle` 重新结算账本。
[打分规则如何处理特殊情况](docs/how-the-desk-works.zh.md#战绩怎么打分硬规则) · [测了什么、什么没通过](docs/how-the-desk-works.zh.md#测了什么什么没通过)。

一份提案不只看它赚没赚。2026-10-12，模型提出：MiniMax（`00100`）一个交易日内站上 225 就减 20 股；同时预测，第五个交易日收在 213 下方的概率是 0.55。代码把这份提案（`prop-7c966b4a33172e8c`）连同它当时用的输入、它自己写明的方法和两条异议一起存了下来。之后它被分开读两次：这笔交易赚没赚；0.55 这个概率给得准不准。[方法评估](https://github.com/KCNyu/clawock/blob/master/docs/architecture/decision-architecture.md#method-records-and-evaluation)两样都报，而且得分高的方法不会被自动采用。

**从开放提案，到可核对的方法证据**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/proposal-review.svg" width="1016" alt="一个真实的开放提案，2026-10-12 的 MiniMax，分五步。01：模型提出：一个交易日内反弹站上 225 就减 20 股，并预测第五个交易日收在 213 下方的概率是 0.55。02：代码在三条通道上审查；事实与可行性两条可以拒绝它，但没有拒绝；策略通道只能提出异议，它提了两条：卖出没有已升级事件支持、主动动作没有催化。03：方法记录保留每一种结局：发布、带异议发布、被拒绝、未发布；这一个是带着异议发布的。04：这份记录在两条互相独立的轴上被读：它的盈亏是未触发，因为价格从未站上 225；0.55 这个概率对不对，另外单独计分。05：旧政策、仅观测、政策参考三个分支的对比在开始之前冻结，首批记录在 2026-10-13，本金与成本相同，缺失的计价留作空洞。不自动晋升方法、不定仓位、不下单。"></p>

## 策略可以搜索自己的参数；采纳是一次要 review 的改动

金风的指标里有 RSI，用来衡量近期价格的涨跌强弱。`rsi` 插件的配置是回看 14 个交易日，把低值视为可能反弹。作者的策略实验室在每日简报后运行，测试其他设置。2026-10-12 的搜索使用了有行情历史的 28 只股票，包括金风。

1. **只试事先声明过的设置。** 插件配置提前列出六种回看长度和两种读法，十二种组合全部计数，不能把碰巧好看的结果说成唯一试过的一组。
2. **一道闸来判其中最好的那组。** 它要求：有足够多没被拿来调参的交易日；排序结果胜过随机，并且比现在的设定好出的幅度不是噪声；被过去的数据「凑」出来的可能性够低；行情做过拆股与分红的复权。配置里可以把这道闸调严，但不能调得比代码里的下限更松。
3. **第二意见可以反对。** 另外几组阈值会判同一次运行，比如扣掉交易成本之后再看。它们能拦，但不能放行闸已经拒掉的东西。
4. **结论记下来。** 每次运行都进台账，台账每次被读取时都会按这些规则再核一遍。
5. **然后它得继续管用。** 过闸的设定会被登记，此后只在「选出它时还没发生」的交易日上计分。

<p align="center"><img src="site/assets/strategy-evolution.svg" width="1016" alt="一次真实的参数搜索，2026-10-12 的 RSI，分五步。01：rsi 这一行在文件里的原样：今天的设定和它可以尝试的设定；这十二种画成一张格子，六种回看长度乘两种读法；今天这一行用的是 14 个交易日、读作反弹，搜索挑中的是 28 个交易日、读作强势延续。02：一道闸对其中最好的一个做五项检查，每项都写出量到的值和要求：705 个交易日对至少 60 个，相对随机的区间 0.0171 到 0.1117、相对今天设定的区间 0.0408 到 0.2195，都在零以上，过拟合概率 0.0 对上限 0.5，价格已复权。03：两个第二意见，扣除交易成本之后、以及只看统计，都会放行。04：账本里有两条：全部 28 个标的上是候选，在价格被确认已复权的 16 个标的上被拒绝，因为那个区间 -0.043 到 0.0529 跨过了零。05：从这里起只有之后的交易日算数，目前 60 个里算了 0 个；把这一行从 14 改成 28 的那次改动还没有被提出，在有人 review 之前这一行仍是 14 个交易日。"></p>

2026-10-12，RSI 的答案是：回看 28 个交易日、读成「强者恒强」，对这些名字的排序会更好。闸放行了它，它被登记。**只用行情源确认已复权的 16 个名字（金风在内）重跑同一搜索，结论是拒绝。** 这个结果靠的是另外 12 个名字，而实验室对它们只有一个依据：单一行情源的记录里没有拆股或分红，没有第二个来源可以对照。现在每次运行都带着这次重跑，过闸的设定自己会说明它经不经得起。

**这次搜索没有改变金风的 RSI 设置。** 下一份简报仍用 14 个交易日和反弹读法。采纳新设置需要审核配置改动；实验室只有在候选设置经受至少 60 个后续交易日的检验、并通过目前未过的检查后，才能提出修改。截至 2026-10-12 这次运行，还没有后续交易日计分，也没有修改提案。

```bash
clawock strategy-lab evolution rsi   # 每次运行、变了什么、每条登记及其之后的表现
clawock strategy-lab row-edits       # 待审核的配置修改提案
clawock strategy-lab verify          # 拿台账对照实验室的边界
```

[一次搜索能得出什么结论、第二意见与实验室的边界](docs/architecture/strategy-plugins.md#boundaries)。

## 模型不被允许做的事

模型负责写观点。算术不归它，给自己打分也不归它；这两样都在 Python 里，有单元测试钉着。放到金风那个早上，就是模型做不了下面这些事：

- **自己挑参考价。** 8.645 是代码里一条规则定的：计划发布之后第一个能成交的价格。
- **给自己的判断打分。** `loss` 是结算代码照着日线写下的。写计划的那个模型碰不到这个字段。
- **没有反方理由就发布。** 缺了反方证据的判断会被拒收，[五分钟跑起来](#五分钟跑起来)里有这个例子。
- **把港币和美元直接相加。** 金风以港币计价。两种货币并排显示，带上汇率和取汇率的时间，不会被直接加在一起。
- **决定风控线有没有被越过。** 每份简报都由代码检查这些线。那天早上它查出四条仓位线、两条杠杆止损被越过，简报一开头写的就是这件事。每次越线都留有带日期的记录，写明当时怎么处置：减仓，或者继续持有并写下理由。任何一条都不会自己去卖出。

这些风控线、越线之后怎么处置、对证据的要求，都画在页首全景图里「Code holds the boundary」那一格。

[全部 12 条,代码具体做什么](docs/how-the-desk-works.zh.md#代码强制执行的规矩)。

## Harness 界面与后台工作

**DeepSeek Harness 的实盘视图与后台队列**

**交代任务，离开聊天，回来收结果。** 你在 dsh 网页端的聊天里交代一件仓库改动，并写明要怎么交付。后台的一个 Agent（Claude Code、Codex 或 OpenCode）接手，你关掉页面它也继续干。等你回来，面板上能看到它做到了哪一步。

这就是 `clawock-dsh` 给 dsh 加的东西：投资决策 skill、Decision Mind 标签页和 provider 面板。后台队列需要主机上装有 clawock 的 **agent-dispatch** runner。runner 负责让每个任务独立跑完，插件负责让你看得见、改得了方向。

<p align="center"><img src="site/assets/harnesses.svg" width="1016" alt="你的 dsh 后台团队:在聊天中委派仓库任务,agent-dispatch 为 Claude Code、Codex 或 OpenCode 启动独立 systemd 任务;真实插件截图显示额度和队列,可以调整排队任务与预算;agent 按任务要求完成 PR、必需 CI、squash-merge 和本机刷新;runner 尽力经微信和 Telegram 回传报告,送达回执与任务结果分开显示"></p>

- **看清正在发生什么。** 订阅用量与重置时刻、provider 余额、各 agent 的真实队列、模型、用时和按 API 标价估算的费用,都在同一块面板。
- **任务在跑,也能改方向。** 把排队任务往前移,在允许时改下一次尝试的模型,调整截止时间与重试预算,取消任务或续跑未完成的会话。
- **结果留得住。** 任务完成但消息发送失败仍然看得见;没收到消息不等于工作消失了。

作者的主机用同一条队列维护自己的代码（页首全景图里「The desk fixes itself the same way」那一格）。巡检轮次核查已经发布出去的东西。提报闸只为拿得出证据的发现开 issue。后台 Agent 带着修复走完 PR 和必需的 CI。被当作噪音关掉的 issue，会让同类发现下次的分量变轻。

**完整队列截图** —— 真实主机上的插件

<br>

<p align="center"><img src="site/assets/dsh-dispatch-queue.png" width="400" alt="真实主机上的完整 provider 面板:Claude 和 Codex 额度窗口及各自队列,DeepSeek 与 MiniMax 余额,OpenCode 免费池,带通知回执的最近结束任务,带可读提报数量、严重级别及 issue 链接的巡检轮次,以及 ops 版本页脚"></p>

[队列能力与配置](examples/dsh/packages/clawock-dsh/README.md#dispatch-queue) · [runner 与 ops 契约](docs/architecture/task-queue.md)。

**单个任务的历史** — 追加指令与进展时间线

<br>

<p align="center"><img src="site/assets/dsh-task-detail.png" width="380" alt="手机布局下的完整真实 dsh 任务详情:已结束的仓库任务,带编号与投递状态的追加指令,以及按时间排列的派发、等待执行锁、执行尝试、指令投递、续跑和通知回执"></p>

问一句「0700.HK 能不能加点仓？」，投资 skill 会带着 Agent 走一遍上面那几步：收集证据，多空各写一遍，再写出带触发价和认错条件的决定。**Decision Mind** 是用来回头看的：点开一笔真实成交，顺着**计划 → 执行 → T+1 → 盈亏**看下去，也就是计划当时怎么说、你实际怎么做、一个交易日后价格在哪、最后是赚是亏。背后没有计划的成交会明说，还没判定的也会明说。USD 与 HKD 分开，下单仍由你来。

<p align="center"><img src="site/assets/dsh-decision-mind.png" width="820" alt="真实 dsh 网页端里的 Decision Mind:成交按日期分组,旁边显示配对计划与 T+1 判定;展开轨迹能看到当时计划、实际执行和结果"></p>

```bash
python -m pip install clawock
dsh plugin --profile web add clawock-dsh
mkdir -p ~/.dsh/skills
cp -r ~/.dsh/profiles/web/node_modules/clawock-dsh/skills/investment-decision ~/.dsh/skills/
```

重启 web profile 后加载。后台队列控制还需要主机上的 runner;没装时面板仍显示 provider 额度与余额。[npm 包](https://www.npmjs.com/package/clawock-dsh) · [安装与队列配置](examples/dsh/packages/clawock-dsh/README.md)。

## 引擎盖下面

上面说的这一切，在作者的真实账户上每天是这样跑的：

<p align="center"><img src="site/assets/architecture.svg" width="1016" alt="KCNyu live desk 架构 —— Python 构建对账后的市场上下文,OpenClaw Agent 辩论交易,clawock 契约把关决策,公开战绩闭环"></p>

<p align="center"><img src="site/assets/decision-pipeline.svg" width="1016" alt="clawock 的一个交易日，从头到尾 —— Python 按顺序的兜底链抓行情（港股腾讯 + 东财，再 stooq，再 yfinance；美股 Nasdaq 打头的七路链；美元兑港元 Frankfurter、exchangerate.host、Yahoo），以及 SEC 与港交所公告、东财资金流、中英文新闻、Reddit 与影响者情绪、宏观与催化剂日历；对账后计算组合风险、分腿集中度、杠杆 regime 刻度盘、量化因子、横截面排名与同业残差，并过回测闸；风险上限、入场闸、盈利质量、论点漂移和新闻证据图都是代码闸；preflight 给 agent 一份上下文包，四位分析师、必须有分歧的多空研究员、三位风险官和一位裁判写出 plan.json；Python postflight 校验并记入 memory/decisions.jsonl，渲染简报卡片，发微信与 Telegram，发布仪表盘；随后由代码用 mark-followed 记录实际执行、按标准日线逐个 episode 结算、校准置信度、用影子组合对比买入持有并发布战绩，第二天的简报再读这份记录;dsh 的 Decision Mind 展示真实成交、当时计划与 T+1 判定供追问,下单仍由人来"></p>

作者的盘前计划在 **08:03 HKT** 发出，没有人守着，定时由 OpenClaw 来跑。每个任务都是三步：`clawock … preflight` 备好文件，模型写，`clawock … postflight` 检查并发布它写的东西：

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/openclaw-cron.png" alt="投研台主机上 OpenClaw 的真实 cron 列表:九个 clawock 任务(盘前简报、港美股场次报告、盘中盯盘),各自的 cron 表达式、所跑的 clawock preflight → postflight 生命周期、上次状态 ok 与耗时" width="820"></p>

<sub>由 <code>site/tools/shoot_openclaw_cron.js</code> 从主机真实的 <code>openclaw cron list --json</code> 渲染;任务 id、投递目标与 prompt 不出图。完整时刻表见<a href="docs/operations/cron-schedules.md">生成的排程表</a>。</sub>

[投研台怎么运转](docs/how-the-desk-works.zh.md)有信息层、运行上下文、结算细则与代码闸的完整说明。

## 五分钟跑起来

选你正在用的 Agent,点 logo 打开对应 harness 的可运行示例:

<div align="center">
<table>
<tr>
<td align="center" valign="top" width="120"><a href="examples/claude-code/CLAUDE.md"><img src="site/assets/harness/claude-code.svg" width="56" height="56" alt="Claude Code"><br><b>Claude Code</b></a></td>
<td align="center" valign="top" width="120"><a href="examples/codex/AGENTS.md"><img src="site/assets/harness/codex.svg" width="56" height="56" alt="Codex"><br><b>Codex</b></a></td>
<td align="center" valign="top" width="120"><a href="examples/openclaw/SKILL.md"><img src="site/assets/harness/openclaw.svg" width="56" height="56" alt="OpenClaw"><br><b>OpenClaw</b></a></td>
<td align="center" valign="top" width="120"><a href="examples/dsh/README.md"><img src="site/assets/harness/deepseek-harness.svg" width="56" height="56" alt="DeepSeek Harness"><br><b>DeepSeek Harness</b></a></td>
<td align="center" valign="top" width="120"><a href="examples/cli/run.sh"><img src="site/assets/harness/any-cli.svg" width="56" height="56" alt="Any CLI"><br><b>自己的 / 纯 CLI</b></a></td>
</tr>
</table>
</div>

**最省事的办法:** 把本仓库地址丢给你的 Agent,让它 `python -m pip install clawock` 后跑 `bash examples/cli/minimal-run/run.sh`。不需要模型,也不需要任何 API 密钥,看到 `isolated run published <run_id>` 就是第一张被 Python 校验过的决策回执。

**手动跑**(Python ≥ 3.11),从空目录到一条已发布决策:

```bash
pip install clawock
clawock workflow install investment-decision --workspace ./my-book
clawock init ./my-book --workflow investment-decision
cd my-book && mkdir -p .clawock/work
clawock run prepare > .clawock/work/request.json
# 你的 Agent 读取请求,写出 decision.json
clawock run publish --request .clawock/work/request.json --artifact decision.json=decision.json
```

模型调用留在你自己的运行时里,费用走你自己的 API key;clawock 本身免费开源。[这一段](examples/cli/workflow-run/run.sh)每个 PR 都在干净虚拟环境里只装 wheel 原样跑一遍。

把 `decision.json` 里的反方证据删掉,`publish` 直接拒收(退出码 1):

```json
{
  "status": "rejected",
  "validation_issues": [
    {"code": "insufficient_opposing_evidence", "message": "requires at least 1 opposing evidence item(s)"},
    {"code": "unsupported_bear_case", "message": "bear_case must cite opposing evidence"},
    ...
  ]
}
```

下图是 [`examples/claude-code`](examples/claude-code/CLAUDE.md) 指令在 Claude Code 里的一次真实运行:

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/claude-code-terminal.png" alt="Claude Code 跑通 investment-decision 全流程:clawock init、clawock run prepare、Claude 写 decision.json、clawock run publish 返回 status: published" width="820"></p>

## 接着看

- [**实时仪表盘**](https://kcnyu.github.io/clawock/) —— 持仓、风控与代码结算的战绩。
- [**每日简报**](https://kcnyu.github.io/clawock/briefs.html) —— 已发布的早读。
- [**决策地图**](https://kcnyu.github.io/clawock/#reflect) —— 每条决策旁边并列当时的信号快照([阅读说明](docs/decision-map.md))。
- [**各 harness 示例**](examples/README.md) —— 同一条决策,五种 harness,外加 npm 上的 dsh 插件。
- [**投研台怎么运转**](docs/how-the-desk-works.zh.md) —— 信息层、每种运行读什么、决策闸、打分规则与 12 条代码规矩。
- [**影响者雷达**](docs/influencer-radar.md) —— 八个公开来源每个交易日扫两次并关联到持仓;落空也照实记空。
- [**命令参考**](docs/reference/commands.md) · [**术语表**](docs/glossary.md) · [**全部项目文档**](docs/README.md) · [**参与开发**](AGENTS.md#code-changes)

### 研究入口

| 问题 | 入口 | 复用范围 |
|---|---|---|
| 分析一家美股公司 | [`us-stock-analysis`](skills/us-stock-analysis/SKILL.md) | 可随 clawock 工作区复用 |
| 分析一家港股公司 | [`hk-stock-analysis`](skills/hk-stock-analysis/SKILL.md) | 可随 clawock 工作区复用 |
| 检查当前组合 | [`portfolio-risk-review`](skills/portfolio-risk-review/SKILL.md) / [`portfolio-swarm-review`](skills/portfolio-swarm-review/SKILL.md) | 依赖已配置的真实组合 |
| 压测一条供应链论点 | [`serenity-skill`](skills/serenity-skill/SKILL.md) | 可作为手动研究框架复用 |
| 复盘一个已披露的报告期 | [`earnings-review`](skills/earnings-review/SKILL.md) | 可复用,产物落 `memory/earnings/` |
| 判断一个新标的值不值得做深度研究 | [`entry-gate`](skills/entry-gate/SKILL.md) | 可复用,产物落 `memory/entry-gates/` |

它们依赖 clawock 的脚本、数据契约与记忆文件,不是独立的一键产品。

## 范围、免责与许可

**为什么要开源、图什么:** 这套系统本来就在跑——这是作者自己的真实账户,亏盈都是自己的钱。开源是把账本和流程摊开,不收费、无付费版、无荐股群;你装不装、跟不跟,和作者的收入没有任何关系。

本仓库包含**真实交易持仓**。它是一个人的记录，也是一个你可以带走的工作区。它**不是投资建议、不是推荐、也不是跟单系统**。没有哪条结果是人工挑出来的：结算规则和每次方法变更都在代码里留有版本。那些叫人「动手」的建议至今没有证明比抛硬币强，你读到时每个数字都可能已经过时。

原创代码 [MIT](LICENSE);改编第三方代码保留原许可与署名,见 [NOTICE](NOTICE) 与 [`THIRD_PARTY_LICENSES/`](THIRD_PARTY_LICENSES/)。行情、新闻、社交内容与 API 访问**不**被 MIT 重新授权,见[第三方数据与服务](docs/legal/third-party-data.md)。

用 [Claude Code](https://claude.com/claude-code)、[openclaw](https://openclaw.com) cron 守护进程、Jekyll + GitHub Pages 与 Python 构建。

<div align="center">
<br>

**[实时仪表盘](https://kcnyu.github.io/clawock/)** &nbsp;·&nbsp; **[每日简报](https://kcnyu.github.io/clawock/briefs.html)** &nbsp;·&nbsp; **[English](README.md)**

<sub>由 <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> 与 Rick 构建维护 · 2026</sub>

</div>
