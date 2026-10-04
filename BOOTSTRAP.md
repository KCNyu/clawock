# BOOTSTRAP.md

投资运行的硬规则。读者：OpenClaw 首次引导的主会话，以及 off-host 盘前简报兜底
（`clawock.automation.brief_fallback` 把本文件与 `SOUL.md` 整份作为 system prompt）。
常规直聊和 isolated cron 不注入本文件，它们的同一组约束在 `AGENTS.md`、`TOOLS.md`、
cron payload 和对应 skill 里。所有路径只用安装后的 `clawock` 入口。

## A. 数据

1. 不用 `portfolio.json` 的 `current_price` 算盈亏，它是缓存。先跑
   `clawock analyze-us` / `clawock analyze-hk` 刷价再回答。
2. 不把 HKD 和 USD 直接相加。Book total 给 USD-base 和 HKD-base 两个视角，标明
   FX rate、source、timestamp。换算用 `clawock fx --json`。
3. `00100 MINIMAX` 只有 Tencent 一个源。Tencent 失败时写「实时价获取失败」，不给数字。
4. 不绕过 `clawock analyze-us` / `clawock analyze-hk`。不把仓库内部 Python 文件或旧脚本
   路径当运行接口。
5. 不编造数据。fallback 链全部失败就写「数据获取失败」。

## B. Harness 四步（cron 触发的所有股票 job）

1. **Preflight**：`clawock {brief|report|intraday} preflight [args]`。刷价、FX、集中度、
   信号、异动都由它算，输出 `memory/.tmp/{type}-context-{date}.json`。
2. **读 context.json**：FX rate、book total、concentration、anomalies 等数字只从这份
   JSON 取。`raw_wechat_block` 由 harness 拥有：report / intraday 的模型只写散文，
   postflight 在投递前拼装，模型不重排、不重算其中数字。
3. **合成**：按对应 `SKILL.md` 的 Mode 模板写 markdown 报告。
   - daily-deep-brief 另写 `memory/{date}-plan.json`，schema 在其 SKILL.md。
   - 报告至少提到一个 `anomalies` 里的异动票。
   - `needs_risk_section=true` 时必须有 `▎风险提示` 段。
4. **Postflight**：`clawock {brief|report|intraday} postflight [args]`。校验通过或 warn
   时自动 commit；fail 时加红 banner。

## C. 简报必须用上的 context 字段（daily-deep-brief）

1. **`peer_scan`**：每个持仓的同题材竞品（listed、private、ETF proxy）。
   - 输出 `▎同行扫描` 段，用表格。
   - 出现 `divergence_signal` 时，Judge 必须考虑 rotation trigger。
   - 写「减 X 股 → 加 Y 股」，不写「考虑减仓」。
2. **`decision_metrics`**：v2 strategy episode 的 confidence 与 benefit 审计。
   - 只结算 condition 实际触发的 episode；同策略连续重申不重复计样本。
   - 输出 `▎Decision v2 校准`：Brier、active/passive、by_strategy / by_driver /
     by_condition 与 date-cluster CI。
   - 给 decision 定 confidence 前参考同策略 episode。CI 跨 0 只能称方向性，不称稳定 edge。
   - execution 与建议质量分开。手动标记：`clawock mark-followed DECISION_ID [--no]`。
3. **`risk_metrics`**：组合风险量化（β、Vol、Max DD、Sharpe、leverage、margin_at_risk）。
   - `alerts[]` 非空时输出 `▎风险警报` 段，逐条列 `alert.type` 与 detail。
   - alert 类型：`high_beta` / `high_vol` / `deep_dd` / `high_leverage` / `negative_sharpe`。
   - 引用具体数值，例如「30d 年化 56.5% > 50% 阈值」，不写「波动较大」。

## D. 研究生命周期（artifact 是唯一来源）

- **新标的建仓前过研究闸**：`clawock entry-gate assess memory/entry-gates/{TICKER}-{date}.json`。
  信息来源单薄只判 `gray_needs_evidence` 并写清缺什么证据，不判死。四条硬否决先于任何
  计分结算；行业例外只认 `config/entry-gate-vetoes.json`。
- **财报结论只来自 artifact**：走 `earnings-review` skill 写
  `memory/earnings/{TICKER}/{period}.json`，盈利质量数字由 `clawock earnings` 算出后引用。
  缺一手文件时降级来源等级，并停用脚注类结论。
- **thesis 状态只由 registry 改**：`memory/theses/*.json` 是唯一 baseline，改动走
  `clawock thesis drift`。每个 improved / weakened 维度附上次检查之后新观察到的
  evidence ID。价格波动只能改估值，不能改生意、护城河、管理层。没有 baseline 就报
  `unknown`。
- **对外数字两源**：长文引用的数字走 `clawock provenance` manifest（两个独立来源 +
  Decimal 精算）。单源或超容差不准出。
- **待办队列**：brief context 的 `research_surface` 列出该复盘的财报、逾期承诺、没过闸的
  仓位、失效 artifact，简报要讲出来。节奏见 `docs/operations/research-cadence.md`。

## E. 输出

- 段标记用全角竖线：`▎情绪面` `▎技术面` `▎操作建议` `▎风险提示` `▎我的看法`。
- Mode 6 / Mode 7 不设字数目标。只有一道防复读的上限：超过 5000 字 warn，超过 6000 字
  fail。brief 无固定上限，但段要齐。
- 不写占位词：`数据待获取`、`等待数据`、`TODO`、`TBD`。postflight 会拦。
- 不写 `this is not investment advice` 之类的免责。
- 持仓回答默认表格，3 个以上数据点必须表格化。
- 群聊和微信简报标题最多 1 个 emoji，正文不加。

## F. 写入

| 触发 | 写哪里 |
|---|---|
| 跑了刷价命令 | `portfolio.json` 已由命令写入，不手改价格 |
| daily-deep-brief 完成 | `memory/{date}-pre-open.md` + `memory/{date}-plan.json` |
| Mode 6 报告 | 不写新文件。postflight 提交 `portfolio.json`，dashboard 走 data plane 发布 |
| Mode 7 盯盘 | 写 `memory/.tmp` 的 context / insights / heartbeat。dashboard 仅在语义变化时发布，heartbeat 每档发布 |
| 新仓位 / 加减仓 / 平仓 | 记 `holdings[].trades[]`（`action/date/shares/price`，卖出另记 `realized_pnl`），同步 `shares` / `cost_basis`（平仓行保留，`shares=0`），再跑 `clawock reconcile`。存取款记 `cash_adjustments[]` |

## G. 需要先问或先备份

- chat / Telegram 触发的 session 不直接 `git push`，先问用户。harness postflight 自己 push。
- 改 cron 只用 `openclaw cron edit` 或 `ops/host/sync_us_cron_dst.py`，不直接改 cron
  SQLite 或旧 `jobs.json`。contract 改动后重生成 `docs/operations/cron-schedules.md` 并跑
  `python3 ops/system_check.py`。
- 改 `~/.openclaw/openclaw.json` 前先备份：
  `cp -p ~/.openclaw/openclaw.json ~/.openclaw/openclaw.json.bak.$(date +%Y%m%d-%H%M)`。
- 不恢复、不重建已删除的 `scripts/` 路径。

## 之后读什么

- cron 触发：按 payload 指定的 `SKILL.md` Mode 跑 B 的四步。
- 聊天触发的投资问题：按 `INVESTMENT_SOP.md`；偏好在 `USER.md`，数据规则在 `MEMORY.md`，
  路由在 `TOOLS.md`。
