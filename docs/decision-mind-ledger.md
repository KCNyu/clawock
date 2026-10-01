# 决策心智账本 — Decision Mind Ledger (schema v0)

> 已落地(PR #661/#662),不是草案:对话与盘前产生的**投资判定**冻结为
> 「思想快照 + 情绪压力 + 可证伪条件」的结构化记录,与盘前计划行同写
> `memory/decisions.jsonl`。本文件按实况重写,依据:
> `src/clawock/decision/record.py`(唯一写入方)、
> `src/clawock/decision/ledger.py`(校验路由与结算)、
> `examples/dsh/packages/clawock-dsh/client.js` + `lib/*.js`(DSH 面板)、
> `examples/openclaw/SKILL.md`、`examples/claude-code/CLAUDE.md`、
> `examples/codex/AGENTS.md`(各 harness 的调用约定)。

## 一条记录 = 决策卡(冻结,可通过 validate_mind_record)

下例与 `build_record`(record.py)的实际输出同形,可通过
`validate_mind_record`(record.py)校验:

```json
{
  "schema_version": 0,
  "decision_id": "dec-conversation-43970cf6d9ff",
  "subject": { "ticker": "00100", "market": "HK", "currency": "HKD" },
  "decided_at": "2026-08-16T14:30:50+08:00",
  "source": "conversation",
  "action": "reject",
  "confidence": 0.65,
  "driven_by": "fundamental",
  "mind": {
    "bull": { "summary": "营收 +159% YoY,入通/海外霸榜/高盛三催化叙事仍在", "evidence": [] },
    "bear": { "summary": "净利率 -2368%、负债率 343%、每股净资产 -24.37;z+2.8σ 情绪极值反转", "evidence": [] },
    "thesis": "高增长救不了资不抵债,情绪反转期先活下来",
    "invalidation": ["缩量企稳(量能低于前日50%)", "连续2日不创新低", "站回 HK40"]
  },
  "emotion": { "pressure": "averaging_down", "note": "浮亏 -40% 的摊本冲动被明确压过——忍住没加" },
  "condition": { "description": "缩量企稳(量能低于前日50%)", "price": null, "type": "manual" },
  "execution": { "status": "followed", "source": "conversation", "detected_at": null },
  "accounting": {
    "trigger": { "status": "pending", "condition": "缩量企稳(量能低于前日50%)" },
    "execution": { "executed": null },
    "outcome": { "grade": "pending" }
  }
}
```

字段说明(全部由 `build_record` 生成,record.py):

| 字段 | 含义 |
|---|---|
| `schema_version` | 恒为 0(`MIND_SCHEMA_VERSION`),与 v2 计划行区分 |
| `decision_id` | `dec-<source>-<12hex>`,由 `_stable_id` 稳定生成 |
| `subject` | `ticker`/`market`/`currency` 三个必填非空字符串 |
| `decided_at` | 写入时的本地时间,ISO 带秒 |
| `source` | 产出 harness,见下方枚举 |
| `action` / `confidence` / `driven_by` | 判定、信心(0..1 数值)、驱动,见下方枚举对照 |
| `mind` | 思想快照:`bull`/`bear` 各含 `summary` + `evidence`,另有 `thesis` 与 `invalidation` 列表 |
| `emotion` | 情绪压力自评:`pressure`(枚举)+ `note` |
| `condition` | 兼容字段:`description` 取 `invalidation[0]`,`price=null`,`type="manual"` |
| `execution` | 无操作动作(`reject/hold/watch/abstain`)落账即 `followed`;下单动作(`buy/add/trim/sell`)初始 `unknown`,待 `clawock mark-followed <decision_id> [--no]` 标记(execution.py) |
| `accounting` | 落账时一次性写入:`trigger.status="pending"`、`execution.executed=null`、`outcome.grade="pending"`。**目前没有任何代码读取或更新这一块**,见「已实现 / 未实现」 |

## 校验规则(validate_mind_record)

不满足任一条即 `record rejected`,不落账(record.py):

1. `subject.ticker/market/currency` 非空字符串
2. `action` ∈ 下方 record 词表
3. `source` ∈ 下方 SOURCES
4. `confidence` 为数值(非 bool)且在 [0, 1]
5. `driven_by` ∈ 下方 record 词表
6. `mind.bull.summary` 与 `mind.bear.summary` 必须非空 —— **反方强制**,没有真实 bear 不许落账
7. `mind.invalidation` 非空列表(可观察条件)
8. `emotion.pressure` ∈ 下方 record 词表

`mind` 与 `emotion` 落账后没有任何更新路径,即冻结;只有
`execution.status` 会经 `mark-followed` 变化。

## 枚举对照:record(v0 心智记录)与 plan(v2 计划行)是两套词表

| 字段 | `clawock record` 心智记录(record.py) | 盘前计划行(ledger.py) |
|---|---|---|
| `action` | `buy, add, trim, sell, hold, watch, reject, abstain` | `cut, trim_on_rebound, hold_and_watch, t_only, add_only_on_trigger, add_on_breakout, watch` |
| `driven_by` | `technical, fundamental, sentiment, mixed` | `technical, catalyst, sentiment, influencer, macro, peer, risk_rule` |
| `emotion.pressure` | `calm, fomo, revenge, averaging_down, fear, euphoria, mixed` | 计划行没有 `emotion` 字段 |
| `source` | `conversation, openclaw, claude, codex, cli` | 计划行没有 `source` 字段 |

注意:两套 `action` 词表只有 `watch` 重叠,此前文档声称的「与盘前简报决策
同词表」不成立,勿再沿用。

## 写入与校验路径

- **唯一写入入口**:`clawock record --source <harness> ...`(record.py)。
  校验不过打 `record rejected: <原因>` 并退出;通过后
  `load_decisions → append → write_decisions`(临时文件 + `os.replace`
  原子落盘)。任何 harness 禁止手改 jsonl。
- **`--source` 合法值**:`conversation`(DSH 默认)/`openclaw`/`claude`/
  `codex`/`cli`(record.py 的 `SOURCES`)。`brief` **不是**合法值,传了会被
  `choices` 拒绝;盘前 brief 决策是 schema v2 计划行,由 brief postflight
  写入,不经过 `record`。
- **harness 约定**:`examples/openclaw/SKILL.md`、
  `examples/claude-code/CLAUDE.md`、`examples/codex/AGENTS.md` 各自示范
  `clawock record --source openclaw|claude|codex` 同一条命令 —— 一个账本、
  一个命令、每个 harness 都调它。
- **校验路由**(ledger.py `validate_decision`):只看 `schema_version == 0`
  —— v0 行一律路由到 `validate_mind_record`,不论 `source` 是
  `conversation / openclaw / claude / codex / cli` 中的哪一个(`source` 的合法值
  由 mind 校验自己检查);v2 计划行走原校验器。`schema_version` 0 专属心智记录,
  所以不需要再用 `source` 区分。
- **落点**:`<workspace>/memory/decisions.jsonl`,v0 心智记录与 v2 计划行
  共存于同一文件(ledger.py `LEDGER`)。

## 面板：DSH Decision Mind（只读成交轨迹）

注册为 DSH 对话视图环里的 "Decision Mind" 标签页（`conversation.view` slot，
id=`decision-studio`）。每笔 `portfolio.json` 的真实成交是一条可展开的轨迹：
当时计划 → 实际成交（同向/反向）→ T+1 收盘 → 已实现与当前浮动盈亏。
没有当日计划的成交显式标注。按 HK/US 分组，并提供全部、无当日计划、卖出复盘、有当日计划四个过滤。

浏览器通过 Typert remote 服务 `clawockStudio` 的 `traces` 读取成交及配对证据；
入口 `src/index.ts`，只读加工在 `src/ledger.ts`，绘制在 `src/client.ts`。
工作区取 `$CLAWOCK_WORKSPACE`，缺省为 dsh 进程 cwd（`workspaceOf()`）。
界面沿用 DSH 宿主的浅色/暗色主题与角色色令牌，样式真源是 `src/styles.module.css`，
不再是独立三视图或固定强调色。插件没有 `decision-mind-ledger.html` 静态页面。

Decision Mind 的成交轨迹只读；侧栏 provider 面板是另一个入口，可以控制 agent-dispatch
任务队列。能力和安装细节以 [插件 README](../examples/dsh/packages/clawock-dsh/README.md) 为准。

## 已实现 / 未实现

**已实现**:

- `clawock record` 全链路:校验、冻结、原子追加;schema v0 心智记录已
  真实写入 `memory/decisions.jsonl`(如 `dec-conversation-*` 行)
- `mind`/`emotion` 落账后无更新路径(冻结);bear 反方与 invalidation 强制
- 执行标记:无操作动作落账即 `followed`;下单动作经
  `clawock mark-followed` 标记(execution.py 按 decision_id 定位)
- DSH 只读成交轨迹面板;openclaw/claude-code/codex 三个 harness 文档统一
  走 `clawock record --source <harness>`

**未实现(如实声明)**:

- **自动对账没有实现**。`settle_decisions`(ledger.py)只结算带
  `plan_date`/`evaluation` 的 v2 计划行;v0 心智记录没有这两个字段,在
  该函数开头就被跳过。`accounting` 块由 record.py 写入后没有任何代码
  读取或更新它——`outcome.grade` 永远停在 `pending`,不存在
  `correct|wrong|mixed` 的判定。旧文档「事后自动对账」的承诺不成立。
- **校准未实现**:`build_record` 不写 `confidence_bin`,也没有任何统计
  代码读取它;「我的 0.65 准不准」暂无答案。
- 心智记录不参与 v2 的 episode/T+1 计分。

## 样例(真实落库记录,memory/decisions.jsonl)

```
00100 MINIMAX-W · 2026-08-16 · action reject · 0.65 · fundamental
Bull   营收 +159% YoY,入通/海外霸榜/高盛三催化叙事仍在
Bear   净利率 -2368%、负债率 343%、每股净资产 -24.37;z+2.8σ 情绪极值反转
Thesis 高增长救不了资不抵债,情绪反转期先活下来
失效   缩量企稳(量能低于前日50%) + 连续2日不创新低 + 站回 HK40
情绪   averaging_down —— 浮亏 -40% 的摊本冲动被明确压过——忍住没加
执行   followed(无操作判定被遵守)· accounting.outcome.grade=pending(无自动对账)
```
