# Decision Map

**What it is.** One page that puts 741 decisions and the five registered signal
histories on the same table: for each decision, the signal values as of that
decision's own plan date; for each signal, the decisions it was standing next to
and what happened afterwards.

**What it is not.** It writes no decision, changes no ledger contract, and
promotes no correlation into an activation. `usable_for_decisions` gates are
untouched. A signal appearing next to `cut` may have caused the cut, or may
simply have been on the table that day; the page says so where it shows the
matrix.

## Reading it

### Coverage is the first number, not the last

A source that could see 12% of the book's decisions is **not a source with a
weak effect — it is a source that was not there**. Measured on 2026-08-30, no
registered source can see more than 42% of the decisions and most see 11–20%,
because the ledger starts on 2026-05-17 and the histories start later (quant
06-11, factor and peer 07-24, news 07-26).

### Snapshot age

The join is one-sided and bounded: a snapshot is used only when its `as_of` is
at or before the plan date and within `MAX_SNAPSHOT_AGE_SESSIONS` (5) of it.
Without that, the drawer would show a full row of values for every decision and
quietly attribute July's factor regime to a June judgement. Every card publishes
the median and maximum age it actually used; on the live data the median is 0 —
when the join fires, it fires on the same session.

## The payload

`assets/data/decision_map.json`, schema 1, written by `clawock decision-map`.

**Columnar, twice over.** Repeating up to 33 signal names inside each of 741
entries — and then 11 field names on top — was 80% of the payload and none of
the information. `signal_order` and the `decisions` field names name each column
once; every decision is a position in parallel arrays, and
`decision_snapshots[i]` is the signal row for `decisions.decision_id[i]`.

**Degradation.** The budget is 200,000 bytes, self-imposed so the page loads on a
phone — the same reason `dashboard.json` has a hard gate at that number. The
chain drops prose first (recoverable from the ledger), then the *signal row* of
older decisions (not the decisions themselves, which would break their own
timeline markers), then the timelines. The aggregates are last because they are
the only part computed from all 741 decisions: dropping them would change the
numbers rather than the amount of detail. The level in force is always printed
in the page's status bar — a page that silently shows less than it says it does
is worse than one that shows a banner.

Measured on 2026-08-30: 175,135 bytes at `recent_decisions_only` — every
decision's metadata and timeline, with the signal snapshot kept for the most
recent 300.

## Where it runs

`clawock decision-map` runs immediately after `dashboard-build` in
`_harness_common`, on the same cadence, and `brief_postflight` stages the output.

It is deliberately **not** part of the dashboard's generation.
`clawock.publish.outputs` owns a four-file write set that is swapped in
atomically; a fifth file whose failure is survivable does not belong inside a
contract whose whole point is that all four land or none do. The map is a
read-only view — a broken one costs a page, not a number — so its return code is
recorded and never gates the publish. This is a deliberate deviation from the
PRD (#1191), which asked for it to be part of `dashboard-build`.

---

## The PRD this was built from

Kept below, unedited, so the built thing can be read against what was specified —
including the two places it deliberately diverges (the write-set ownership above,
and the payload budget, which the PRD sized for five signals when there are now
thirty-three).

# Decision Map — PRD + Roadmap

> 写在 issue 里之前的内部稿件。最终落到 KCNyu/clawock 的两份 issue:
> - **#PRD**:产品需求文档 + 数据契约 + 验收
> - **#ROAD**:阶段切分 + 每阶段产物 + 触发条件

---

## 1. 背景与目标

### 1.1 现状(为什么现在做)

clawock 现在的产物分散在 8 类 JSON 文件里,各自有界面但**互不连**:

| 数据 | 文件 | 已有视图 |
|---|---|---|
| 决策 | `memory/decisions.jsonl` (741 行) + `assets/data/dashboard.json` | overview tab 最近 N 条 + weekly review |
| 信号快照(quant) | `assets/data/quant_signals_history.jsonl` (58 行) | signal-panel 里 rank IC |
| 信号快照(t0) | `assets/data/t0_setups_history.jsonl` (1177 行) | signal-panel 里 rank IC |
| 信号快照(factor) | `assets/data/cross_sectional_factor_history.jsonl` (24 行) | signal-panel 里 rank IC |
| 信号快照(peer) | `assets/data/peer_residual_history.jsonl` (24 行) | signal-panel 里 rank IC |
| 信号快照(news) | `assets/data/news_evidence_history.jsonl` (25 行) | signal-panel 里 rank IC |
| 宏观/事件 | `assets/data/macro.json` + `em_news.json` | brief 里的一段 |
| 业绩 | `memory/bars/` 逐日 / `assets/data/shadow_portfolio.json` | equity 曲线 |

**已知问题**(08-29 memory):
- **信息层永远不可观测**(`#1132`):`information_overlay` cohort = 空,dashboard 显示 `warming_up` 像在预热
- **composite factor 排反**(`#1133`):t1 / t5 IC 是 −0.09 / −0.20,无法判断是 defect 还是 regime
- **信号面板只到截面层**(`#1131` PR 已合):不等同于"决策当时看到了什么"

**用户的痛点**:
- "我想知道 LLM 做某个决策时,看到了哪些信号"
- "哪些信息源对哪类 action / 哪个 horizon 真的有正向作用"
- "某条消息出现后,所有后续决策有没有跟着走、走得对不对"

### 1.2 目标(不是什么 / 是什么)

**不是**:
- ❌ 不是把现有 8 张卡片重排
- ❌ 不是引入新的信号源
- ❌ 不动决策合约 / 不动 pre-registration 契约(`peer_residuals.load_rule_config`)
- ❌ 不新增每日 cron

**是**:
- ✅ 在 site/ 加一个 **Decision Map** tab,跟 overview / decision-deck-v8 并列
- ✅ 把"决策 × 信号快照 × 时间 × 后续收益"四维数据,投影到一个可下钻的交互面
- ✅ 自包含:每条决策旁边列"当时该标的看到了哪些信号、各信号的值、来源时点"
- ✅ 倒排视角:每个信号源一个卡片,显示"它在哪些决策中被引用了、被引用后表现如何"
- ✅ 时间线:每只票一条时间线,标出信号出现点 / 决策点 / 结算点
- ✅ 可筛选:按 ticker / 时间窗 / horizon / driven_by / 信息源

### 1.3 用户故事

| 谁 | 在什么场景下 | 要回答什么 | 用什么 view |
|---|---|---|---|
| kcn 在评审一条 buy 决策 | "这条决策合理吗" | 当时 news_signed_score 多少 / factor composite 多少 / RSI 是否极端 | **决策详情面板**(右抽屉) |
| kcn 在做月度回顾 | "哪条消息源真的有用" | 每条 news 事件 → 后续被多少决策引用 → t5/t20 表现如何 | **信息源倒排**(顶部 tab) |
| kcn 在审一个新提的 thesis | "类似情况下以前怎么走" | 这只票过去 6 个月所有 decision + 当时所有信号快照 | **时间线**(底部) |
| kcn 在跟 model 对账 | "model 用了哪些信号" | 一条 decision 的 rationale 里所有关键词,反向追溯到 signal value | **决策 × 信号矩阵**(中部主网格) |

---

## 2. 范围(scope 内 / scope 外)

### 2.1 Scope 内

- 静态 HTML 页面(site/decimap/index.html),挂在 nav 上
- 一个 Python 投影脚本(`src/clawock/publish/decision_map.py`),生成 `assets/data/decision_map.json`
- 接 `clawock dashboard-build` 流水线(同一个 build 调用)
- 数据全部从已有的 `assets/data/*` + `memory/*` 读取,**不接新数据源**
- 交互:筛选( ticker / 日期窗 / horizon / driven_by / 信息源 )+ 下钻(点决策 → 抽屉打开)
- payload ≤ 200KB 闸(与 overview / decision_audit 一致;超出则降级到只列 schema,不下钻)
- CI 测试:
  - 数据契约测试(每个 block schema)
  - 重生一致性测试(`clawock dashboard-build` 跑两次,带 `generated_at` 之外的字段必须 byte-identical)
  - payload 闸测试

### 2.2 Scope 外

- ❌ 新信号源 / 新数据 provider
- ❌ 实时数据更新(仍走每日 dashboard-build)
- ❌ 写决策 / 修改决策 / 写信号(只读)
- ❌ 任何动 `decision/ledger.py` 契约的改动(只读 ledger)
- ❌ 任何动 pre-registration(`peer_residuals.load_rule_config`)的改动
- ❌ 跨 runtime 数据合并(只在 clawock workspace 内部)

---

## 3. 信息架构

Decision Map tab 是一个三层结构:

```
┌─────────────────────────────────────────────────────────────────┐
│ TAB: Decision Map                                                │
├─────────────────────────────────────────────────────────────────┤
│ HEADER(筛选条)                                                  │
│  [Ticker ▾] [Date range ▾] [Horizon ▾] [Driven by ▾] [Source ▾]│
├─────────────────────────────────────────────────────────────────┤
│ ROW A: 信息源倒排                                                │
│  ┌──news.signed_score──┐ ┌──factor.composite──┐ ┌──rsi14──────┐ │
│  │ t1: +0.19           │ │ t1: −0.09          │ │ t1: −0.19   │ │
│  │ used in 4 decisions │ │ used in 0          │ │ used in 12  │ │
│  │ win rate t5: 67%    │ │ win rate t5: NA    │ │ win rate t5 │ │
│  └─────────────────────┘ └────────────────────┘ └─────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ ROW B: 决策 × 信号矩阵(主网格)                                  │
│  列 = 决策(action=buy/trim/hold/cut)                            │
│  行 = 信息源(factor / quant / news / peer / t0)                  │
│  每个单元格 = 该类 action 下,该信息源当时的                     │
│     - 中位值 / IQR / 计数                                        │
│     - 该信息源驱动的 settle performance                          │
├─────────────────────────────────────────────────────────────────┤
│ ROW C: 时间线(可滚动)                                           │
│  Ticker timeline:                                                │
│  ─●─────●────●──────●────●────●──                                │
│   signal news  decision buy   settle t5  decision cut  news       │
├─────────────────────────────────────────────────────────────────┤
│ RIGHT DRAWER(点决策时滑出)                                      │
│  Decision #N  ticker=00100  action=trim_on_rebound  driven_by=tech│
│  Created 2026-05-17  rationale: ...                              │
│  At that moment:                                                │
│    quant.rsi14=28.3   quant.zscore20=-1.87   trend_on=null        │
│    t0.range_pos=466.7  grade="追高低质"                          │
│    factor.composite=NA  (composite started 2026-07-24)            │
│    news: 0 events (or list events with signed_score)             │
│  Forward returns: t1=+0.49%   t5=0%   t20=−11.7%                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 数据模型(JSON 输出 schema)

### 4.1 `assets/data/decision_map.json` (主载荷)

```json
{
  "schema_version": 1,
  "generated_at": "<UTC ISO>",
  "as_of": "<canonical bar date>",
  "filters": {
    "tickers": ["00100","02208",...],
    "date_window": {"start":"2026-05-01","end":"2026-08-29"},
    "horizons": ["t1","t5","t20"],
    "driven_by": ["technical","factor","sentiment","peer","risk_rule","catalyst","macro"],
    "sources": ["quant","t0","factor","peer","news","macro"]
  },
  "info_source_cards": [
    {
      "source_id": "news.signed_score",
      "source_kind": "news",
      "registered_sessions": 18,
      "ic": {"t1": +0.09, "t5": +0.19, "t20": null},
      "ic_ci95": {"t1": [-0.05,+0.23], "t5": [+0.039,+0.345], "t20": null},
      "pbo": {"t1": 0.61, "t5": 0.64, "t20": 0.13},
      "decision_coverage": {
        "buy": {"count": 0, "win_rate_t5": null, "median_t5_pct": null},
        "trim": {"count": 2, "win_rate_t5": 0.5, "median_t5_pct": +0.3},
        "hold": {"count": 5, "win_rate_t5": 0.6, "median_t5_pct": +0.0},
        "cut": {"count": 1, "win_rate_t5": 1.0, "median_t5_pct": -0.5}
      },
      "rationale_keywords": ["earnings","guidance","forecast"],
      "notes": "reuses #1131 signal-panel table; adds decision-cohort axis"
    },
    ...
  ],
  "decision_signal_matrix": {
    "schema_version": 1,
    "rows": [
      {
        "source_id": "quant.rsi14",
        "by_action": {
          "buy":    {"count": 0, "median_value": null, "iqr": null},
          "trim":   {"count": 8, "median_value": 28.0, "iqr": [22, 35]},
          "hold":   {"count": 53,"median_value": 48.0, "iqr": [40, 58]},
          "cut":    {"count": 7, "median_value": 24.0, "iqr": [19, 28]}
        },
        "by_outcome": {
          "win_t5":  {"count": 12,"median_value": 35.0},
          "loss_t5": {"count": 4, "median_value": 26.5}
        }
      },
      ...
    ]
  },
  "ticker_timelines": {
    "00100": {
      "ticker": "00100",
      "events": [
        {
          "ts": "2026-05-17T08:00:00+08:00",
          "kind": "decision",
          "ref": "dec-9a8c454130f2",
          "summary": "trim_on_rebound  price_below $730",
          "driven_by": "technical",
          "rationale_keywords": ["trim","rebound","$730","hold"],
          "outcome": {"t1": +0.49, "t5": 0.0, "t20": -11.7}
        },
        {
          "ts": "2026-05-17T09:30:00+08:00",
          "kind": "snapshot",
          "source_id": "quant.rsi14",
          "value": 28.3
        },
        ...
        {
          "ts": "2026-05-20T16:00:00+08:00",
          "kind": "settlement",
          "ref": "dec-9a8c454130f2@t5",
          "benefit_pct": 0.0
        },
        {
          "ts": "2026-06-05T...",
          "kind": "news",
          "event_id": "evt_xxxxx",
          "title": "...",
          "signed_score": -0.42
        }
      ],
      "price_overlay": {
        "start_date": "2026-05-01",
        "end_date": "2026-08-29",
        "series": [
          {"date": "2026-05-01", "close": 480.0},
          ...
        ]
      }
    },
    ...
  },
  "decision_lookup": {
    "dec-9a8c454130f2": {
      "decision_id": "dec-9a8c454130f2",
      "ticker": "00100",
      "action": "trim_on_rebound",
      "plan_date": "2026-05-17",
      "driven_by": "technical",
      "rationale_full": "...",
      "confidence": 0.65,
      "at_snapshot": {
        "quant.rsi14": 28.3,
        "quant.zscore20": -1.87,
        "t0.range_pos": 466.7,
        "t0.grade": "追高低质",
        "factor.composite": null,
        "factor.coverage_pct": null,
        "peer.triggered_rules": null,
        "news.events_72h": 0
      },
      "outcomes": {"t1": +0.49, "t5": 0.0, "t20": -11.7}
    },
    ...
  },
  "tickers": ["00100","02208","02513","03032","03033",...],
  "as_of_session_count": 22,
  "size_bytes": 178543,
  "payload_cap_bytes": 200000
}
```

### 4.2 字段语义

- `generated_at`:UTC ISO,must be `generated_at` key per memory (`clawock-open-issue-batch-2026-08-29.md` 三方法学之一)
- `as_of`:决策/快照的"事实截止日"= 最新 bar 日期
- `info_source_cards[].decision_coverage`:这是新轴,signal-panel 没有 — 把"该信息源在每类 action 的决策中出现过几次+对应的 win_rate"
- `decision_signal_matrix.rows[].by_outcome.win_t5`:settled 决策在该 source 上的中位值 — 用来回答"信号值高时,win 率高不高"
- `decision_lookup[decision_id].at_snapshot`:**新投影** — 一条决策的"信号足迹",从 ledger 行 + 同 ticker 同 session 的 quant/t0/factor/peer/news 快照取
- `ticker_timelines`:每只票一条时间线,events = decision + snapshot + settlement + news

### 4.3 不导出什么

- 不导出原始 rationale 全文超过 200 字符的部分(只导 `rationale_keywords[]`)
- 不导出 `evaluation.execution_price`(内部分析用,不进 dashboard)
- 不导出 `signal_provenance` 整块(PII / 模型原文不进 payload)

---

## 5. 数据来源与 join 规则

| 输出字段 | 数据源 | join key | 时间窗 |
|---|---|---|---|
| `decision_lookup[*]` | `memory/decisions.jsonl` | `decision_id` | 全部 |
| `decision_lookup[*].at_snapshot.quant.*` | `assets/data/quant_signals_history.jsonl` | `ticker` + `as_of ≤ plan_date ≤ as_of + 1d` | 决策当天 |
| `at_snapshot.t0.*` | `assets/data/t0_setups_history.jsonl` | 同上 | 同上(去重 by ticker+signal)|
| `at_snapshot.factor.*` | `assets/data/cross_sectional_factor_history.jsonl` | 同上 | 同上 |
| `at_snapshot.peer.*` | `assets/data/peer_residual_history.jsonl` | 同上 | 同上 |
| `at_snapshot.news.events_72h` | `assets/data/news_evidence_history.jsonl` | 决策前 72h 内 ticker 命中 events | 决策前 72h |
| `outcomes.t1/t5/t20` | `memory/decisions.jsonl[evaluation.benefit_*]` | `decision_id` | decision 自带 |
| `ticker_timelines.events[*]` | 同上四类 | `ts == event timestamp` | 全部 |
| `ticker_timelines.price_overlay` | `memory/bars/<ticker>.json` | ticker + date | 时间窗内 |
| `info_source_cards[*].ic` | `clawock signal-panel` (已有 PR #1131) | 复用 PR #1131 输出 | 同 #1131 |
| `decision_signal_matrix.rows[*].by_action[*]` | `memory/decisions.jsonl` × 同 ticker 同 session 信号快照 | `ticker + session_date == plan_date - 1` | 决策前最近 session |
| `decision_signal_matrix.rows[*].by_outcome.win_t5` | `memory/decisions.jsonl[evaluation.benefit_t5_pct > 0]` × 同 ticker 同 session 信号快照 | 同上 | 同上 |

### 5.1 去重规则

- `t0_setups_history` 一天会写 ~14 个盘中快照(per memory);`at_snapshot.t0.range_pos` **必须按 (session,ticker,signal) 去重**,否则一个 tick 一天进 14 次,会把 IC 一部分喂给"采样频率"而不是信号本身(per memory `clawock-open-issue-batch-2026-08-29.md`:`t0_setups_history` 的坑)
- `news_evidence_history` 同 ticker 一天可能多 events:`at_snapshot.news.events_72h` 取 count + 中位 signed_score + max(|signed_score|)

### 5.2 Missing data 约定

- `at_snapshot.factor.* = null` 当 factor composite 在 plan_date 之前还没注册(`as_of ≤ registered_at`)
- `at_snapshot.peer.* = null` 当 peer 还没触发
- 显示端:卡片里显示 `—` 而非 `null`,避免被误读为"信号=0"

---

## 6. 交互规格

### 6.1 顶部筛选条

5 个独立筛选:
- **Ticker**:多选 chip(只显示出现在 ledger 里的)
- **Date range**:两个 date input,默认 [plan_date 最早, as_of]
- **Horizon**:`t1 / t5 / t20` 多选 chip
- **Driven by**:`technical / factor / sentiment / peer / risk_rule / catalyst / macro` 多选 chip
- **Source**:`quant / t0 / factor / peer / news / macro` 多选 chip

每个筛选变化 → 重新跑客户端计算(client-side filter,不重 build):
- `info_source_cards` 的 IC/PBO **不变**(全期)
- `decision_coverage`、`by_action`、`by_outcome` 按筛选重算
- `decision_lookup` 按筛选过滤
- `ticker_timelines` 按筛选过滤

### 6.2 ROW A:信息源倒排卡

每张卡:
- 左上:信号名( `quant.rsi14` / `factor.composite` / `news.signed_score` )
- 中:三 horizon 的 IC + CI95 + PBO(从 #1131 输出取)
- 下:`decision_coverage` 表格:4 行 (buy/trim/hold/cut),列 = count / median_t5_pct / win_rate_t5
- 卡底:展示 "在 N 条决策里出现",点击切到 ROW B 高亮该决策

交互:点击卡 → ROW B 滚动到该行,ROW C 时间线切换到该信号关联的 ticker

### 6.3 ROW B:决策 × 信号矩阵

主网格:
- 列 = 4 类 action(buy / trim / hold / cut)
- 行 = 信息源( `quant.rsi14` / `quant.zscore20` / `t0.range_pos` / `factor.composite` / `peer.triggered_rules` / `news.signed_score` / ... )
- 单元格 = `{count, median, iqr, win_rate}` 四元组
- 单元格颜色编码:count 大 + win_rate > 0.5 = 绿色高亮;count > 0 但 win_rate < 0.5 = 浅红;count=0 = 灰

交互:点击单元格 → 打开 ROW C 时间线 + 右抽屉列出该 (action × source) 的所有决策

### 6.4 ROW C:时间线

每只 tick 一条 row:
- 横轴 = 时间
- 事件点 = 三色:
  - 红 = decision (按 action 类型再分深浅)
  - 蓝 = signal snapshot
  - 绿 = settlement
  - 紫 = news
- 下面叠价格曲线(`memory/bars/<ticker>.json` close)
- 鼠标 hover 事件点 → tooltip 显示该事件简述
- 点击 → 右抽屉打开

### 6.5 右抽屉(Decision 详情)

打开条件:点击任意决策点(ROW C 时间线 / ROW B 矩阵 / 直接搜索)
显示内容:
- 顶部:decision 标题( ticker + action + price condition + date )
- 中部:`at_snapshot` 表(全 5 类信号在该决策当天的值)
- 底部:`outcomes` 表格(t1/t5/t20 的 benefit_pct + 当时 plan_date + 真实结算日期)
- 折叠:`rationale_keywords` 与 `rationale_full` 的对比(让用户看哪些关键词触发了模型)

### 6.6 全屏分屏约束

- 视口 ≥ 1280px:三栏(ROW A 1/4 + ROW B 1/2 + ROW C 1/4)
- 视口 1024-1279px:ROW A 顶部 + ROW B 主体 + ROW C 折叠
- 视口 < 1024px:tab 切换(每 ROW 一个 tab)

---

## 7. payload 预算与降级

memory (`clawock-size-gate-measured-the-wrong-bytes.md`) 教训:**payload 闸量的是字面大小,不是语义**。

### 7.1 预算

| 段 | 当前样本 | 估算(10×数据) | 闸 |
|---|---|---|---|
| `info_source_cards` | ~10KB | ~20KB | 30KB |
| `decision_signal_matrix` | ~30KB | ~60KB | 100KB |
| `decision_lookup` 741 行 | ~120KB | ~500KB | 200KB ← **超** |
| `ticker_timelines` 30 只票 | ~80KB | ~250KB | 200KB ← **超** |
| 合计 | ~240KB | ~830KB | **200KB** |

### 7.2 降级顺序

1. **首选**:裁剪 `rationale_keywords` 数组长度(每条决策 ≤ 8 个)
2. **次选**:`ticker_timelines.price_overlay` 限制到 ≤ 90 个交易日 / 票
3. **再次**:`ticker_timelines.events[]` 每只票 ≤ 60 个事件,优先保留 decision + settlement
4. **最后**:移除 `ticker_timelines` 整个段,只保留 `decision_lookup` + `info_source_cards` + `decision_signal_matrix`

### 7.3 重生一致性

`clawock dashboard-build` 跑两次,`generated_at` 之外的字段必须 byte-identical(对 `overview.json` / `dashboard.json` 已有同类测试,这次加 `decision_map.json` 同款测试)。

---

## 8. 验收

### 8.1 数据契约测试(`tests/test_decision_map_contract.py`)

```python
def test_decision_map_payload_shape():
    payload = json.loads((Path("assets/data/decision_map.json")).read_text())
    assert payload["schema_version"] == 1
    assert "generated_at" in payload  # per memory: 时间戳字段必须叫 generated_at
    for s in payload["info_source_cards"]:
        for h in ("t1","t5","t20"):
            assert h in s["ic"]
            assert h in s["ic_ci95"]

def test_at_snapshot_covers_all_5_sources():
    """每条 decision 在 lookup 里有 5 类信号,缺失显式 null,不静默缺席"""
    payload = json.loads(...)
    for d in payload["decision_lookup"].values():
        snap = d["at_snapshot"]
        for src in ("quant","t0","factor","peer","news"):
            assert src in snap

def test_t0_setups_deduped_per_session_per_ticker():
    """memory 教训: t0_setups_history 必须按 (session, ticker, signal) 去重"""
    # 检查 build 脚本里的去重逻辑有单测

def test_payload_size_within_cap():
    payload = ...read_text()
    assert len(payload.encode("utf-8")) <= 200000
```

### 8.2 重生一致性测试(`tests/test_decision_map_rebuild.py`)

```python
def test_rebuild_byte_identical_excluding_timestamp():
    """两次 build 出来的文件去掉 generated_at 后必须 byte-identical"""
    p = Path("assets/data/decision_map.json")
    first = json.loads(p.read_text())
    # rebuild
    subprocess.run(["clawock","dashboard-build"], check=True)
    second = json.loads(p.read_text())
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second
```

### 8.3 E2E 测试(`tests/dashboard_decision_map.spec.js`)

- 加载 `/decimap/`,筛 ticker=00100,验证 ROW A 的卡片数和 snapshot 一致
- 点 ROW B 单元格,验证抽屉打开且 at_snapshot 字段非全 null
- 切 horizon=t5,验证 by_outcome.win_t5 重新计算
- 视口 < 1024 时,验证 tab 切换可用

### 8.4 与既有闸的相容

- `decision/ledger.py` 契约:**不碰**
- `peer_residuals.load_rule_config`:**不碰**
- `dashboard 200KB payload 闸`:**沿用**(`serialize_dashboard_payload` 加 decision_map 一支)

---

## 9. 风险与边界

### 9.1 信号面板 vs 决策地图的关系

| | signal-panel (`#1131`) | decision-map (本次) |
|---|---|---|
| 度量单位 | session × signal × ticker | decision × signal × ticker |
| 度量 | rank IC / PBO | win_rate / median / iqr |
| 时间维度 | 一个 session 一行 | 一条决策一行 |
| 样本 | 截面 | 决策子集 |
| 不下钻 | 是(只给表) | 是(给下钻) |
| 是不是 source-of-truth | 是("source 是否值得纳入决策") | 否("决策实际吃了什么") |

**两个面板互补**:signal-panel 答"这个信号源有信息吗",decision-map 答"我们用了它的哪些部分、用得对不对"。decision-map **复用** signal-panel 的 IC/PBO 字段,**不重新算**。

### 9.2 PII / 隐私

- rationale 全文是模型原文,可能含 ticker-specific 的敏感性
- **导出的 `rationale_full` 必须先过**:脱敏规则 = 移除 ticker / 价格 / 金额字段(只保留 hash)
- 或者**只导 keywords**(默认):从 rationale 用 `jieba` 切词 + 关键词提取(top-8)

### 9.3 计算成本

- `decision_lookup[*].at_snapshot` join 5 类信号 × 741 行 = 最多 3705 次 dict lookup,可接受
- `ticker_timelines.price_overlay` 每只票 ≤ 90 交易日 × 30 票 = 2700 close 点,序列化后 ~22KB

### 9.4 已知盲区

- `news.signed_score` **当前样本只有 18 sessions**(per memory `#1131`),cell 里 count 多数 = 0;UI 要明确显示 "n=0,no data"
- `factor.composite` **2026-07-24 才注册**,6 月份的决策都缺 factor 快照;UI 显示 "factor not registered at that time"
- `peer.triggered_rules` 当前**几乎空**(PR #1130 端点修了但 flag 还关,per `#1122`)

---

## 10. Roadmap(阶段切分)

### Phase 1:骨架 + 决策详情(2-3 PR,1 周)

**触发条件**:无(立即可做)

**产物**:
- `src/clawock/publish/decision_map.py`(~400 LOC)
- `assets/data/decision_map.json` schema v1
- 接 `clawock dashboard-build` 流水线
- `site/decimap/index.html` 静态页(只显示 ROW C 时间线 + 右抽屉)
- `tests/test_decision_map_contract.py` + `tests/test_decision_map_rebuild.py`
- 文档:`docs/decision-map.md`

**验收**:`clawock dashboard-build` 跑通 + 打开 `/decimap/` 能看到 00100 的时间线 + 点决策 → 抽屉显示 at_snapshot

**不做**:ROW A 信息源倒排卡(只显示 IC 字段,空的赢率卡)、ROW B 矩阵(本阶段只渲染 grid,内容是下一阶段)

**依赖**:无

### Phase 2:信息源倒排卡 + 矩阵(2 PR,1-2 周)

**触发条件**:Phase 1 合并

**产物**:
- ROW A 全功能卡(8-10 个信号,每个 IC + PBO + decision_coverage 表格)
- ROW B 决策 × 信号矩阵(8 行 × 4 列 = 32 单元格,每格 count/median/iqr/win_rate)
- 筛选条全部 5 项接通
- payload 闸测试 + 降级逻辑跑通

**验收**:
- 选 ticker=00100 + horizon=t5 + source=quant → ROW A 只剩 4 张 quant 卡
- 矩阵里"trim"列的 median 与 raw data 一致
- payload < 200KB

**依赖**:Phase 1

### Phase 3:交互细节 + E2E + 移动端(1-2 PR,1 周)

**触发条件**:Phase 2 合并

**产物**:
- 矩阵单元格颜色编码 + 点击下钻
- 抽屉 `rationale_keywords` vs `rationale_full` 对比视图
- E2E test(`tests/dashboard_decision_map.spec.js`)
- 移动端折叠
- payload 降级到三级全跑通

**验收**:
- E2E 通过(playwright)
- 视口 < 1024 时 tab 切换工作
- 强制 payload 超 200KB 时降到第 3 级,UI 顶部显示降级提示

**依赖**:Phase 2

### Phase 4:与 #1131 signal-panel 字段复用 + KPI 收敛(1 PR,可选)

**触发条件**:Phase 3 合并

**产物**:
- ROW A 的 IC/CI95/PBO 字段改为从 `signal-panel` 输出取,**不重复计算**
- 加 `kpi:decision_count / kpi:active_signal_coverage / kpi:signal_to_decision_ratio`
- 顶部摘要一行:`N decisions over N sessions · M signals referenced · KX decision-to-signal coverage`

**验收**:IC/PBO 字段值与 `signal-panel --as-of` 输出 byte-identical

**依赖**:Phase 3 + #1131 PR 已是基线

### Phase 5:与 signal_panel 双向回写 + 历史回顾(可选,远期)

**触发条件**:Phase 4 合并 + 用户多次反馈需求

**产物**:
- "前 X 期表现"对比视图
- 与 `information_overlay` (`#1132` 修后)字段打通
- 与 `factor.composite` (`#1133` 修后) per-factor 维度打通

**依赖**:Phase 4 + #1132 + #1133 完成

---

## 11. 不在 roadmap 的(显式排除)

- ❌ "决策生成器"——给 LLM 反向提示用哪些信号(超出 dashboard 范围)
- ❌ "实时信号推送"——看板不该做推送
- ❌ "跨账户/跨用户聚合"——CLAWOCK_PRODUCT_GOAL.md 明确是单账户
- ❌ "信号回放 / what-if"——超出 dashboard 范围,该走 walk-forward 工具
- ❌ "signal-panel 完全替换"——decision-map 是补充,不是替代(per 9.1)

---

## 11.5 反哺路径合规矩阵(本节为 kcn 拍板而设,08-29 第二次修正)

决策地图的产出 = 「信号 × 决策 × 结算」三维投影。用户提了一个更深的问题:**这些数据能反哺每日决策吗?我们本身就需要调整决策因子,让 input 自进化而不是改 runtime**。这其实是 clawock 产品的**核心价值**,不是越界 — 但要分清楚 input 维度 vs runtime 维度。

完整论证见 memory `clawock-input-evolution-boundary.md`(08-29 写入,纠正早期 `clawock-self-improving-boundary.md` 的误读)。

### 核心判据:input 进化 vs runtime 进化

| | Input 维度 ✅ | Runtime 维度 ❌ |
|---|---|---|
| 改的是什么 | **静态 artifact 文件**(JSON / JSONL / 数字 / 文本) | **LLM 行为**(prompt / tool 权重 / agent 循环) |
| 改的是谁的状态 | clawock 内部(input 数字、weight、threshold) | clawock 之外的 runtime(model prompt / tool registry / agent loop) |
| 回滚方式 | git revert / 改 JSON / 删 `signal_provenance` 一行 | 需要重启 model / 改 agent 循环(不可 git 化) |
| 产物形式 | 可被 git diff、可被 CI 校验 | runtime state,clawock 看不到也管不了 |
| 历史路径 | `thesis_registry.py drift` / `signal-panel` / `research_provenance.py` / `quant_signal_review` | 没有历史路径,会撞 `peer_residuals.load_rule_config` 红线 |

满足 3 条 = input 维度,可做。任意一条不满足 = 跨进 runtime,禁止。

---

### Level 1 — Read-side 反哺 ✅ 完全合规

**做法**:决策地图 PRD(#1189-#1195)展示「信号 → 决策 → 结算」反向链路。

**为什么合规**:不写 / 不改 / 不跨进 runtime,只读 ledger + 5 类信号快照。

**已落到 issue #1189-#1195**,Phase 1 可立刻做。

---

### Level 2 — Write-side 反哺 = 把 at_snapshot 写回 ledger 锚点 ✅ **部分合规**(原判越界,08-29 纠正)

**做法**:决策合约加 `signal_snapshot_ref` 字段,指向决策当时的 at_snapshot。

**早期判越界的理由**(已纠正):
- ❌ 误以为这是 "self-improving 越界" — 错,这是 **input 维度写静态锚点**
- ✅ 真正的问题是:动 `decision/ledger.py` 的 schema 改动需要回填 + 测试钉兼容性

**重新判定的合规边界**:
- `signal_snapshot_ref` 是**静态锚点**(决策时点的 reference,数字本身不变)
- 它**不动** decision 的 rationale / action / 后续判断
- 它让 ledger 追溯变可观测,这是 Level 1 的延伸

**例外规则**(必须满足才合规):
- 写回 ledger 的字段必须是**只读事实**(数字、ref、snapshot),不能写"基于这个 snapshot 的判断"/"自调权重"等决策性字段
- 需要 kcn 拍板 + schema migration plan + 测试钉死兼容性

---

### Level 3 — Inference-side 反哺 = brief 看到「上一轮用过的信号表现」 ⚠️ 半合规,三道闸

**做法**:brief 生成时 prompt 注入一段「过去 20 条决策 + signal-panel 最近 IC」。

**判定**:这是 **input 维度**(把已发布的数字作为 context),但需要闸**防止它跨进 runtime**(不让数字驱动决策路径)。

**三道闸必须装**:

1. **闸 A — context budget**:注入 context 只加不减,必须按 memory `clawock-injected-context-has-no-budget.md` 规则记账
2. **闸 B — 时间戳命名**:字段必须叫 `generated_at`(memory `clawock-open-issue-batch-2026-08-29.md` CI 规则)
3. **闸 C — 不作为依据**:brief prompt 里加硬约束 "Decisions must not be justified by the IC numbers in the context block; IC numbers are read-only signals for human review"

**判定**:合规形式 = 让模型**看到**数字但不让数字**驱动**决策路径。

---

### Level 4 — Auto-rebalance 反哺 = 改 `driven_by` 路径 ❌ 越界

**做法**:model 不动,但 `decision/ledger.py` 加逻辑,根据 signal-panel 自动把 `driven_by: technical` 改为 `driven_by: factor`。

**为什么越界**(跨进 runtime 维度):
- memory `clawock-driven-by-canonical-risk-rule.md`:`driven_by` 必须来自 risk rule,**不能来自信号表现**
- memory `clawock-add-side-gate-structurally-closed.md`:加仓闸有结构约束,不是「如果 IC 高就开」
- 这是**自动搜索**,正是 memory `clawock-open-issue-batch-2026-08-29.md` 反复警告的「仓库拒绝的搜索」
- 改的是 decision 的归因路径(runtime 决策路径),不只是 input

**例外**:禁止。

---

### Level 5 — Self-tuning 模型反哺 ❌ 绝对越界

**做法**:LLM 自己改 prompt / 改工具权重 / 改 next-action。

**为什么绝对越界**:
- product-goal 原文 "clawock must not become a **model client, agent runtime, or agent launcher**"
- 改的是 model / agent 循环本身,跨进 runtime 维度
- 越过这条线 = clawock 变成第二个 runtime,产品定位崩

**例外**:禁止。

---

### Level 6 — Input 维度的自进化 ✅ **产品核心价值**(新发现,08-29 补)

**做法**:决策因子、thesis、research surface、信号权重**在受闸条件下自适应**。

这就是 kcn 描述的产品形态,**clawock 已经在做**:

| 模块 | 形式 | 闸 |
|---|---|---|
| `thesis_registry.py drift` | thesis 文档自适应 | evidence-driven drift gate |
| `signal-panel` | 测信号 IC + PBO | CI 闸 + weight 不自动调 |
| `research_provenance.py` | 研究产物喂回 brief | artifact 合法性闸 |
| `quant_signal_review` | 信号衰减判定 | n>=20 解锁门 + cluster bootstrap |
| `combined_regime.py` | regime 探测 | OOS 验证 |
| `cross_sectional_factor` | 因子打分 | per-factor IC 测(#1133 修了后) |
| `#1159` Insight scoring | 信号评分闭环 | 不改决策路径 |
| `#1161` Factor tear-sheet | 因子分析 | 不改决策路径 |
| Decision 地图 PRD(#1189-#1195) | 反查 at_snapshot | 只读 |

**核心特征**:
- 进化的是 **input 内容**(数字、权重、阈值、文本)
- 进化走的路径是**显式的 artifact 文件**(JSON / JSONL),每一步可被 git diff 看到
- 进化**有闸**:每次 push、每个 PR、有显式校验测试
- 进化的产出被 `clawock <command>` 重新读取,workflow 本身不变

---

### Level 7 — Input 自进化 + LLM 决策仍由 LLM 做 ✅ **正解**(08-29 补)

**做法**:
- 决策因子 + thesis + signal weight **受闸自进化**(Level 6)
- LLM 看到这些 input,基于自己的判断做决策
- LLM 的决策路径**由外部 runtime 拥有**,不受 clawock 影响

这就是 kcn 描述的最终产品形态:

> "我们本身就需要调整我们的决策因子,我们只是让 input 进化,而不改变 runtime 本身。我们类似于一套**自进化可迁移的 workflow** / 基于各种 runtime 框架的 agent"

**关键判据**:
- clawock 输出 = **input**(数字、文本、artifact)
- LLM = **消费者**(input 端)
- LLM 自己的判断路径 = **runtime**,clawock 看不到也管不了
- clawock **只改 LLM 看到的数字**,不改 LLM

与 product-goal 的 "**install decision intelligence into any agent**" 完全吻合。

---

### 为什么 "input 进化 vs runtime 进化" 的区分是产品关键(三条理由)

#### 1. 审计性可以保留(input 维度)

input 维度的进化产物都是 **可被 git diff** 的 JSON / JSONL,审计链不断:
- 改动前:git diff 看到 input 数字变了
- 改动后:CI 跑闸,product 数字是否仍然正确
- 任何时候:git revert 就能回滚

诚实性 = 可声明(因为改动路径是显式的)。

#### 2. governed improvement 的 cost curve 是线性的(input 维度)

input 维度每加一条进化路径,闸的数量**线性增长**:
- 新因子:1 闸
- 新 signal weight 调优:1 闸
- 新 thesis 类型:1 闸
- 任意两条并存:无新闸(都走同一个 CI)

clawock 当前的 strength 在**宽度**(8 个信息层、741 行决策、25 份 plan)。**深度**(每个信号被采信多少次、被怎么采信)还是 0。深度 = 反哺的真正收益,**走 input 维度 + 受闸**,成本可控。

#### 3. rationale 闭环可控(input 维度)

决策 rationale 文本是模型原文。memory `clawock-driven-by-canonical-risk-rule.md` 警告:`rationale` 是模型写作的**事后辩护**,不是决策驱动的因果。

input 维度进化**不动 rationale / action / 后续判断**,只动**输入给模型的数字 / 文本**。rationale 仍然是模型的输出,不是被 clawock 反向推理出来的。定位反转不发生。

#### 反例:为什么 runtime 维度仍越界

如果跨进 runtime:
- `clawock` 改 model prompt → 等于 clawock 变成 model client(红线)
- `clawock` 改 tool 权重 → 等于 clawock 变成 agent launcher(红线)
- `clawock` 自动调 `driven_by` → 等于 clawock 改 runtime 决策路径(撞 `peer_residuals.load_rule_config` 红线)
- `clawock` 改 agent 循环 → 等于 clawock 变成 agent runtime(红线)

每一条都是 product-goal 明文禁止的。

---

### 可行路径(本节判断结果,08-29 第二次修正)

| 路径 | 合规性 | 状态 |
|---|---|---|
| 决策地图 PRD #1189-#1195 | ✅ Level 1 (Read-side) | Phase 1 可立刻做 |
| Level 2 Write-side(ledger 锚点) | ✅ **部分合规**(input 维度) | 待 kcn 拍板 + schema migration plan |
| Level 3 Inference-side | ⚠️ 三道闸后合规 | 待 kcn 拍板开新 issue |
| Level 6 Input 自进化 | ✅ **核心价值**(clawock 已在做) | 继续推进(无新 work) |
| Level 7 Input 自进化 + LLM 决策仍由 LLM 做 | ✅ **正解** | 这就是产品形态本身 |
| Level 4 Auto-rebalance `driven_by` | ❌ 越界(runtime 维度) | 不做 |
| Level 5 Self-tuning 模型 | ❌ 绝对越界(product-goal 红线) | 不做 |

完整论证见 `clawock-input-evolution-boundary.md`(08-29 写入,纠正早期 `clawock-self-improving-boundary.md` 的误读)。

### 关键结论

> clawock workflow **本来就是自进化的**(Level 6 / Level 7),这是产品的**核心价值**。
>
> 进化发生在 **input 维度**(决策因子 / thesis / research surface / 信号权重),受闸、走 artifact、可回滚、可 git diff。
>
> 进化**不发生**在 **runtime 维度**(model / prompt / agent 循环 / 工具权重)— 那是 product-goal 明文禁止的越界。
>
> 决策地图 PRD = Level 1 Read-side + Level 6 Input 自进化的**可观测化**:把已经在自进化的 input 维度,从隐性(in 模型 context)变成显性(在 dashboard),让 kcn 能看到、能审、能调。

---

## 12. Issue 切分(预)

落到 GitHub 上时,分两份:

- **Issue #PRD**:`[product-decision-map] PRD:把"决策×信息源"投影到 site 新 tab`
  - 标题 + 本文档 §1-7
  - 标签:`enhancement` `domain:signal-research` `scope:in-scope` `priority:P1`(因为它是后续 P1 issues 的载体)+ `phase:prd`
- **Issue #ROAD**:`[product-decision-map] roadmap:5 阶段切分,从骨架到 signal-panel 复用`
  - 标题 + 本文档 §10-11
  - 标签:同 + `phase:roadmap`

phase 1-5 每条**独立 issue**:
- `[decision-map][phase-1] 骨架 + 决策详情`
- `[decision-map][phase-2] 信息源倒排卡 + 矩阵`
- `[decision-map][phase-3] 交互细节 + E2E + 移动端`
- `[decision-map][phase-4] signal-panel 字段复用`
- `[decision-map][phase-5] 历史回顾(可选)`

每条 phase issue 的 acceptance 直接引用本文档对应 Phase 的 §X。

---

## 附录 A:与现有 issue 的关系

| 已有 issue | 关系 |
|---|---|
| `#1131` signal-panel | 上游(复用 IC/PBO 字段) |
| `#1132` information_overlay | 互补(#1132 修了后,decision-map 可显示 overlay 状态字段) |
| `#1133` factor composite | 互补(修了后,decision-map per-factor IC 可接进 ROW A) |
| `#1159` Insight scoring | 未来增强(可成为 ROW A 的辅助指标) |
| `#1161` Factor Analysis | 未来增强(可成为 ROW B 矩阵的副视图) |
| `#1114` backtest 资产类 | 独立(decision-map 只读 ledger,不评估回测) |
| `#1122` HK peer 自动 | 互补(peer 自动打开后,ROW B peer 行才有 count) |

## 附录 B:相关 memory

- `clawock-open-issue-batch-2026-08-29.md`:`generated_at` 命名约定 + 三方法学
- `clawock-size-gate-measured-the-wrong-bytes.md`:payload 闸按字节量
- `clawock-product-goal.md`:portable decision workflow + verifiable harness
- `clawock-dashboard-output-ownership.md`:dashboard 三产物 ownership / semantic diff
- `clawock-issue-first.md`:可执行问题先建 issue 写证据/ROI/验收再实现
- `clawock-dashboard-mobile-lifecycle-2026-08.md`:dashboard 移动生命周期