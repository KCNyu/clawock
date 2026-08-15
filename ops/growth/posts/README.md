# 推广文案(待发布)

发布前检查:README 数字已由 readme-metrics 自动刷新;发布后把链接换成当时的 live 数据。所有发布都走 kcn 的账号。

## X(英文,首发建议)

> AI trading bots are a grift genre. This one posts its own −16%, tells you its 53% hit rate is noise (95% CI 42–64%, n=73), and ships a command that re-settles its entire ledger: `clawock audit-resettle`.
>
> "The market doesn't care how confident the model was."
>
> I don't know if it makes money. It's the only one I believe.
> github.com/KCNyu/clawock

thread 续帖:
1. "Everyone's building harnesses (OpenClaw, Codex, DSH — 5万 stars in a week). I built the layer that doesn't care which one you use: same decision contract on pure CLI / OpenClaw skill / Claude Code instruction / Codex AGENTS.md / DeepSeek Harness. examples/harness-agnostic"
2. "90 days live on a real HK+US account. 177 judgments settled by Python, never by the model. 640 ledger records public. Every number reproduces from one command — if it doesn't match, we lose."
3. "DSH users: `dsh plugin --profile web add clawock-dsh` — the skill package is on npm."

## 知乎(中文长文)

标题:《都在卷 Agent Harness,我开源了一个"不挑 harness"的投资决策引擎——实盘 90 天,亏损全公开》

正文结构:
1. 蹭点开场:DeepSeek Harness 开源一夜 5 万星,"Harness 工程"成新风口;但 harness 管的是 Agent 怎么跑,不管跑得对不对——尤其当它拿着你的钱。
2. 反差点:我的项目把 AI 战绩交给代码结算,实盘 90 天 −15.95%,每一笔亏损都摊开(原始账本链接)。卖点不是"赚得更多",而是"骗不了人"。
3. 四件事:①每天 08:00 多 Agent 辩论+证据链简报;②40+ 模块信息流(SEC EDGAR/东财/港交所/影响者雷达——特朗普 Truth Social 一手源、马斯克);③Python 确定性结算,模型不能给自己打分,53%/55% 的置信区间跨 50% 自己先盖章噪声;④每条建议带执行状态,人机混合成绩明说。
4. 诚实边界:"对不上算我们输"——audit-resettle 可复算;不是荐股,不是跟单,作者自己的真金白银。
5. 行动:github.com/KCNyu/clawock,60 秒跑通,DSH 用户一条命令装 skill。

## 小红书(笔记)

标题:《AI 炒股亏了 16%,我却想把它讲给所有人听》

正文:一个真实港美股账户让 AI 跑了 90 天,亏了 15.95%——但它把每一笔亏损都摊开给你看,连"没跑赢买入持有"都自己承认。每天早 8 点四个 AI 先吵一架、一个裁判拍板、代码自动记账,想赖账代码不答应。命中率 53% 它自己说"跟抛硬币差不多"……全网第一个敢这么干的 AI 投研系统。免费、开源、不荐股、无付费版。围观真实账本:链接

标签:#AI炒股 #开源 #投资 #避坑 #DeepSeek #AIAgent
