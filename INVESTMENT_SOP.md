# Investment Workspace SOP

## 目标
让任何模型（Claude / GPT / openclaw 自身）进入这个 workspace 后，都能稳定接上投资分析上下文，不依赖一次性的语义检索命中。

## 单一事实来源

| 内容 | 文件 |
|---|---|
| 当前持仓 | `portfolio.json` |
| 长期规则 / 铁律 / 偏好 | `MEMORY.md` |
| 活跃 / 已清仓 ticker | `portfolio.json`（`shares > 0` 即活跃，`shares == 0` 即已清仓） |
| 工具 / 脚本 / fallback 链 / cron 路由 | `TOOLS.md` |
| Skill 入口 | `skills/{us,hk}-stock-analysis/SKILL.md`、`skills/portfolio-{risk,swarm}-review/SKILL.md` |

## 标准启动顺序（投资类问题必走）

适用主题：持仓分析 / 节后操作 / 个股盈亏 / 美股港股仓位 / 加仓减仓 / 估值 / 情绪面。

1. 读 `MEMORY.md` —— 拿铁律、用户偏好、已知陷阱
2. 读 `portfolio.json` —— 拿当前持仓 / cost / current_price
3. 活跃 / 已清仓从上一步的 `portfolio.json` 直接读：`shares > 0` 是活跃，`shares == 0` 是已清仓（避免分析废持仓）
4. **路由到 skill** ——
   - 美股个股 → `us-stock-analysis` Mode 1-5
   - 港股个股 → `hk-stock-analysis` Mode 1-5
   - 持仓快速 → `portfolio-risk-review`
   - 持仓深度 → `portfolio-swarm-review`
   - 供应链卡点深挖 / AI半导体瓶颈选股 / "用 Serenity 的方式看 X" / thesis 压力测试 → `serenity-skill`（重、手动深挖，不进 cron）
   - cron 简报 → 对应 skill 的 Mode 6/7
5. **跑脚本取最新价**（**绝不直接用 portfolio.json 缓存价**）：
   - 美股：`clawock analyze-us [TICKER]`（7 路 fallback + RSI/MA/news/signal）
   - 港股：`clawock analyze-hk [TICKER]`（Tencent 主源 + Eastmoney 全量独立对账/兜底 → stooq → yfinance）
   - 仅刷价：`clawock us-quotes`
6. 输出分析（按 skill 输出格式）
7. 重要操作后：更新 `portfolio.json` + git commit（AGENTS.md 有 auto-commit 规则）

## 数据规则

→ 见 `MEMORY.md § 数据规则` （唯一权威）。SOP 不重复，只提醒：
**没跑脚本就不要谈盈亏。**

## 写入规则

- 不在 `MEMORY.md` 维护详细持仓副本，避免重复和过期
- `MEMORY.md` 只放：规则、偏好、长期结论、关键联动
- `portfolio.json` 只放：当前持仓、成本、现价、已实现盈亏、必要注释
- 活跃 / 已清仓**不另立文件**：`portfolio.json` 的 `shares` 就是答案。手工维护的
  ticker 副本 2026-05-14 之后就没人更新过，到 08-26 已经把 7 个在持的名字写成清仓、
  把 3 个清掉的写成活跃（#1067），删了

## 检索优化

为提升语义检索命中，关键文件中需保留这些常用词：
openclaw workspace / 投资记忆 / portfolio / 持仓 / 美股 / 港股 / 节后操作 / Rick / kcn

## 输出规则（kcn 偏好）

- 持仓回答**默认用表格**（3+ 数据点必用表）
- 直接判断，**跳过 hedging / 跳过 "this is not financial advice"** 之类的免责
- 明确区分：实时数据 / 收盘数据 / 旧缓存数据
- 失败时**明确告知**数据来源和时效，禁止静默
- 数据时效附带在末尾："数据: analyze_*_stocks.py {timestamp}"

## 维护规则

| 触发 | 同步更新 |
|---|---|
| 买卖成交 | `portfolio.json` |
| 重要策略变化 | `MEMORY.md` |
| 数据源 / fallback 优先级变化 | `MEMORY.md` + `TOOLS.md` |
| Skill 输出格式调整 | 直接改 `skills/{name}/SKILL.md` 的对应 Mode 段，cron 自动跟随 |
