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

你手里有港股或美股持仓，也已经在用 Claude Code、Codex、OpenClaw 这样的 AI Agent。clawock 给这个 Agent 排了一套围着你的持仓转的日常：每天早上，它读 Python 夜里抓好的资料，把每只持仓的看多和看空理由都写出来，再交给你一份计划：做什么，到什么价位才做，跌到什么价位这个想法作废。**下单的是你。** 收盘后，由代码判这份计划是对是错；第二天早上写新计划时，这个结果就摆在它面前。

<p align="center"><img src="site/assets/rsi-loop.svg" width="1016" alt="clawock 全景：八个信息层经兜底路径进入；Python 对账并认证出一份上下文；Claude Code、Codex、OpenClaw、DeepSeek Harness 或你自己的 CLI 在同一份证据上写多空两方；代码复核集中度并执行配置中的风控边界、记下越线之后的处置并执行证据要求；计划送到你手里，下单由你；代码把每条判断结算为赢、输或无法打分；记录沿两个回路返回，一个经历史与只用更早日期的校准进入下一次判断，一个经有边界的提案与具名审查进入证据规则；在作者的主机上，巡检轮次、提报闸、后台 agent 与必需 CI 维护实盘自身的代码，在 DeepSeek Harness 里看得见"></p>

**这个循环，就是这里说的 RSI（Recursive Self-Improvement，递归自我改进）。** 每次判断都会留下它用过的证据和它得到的结果，下一次判断两样都读。**它不承诺收益。** 到目前为止，那些叫作者「动手」的建议，还没有证明自己比抛硬币强。你拿到的是一份越积越厚、可以逐行核对的记录。

这一页从头到尾跟着一次真实的判断走：2026-10-08 早上的金风科技（`02208`，港股）。计划写的是「观察，站上 8.97 才动手」。到下一个交易日收盘，股价又低了 4.22%，公开账本在它旁边记着 `loss`。下面几节会一再回到那个早上。

那份计划里的每个数字，都是[一个插件算出来的，一个插件对应一行配置](#能算的都是插件结果能做什么不是)。策略可以[自己去找更好的设定](#策略可以搜索自己的参数采纳是一次要-review-的改动)，但它最多只能交出一份提案，由人来 review。想先跑起来？[五分钟跑起来](#五分钟跑起来)。

## 能算的都是插件；结果能做什么不是

先看金风这次判断。作者的账户里有 400 股金风科技（`02208`，港股），平均成本 14.084。下面是 2026-10-08 早上发生在这只股票上的全部事情。先交代一个词：clawock 算出来的每个数字都出自一个插件，每个插件是 `config/strategy-plugins.json` 里的一行。这一页就把这样的一行叫作**行**。

1. **一行插件算出它的数字。** `factors` 这一行读了金风的日线，给出一行结论：趋势关闭，股价在 200 日均线下方 31.8%。一行插件只做这件事：把输入变成一个读数。
2. **模型就这个读数写出多空两方。** 多方：同业里只有它给出了一个可以执行的确认价，而组合里几乎没有与恒生科技和 AI 无关的仓位。空方：趋势关闭、均线下方 31.8%，组合里已经触发 4 条风控，这是拿最弱的仓位去换最弱的证据。裁决：先观察，在价格到之前把触发价钉在纸上。
3. **计划具体到可以被证明是错的。** 观察；五个交易日内站上 8.97 才动手；跌到 8.923 这个想法作废。信心 0.34。
4. **结算由代码完成。** 不是模型，也不是那行插件。参考价 8.645，是计划发布之后第一个能成交的价格。到下一个交易日收盘，它又低了 4.22%。结果：`loss`。
5. **这次亏损回到了记录里。** 它是公开账本上的 `dec-6d9e8bdc8817`，下一份简报读到的历史战绩把它算了进去。

<p align="center"><img src="site/assets/strategy-plugins.svg" width="1016" alt="一次真实判断，2026-10-08 的金风，分五步。01：factors 这一行画成插在插座里的一个模块，旁边留着一个空插座给你自己的行；它算出一条读数：趋势关闭，价格在 200 日均线下方 31.8%。02：模型就这条读数写出多方与空方。03：落在纸上的计划：观察，五个交易日内站上 8.97 才动手，8.923 作废，信心 0.34，存在分歧。一条线标着「从这里往下不是行」。04：金风截至 2026-10-09 的八根日线，动手价与作废价横贯其上；代码取 2026-10-08 的开盘价 8.645 为参考价，按下一个收盘 8.28 计价，低 4.22%，判为亏损。05：账本里存下的那一条，dec-6d9e8bdc8817，结果 loss。没有任何行可以给自己的判断打分、挑一个更有利的参考价、把亏损改成别的结果，或者让它不上账。"></p>

**能换的是第 1 步。** 把 `factors` 这一行换成你自己的，金风那一行结论就会按另一种方式算出来：换一条均线、换一个窗口、换一个数据源。第 4、5 步不会动，因为它们不是插件行。没有任何一行能给自己的判断打分、挑一个更好看的参考价、把那个 `loss` 改成别的，或者不让它进账本。两套不同的策略之所以能放在同一份记录上比较，原因就在这里：判这次判断的代码，也是判它们的代码。

每一行占一个插座，而装进你 harness 的东西仍然很少：一个 skill、一个 CLI 和一份 JSON 契约。模型、对话和工具仍归你的 Agent。

**每一行都要说清自己量的是什么。** 读数会进入决策的行，必须先声明输入、每个输出的单位与窗口、以及量不出来时这个字段是什么，才会被挂载。任何一行都不得把昨天的读数当成今天的交回来。

| 行 | 量什么 | 量不出来时 |
|---|---|---|
| `factors` | 每个标的的趋势、动量、RSI、波动与离场线，由日线算出。金风那句「均线下方 31.8%」就出自这里 | 该字段为空；日线不足 30 根则整行没有 |
| `bar-signals` | 每个交易日里，一只股票的交易成本有多高、接下来可能动多大 | 留空，绝不写 0：「估不出来」不等于「交易成本低」 |
| `sentiment` | 七天内的 Reddit 提及数，以及点名公众人物的言论 | 整段省略，并写明扫描是缺失、过期还是读不了 |
| `morning-scans` | 宏观快照与中文资讯，并且是每个定时扫描文件的唯一读取处 | 同上：省略，并给出原因 |
| `strategy-scores` | 每个标的在每个研究策略当前设定下排第几；仅作参考 | 写明未取到及原因 |

**坏掉的行自己坏。** 一行加载失败，需要它的那些运行会停下并点名这一行，其余照常。

**你自己的行。** 行指向一个已安装的 Python 模块，所以它可以是你的：一个 `apply(ctx, config)` 函数、一份「我读什么」的声明、一行配置。这样它就有了一个插座。但第 4、5 步它依然说了不算。行就是普通的 Python 代码，用你自己的权限运行，不是安全沙箱，所以只装你信得过的模块。

**整套系统可以热插拔，和 dsh 是同一种设计。** 一个文件里二十行：十三行是简报、报告和盘中检查计算时用的，七行是策略实验室做研究时挂载的。其余的行在跑的时候拔掉一行，只有声明过需要它的行会停下来等；插回去，它们自己重新启动。改一行的设置，这一行就在新设置下重启。这就是 [dsh](examples/dsh/README.md) 插件所基于的那套设计，用 Python 重写了一遍。

<p align="center"><img src="site/assets/plugin-system.svg" width="1016" alt="整套插件系统，分七部分。01：无论哪个 Agent 在跑这张台子（Claude Code、Codex、OpenClaw、dsh 或任意 CLI），执行的都是 brief、report、intraday 和 strategy-lab 这几条命令。02：一个文件 strategy-plugins.json 列出全部的行：十三个现网行、七个研究行，每行是一个 id、一个模块和它的设置。03：宿主把每一行挂进一个插座；二十行全部按名字画出，研究行 bars 被从插座里拔了出来，另有一个空插座留给你自己的行。04：拔出 bars 会撤销它唯一的一次注册，声明过需要 bars 的 optimizer 行进入等待，其余五行从未停过；插回去，optimizer 自己重新启动。05：改一个设置，把 daily-bars 行的 adjustment 从 qfq 改成 raw，这一行停下并在新设置下重新启动。06：dsh 所基于的五个原语与它们在这里的名字并排：文件里的一行、fiber、provide 与 inject、effect、update。07：没有插座的东西：结算、账本和风控上限。"></p>

```bash
clawock strategy-lab list       # 每一行、它提供什么、在等什么
clawock strategy-lab sources    # 每一行的输入、单位、窗口与缺数据时的行为
```

[策略插件：内核、行、声明、事件与边界](docs/architecture/strategy-plugins.md) · [在仓库之外写一个插件](docs/architecture/strategy-plugins.md#writing-a-plugin-outside-this-repository)。

## 任何 harness，同一套会积累的决策契约

假设你今天用 Claude Code，下个月换成 Codex。你不用从头再来，因为 clawock 从来就不在聊天窗口里。它是一个 skill（`investment-decision`）、一个命令行工具，加上工作区里的几个文件。只要 Agent 能读文件、写文件、跑命令，就能接着用：**Claude Code / Codex / OpenClaw / DeepSeek Harness / 你自己的脚本**。

属于 Agent 的东西还是它的：模型、对话、记忆、研究工具、你的凭证和权限。clawock 从不启动模型。它只在你的 Agent 周围做四件事：把输入固定下来，检查输出，过后给结果打分，把记录留住。

就是下面这几个文件。第一、二、五、六个，你在自己的 harness 里会碰到。另外两个是作者每天的实盘写出来的。

| 文件 | 谁写的 | 里面是什么 |
|---|---|---|
| `request.json` | clawock，在你运行 `clawock run prepare` 时 | 这次判断用的材料，每份文档都带指纹，事后换不掉 |
| `decision.json` | 你的 Agent | 它的回答：看多的理由、看空的理由、动作，以及什么情况说明它错了 |
| `plan.json` | 作者的实盘，每天早上 | 同样的回答，但覆盖整个组合，每只持仓一条 |
| `decisions.jsonl` | 作者的实盘 | 公开账本：一次判断一行，代码结算后把结果补在这一行上 |
| `outcome.json` | 你，等观察期过了之后 | 你看到的价格，以及价格是从哪里来的 |
| `evaluation.json` | clawock，在你运行 `clawock workflow evaluate` 时 | 方向对不对。不是赚了多少钱 |

**「越用越聪明」，指的是这堆文件越来越厚。** 模型没有变。变的是下一次判断读得到的东西：以前每次判断背后的证据，你实际做了什么，每次结果如何，以前给出的信心数字有多可信。换 Agent 的时候，把新的 Agent 指向同一个工作区，它就从同一批文件接着干。全新的工作区是空的：它不会自带作者的数据源、定时任务和历史，这些要你自己接。

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

送到你手里的，是 08:03 简报里的一行：「09:30 HKT 开盘后：02208 站上 8.97 才动手、五个交易日内有效，跌回 8.923 立刻认输。」盘中，卡片会拿最新行情去对照早上这个触发价。金风当天最高到 8.71，没有碰到 8.97，所以你什么都不用做。

**你拿到的是一份计划和一张回执。** 作者的实盘每天留下简报和 `plan.json`。在你自己的 harness 里，Agent 写出 `decision.json`，你运行 `clawock run publish`。这时 Python 检查四件事：每个论断都指向那包材料里的某份文档；有反方理由；写明了什么情况算判断错了；订单和汇率的算术对得上。四件都过，你拿到一张和那包材料绑定的回执。缺了反方理由，就拒绝发布。在作者的实盘上，对话里得出的结论用 `clawock record --source <harness>` 记进账本。不管走哪条路，下不下单由你决定。

<p align="center"><img src="site/assets/decision-card-example.png" width="640" alt="一张 clawock 决策回执:标的、各自引用证据的看多与看空理由、论点、失效条件、置信度与动作,以及已发布的 run id 和固定的证书"></p>

<sub>示例输出，不是真实结算。</sub>

**实盘完整多空辩论**

<p align="center"><img src="site/assets/debate-flow.svg" width="1016" alt="clawock 的多 Agent 辩论 —— 一份证据包喂给四种分析师视角;两名研究员建立多空对立论点并记录分歧点;三种风险声音与一位裁判点名策略框架,收敛成 plan.json,进入下一场的打分环"></p>

在作者的实盘上，这场辩论由几个角色分头完成：四位分析师，一多一空两位研究员，三位风险官，还有一位裁判；裁判要写明每条结论用的是哪套策略。这套辩论改编自 [TradingAgents](https://github.com/TauricResearch/TradingAgents)。在你自己的 harness 里，你现有的那一个 Agent 也要满足同样两条：读同一份证据，写出反方理由。

## 收盘后：结果回到下一次判断

收盘不是对话的终点。你用 `mark-followed` 标记跟随 / 未跟随的执行证据，代码按各市场自己的日历和标准日线检查触发与结果；同一论点的重复表态归为同一 episode，没法结算的也留在记录里。

**下一次从这份记录开始。** 实盘下一份简报读决策指标、历史复盘与置信度校准；校准只用更早日期，样本不足时收缩或弃权。失败判断连着原始证据留下来，Agent 可以复核昨天的理由，而不是每天重新讲一遍故事。

**换个 harness 也能继续反馈。** 可迁移工作流用带来源的 `outcome.json` 生成 `evaluation.json`（方向评估，不是已实现盈亏）；评估或拒收回执可触发有边界提案，经具名审查接受后应用，并保留回滚记录。目前只允许调整证据数量与无一手来源时的置信度上限，不能自行改策略、买卖规则或 skill。这是可审查的改进路径，不是自动变得更赚钱。

<p align="center"><img src="site/assets/feedback-learning.svg" width="1016" alt="收盘之后：模型只提交一次判断，代码按各市场日历用基准日线核对触发，同一论点归为一个案例，结算为赢、输或无法打分并全部发布；实盘里执行、结算、历史与校准绕回下一份简报；换个 harness 时，观察到的结果可以触发有边界的提案，经具名审查接受或拒绝，应用时保留回滚记录"></p>

截至 <!-- CW_M:as_of -->2026-10<!-- /CW_M:as_of -->,这个投研台已经公开结算了 **<!-- CW_M:settled -->166<!-- /CW_M:settled --> 条判断**,全部由 Python 机械结算后发布:赢的、输的、没法打分的都在。

| 组 | 方向命中率 | 样本 |
|---|---|---|
| 主动建议(cut / trim / 加仓) | <!-- CW_M:active_pct -->53%<!-- /CW_M:active_pct --> | n=<!-- CW_M:active_n -->58<!-- /CW_M:active_n -->,95% 区间约 <!-- CW_M:active_ci -->40%–66%<!-- /CW_M:active_ci --> |
| 只是躺着 hold | <!-- CW_M:hold_pct -->31%<!-- /CW_M:hold_pct --> | n=<!-- CW_M:hold_n -->108<!-- /CW_M:hold_n --> |
| 高信心主动判断 | <!-- CW_M:hi_pct -->56%<!-- /CW_M:hi_pct --> | n=<!-- CW_M:hi_n -->16<!-- /CW_M:hi_n -->,95% 区间约 <!-- CW_M:hi_ci -->32%–80%<!-- /CW_M:hi_ci --> |

<p align="center"><img src="site/assets/shadow-backtest.png" alt="累计案例胜率对 50% 方向命中基线" width="760"></p>

<sub>累计案例胜率对 50% 方向命中基线:衡量方向对了多少次,不是赚了多少。每周刷新;实时数字在<a href="https://kcnyu.github.io/clawock/#drill">持仓页</a>。</sub>

读这些数字,请带着四条限定:

- **是诊断,不是收益证明。** 方向命中率与盈亏无关;区间包含 50% 时统计上还不能算优势,该是噪声的地方就标成噪声。
- **真实账户另算。** 折美元合并 **<!-- CW_M:return_pct -->−26.91%<!-- /CW_M:return_pct -->**(实盘,已实现 + 浮动;美股、港股分开看见页首的图),对比买入持有仍然落后。
- **影子组合是模拟,不是实盘。** 跟随建议与买入持有在同一时间线上回放,见[持仓页](https://kcnyu.github.io/clawock/#drill)。
- **账户成绩是人机混合的成绩。** 跟不跟由账户所有者决定:<!-- CW_M:rows -->1013<!-- /CW_M:rows --> 条记录里 followed <!-- CW_M:followed -->573<!-- /CW_M:followed --> / not_followed <!-- CW_M:not_followed -->390<!-- /CW_M:not_followed --> / unknown <!-- CW_M:unknown -->50<!-- /CW_M:unknown -->,每条都带执行状态。

杠杆刻度盘的择时能力目前不可与随机区分,[Reflect](https://kcnyu.github.io/clawock/#reflect) 照实写着。战绩可以复算:`clawock audit-resettle` 重新结算整本决策账(默认不写入),`clawock scorecard-provenance --check` 核对公开记分出自账本的哪几行。[原始账本全部公开](https://github.com/KCNyu/clawock/blob/master/memory/decisions.jsonl) · [打分硬规则](docs/how-the-desk-works.zh.md#战绩怎么打分硬规则) · [测了什么、什么没通过](docs/how-the-desk-works.zh.md#测了什么什么没通过)。

方法提案保留冻结输入和版本化预测；[方法评估](https://github.com/KCNyu/clawock/blob/master/docs/architecture/decision-architecture.md#method-records-and-evaluation) 分开收益与命中率，支持前瞻对照，不自动晋升方法。

**从开放提案，到可核对的方法证据**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/proposal-review.svg" width="1016" alt="一个真实的开放提案，2026-10-12 的 MiniMax，分五步。01：模型提出：一个交易日内反弹站上 225 就减 20 股，并预测第五个交易日收在 213 下方的概率是 0.55。02：代码在三条通道上审查；事实与可行性两条可以拒绝它，但没有拒绝；策略通道只能提出异议，它提了两条：卖出没有已升级事件支持、主动动作没有催化。03：方法记录保留每一种结局：发布、带异议发布、被拒绝、未发布；这一个是带着异议发布的。04：这份记录在两条互相独立的轴上被读：它的盈亏是未触发，因为价格从未站上 225；0.55 这个概率对不对，另外单独计分。05：旧政策、仅观测、政策参考三个分支的对比在开始之前冻结，首批记录在 2026-10-13，本金与成本相同，缺失的计价留作空洞。不自动晋升方法、不定仓位、不下单。"></p>

## 策略可以搜索自己的参数；采纳是一次要 review 的改动

还是金风。系统给它算的数字里有一个是 RSI，而算 RSI 的那一行有一个设定：回看 14 个交易日，数值低就读成「要反弹」。这个设定对吗？每天早上简报之后，策略实验室都会问一遍，对象是它有行情的全部 28 个名字，金风是其中之一。

1. **只试事先声明过的。** 那一行提前列出了自己的备选设定：六种回看长度、两种读法，一共十二组。十二组全部计数，所以碰巧好看的那一组没法冒充「只试了这一组」。
2. **一道闸来判其中最好的那组。** 它要求：有足够多没被拿来调参的交易日；排序结果胜过随机，并且比现在的设定好出的幅度不是噪声；被过去的数据「凑」出来的可能性够低；行情做过拆股与分红的复权。配置里可以把这道闸调严，但不能调得比代码里的下限更松。
3. **第二意见可以反对。** 另外几组阈值会判同一次运行，比如扣掉交易成本之后再看。它们能拦，但不能放行闸已经拒掉的东西。
4. **结论记下来。** 每次运行都进台账，台账每次被读取时都会按这些规则再核一遍。
5. **然后它得继续管用。** 过闸的设定会被登记，此后只在「选出它时还没发生」的交易日上计分。

<p align="center"><img src="site/assets/strategy-evolution.svg" width="1016" alt="一次真实的参数搜索，2026-10-12 的 RSI，分五步。01：rsi 这一行在文件里的原样：今天的设定和它可以尝试的设定；这十二种画成一张格子，六种回看长度乘两种读法；今天这一行用的是 14 个交易日、读作反弹，搜索挑中的是 28 个交易日、读作强势延续。02：一道闸对其中最好的一个做五项检查，每项都写出量到的值和要求：705 个交易日对至少 60 个，相对随机的区间 0.0171 到 0.1117、相对今天设定的区间 0.0408 到 0.2195，都在零以上，过拟合概率 0.0 对上限 0.5，价格已复权。03：两个第二意见，扣除交易成本之后、以及只看统计，都会放行。04：账本里有两条：全部 28 个标的上是候选，在价格被确认已复权的 16 个标的上被拒绝，因为那个区间 -0.043 到 0.0529 跨过了零。05：从这里起只有之后的交易日算数，目前 60 个里算了 0 个；把这一行从 14 改成 28 的那次改动还没有被提出，在有人 review 之前这一行仍是 14 个交易日。"></p>

2026-10-12，RSI 的答案是：回看 28 个交易日、读成「强者恒强」，对这些名字的排序会更好。闸放行了它，它被登记。**只用行情源确认已复权的 16 个名字（金风在内）重跑同一搜索，结论是拒绝。** 这个结果靠的是另外 12 个名字，而实验室对它们只有一个依据：单一行情源的记录里没有拆股或分红，没有第二个来源可以对照。现在每次运行都带着这次重跑，过闸的设定自己会说明它经不经得起。

**这给金风带来了什么变化？没有。** 下一份简报里，它的 RSI 仍是按 14 个交易日、读成反弹来算的，因为那一行就是这么写的。改那一行，是要有人 review 的改动。实验室最多只能提出这次改动，而且要等新设定在至少 60 个之后的交易日上站得住、并且过了它现在没过的那项检查。到目前为止，它一个交易日都还没计分，也没有任何提案。

```bash
clawock strategy-lab evolution rsi   # 每次运行、变了什么、每条登记及其之后的表现
clawock strategy-lab row-edits       # 实验室提出的改行提案，供 review
clawock strategy-lab verify          # 拿台账对照实验室的边界
```

[一次搜索能得出什么结论、第二意见与实验室的边界](docs/architecture/strategy-plugins.md#boundaries)。

## 模型不被允许做的事

分数不是模型自己打的,账也不是模型自己记的。可能把记录算坏的算术都在 Python 里,有单元测试钉着。 集中度复核、配置中的风控边界、越线处置与证据要求画在页首全景图的第 04 格。

[全部 12 条,代码具体做什么](docs/how-the-desk-works.zh.md#代码强制执行的规矩)。

## Harness 界面与后台工作

**DeepSeek Harness 的实盘视图与后台队列**

**交代任务、离开聊天、回来收结果。** `clawock-dsh` 把投资决策 skill、Decision Mind 标签页和 provider 面板带进 dsh 网页端。在装了 clawock **agent-dispatch** runner 的主机上,这块面板还让你随时看见并控制 Claude Code、Codex、OpenCode 这支后台团队:你在聊天里委派仓库改动并写明交付要求,runner 让任务独立跑完,插件让你随时看进度、改方向。

<p align="center"><img src="site/assets/harnesses.svg" width="1016" alt="你的 dsh 后台团队:在聊天中委派仓库任务,agent-dispatch 为 Claude Code、Codex 或 OpenCode 启动独立 systemd 任务;真实插件截图显示额度和队列,可以调整排队任务与预算;agent 按任务要求完成 PR、必需 CI、squash-merge 和本机刷新;runner 尽力经微信和 Telegram 回传报告,送达回执与任务结果分开显示"></p>

- **看清正在发生什么。** 订阅用量与重置时刻、provider 余额、各 agent 的真实队列、模型、用时和按 API 标价估算的费用,都在同一块面板。
- **任务在跑,也能改方向。** 把排队任务往前移,在允许时改下一次尝试的模型,调整截止时间与重试预算,取消任务或续跑未完成的会话。
- **结果留得住。** 任务完成但消息发送失败仍然看得见;没收到消息不等于工作消失了。

作者的主机用同一条队列维护自己（页首全景图第 09 格）：巡检轮次核查实盘发布出去的东西，提报闸只为拿得出证据的发现开 issue，后台 agent 带着修复走完 PR 与必需 CI，被当作噪音关掉的 issue 会让同类发现下次降级。

**完整队列截图** —— 真实主机上的插件

<br>

<p align="center"><img src="site/assets/dsh-dispatch-queue.png" width="400" alt="真实主机上的完整 provider 面板:Claude 和 Codex 额度窗口及各自队列,DeepSeek 与 MiniMax 余额,OpenCode 免费池,带通知回执的最近结束任务,带可读提报数量、严重级别及 issue 链接的巡检轮次,以及 ops 版本页脚"></p>

[队列能力与配置](examples/dsh/packages/clawock-dsh/README.md#dispatch-queue) · [runner 与 ops 契约](docs/architecture/task-queue.md)。

**单个任务的历史** — 追加指令与进展时间线

<br>

<p align="center"><img src="site/assets/dsh-task-detail.png" width="380" alt="手机布局下的完整真实 dsh 任务详情:已结束的仓库任务,带编号与投递状态的追加指令,以及按时间排列的派发、等待执行锁、执行尝试、指令投递、续跑和通知回执"></p>

问一句“0700.HK 能不能加点仓?”,投资 skill 会带着 agent 收集证据、做多空辩论、写出有边界的决策。**Decision Mind** 让你点开一笔真实成交,顺着**计划 → 执行 → T+1 → 盈亏**往下看。没有计划、尚未判定都明说,USD 与 HKD 分开,下单仍由你来。

<p align="center"><img src="site/assets/dsh-decision-mind.png" width="820" alt="真实 dsh 网页端里的 Decision Mind:成交按日期分组,旁边显示配对计划与 T+1 判定;展开轨迹能看到当时计划、实际执行和结果"></p>

```bash
python -m pip install clawock
dsh plugin --profile web add clawock-dsh
mkdir -p ~/.dsh/skills
cp -r ~/.dsh/profiles/web/node_modules/clawock-dsh/skills/investment-decision ~/.dsh/skills/
```

重启 web profile 后加载。后台队列控制还需要主机上的 runner;没装时面板仍显示 provider 额度与余额。[npm 包](https://www.npmjs.com/package/clawock-dsh) · [安装与队列配置](examples/dsh/packages/clawock-dsh/README.md)。

## 引擎盖下面

同一套闭环在作者的真实账本上怎么落地：

<p align="center"><img src="site/assets/architecture.svg" width="1016" alt="KCNyu live desk 架构 —— Python 构建对账后的市场上下文,OpenClaw Agent 辩论交易,clawock 契约把关决策,公开战绩闭环"></p>

<p align="center"><img src="site/assets/decision-pipeline.svg" width="1016" alt="clawock 的一个交易日，从头到尾 —— Python 按顺序的兜底链抓行情（港股腾讯 + 东财，再 stooq，再 yfinance；美股 Nasdaq 打头的七路链；美元兑港元 Frankfurter、exchangerate.host、Yahoo），以及 SEC 与港交所公告、东财资金流、中英文新闻、Reddit 与影响者情绪、宏观与催化剂日历；对账后计算组合风险、分腿集中度、杠杆 regime 刻度盘、量化因子、横截面排名与同业残差，并过回测闸；风险上限、入场闸、盈利质量、论点漂移和新闻证据图都是代码闸；preflight 给 agent 一份上下文包，四位分析师、必须有分歧的多空研究员、三位风险官和一位裁判写出 plan.json；Python postflight 校验并记入 memory/decisions.jsonl，渲染简报卡片，发微信与 Telegram，发布仪表盘；随后由代码用 mark-followed 记录实际执行、按标准日线逐个 episode 结算、校准置信度、用影子组合对比买入持有并发布战绩，第二天的简报再读这份记录;dsh 的 Decision Mind 展示真实成交、当时计划与 T+1 判定供追问,下单仍由人来"></p>

作者自己的投研台在 **08:03 HKT** 送出盘前计划，用 OpenClaw 无人值守地跑这一套。每个任务都是 `clawock … preflight` → 模型写 → `clawock … postflight`:

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

本仓库包含**真实交易持仓**,是个人记录与可携带工作区——**不是投资建议、不是推荐、也不是跟单系统**。结算规则与方法学变更都在代码里版本化,任何一条结果都不是人工挑选的;主动建议至今没显出优势,你读到时每个数字都可能已经过时。

原创代码 [MIT](LICENSE);改编第三方代码保留原许可与署名,见 [NOTICE](NOTICE) 与 [`THIRD_PARTY_LICENSES/`](THIRD_PARTY_LICENSES/)。行情、新闻、社交内容与 API 访问**不**被 MIT 重新授权,见[第三方数据与服务](docs/legal/third-party-data.md)。

用 [Claude Code](https://claude.com/claude-code)、[openclaw](https://openclaw.com) cron 守护进程、Jekyll + GitHub Pages 与 Python 构建。

<div align="center">
<br>

**[实时仪表盘](https://kcnyu.github.io/clawock/)** &nbsp;·&nbsp; **[每日简报](https://kcnyu.github.io/clawock/briefs.html)** &nbsp;·&nbsp; **[English](README.md)**

<sub>由 <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> 与 Rick 构建维护 · 2026</sub>

</div>
