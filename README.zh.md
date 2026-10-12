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

clawock 把你已经在用的 AI Agent 接成一套围绕港美股持仓连续工作的投研流程：**信息收集 → 有反方的决策 → 代码结算 → 反馈给下一次判断**。下单仍由你来。

<p align="center"><img src="site/assets/rsi-loop.svg" width="1016" alt="clawock 全景：八个信息层经兜底路径进入；Python 对账并认证出一份上下文；Claude Code、Codex、OpenClaw、DeepSeek Harness 或你自己的 CLI 在同一份证据上写多空两方；代码复核集中度并执行配置中的风控边界、记下越线之后的处置并执行证据要求；计划送到你手里，下单由你；代码把每条判断结算为赢、输或无法打分；记录沿两个回路返回，一个经历史与只用更早日期的校准进入下一次判断，一个经有边界的提案与具名审查进入证据规则；在作者的主机上，巡检轮次、提报闸、后台 agent 与必需 CI 维护实盘自身的代码，在 DeepSeek Harness 里看得见"></p>

**RSI 指递归自我改进（Recursive Self-Improvement）闭环**：每次判断留下证据与结果，下次接着这份记录往前走。**不承诺收益。** 主动建议尚未显出优势；可核验、能积累的判断才是你拿到的东西。

能算的都是[由一行配置挂载的插件](#能算的都是插件结果能做什么不是)。策略可以[搜索自己的参数](#策略可以搜索自己的参数采纳是一次要-review-的改动)，但只能产出提案。想先跑起来？[五分钟跑起来](#五分钟跑起来)。

## 能算的都是插件；结果能做什么不是

装进你 harness 的东西很少：一个 skill、一个 CLI 和一份 JSON 契约。模型、对话和工具仍归你的 Agent。在 clawock 里面，凡是算出一个读数的东西，都是**由一行配置挂载的插件**：因子表、日线估计量、情绪面读取、日线数据源、加仓侧与盘中政策。想换掉它算什么，改一行。

<p align="center"><img src="site/assets/strategy-plugins.svg" width="1016" alt="插件：十二个现网行像钟面上的十二个刻度一样围着一个内核，五个信号源、一个数据源、六个政策，各自向内核提供一个服务；内核给出 provide、inject、effect、event 四个原语。下面三句话：读者按名字向内核取服务，从不直接 import 插件；一行挂载失败只停掉读它的路径，并被点名；结算、闸和台账不是行，所以换掉一行改变不了结果能做什么。"></p>

**边界在哪。** 插件只能发布一个服务，或者声明它要读哪些服务。一行配置能做的只有这些。它不能给判断打分，不能发布决策，也不能给自己发许可：

- 结算是 Python 在规范日线上做的。没有插件、也没有模型能写分数。
- `clawock run publish` 用同一份 schema 和同一个校验器核对每一份决策，不管它是哪个 harness 写的。
- 研究侧插件只能产出提案。提案算不算 candidate 由注册闸判定，两种情况下现网许可都是 false。

所以策略可以换，结果仍然可比：判结果的那段代码不在可换的东西里面。

**信号源要说清自己量的是什么。** 标为信号源的行，必须先声明输入、每个输出的单位与窗口、以及量不出来时这个字段是什么，才会被挂载。任何信号源都不得把旧读数当成今天的交回来。

| 信号源 | 类别 | 量什么 | 量不出来时 |
|---|---|---|---|
| `factors` | 因子 | 每个标的的趋势、动量、RSI、波动与离场线，由日线算出 | 该字段为 null；不足 30 根日线则整行没有 |
| `bar-signals` | 技术面 | 每个交易日的流动性与波动估计量 | null，绝不写 0：算不出不等于流动性好 |
| `sentiment` | 情绪面 | 七天内的 Reddit 提及数与点名人物的言论，读自早间两份扫描 | 读数整段省略，状态写明是缺失、过期还是读不了 |
| `rsi` | 策略 | 一个带方向的分数，由策略实验室排序 | null，该标的当天不参与排序 |
| `strategy-scores` | 策略 | 每个实验室策略按配置行已登记的参数，给各持仓的分数与排名，连同实验室对它的结论；简报把它当参考读 | 读数写明 unavailable 及原因 |

**坏掉的行自己坏。** 一行挂载失败，读它那个服务的运行会停下并点名这一行，其余照常。

**你自己的插件。** 行里的 module 是导入路径，所以插件可以是任何已安装的包：写一个 `apply(ctx, config)`，声明它读什么，加一行。挂载给它的是一个插座，不是权限；同一道闸、同一本台账照样管它。

```bash
clawock strategy-lab list       # 每个已挂载的行、它提供什么、在等什么
clawock strategy-lab sources    # 每个信号源：输入、单位、窗口、缺数据时的行为
```

[策略插件：内核、行、声明、事件与边界](docs/architecture/strategy-plugins.md) · [在仓库之外写一个插件](docs/architecture/strategy-plugins.md#writing-a-plugin-outside-this-repository)。

## 任何 harness，同一套会积累的决策契约

你可以在 **Claude Code / Codex / OpenClaw / DeepSeek Harness / 任意能读写文件并调用 CLI 的运行时**里继续用同一套 `investment-decision` skill 与产物契约。模型、对话、记忆、研究工具、凭证与权限跟着你的 Agent；clawock 负责认证输入、核验输出、评估结果和记录改进，不启动另一个模型。

“越用越聪明”有可查的落点：证据连到决策，决策连到执行与结果，历史进入下一次上下文，置信度由更早样本校准，证据要求的改动留有审查与回滚记录。换 harness 时，保留工作区产物并接回上下文；连续性来自这些文件，不依赖某个聊天窗口。新工作区不会自动拥有作者的实盘数据源、排程和历史，需按能力检查配置。

<p align="center"><img src="site/assets/product-architecture.svg" width="1016" alt="clawock 产品架构 —— 外部运行时拥有模型、对话、记忆与工具;包提供可迁移工作流、认证上下文、确定性对账、评估和有边界改进"></p>

[通用调用与反馈协议](docs/architecture/runtime-protocol.md#evaluate-and-improve-without-owning-the-agent) · [工作流的改进边界](docs/architecture/harness.md#ownership).

## 信息进来：先有来源，再有观点

早上打开简报前，Python 已按兜底链抓好腾讯 / Nasdaq 等行情、SEC / 港交所公告、东财资金流、中英文新闻、宏观与情绪，再对你的账本、汇率和风险做核对。旧闻与实时信息分开标，失败的源点名为“未取到”，不会被写成“没有消息”。港股基础覆盖齐全，**研究广度落后美股**。

**你拿到的是证据包。** 实盘简报的 `preflight` 把本次判断需要的核心包与可按需读取的参考层落盘；Agent 不用从聊天里猜这批数据的来历。迁到自己的 harness 时，`run prepare` 产出 `request.json`，把上下文逐文件及整体的 SHA-256、工作流版本和整包证书固定下来。

**认证固定的是“用了什么”。** 引用包含来源、发布时间或观察时间；哈希核对内容与代次，不能证明新闻是真的。源需要的访问凭证与模型 API key 仍由你的运行时保管，不进公开仓库。可迁移 skill 也允许 Agent 用自己的研究工具补充可追溯证据；实盘定时任务读 Python 已装配的文件。

**实盘完整信息流与投递路径**

<p align="center"><img src="site/assets/information-flow.svg" width="1016" alt="clawock 数据流 —— 8 个信息层经有序的多源兜底抓取;Python 对账并计算风险;盘前简报、时段报告与盘中巡检各自跑 preflight,只组装本次能用的块;模型只读这些文件、从不自己抓数据;Python postflight 校验后发布到 master、仪表盘轮询的 data-plane 分支,并投递微信与 Telegram;不调用 LLM 的 crontab watchdog 兜底送达"></p>

[信息层与来源目录](docs/how-the-desk-works.zh.md#信息层) · [认证协议](docs/architecture/runtime-protocol.md).

## 决策出来：多空同读一份证据

比如你问“今天能不能加仓？”：Agent 先写看多依据，再写能推翻它的反方；最后落到动作、触发条件、置信度和论点失效条件。实盘简报用分析师、多空研究员、风险官与裁判完成这个辩论；可迁移工作流把同样的证据与反方要求带进你当前的 Agent。

**你拿到的是计划与回执。** 实盘每天留下简报和 `plan.json`，盘中卡片把新行情对照早上的触发价。可迁移工作流交出 `decision.json`，Python 校验引用关系、反方、失效条件及订单 / 汇率算术，发布后给出固定代次的回执；缺少反方就拒收。对话里产生的实盘判定用 `clawock record --source <harness>` 落账，下单仍由你决定。

<p align="center"><img src="site/assets/decision-card-example.png" width="640" alt="一张 clawock 决策回执:标的、各自引用证据的看多与看空理由、论点、失效条件、置信度与动作,以及已发布的 run id 和固定的证书"></p>

<sub>示例输出，不是真实结算。</sub>

**实盘完整多空辩论**

<p align="center"><img src="site/assets/debate-flow.svg" width="1016" alt="clawock 的多 Agent 辩论 —— 一份证据包喂给四种分析师视角;两名研究员建立多空对立论点并记录分歧点;三种风险声音与一位裁判点名策略框架,收敛成 plan.json,进入下一场的打分环"></p>

多空辩论改编自 [TradingAgents](https://github.com/TauricResearch/TradingAgents)；裁判给每条判定写明策略框架。

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

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/proposal-review.svg" width="1016" alt="三路审查：事实与可行性错误可以阻止发布，策略异议随提案保留。被拒绝和未发布的提案也记账。按 episode 统计的收益、预测评分与冻结的前瞻对照分开，不自动晋升方法或下单。"></p>

## 策略可以搜索自己的参数；采纳是一次要 review 的改动

策略插件声明自己现在用的参数，以及允许被搜索的网格。每天早上简报之后，策略实验室在复权日线上把这张网格走步向前跑一遍，把结果记下来。没有人参与的「自我改进」就走到这里，每一步都由代码管住：

1. **搜索。** 网格在运行之前就声明了，所以试过的每一组参数都被计数。
2. **过闸。** 注册闸要求样本外交易日够多、优势与增益的区间都在零以上、过拟合概率够低、日线已复权。配置行可以把闸调严，但不能调到比代码里的下限更松。
3. **第二意见。** 备选闸用另一组阈值判同一次运行。带现网效力的可以提出异议；没有哪个能放行注册闸拒掉的提案。
4. **记账。** 每条结论连同所读日线的摘要进入实验室台账，每次运行都会把台账读回来、按这些规则再核一遍。
5. **之后的交易日。** 被放行的候选参数会被登记，此后只在选出它们时还不存在的交易日上计分。

<p align="center"><img src="site/assets/strategy-evolution.svg" width="1016" alt="一次真实运行：2026-10-12 的 RSI 搜索自己的参数。六个周期、两个方向的已声明网格按平均秩 IC 着色，标出已登记的点和搜索选中的点；注册闸逐项检查全部通过，带现网效力的扣成本备选闸没有异议；只用行情源确认已复权的 16 个名字重跑同一搜索，区间跨零、被拒；时间轴上，登记只让之后的交易日开始计分，目前一个都还没计，配置行里仍是原来登记的参数。"></p>

图里是一次真实运行。2026-10-12，登记为「14 日反转」读法的 RSI 插件，在持仓相关的 28 个名字上搜索了十二组参数。搜索更偏向「28 日动量」读法，闸放行了它，它被登记。**只用行情源确认已复权的 16 个名字重跑同一搜索，结论是拒绝。** 这个候选依赖另外 12 个名字，而它们的依据只是单一行情源的记录里没有公司行动，没有第二个来源可以对照。现在每份提案都带着这次重跑，候选自己会说明它经不经得起。

这条链的两端都接上了。简报读的是每个策略**按配置行已登记参数**算出的分数，所以候选在那一行被改之前不会改变简报看到的任何东西。当一条登记在至少 60 个之后的交易日上计过分、区间在零以上、且结论经得起上面那次重跑时，实验室会写下一条**改行提案**：从哪组参数改到哪组、依据是什么。它只能是提案。改那一行是要有人 review 的改动，实验室里没有任何代码会去执行它。

还没有发生的事：之后的交易日一个都还没计分，所以还没有任何提案；而这个候选只要过不了那次重跑，就不会被提出。

```bash
clawock strategy-lab evolution rsi   # 每次运行、变了什么、每条登记及其之后的得分
clawock strategy-lab row-edits       # 实验室提出的改行提案，供 review
clawock strategy-lab verify          # 拿台账对照实验室的边界
```

[一次优化能得出什么结论、备选闸与实验室的边界](docs/architecture/strategy-plugins.md#boundaries)。

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
