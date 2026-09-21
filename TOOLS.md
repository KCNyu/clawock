# Tools: task routing

OpenClaw injects this index. Use it directly when already in context; do not read it again at startup.
Select the relevant skill or reference section only. For ordinary chat or an explicit coding-task dispatch,
no investment data, provider catalog, cron map or repository investigation is needed before replying/dispatching.

## Sources and commands

- `portfolio.json`: authoritative holdings; `shares > 0` means active. Read only for a portfolio/position task.
- `MEMORY.md`: runtime investment rules; use the injected copy in direct chat. Coding-agent durable memory stays outside the repo.
- `INVESTMENT_SOP.md`: investment questions only. Fetch current prices before giving price-dependent advice.
- Installed `clawock` CLI owns workflows and tools; source is `src/clawock/`. Never revive old root scripts or `scripts/data/` entrypoints.
- `clawock analyze-us` / `clawock analyze-hk`: market analysis; `clawock us-quotes`: US price refresh.
- `clawock fx`: conversion; HKD and USD must be converted before totaling. Data rules remain in `MEMORY.md`.
- `clawock entry-gate`, `clawock earnings`, `clawock thesis`, `clawock provenance`, `clawock research`: research lifecycle;
  artifacts in `memory/entry-gates/`, `memory/earnings/`, `memory/theses/`.
- Scheduled jobs use `clawock brief|report|intraday` preflight/postflight. Follow the selected job/skill; do not manually trigger the daily brief for an unrelated question.
- Tool parameters: [commands](docs/reference/commands.md). Data sources, fallbacks, publishing, cron and sentiment recipes:
  [tool operations](docs/reference/tool-operations.md), read only the needed section.
- Published dashboard data gate: `dashboard-artifact-gate.yml` ([workflow](.github/workflows/dashboard-artifact-gate.yml)); validates the published generation.
- Research cadence: [research-cadence](docs/operations/research-cadence.md). Cron contract: `config/cron-schedules.json`;
  generated schedule: `docs/operations/cron-schedules.md`.
- Skill installation follows [skills-store-policy](docs/operations/skills-store-policy.md): `skillhub` first, `clawhub` fallback;
  show source/version/risk and obtain the required confirmation before installation.

## Skill 路由表（什么场景用哪个）

| 场景 | 入口 skill | 备注 |
|---|---|---|
| "分析 RKLB" / "compare AAPL vs MSFT" / 美股个股问题 | `us-stock-analysis` | 4 模式（quick/technical/fundamental/full）+ sentiment mode 5 |
| "分析 00100" / "07226 怎么样" / "恒科今天" / 港股问题 | `hk-stock-analysis` | 4 模式 + 港股专属 sentiment（雪球/富途）+ 南向资金 |
| "看下持仓 / 节后操作 / 持仓有什么风险" | `portfolio-risk-review` | 单 pass、4 lens、快速可行动 |
| "深度复盘 / 持仓全面诊断 / 大幅调仓前" | `portfolio-swarm-review` | 3 tier（analyst→bull/bear→risk debate）+ confidence 评分，重，慢 |
| "用 Serenity 的方式看 X" / 产业链卡点深挖 / AI半导体瓶颈选股 / thesis 压力测试 | `serenity-skill` | 供应链 chokepoint 框架（8 因子评分卡 `skills/serenity-skill/scripts/serenity_scorecard.py`）；**重、手动深挖、不进 cron**；证据阶梯把 KOL/社媒判弱证据 → 对冲追微盘 pump |
| 教育性问题（"什么是 MACD"、"position sizing 怎么算"） | `trading`（clawhub 装的） | guardrails 重、不给具体买卖判断；具体判断走上面 4 个 |
| 抓需 JS 渲染 / 反爬的页面（雪球评论 / Futu 社区 / Reddit 深页） | `scrapling` | 配合上面的 stock-analysis Mode 5 调用 |
| Web 搜索（新闻 / X / 中文社区 / 政策） | `tavily-search` | 不要让模型自己改用 Yahoo/Google 临时拼搜索。**免费档 1000 credits/月全局共享**，调用必带 `--bucket`（brief/report/intraday/research/extract）；盘中常规盯盘别烧、超限自动优雅降级回内置搜索 |
| openclaw 升级后健康检查 / 磁盘膨胀 | `openclaw-tune` | 不动股票 |
| 「这票值不值得研究」/ 建仓前先筛新标的 | `entry-gate` | 信息分级 A/B/C 与投资质量分开;四条硬否决先于任何计分;C 级只判 gray 不判死;产物 `memory/entry-gates/` |
| 「财报出了 / 复盘这个季度 / 当初承诺兑现了吗」 | `earnings-review` | 一手 filing/港交所公告优先,盈利质量由代码算,承诺账本跨期滚动;事件驱动、不进 cron;产物 `memory/earnings/` |
| 盘前深度简报（cron #10 自动跑，非人工入口） | `daily-deep-brief` | preflight 出 context → swarm 分析 → plan.json;人工别手动触发,改它先读 SKILL 的 postflight schema |
| openclaw 升级 / 依赖迁移 | `openclaw-upgrade` | 升级后必数 cron 个数;不动股票 |
| issue / PR / CI run / gh api | `github` | 走 `gh` CLI;仓库改动仍遵守 AGENTS.md 的 worktree→PR 规矩,别直接推 master |

`skills/_shared/` 不是 skill，是 hk/us 共用的片段（盘中 status sidecar 规范）——改盘中横幅只改那一份。

研究生命周期各环节跑多勤（每天 / 按事件 / 每次 push）见 `docs/operations/research-cadence.md`。

⚠️ **不要做的 routing 错误**：
- `trading` skill 默认禁止"直接买卖建议" → 用户问"应该买不买" 时不走它，走 `us/hk-stock-analysis`（用户偏好已写在 MEMORY.md）
- 持仓问题不要走 `us-stock-analysis` 的 Full Report → 走 `portfolio-risk-review`（持仓视角）
- 单只股的分析也不要走 `portfolio-swarm-review`（杀鸡用牛刀）→ 走 `us/hk-stock-analysis` Mode 4
