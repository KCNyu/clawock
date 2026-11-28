---
name: daily-deep-brief
description: 工作日 08:03 HKT 盘前简报 cron。先运行 preflight，输入为同代决策摘要及按需证据。写 plan、judgment 和 insights JSON，再运行 postflight 校验、渲染和投递。休市时结束，手动复盘使用 portfolio-swarm-review。
---

# Daily Deep Brief (08:03 HKT, weekday)

8 点这个时点：HK 开盘前 ~90 分钟，US 已收盘 ~4 小时。盘前是 deep think 最好的窗口 —
有完整夜间消息面，没有盘中执行压力。

工作日简报任务是正例。临时请求复盘昨日持仓时，使用 `portfolio-swarm-review`。
若 postflight 拒收，按 Step 5 根据返回字段覆盖修复本代草稿并重试。

## Harness 架构（不可越权）

```
┌──────────────────────┐   ┌────────────────┐   ┌──────────────────────────┐
│ clawock brief preflight │──►│ LLM (你 / Rick) │──►│ clawock brief postflight  │
│   (确定性 + 幂等)      │   │ (只写判断/反方) │   │ 校验 → 渲染 → 投递        │
└──────────────────────┘   └────────────────┘   └──────────────────────────┘
   指标/因子/风险/evidence     查 packet summary     校验 plan+judgment，
   编译 typed packet           写 plan + judgment    brief_render 出 md+微信卡，
                               (纯文本，不写版式)    Pages 只读稳定 projection
```

**为什么这样分**：之前完全交给 LLM，模型可能漏快照、漏 HHI、漏 FX、漏 retrospective。
确定性步骤交给脚本（一定执行，无遗漏）；LLM 只做"分析综合"这个不能脚本化的部分。

## 🔒 Exec 铁律：退出码就是整回合的判据

**每一条 `exec` 的退出码会被当成整个回合的成败。** 一条中途的非零退出会让 cron 把
**已经做完并已投递**的一轮判成 `error`（2026-08-18：简报全部产出、`wechat_sent: true`、
commit+push 都成了，但一条读「可能不存在的文件」的 exec 非零退出，整轮仍被记成红）。

规则正文只有一份：本回合任务消息里的「Exec 契约」（源文件
`config/cron-payloads/_exec-contract.md`，简报、报告、盘中共用）。本 skill 不另写一套，
两句话的要点：

- **探测**（读可选文件、`ls`/`grep`/`head`/`test`）给那一条探测自己兜底 `|| true`。
- **业务步骤**（preflight / postflight）的结果必须原样可见：不接管道、不补 `|| true` /
  `; true`，只允许 `; echo "EXIT=$?"`。preflight 退 2 就是失败，不是「今天还没产出」。

配套的窄规则见 Step 5 的「送达确认铁律」（#558）：那条禁的是 postflight 之后再去读
marker 确认送达。

## 6-step 流程（严格按顺序）

### Step 1: 跑 preflight（一行命令搞定所有确定性活）

```bash
clawock brief preflight
```

盘前 cron 在第一轮并行读取本指引并调用 preflight。preflight 按简报的 HKT 日期检查两市，
返回 `market_closed` 时直接结束。

**行情失败闸**：US 或 HK 刷新失败时，preflight 退出 1，并把本日 context 与
manifest 换成 `price_refresh_failed` 的失败代（无持仓数字、无 decision packet）。
看到该状态立即结束本轮，不写 plan/judgment，不调用 postflight；修复行情后重跑
preflight。fallback 会拒绝生成，postflight 也会阻止发布。其他资料采集警告仍按
本次 context 的 `issues` 逐项披露。

这一步内部做了：

1. `clawock analyze-us` — US 价格刷新（7-route fallback + RSI/MA）
2. `clawock analyze-hk` — HK 价格刷新（Tencent 主源 + Eastmoney 全量独立对账/兜底 → stooq → yfinance + 恒指 + 信号）
3. `clawock fx --json` — USDHKD 实时汇率（Frankfurter → exchangerate.host → Yahoo）
4. `cp portfolio.json memory/snapshots/{date}.json` — 每日快照（longitudinal 基础设施）
   - **为什么**：`portfolio.json` 是滚动覆盖的 ground truth，每次刷价就丢前一刻状态。
     有 snapshot 历史才能做 Rolling P&L 曲线 / Alpha vs benchmark / Drawdown 分析 / Position 变化追溯。
   - ⚠️ **不可补做** — 每过一天少一份永远拿不回来的数据。
5. **HHI / Top2 集中度算法**（HK + US leg 分开）
6. **SEC EDGAR fundamentals** — 从当天 `portfolio.json` 动态筛选 `shares > 0` 的 US 持仓；跳过 `is_leveraged_etf=true` 或被名称启发式识别为杠杆 ETF 的标的，其余单股逐一跑 `clawock filings`
   - 杠杆 ETF 检测启发式（name 关键词）：'倍', 'Direxion', 'T-Rex', 'Defiance', 'ProShares',
     '2X Long', '3X Long', 'Daily Target'
   - 不在文档硬编码 ticker；实际名单以当天持仓和上述动态过滤结果为准
7. **Retrospective**：读 prior v2 plan，对每个 decision 按 strategy 检查 condition 是否触发、模拟 benefit 与 confidence calibration

输出分三层：

- `memory/.tmp/brief-context-{date}.json` —— 完整、不可裁剪的审计事实；供 postflight 校验，**不要整份 cat 进模型上下文**。
- `memory/.tmp/brief-context-{date}/manifest.json` + `core.json` + feature bundles —— 同一 `generation_id` 下的模型输入边界。manifest 记录路径、hash、字段、逐 section 大小和预算。
- manifest 的 `tools.decision_packet` —— harness 编译的 typed 决策边界；证据 ID、算术和授权边界由代码拥有；技术分类、量化评级与候选是登记策略的意见。

### Step 2 / Step 2.5: 读取本代输入

[Preflight 成功后读取摘要、查询与按需 bundle 协议](references/packet.md)

[需要时阅读登记的技术形态](references/technical-playbooks.md)。

摘要为唯一常驻事实输入。按票和按 section 查同代数据。若 preflight 为休市或失败，按 Step 1 停止。

### Step 3: Swarm 分析

[分析前读取分工、证据和风险约束](references/swarm.md)

[写判断前读取写作、集中度与货币规则](references/style.md)

### Step 4: 写 plan、judgment 和 insights

[写文件前读取输出协议和字段口径](references/plan-schema.md)

完整写入三份 JSON 草稿。报告 Markdown 和微信卡由 postflight 渲染。

### Step 5: 跑 postflight（验证 + commit + 自动投递微信）

```bash
clawock brief postflight
```

输出 JSON：
```json
{
  "status": "pass|warn|fail",
  "issues": [...],
  "wechat_prefix": "...",
  "wechat_sent": true,
  "commit_ok": true,
  "commit_msg": "committed"
}
```

- `pass` — 全部 OK，已 `git commit`
- `warn` — 有非 critical 实质问题或 ≥40KB 极端超长（≤4 个），已 commit 但标 `(validation warnings)`
- `fail` — 缺文件/JSON 解析错/critical 字段缺失，**不 commit**、**不投递**
- `wechat_sent` — postflight 自动投递结果（见下）

**status 不是逐条 issue 判的，别自己猜哪条是硬闸。** `fail` 只由 critical 关键词
（`缺失` / `解析失败` / `表格 #`）或 issues > 4 条触发；其余都是 warn，照样 commit + 投递。

**`fail` 才需要修**：按 `issues` 一次修正本次阻断项。保留已通过的字段，
用 `write` 完整覆盖需要修的文件，再运行一次正式 postflight。
如果仍返回 `fail`，用最终状态和剩余问题结束本轮，由既有 watchdog 接管。

**`warn` 和 `pass` 一样是终态（`commit_ok: true` 时）：已 commit、已尝试投递，不要为了变成 pass 再跑 postflight。**
重跑不会再投递（当天已有投递记录就跳过），只会多一次 commit + push + dashboard 重建，
报告正文也不会因此更好。具体到 warn 里的各条：

- 带 `(advisory)` 的提示（管线术语等）和正文超长：**不改文件、不重跑**，下次生成时注意。
- `wechat_sent: false`：同样**不重跑**、不手动发——重跑只会被投递幂等检查跳过。
- 唯一例外是 `projection_status: invalid`（issue 以 `judgment 未通过校验` 开头）：Pages 会丢掉整个
  判断层（见 C 节），值得修**一次**。先 `read` 当前 judgment，按 `projection_issues` 一次改完所有
  点名字段，其余字段原样保留（整份 `write` 时最容易把没点名的字段弄丢），再重跑一次 postflight。
  这一次之后不论结果如何都结束本轮。重跑改写了已投递的报告时，postflight 自己会在页面标题下加
  「投递后修订」说明并记一条 `content_revised_after_delivery`（不重发卡片）；不要自己写说明或补发。

> **2026-09-17 教训**：首轮 warn 已 commit；模型先按 judgment 超长重写整份 judgment，重跑后
> 发现重写时丢了一个 `peer_read`，又顺手改 plan 里的 advisory 术语再跑一次，三次 postflight
> 产生三个 commit。旧版「改完任何一条 issue 就重跑」没限定只对 `fail`，读起来像 warn 也要修到干净。

> **2026-07-27 教训**：旧规则把 35.8KB 和表格 critical 混在同一个 issues 列表里，模型误把
> 体量当硬闸，事后一路裁到 23.7KB，既浪费时间/tokens 又引入编辑错误。新规则把体量单独记录：
> 只保留 ≥40KB 可读正文的 `warn`；小于此值是 `within_budget`，不再有 28KB 目标或中间 advisory 档。
> 无论哪档都保留完整正文，绝不在 postflight 后硬截断。报告由 `brief_render` 渲染；这条闸留着是为了在渲染器或持仓规模变化时仍能报警。

### 投递（Step 5 postflight 内自动，你什么都不用做）

> **🔒 投递已解耦——你绝不要手动发微信、绝不调任何 message/send 工具、也不要把卡片当回复文本贴出来。**
>
> pass/warn 时 **`brief_postflight` 自己**会用 fresh-token 短连接把渲染出的
> `brief-card-{date}.txt` 及当天风险待复查队列组成卡片，投到 kcn 微信（cron 已设 `delivery=none`），
> 并同步 Telegram，把两路结果记到 `memory/.tmp/brief-sent-{date}.json`。
> `brief_watchdog`（08:36）在 Telegram marker 缺失/失败时补投 Telegram；微信只在回执明确记录发送失败时补发一次，其余情况不重发。
>
> **为什么这样改（2026-06-08）**：旧的 `delivery=announce` 在长 turn 末尾用 turn 起点抓的 token 投递，brief turn 恒 >160s（173–975s）→ token 必过期 → 静默丢、`delivered=true` 是假信号（见 memory: openclaw-wechat-longturn-token-expiry）。短命 message send 每次抓新 token，且独立于 turn 时长，kcn 实测可靠（同 intraday 架构）。
>
> **你的职责到 Step 5 跑完 postflight 为止**：产出 B/C/D 三个文件（plan / judgment / insights）+ 跑 postflight，报告与微信卡由 postflight 内的 `brief_render` 生成。看到 status 为 `pass`/`warn` 且 `commit_ok: true` 即大功告成（`wechat_sent` 为 false 也一样，不要手动补发），**立即结束本轮，不要再追加任何思考或内容**。
>
> **🔒 送达确认铁律（2026-08-15 起，#558）**：
> postflight **之后禁止**用 exec / list / show 去读 `memory/.tmp/` 下的 marker、claim、sent 文件"眼见为实"确认送达。
> 送达由 postflight 的 marker + watchdog 兜底负责，`wechat_sent: true` / postflight 输出里的投递摘要就是权威。
> 违例形态（2026-08-10~14 复发 ≥5 次）：`Exec failed: list files in memory/.tmp/report-sent-*.json` → 整回合被判 error → 该槽位投递缺口（#544）。**postflight 说送到了就是送到了，不要二次确认。**
>
> 这条是窄规则（只管 postflight 之后的送达确认）。**一般形式见文档开头的「Exec 铁律：退出码就是整回合的判据」** —— 2026-08-18 同一机制换个位置又发生了一次（Step 3 读昨日 notes，末尾 `head` 读到不存在的文件 exit 1，简报已投递却仍判红）。
