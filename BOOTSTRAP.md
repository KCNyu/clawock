# BOOTSTRAP.md — OpenClaw main-session bootstrap

> OpenClaw 主会话通过 `agent:bootstrap` 读取本文件。isolated cron 不读取
> `BOOTSTRAP.md`，它会注入 `AGENTS.md` / `TOOLS.md` 等 allowlist 文件并由 cron
> payload 指定 skill。两条路径都只使用安装后的 `clawock`
> 入口。**这是硬约束，不是建议。**

---

## 🔒 必须遵守（hard rules）

### A. 数据规则

1. **绝不**用 `portfolio.json` 的 `current_price` 计算盈亏 — 它是旧缓存。先跑
   `clawock analyze-us` / `clawock analyze-hk` 刷价，再回答。
2. **绝不**把 HKD 和 USD 相加。Book total 必须双视角（USD-base + HKD-base），
   显式标 FX rate + source + timestamp。换算工具 `clawock fx --json`。
3. **绝不**对 `00100 MINIMAX` 在 Tencent 失败时假装拿到数据 —
   它是唯一源，挂了必须明说 "实时价获取失败"。
4. **绝不**绕过已安装的 `clawock analyze-us` / `clawock analyze-hk` 入口。
   harness/automation/策略归 `clawock`，本实例只提供声明式 profile 与数据；
   不把仓库内部 Python 文件或旧脚本路径当运行接口。

### B. Harness 流程（cron 触发的所有股票 job）

不论是哪个 LLM 在跑（MiniMax / Xiaomi / GLM / Claude / GPT），都按 **4 步**：

1. **Preflight**：`clawock {brief|report|intraday} preflight [args]`
   - 把所有确定性活（刷价 / FX / HHI / 信号 / 异动）下放给 Python
   - 输出 `memory/.tmp/{type}-context-{date}.json`
2. **读 context.json**：
   - 数字（FX rate / book total / concentration / anomalies）**只从 JSON 取**
   - `raw_wechat_block` 是 harness-owned 数据块；report / intraday 的模型只写散文，postflight 在投递前拼装，模型不得重排或重算其中数字
3. **LLM 合成**（你这一步）：
   - 按对应 SKILL.md 的 Mode 模板写 markdown 报告
   - daily-deep-brief 还要写 `memory/{date}-plan.json`（schema 在 SKILL.md 里）
   - 报告里**必须**至少提一个 `anomalies` 字段里的异动票
   - 若 `needs_risk_section=true`，必须有 ▎风险提示 段
4. **Postflight**：`clawock {brief|report|intraday} postflight [args]`
   - 校验 → pass / warn 自动 commit；fail 加红 banner

### C+. 自进化机制（daily-deep-brief）

context.json 的决策/自进化字段，**必须用上**：

1. **`peer_scan`** — 每个持仓的同题材竞品（listed + private + ETF proxy）
   - 必须输出 ▎同行扫描 段（表格）
   - 出现 `divergence_signal` 字段 → Judge 必须考虑 rotation trigger
   - 不许说 "考虑减仓"，要说 "减 X 股 → 加 Y 股"

2. **`decision_metrics`** — v2 strategy episode 的 confidence 与 benefit 审计
   - 只结算 condition 实际触发的 episode；同策略连续重申不重复计样本。
   - 输出 ▎Decision v2 校准：Brier、active/passive、by_strategy/by_driver/by_condition 与 date-cluster CI。
   - 给 decision 的 confidence 前参考同策略 episode；CI 跨 0 只能称方向性，不许声称稳定 edge。
   - execution 与建议质量分离。手动标记：`clawock mark-followed DECISION_ID [--no]`。

3. **`risk_metrics`** — 当下组合风险量化（β/Vol/Max DD/Sharpe/leverage/margin_at_risk）
   - 出现 `alerts[]` 数组 → 必须输出 ▎风险警报 段，列举每个 alert.type + detail
   - alert 类型: high_beta / high_vol / deep_dd / high_leverage / negative_sharpe
   - 不许只是 "波动较大"，要说 "30d 年化 56.5% > 50% 阈值"，引用具体数值

### B+. 研究生命周期（artifact 即真源）

- **新标的建仓前先过研究闸**：`clawock entry-gate assess memory/entry-gates/{TICKER}-{date}.json`。
  信息来源单薄只判 `gray_needs_evidence`（要写清缺什么证据），**不判死**；四条硬否决先于任何计分结算，行业例外只认 `config/entry-gate-vetoes.json` 里按板块写好的那几条。
- **财报结论只能来自 artifact**：走 `earnings-review` skill 写 `memory/earnings/{TICKER}/{period}.json`，盈利质量数字由 `clawock earnings` 算出来再引用，别在报告里现编。缺一手文件就降级来源等级并禁用脚注类结论。
- **thesis 状态只能由 registry 改**：`memory/theses/*.json` 是唯一 baseline；改动走 `clawock thesis drift`，每个 improved/weakened 维度必须附上次检查之后新观察到的 evidence ID。价格波动只能改估值，动不了生意/护城河/管理层。没有 baseline 就诚实报 `unknown`。
- **对外数字两源**：长文里引用的数字走 `clawock provenance` manifest（两个独立来源 + Decimal 精算），单源或超容差直接卡准出。
- 每天的待办队列在 brief context 的 `research_surface`（该复盘的财报 / 逾期承诺 / 没过闸的仓位 / 失效 artifact）——简报要把它讲出来。节奏依据见 `docs/operations/research-cadence.md`。

### C. 输出约束

- **段标记必须用全角竖线**：`▎情绪面` `▎技术面` `▎操作建议` `▎风险提示` `▎我的看法`
- 报告长度：Mode 6 / Mode 7 不设字数目标，长度由模型判断；只有一道防复读死循环的天花板 >5000 warn / >6000 fail；brief 同样无固定上限但段要齐
- **禁止敷衍词**：`数据待获取`、`等待数据`、`TODO`、`TBD` — postflight 会拦截
- **禁止 hedging 免责声明**：跳过 `this is not investment advice` 之类，铁律已注册
- 持仓回答**默认表格**（≥3 数据点必须表格化）

### D. 写入规则

| 触发 | 写哪个文件 |
|---|---|
| 跑了刷价脚本 | `portfolio.json` 已被脚本写，不要手改 |
| daily-deep-brief 完成 | `memory/{date}-pre-open.md` + `memory/{date}-plan.json` |
| Mode 6 报告 | 不写新文件；postflight 自动 commit portfolio.json，dashboard 走 data plane 发布 |
| Mode 7 盯盘 | 写 `.tmp` context/insights/heartbeat；不提交 `portfolio.json`，dashboard 仅语义变化提交，heartbeat 每 slot 发布 |
| 手动复盘 | `memory/{date}.md`（用户手写的，agent 别擅自填） |
| 新仓位 / 加减仓 / 平仓 | 手工记录 `holdings[].trades[]`（`action/date/shares/price`，卖出另记 `realized_pnl`），同步 broker 真值叶子（`shares` / `cost_basis`；平仓行保留、`shares=0`），再跑 `clawock reconcile`；存取款另记 `cash_adjustments[]` |

---

## 🚫 永远不做

- 编造数据；fallback 链全挂了就明说"数据获取失败"
- 从 chat / Telegram 触发的 session 不要直接 `git push` — 先问用户。harness postflight 跑完会自动 push（带 rebase+retry），不用 LLM 操心
- 绕过 `openclaw cron edit` / `ops/host/sync_us_cron_dst.py` 直接改 cron SQLite/旧 `jobs.json`；contract 改动必须重生成 `docs/operations/cron-schedules.md` 并跑 `ops/system_check.py`
- 改 `~/.openclaw/openclaw.json` 不备份（先 `cp -p X X.bak.$(date +%Y%m%d-%H%M)`）— 自动化 LLM 也要遵守
- 从 dated memory 恢复或重建已删除的 `scripts/` 路径
- 在 group chat / WeChat 简报里加 emoji 烟花（标题 1 个 emoji 上限）

---

## 📚 读完这个之后

按 `CLAUDE.md` 的 required reads 顺序补全上下文：
SOUL.md · USER.md · MEMORY.md · TOOLS.md · INVESTMENT_SOP.md · portfolio.json

Cron 触发的 session：直接按 SKILL.md 的 Mode 模板跑 4 步。
Topic / chat 触发的 session：先按上面的 required reads 补全上下文，再回答。

---

_本文件约束主会话；isolated cron 的同一运行边界由 `AGENTS.md`、`TOOLS.md`、payload 与对应 skill 共同约束。_
