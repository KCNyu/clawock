---
name: daily-deep-brief
description: kcn 每个工作日 08:00 HKT 跑一次的盘前全 swarm 深度分析。harness 化：`scripts/harness/brief_preflight.py` 跑所有确定性步骤（刷价 / FX / snapshot / HHI / SEC EDGAR / retrospective），LLM 只做 swarm 创造性（Tier 1/2/3/Judge），`scripts/harness/brief_postflight.py` 验证 + commit。**输出**：完整 markdown 落盘 `memory/{date}-pre-open.md` + 结构化 `memory/{date}-plan.json` + 完整版发 WeChat（plugin 16KB 单 chunk 够装；顶部 ≤150 字 TL;DR 给手机第一屏）。**只在每日 8 点 cron 触发时使用；手动深度分析仍走 portfolio-swarm-review。**
---

# Daily Deep Brief (08:00 HKT, weekday)

8 点这个时点：HK 开盘前 ~90 分钟，US 已收盘 ~4 小时。盘前是 deep think 最好的窗口 —
有完整夜间消息面，没有盘中执行压力。

## Harness 架构（不可越权）

```
┌────────────────────┐     ┌───────────────┐     ┌────────────────────┐
│ scripts/harness/brief_preflight.py │ ──► │ LLM (你 / Rick)│ ──► │ brief_postflight.py│
│  (确定性 + 幂等)   │     │  (Tier 1/2/3) │     │   (验证 + commit)  │
└────────────────────┘     └───────────────┘     └────────────────────┘
   刷价/FX/snapshot/         读 context.json        校验 markdown +
   HHI/EDGAR/retro           写 markdown +          plan.json schema
                             plan.json
```

**为什么这样分**：之前完全交给 LLM，模型可能漏快照、漏 HHI、漏 FX、漏 retrospective。
确定性步骤交给脚本（一定执行，无遗漏）；LLM 只做"分析综合"这个不能脚本化的部分。

## 6-step 流程（严格按顺序）

### Step 1: 跑 preflight（一行命令搞定所有确定性活）

```bash
python3 /root/.openclaw/workspace/scripts/harness/brief_preflight.py
```

这一步内部做了：

1. `scripts/data/analyze_us_stocks.py` — US 价格刷新（7-route fallback + RSI/MA）
2. `scripts/data/analyze_hk_stocks.py` — HK 价格刷新（Tencent → stooq → yfinance + 恒指 + 信号）
3. `scripts/data/fetch_fx.py --json` — USDHKD 实时汇率（Frankfurter → exchangerate.host → Yahoo）
4. `cp portfolio.json memory/snapshots/{date}.json` — 每日快照（longitudinal 基础设施）
   - **为什么**：`portfolio.json` 是滚动覆盖的 ground truth，每次刷价就丢前一刻状态。
     有 snapshot 历史才能做 Rolling P&L 曲线 / Alpha vs benchmark / Drawdown 分析 / Position 变化追溯。
   - ⚠️ **不可补做** — 每过一天少一份永远拿不回来的数据。
5. **HHI / Top2 集中度算法**（HK + US leg 分开）
6. **SEC EDGAR fundamentals** — 对每个 `is_leveraged_etf=false` 的 US 单股跑 `scripts/data/fetch_us_filings.py`
   - 杠杆 ETF 检测启发式（name 关键词）：'倍', 'Direxion', 'T-Rex', 'Defiance', 'ProShares',
     '2X Long', '3X Long', 'Daily Target'
   - 当前实际跑 EDGAR 的票：RKLB / CRCL（其他 5 个 US 持仓都是杠杆 ETF）
7. **Retrospective**：读 prior `memory/*-plan.json`（日期 < 今天的最新），对每个 action 算
   trigger 是否触发 + 模拟 P&L + confidence calibration

输出：`memory/.tmp/brief-context-{date}.json` —— 所有数据准备好的单一 JSON。

### Step 2: 读 context.json

```bash
cat /root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d).json
```

context.json 关键字段：
- `prices_refreshed_at` / `fx`（`rate`, `source`, `fetched_at`）
- `book` — `usd_total_pnl`, `hkd_total_pnl`, `hk_leg_hkd`, `us_leg_usd`（FX 已换算）
- `concentration` — `{hk: {hhi, top2_pct, weights, verdict}, us: {...}}`
- `edgar_summaries` — 单股最新 quarter 财报关键数字
- `retrospective` — 上次 plan.json 每个 action 的触发结果 + 模拟 P&L
- `macro` — VIX / DXY / 10Y / F&G / HSI / HSTECH / SPX / NASDAQ + Fed press top 3（GH Action 每个工作日 23:30 UTC 刷）
- `sentiment` — 每个持仓票的 Reddit 提及数 + Reddit top 3 + Google News top 3（无 signal 的票已被剔）

### Step 3: Swarm 分析（你的创造性工作）

按下面这个 3-tier 流程做分析。所有数字**只能从 context.json 取**，不要凭空造。

#### Required reads (delta vs `AGENTS.md` baseline)

`AGENTS.md` 已要求每个 session 都读 SOUL.md / USER.md / MEMORY.md / TOOLS.md / 当日 daily memory，**这里不重复**。仅追加：

1. `portfolio.json` — 持仓 ground truth（preflight 已刷过价）
2. `memory/{昨天 YYYY-MM-DD}-pre-open.md` 如果存在 — 上次 thesis 和 next-session plan
3. `memory/{昨天 YYYY-MM-DD}.md` 如果存在 — 用户手写笔记
4. `INVESTMENT_SOP.md` — 启动顺序参考

#### Regime detection（先跑，定调）

| Regime | 触发 | sizing 含义 |
|---|---|---|
| Trending up | 指数 ADX > 25, MA20 > MA50, RSI 50-70 | 杠杆可持，反弹时只看过热点（RSI > 75）减 |
| Trending down | 指数 ADX > 25, MA20 < MA50, 连续低低 | 杠杆 decay 加速，preferred cash，不加 |
| Range-bound | ADX < 20, RSI 在 50 附近震荡 | T-only，fade extremes |
| Volatile / regime change | 高方差，MA 矛盾，sentiment 混乱 | 缩规模、放宽止损、等清晰 |

**两个市场分开判**（kcn book 是港股 + 美股 mismatch 是常态）：
- US: 用 QQQ / SOX 走势
- HK: 用 ^HSTECH / 恒指

#### Tier 1 — 4 个分析师角度（独立思考、合并成一张大表）

| 票 | Market | Fundamentals | Sentiment | Cross-Market |
|---|---|---|---|---|
| {ticker} | 距成本 / RSI / MA stance / 1 行评级 | EDGAR latest period 或 ETF underlying | 散户温度 / news 异动 | 跟随 / 背离 |

- Fundamentals 优先用 EDGAR（preflight 已抓），其次 web search peer/历史 P/E
- Sentiment：US 看 r/wallstreetbets + Tavily；HK 看雪球 + 富途 + 南向资金
- Cross-Market：纳指→恒科链路当日是否工作；US 隔夜 vs HK 即将开盘

#### ⚡ 板块全景（必跑 — context.json 不覆盖）

每日 Tier 1 后必做一段板块横向扫描，目标回答："你持仓在板块里**领涨/落后/中位**？归因是什么？"

- 板块来源是动态的：读 `memory/peer-map.json`，**每个 active ticker 的 `theme` 字段就是它的板块名**（如 "HK AI 大模型" / "HK 科技指数 2x leveraged (HSTECH 标的)" / "商业航天"）。持仓变了，板块自动跟变 — 不要在 SKILL.md / 报告里写死任何特定 ticker
- 对每个去重后的 theme 跑一次 **tavily-search**（或等价 web search 工具）：
  - HK 板块 → 搜 "今日 HK {theme} 涨幅榜 / 板块异动"
  - US 板块 → 搜对应 sector ETF（如 SOXX/QQQ/ARK） + 今日成分涨跌
- 每个板块输出：Top 3-5 涨幅 + 你持仓票在榜单中的位置（领涨/落后/中位）
- **归因句必带**：落后是因为(a) 利好时点（盘后才公布）/ (b) 早盘异常抛压 / (c) β 错配 / (d) 个股逻辑滞后？
- 输出在 ▎板块全景 段（pre-open.md 必带），引用 ≥3 个具体涨跌幅 + 1 个明确归因
- ⚠️ **持仓自己的数字** (RSI/MA/PnL) 仍然从 context.json 取，板块这段只 search 板块/同行公开行情
- **同时落盘到** `memory/.tmp/sector-scan-{date}.json`（build_dashboard 会读，让 GH Pages dashboard 同步显示）。schema：
  ```json
  {
    "generated_at": "{ISO8601}",
    "date": "{YYYY-MM-DD}",
    "sectors": [
      {
        "theme": "HK AI 大模型",
        "tickers_in_book": ["00100"],
        "top_movers": [
          {"ticker": "06651", "name": "五一视界", "pct": 27.6, "catalyst": "具身智能数据平台"},
          {"ticker": "00992", "name": "联想集团", "pct": 15.0, "catalyst": "AI 营收翻倍"}
        ],
        "self": [
          {"ticker": "00100", "pct": 0.07, "rank_text": "落后", "attribution": "Token Pay 盘后才公布"}
        ]
      }
    ],
    "narrative": "今天港股 AI 板块全面爆发，主角不是 MINIMAX 而是..."
  }
  ```
  - 缺失/解析失败 dashboard 容错（market_context 退回 portfolio.json 的 {}），不影响 brief 投递

#### Tier 2 — Bull vs Bear（必须有真分歧）

两段，各 80-120 字。Bull 用 Tier 1 数据组装"持有 + 加仓"案；Bear 用 Tier 1 数据组装"减仓 + 砍仓"案。**至少在 1 个仓位上观点不同** — 完全一致说明辩论失败。

引用：每方至少引 2 个具体 Tier 1 数据点（不是 vibes）。

#### Tier 3 — 3 个 Risk Voice + Judge

| Voice | 立场 | 必须做的 |
|---|---|---|
| Aggressive | 抓 upside | 引用 Bull 最强点；指出 Conservative 错过了什么 |
| Conservative | 保本 derisk | 引用 Bear 最强点；指出 Aggressive 低估的尾部 |
| Neutral | 拍中线 | **对每个争议票必须拍一边**，"看情况"是失败答 |

**Judge** 权重规则：
- kcn 风险偏好 = **激进**（USER.md），Aggressive 默认略多权重
- **但** trending down regime 启动时 Conservative 权重 +1 档
- 数据 stale 任何一段 → 涉及票 confidence -10pp

输出 **5 个 action bucket**（也是 plan.json 的 `bucket` 字段）：

| bucket | 含义 |
|---|---|
| `cut` | thesis 破，挂卖单 |
| `trim_on_rebound` | thesis 弱化，等强势 |
| `hold_and_watch` | thesis 完好，无操作 |
| `t_only` | 不留隔夜信念，fade 极值 |
| `add_only_on_trigger` | 明确触发条件后加仓 |

每个 bucket 内：ticker + 1 行具体理由 + 1 行触发价/条件。

**每个 action 还必须带 `driven_by` 字段(plan.json)——这个 call 主要被哪个数据源驱动**(写进 calibration,日后能算出"哪个消息源真有 edge"):

| driven_by | 含义 |
|---|---|
| `technical` | 价格/MA/RSI/缺口/量价(默认值；纯图表驱动归这里) |
| `catalyst` | 硬事件：财报/指引/SEC/EDGAR/M&A/产品发布(catalysts + 新闻里的硬催化) |
| `sentiment` | 软情绪：Reddit 热度 / Google News 情绪 / 散户温度 |
| `influencer` | Trump 原帖 / Musk 言论 |
| `macro` | VIX/利率/DXY/指数 regime |
| `peer` | 相对强弱 / 板块轮动(同行扫描驱动) |

规则：**只填主导那一个**(不是把所有沾边的都列上)。若是技术面为主、消息面只是佐证 → 填 `technical`。这个字段决定我们能不能回答"消息面值不值得听",所以要诚实归因,别把图表驱动的 call 贴成 catalyst 来给自己加分。

#### ⚖️ 消息面权重铁律(硬催化 vs 软情绪 — REQUIRED 遵守)

不是所有消息面都等价。**硬催化是真信号,软情绪是高噪声、均值回归。** 两者对决策的权限不同:

| 类别 | 包含 | 对决策的权限 |
|---|---|---|
| **硬催化** (hard) | 财报/指引 surprise、SEC/调查、EDGAR 文件、M&A、产品发布/召回、评级机构正式上下调、明确的政策落地 | **可以翻 bucket**(hold→cut 等),可作为主导 `driven_by` |
| **软情绪** (soft) | Reddit 提及数/热度、Google News 标题情绪、散户温度、Trump/Musk 喊话(无落地)、"看好/看空"类口风 | **只能动 confidence ±10pp,不能单独翻 bucket** |

硬性规则:
- **软情绪单独存在时,bucket 必须维持技术面/基本面给出的那个**;软情绪只允许把该 action 的 confidence 上下微调最多 ±10pp,且要在 rationale 写明"软情绪佐证/背离,confidence ±X"。
- **只有硬催化能驱动一次 bucket 翻转**(尤其翻成 cut/trim/add)。若你想下主动 call 但手里只有软情绪 → 降级为 `hold_and_watch` + 设触发价观察,别直接动手。
- influencer(Trump/Musk)默认归 **软情绪**;仅当其言论对应**已落地的政策/行政令/具体合同**才升级为硬催化。
- 自检:若某 action 的 `driven_by` 是 `sentiment` 或 `influencer` 且 bucket ∈ {cut,trim_on_rebound,add_only_on_trigger} → **这违反铁律,改回 hold_and_watch 或换硬证据**。

#### 🛡️ 消息面证伪不证实(牛市最关键 — REQUIRED)

牛市里你已经满仓在涨。**利好新闻 ≠ 该动作**——你已经持有,继续骑就行;利好不需要你"为了兑现它"去减仓。**唯一该让你主动出手的是利空的个股级硬催化。**

每条进入决策的新闻先打一个标签(在 ▎社交舆情速读 / ▎名人异动 段标注):
- **confirming**(印证你已有持仓方向的利好)→ **不触发任何 cut/trim/add**。最多维持 hold,别拿它当减仓"锁利"或加仓"追高"的理由。
- **disconfirming**(动摇持仓 thesis 的利空)→ 只有当它是**硬催化**(见上节)时,才允许驱动 cut/trim。

硬性规则:
- **不准用利好新闻 justify 主动减仓/加仓**(牛市 churn 的头号来源)。"催化已兑现/已在价"是观望理由,不是出手理由——若真要动,driven_by 必须是 `technical`(估值/技术过热),不能挂成 catalyst。
- 想加仓(add)同样要硬触发:明确回踩支撑价 + 量价确认,不是"利好所以追"。
- 一条新闻若你判为 confirming 又想据此出手 → 停,这是矛盾,改 hold_and_watch。
- 例外:止盈/再平衡这类**纪律性**减仓与新闻无关,正常走(driven_by=`technical`),但要在 rationale 标明是纪律不是消息。

#### Strategy frame menu — Judge 段必须显式选 1-3 个 per action

让 Judge 明示哪个 strategy frame 在驱动每个 action（traceability，错了能反推），从下面 8 个里选：

| Frame | 触发条件举例 |
|---|---|
| `momentum` | MA 多头排列 / 量价齐升 / 新高 + 成交放量 |
| `mean_reversion` | RSI > 75 / < 25 / 偏离布林带 +2σ |
| `breakout` | 突破前高 / 关键阻力位 + 放量确认 |
| `relative_strength` | 跑赢/输 benchmark > 3pp（peer 涨自己跌也归此） |
| `earnings_setup` | 财报前后 5d / 预期 vs 实际 surprise |
| `sentiment_shift` | F&G 拐点 / 新闻情绪 5d 翻转 / 异常 short interest |
| `technical_breakdown` | 跌破 200MA / 跳空缺口 / 头肩顶 |
| `sector_rotation` | 同板块 peer 强自己弱（或反之） |

格式：

```
▎Judge — strategy frames

| Ticker | Action | Frame | Detail |
|---|---|---|---|
| SOXL | trim_on_rebound | technical_breakdown + relative_strength | 跌破 200MA + 跑输 NVDA -8pp |
| 00100 | hold_and_watch | sentiment_shift | F&G 从 fear 转 neutral |
| RKLB | cut | mean_reversion | RSI 78 + 浮+82% |
```

**禁止**：模糊"综合判断"/"基本面看好"。每个 action 必须落到具体 frame + 数值。

#### Confidence calls

每个主要 action 给 0-100% 信心 + 1 行简单理由：

| 区间 | 校准 |
|---|---|
| 80-100% | 4 个 analyst 全部同向，Bull/Bear 强点收敛，数据新鲜，regime 清晰 |
| 60-79% | 大部分同向，1 个 analyst 异议，regime 清晰 |
| 40-59% | analyst 分裂，regime 混乱，或 1 段数据 stale |
| 20-39% | 信号冲突，疑似 regime change，多段数据 stale |
| < 20% | 不要按这个 read 行动；等清晰 |

#### Retrospective markdown 模板

把 context.json 的 `retrospective` 字段渲染成下面这段，**插在 brief 顶部**（TL;DR 之后，Header 之前）：

```
▎昨日 plan 兑现度（{上次 plan 日期}）

| Action | Plan | 实际 | 模拟 ±$ | 评 |
|---|---|---|---|---|
| Cut 50% ROBN @开盘 | 砍 20股 | 砍 N股 @${px} | ±$X vs hold | ✓/✗/⊘ |
| Trim 30% 07226 @4.10 | 减1860股 | 未触发 (high 4.05) | -HK$Y (机会成本) | ✗ trigger 过紧 |

▎Confidence calibration (累计)
- conf 80%+: N/M 触发 (X%)
- conf 60-79%: ...
- conf <60%: ...

▎Lesson (1-2 行)
{什么 trigger 设过紧/松；什么 thesis 站住/破；哪个 confidence 区间过自信}
```

评符号：✓=执行准、✗=未触发或反向、⊘=trigger 设了但 plan 本身就是中性。
机会成本可能为正（trigger 未触发 = 错过 alpha）或负（trigger 未触发 = 躲过损失）。

#### ▎同行扫描 (REQUIRED — postflight 校验)

**preflight 给了 `peer_scan` 字段**，每个持仓有 listed_peers（带 pct_1d / pct_5d）+ private_peers（待 IPO 名单）。

格式：

```
▎同行扫描

| 持仓 | 主题 | 今日 self | 最强同行 | 差距 | 判断 |
|---|---|---|---|---|---|
| 00100 MINIMAX | HK AI 大模型 | -6.6% | 02273 智云健康 -0.2% | +6.4pp | ⚠️ 题材弱但同行更强 — 个股 alpha 在掉 |
| 07226 2x恒科 | HSTECH 杠杆 | -5.2% | 00700 腾讯 +0.3% | +5.5pp | ⚠️ 杠杆放大 underlying 弱势 — 减仓换 1x |
| ... | | | | | |

私域同行追踪（仅信息层）：
- 智谱 Zhipu D 轮估值 220 亿
- 月之暗面 Kimi 用户数 ...
```

**判断模板**（必给一个）：
- 题材+ 自己+ → "alpha 抓住了"
- 题材+ 自己- → "考虑切换：peer 比我强"
- 题材- 自己- → "持有合理，等题材轮回"
- 题材- 自己+ → "稀有，珍惜"

**如果出现 ⚠️ 切换信号 → Tier 3 Judge 给 rotation trigger**（例："00100 反弹至 800 减 20 股，换入 0020 商汤")。

#### ▎大盘速读 (REQUIRED if `context.macro` 存在且 age_hours ≤ 36)

从 `context.macro` 抓数，写**一段 5 行以内**的市场 context（不是论文）。每行 1 个指标 + 1 句"对我持仓意味什么"。

格式：

```
▎大盘速读

- VIX 17.0 (+2.5%) · F&G 60.8 greed → 风险偏好仍在但开始降温, leveraged 仓位 (SOXL/RKLX/7226) 注意
- SPX 7519 (+0.1%) / NDX 30001 (+0.5%) → 美股小幅向上, 不构成 regime 切换
- HSI 25612 (+0.05%) / HSTECH 4989 (+0.85%) → HSTECH 4900 支撑确认, 07226 杠杆暴露 OK
- 10Y yield 4.49% (-1.4%) · DXY 99.1 → 利率回落小幅利好成长股
- Fed 最新动态: {fed_press[0].title 截断到 80 字符}
```

规则：
- macro 数据 age_hours > 36 时整段写"⚠️ macro 数据 stale ({age}h), 跳过本段"；postflight 不 fail
- 每行末尾 → 后必须是**对当前持仓**的具体含义（不是教科书定义）
- Fed press 段，如果今日无新发布或与利率无关（如人事任命）可省略最后一行

**🧭 Regime guard(REQUIRED — 本段第一行)**：`context.macro.regime` 给出 `label`(risk_on/neutral/risk_off)+ `reasons`。本段开头必须写一行：
```
🧭 Regime: {label}({reasons 拼接}) → {该 regime 下的决策默认}
```
据 regime 收敛主动操作(calibration 实测 hold 在 risk_on 下 76%、主动信号仅 40%):
- **risk_on** → **默认动作 = HOLD,别跟趋势对着干**。cut/trim 必须有 disconfirming 硬催化才允许(见证伪铁律);所有主动 call(cut/trim/add)confidence **上限 ≤0.55**,并在 rationale 写"risk_on regime,主动信号历史 ~40%,倾向不动"。牛市砍仓结构性吃亏。
- **neutral** → 正常按 frame 判断,无额外封顶。
- **risk_off** → 防御优先,cut/trim 门槛放宽(可信度提高),add 需更强触发;杠杆仓位优先减。
- regime 缺失(null,数据 stale)→ 写"regime 未知,主动操作按常规谨慎"并跳过封顶。

#### ▎社交舆情速读 (REQUIRED if `context.sentiment.tickers` 非空)

从 `context.sentiment.tickers` 抓数，**只列有信号的票**（context 已剔掉 0 mention + 0 news 的）。

格式：

```
▎社交舆情速读

| 票 | Reddit 7d | 新闻关键词 | 近5日 | 信号判断 |
|---|---|---|---|---|
| RKLB | 0 mentions | "$90M Space Force deal" "52-week high" | +12% | 利好已在价(已涨12%)— 追高无 edge,观望 [confirming] |
| CRCL | 0 mentions | "crypto cool" "Q1 miss" "insider sell" | -3% | ⚠️ 利空硬催化(Q1 miss)+ 尚未反应 — 严守止损 [disconfirming] |
| SOXL | 12 mentions ↑ | "TSMC capex beat" | +4% | 散户温度上升(软情绪)— 维持 hold,不据此加仓 [confirming] |

异常关注（必带）:
- {ticker}: Reddit mention 突然飙升或新闻里出现 "miss / SEC / probe / fraud / lawsuit / downgrade" 关键词
```

规则：
- **近5日列**取自 `context.sentiment.tickers[].recent_move`(`px_pct` over `n_sessions`,可能为 null=无快照)。**price-in 判断必做**:利好 + 该票近5日已大涨 → 多半"已在价",追/不减都行但别当新理由出手;利好 + 近5日没动 → 才有"未反应"的可操作空间;利空 + 已大跌 = 部分消化,利空 + 没跌 = 风险未释放要警惕
- 新闻关键词只抽 2-3 个动词/名词短语，不要复制全标题
- 信号判断必须连到**你今天对这个票的 action bucket**（一致 / 矛盾要点出来）
- **每条信号判断结尾标 `[confirming]` 或 `[disconfirming]`**（见"消息面证伪不证实"铁律）：confirming 利好**不得**驱动 cut/trim/add；只有 disconfirming 的硬催化能驱动减仓
- "异常关注"段：扫所有 ticker 的 news_top + reddit_top 文本，命中负面关键词 (`miss/SEC/probe/fraud/lawsuit/downgrade/halt/recall/short report`) 必列；无命中写"无"
- sentiment 数据 age_hours > 36 整段写"⚠️ sentiment 数据 stale, 跳过本段"

#### ▎名人异动/政策风向 (REQUIRED if `context.influencer.counts.total > 0` 且 age_hours ≤ 36)

从 `context.influencer` 抓数。这是 Trump 原帖 + Musk 言论(新闻代理)，LLM 已筛市场相关性并交叉匹配过持仓。三档优先级：**撞持仓 > 新机会 > 板块相关**。

格式：

```
▎名人异动/政策风向

撞持仓:
- 🔴 Trump 看多加密 → 你的 CRCL 直接受益, 关注开盘资金流 (rel 75)

新机会(他们推荐/点名但你没持仓):
- 🟡 Musk 看空 TSLA(robotaxi 兑现不及预期) → 若考虑做空/规避 EV 板块可纳入观察
- 🟡 Trump 点名 XYZ "great company" → 政策受益标的, 评估是否进 watchlist

板块相关(主题级, 非直接点名):
- Trump 挺加密货币 → 涉及你的 CRCL 板块敞口
```

规则：
- **撞持仓**(`held_hits`)必列且置顶，每条连到"对该持仓今天的 action 含义"
- **新机会**(`new_ideas`)是 kcn 没持有但被点名/推荐的票——这是选股线索，点出 stance(看多/看空)和是否值得进 watchlist；kcn 明确说过"不一定有买，要看他们推荐什么"
- **板块相关**(`sector_hits`)只在前两档为空或想补充主题背景时写，1-2 条即可，别灌水
- stance=attack/sell 的"新机会"是**规避/做空**信号，不是买入信号，措辞要分清
- Musk 条目标注是"新闻代理"(二手)，可信度低于 Trump 原帖，措辞留余地
- influencer 数据 age_hours > 36 或 counts.total=0 整段写"⚠️ 名人异动数据 stale/无信号, 跳过本段"；postflight 不 fail

#### ▎Confidence 自校准 (REQUIRED if `self_calibration.samples >= 5`)

context.json 有 `self_calibration` 字段含 Brier 30d + 每个 bucket 实际胜率 + 信心分桶实际率。

格式：
```
▎Confidence 校准

过去 30 天 Brier = X.XXX (good/marginal/poor)
- cut bucket: N 次, win rate Y%, 平均报 confidence Z% → 校准差距 +/- Wpp
- ...

本次报 confidence 时考虑:
- 你过去 70-80% 信心实际只赢 X% → 这次类似情境的我会调到 Y%
```

如果 self_calibration.samples < 5，这段写 "校准窗口未填满（N/5），跳过"。

**注意**：上面的 brier / per_bucket 只计 `followed=true` 的 plan actions（kcn 真执行了的，≈ 被动 hold），会掩盖主动信号的真实质量。
kcn 标记方式：`python3 scripts/data/mark_followed.py YYYY-MM-DD TICKER BUCKET [--no]`

**REQUIRED 同时引用 `self_calibration.advice_track_record`**（口径 = T+1 次日回测、**所有已结算**行不过滤 followed —— 这才是"建议本身"的成色）。它含 `active_signals` / `passive_holds` / `per_bucket` / `per_confidence_band`，每项带 `win_rate` + `overconfidence_gap`(报的信心−实际胜率,>0=过度自信)。本次定 confidence 时**必须据此收敛**：
- `active_signals.win_rate < 0.50` → 你的 cut/trim/add 信号历史上没 edge，这次主动信号的 confidence 上限压到 ≤0.60、并在理由里直说"主动信号近 N 次仅 X% 胜率"。
- 某 `per_confidence_band` 的 `overconfidence_gap > 0.15`(尤其 `>=0.75` 档)→ 你在那个信心档系统性过度自信,本次同档 confidence 下调该 gap 的量。
- 诚实呈现给 kcn：主动 vs 被动胜率对比 + 一句"模型主动信号目前是否值得听"。样本 < ~20 时注明"样本小,方向性参考"。
- 同时看 `advice_track_record.secondary_T5`(T+5 副镜):若主动信号 **T+1 和 T+5 都 <0.50**，说明不是单日噪声、是真没 edge,措辞更硬;若 T+1 高但 T+5 低 = "对了一天、看错 thesis"，提醒 next-session 触发可设更紧/更快了结。

**🎯 vs-baseline(最重要,REQUIRED 摆头条)**：`advice_track_record.vs_baseline` 给出 **LLM 决策胜率 vs "无脑全持有"基线**的 `alpha_pp`。这是抗 regime 的"模型到底有没有用"判据。**brief 的 ▎Confidence 校准段第一行必须是**：
```
🎯 近 30 天 LLM 决策 vs 无脑全持有：alpha {alpha_pp:+}pp（{verdict}）
```
若 `alpha_pp < 0`（LLM 跑输持有）→ 当期所有主动 call 的 confidence 上限压到 ≤0.55,并明说"模型主动决策当前跑输持有,本次倾向不动/小动"。注:单一 regime,标注"待熊市/震荡确认"。

#### ▎决策记忆 (reflections — REQUIRED if `context.reflections` 非空)

`context.reflections[ticker]` 是每个持仓的历史同类决策战绩(`bucket_history` 如 "清×9 胜3" / `recent` / `lesson`)。**给某标的下主动 call 前必须先看它的 reflection**:
- 若该票 `bucket_history` 显示你**反复做某动作且多半错**(如 ROBN "清×9 胜3")→ 这次别再机械重复,要么换论据要么降级为 hold,并在 rationale 里引"过去 N 次清 ROBN 错 M 次"。
- `win_rate < 0.5` 的票 → 主动 call 需要比平时更强的新증据才出手。

#### Next-Session Plan（可交易，不是观察清单）

**决策优先(decision-first)**:先用 `reflections` + `advice_track_record` 为每个持仓定 bucket(hold/cut/trim/add)+ confidence,**再**写上面的叙事去论证这个决策——不要先写一大篇分析再顺出动作。决策是主角,叙事是它的理由。宁可 1-3 个高确信动作,其余 hold,也不要 8 个摊薄的逐票评级。

格式：
```
1. {时点 + 时区}: {具体观察 / 触发}
2. {时点 + 时区}: ...
```

包含：
- HK 开盘前 09:00 HKT 查什么消息
- HK 开盘后 09:30 HKT 关注哪个票什么价位
- US 盘前 16:00 HKT 之前查什么
- US 开盘后 21:30 HKT 关注什么
- Book-level metric 红线（例：港股浮亏到 X% 触发 forced derisk）

### Step 4: 写两份输出文件

#### A. Markdown 报告 → `memory/{YYYY-MM-DD}-pre-open.md`

结构（**postflight 会校验这些段标记**，缺哪个 fail）：

- `# Header`（regime US/HK 分开 + FX rate + book USD/HKD 双视角）
- `## ▎仓位明细` —— HK + US 各一张 7 列 markdown 表 `代码 | 股 | 成本 | 现价 | 今日 | 浮% | 浮$`（与 Mode 6/7 cron 完全一致；数据从 context.json 的 `portfolio.portfolios.{hk,us}_stocks.holdings` 直接取，**只列 shares>0 的**。2026-05-21 起的 visual-width-aware 渲染推荐 import `scripts.data._wechat_table.render_holdings_table`，省得手算 CJK 对齐）
- `## Retrospective`（来自 context.json 的 retrospective）
- `## Tier 1` 大表
- `## Tier 2` Bull vs Bear
- `## Tier 3` Aggressive/Conservative/Neutral + Judge
- `## ▎同行扫描` peer rotation matrix (uses `peer_scan` from context)
- `## ▎大盘速读` macro 一句话 5 行内 (uses `macro` from context; 数据 stale > 36h 时跳过)
- `## ▎社交舆情速读` per-ticker Reddit + news (uses `sentiment` from context; 无信号票自动剔)
- `## ▎名人异动/政策风向` Trump/Musk radar (uses `influencer` from context; 撞持仓>新机会>板块相关, total=0 或 stale>36h 跳过)
- `## Confidence` 表
- `## ▎Confidence 校准` self-calibration (uses `self_calibration` from context, if samples ≥ 5)
- `## Next-Session` plan

必须包含的内容关键词（postflight 检查）：
- "HHI" — 集中度段
- "USDHKD" 或 "FX" 或 "汇率" — FX 段
- 不能出现 "合计 -4423" / "合计 -4,423" 这种 HKD+USD 直接相加的历史 bug

#### B. 结构化 plan → `memory/{YYYY-MM-DD}-plan.json`

postflight 严格 schema 校验：

```json
{
  "date": "2026-05-18",
  "fx_rate_usdhkd": 7.8315,
  "fx_source": "Frankfurter",
  "regime": {"us": "trending-up", "hk": "trending-down"},
  "book": {
    "usd_total_pnl": -117.0,
    "hkd_total_pnl": -918.0,
    "hk_leg_hkd": -4936.0,
    "us_leg_usd": 513.0
  },
  "actions": [
    {
      "ticker": "ROBN",
      "bucket": "cut",
      "size_pct": 50,
      "size_shares": 20,
      "trigger_type": "open",
      "trigger_price": null,
      "trigger_condition": "周一开盘任意价",
      "confidence": 0.82,
      "driven_by": "catalyst",
      "rationale": "HOOD Q1 26 earnings miss + crypto rev -47%"
    }
  ],
  "watch_levels": {
    "hstech_breakdown": 4800,
    "soxl_breakdown_pct": -4,
    "book_force_derisk_usd": -300
  }
}
```

合法 enum：
- `bucket` ∈ {`cut`, `trim_on_rebound`, `hold_and_watch`, `t_only`, `add_only_on_trigger`}
- `trigger_type` ∈ {`open`, `price_above`, `price_below`, `index_breakdown`, `event`, `manual`}
- `driven_by` ∈ {`technical`, `catalyst`, `sentiment`, `influencer`, `macro`, `peer`}（**每个 action 必填**，见"消息面权重铁律"段的归因表；postflight 校验，软情绪不得单独翻 bucket）
- `confidence` ∈ [0.0, 1.0]

**trigger_type 详解**（决定 retrospective 怎么算触发）：

| 值 | 含义 | 模拟触发逻辑 |
|---|---|---|
| `open` | 开盘任意价 | 永远触发（trigger_price 一般 null） |
| `price_above` | 价格突破上方 | `day_high >= trigger_price` |
| `price_below` | 价格跌破下方 | `day_low <= trigger_price` |
| `index_breakdown` | 指数破位 | trigger_condition 字段说明哪个指数 + 哪个值 |
| `event` | 事件型（财报/公告） | 手动判断，不进 calibration 统计 |
| `manual` | 完全靠人判断 | 不参与 calibration |

#### C. LLM 复盘 sidecar → `memory/.tmp/insights-{YYYY-MM-DD}.json`

build_dashboard 会读它，让 dashboard 上 **行为复盘 / 唱反调 Pre-mortem / 隐藏集中度** 三张卡同步刷新（缺失/解析失败容错，卡自动隐藏，不影响 brief 投递）。这是 dashboard 上唯一由你（LLM）写的"对决策本身的反思"层 —— 数字算不出来、只有你能写。

**铁律（accuracy）**：所有数字只能引 `brief-context-{date}.json` 里**真实出现过的** win_rate / Brier / 仓位权重 / HHI / pnl%。**绝不编造 context 里没有的具体美元金额或未发生的交易**。宁可不写一条，也不要编数字。

```json
{
  "generated_at": "{ISO8601}",
  "behavioral_review": {
    "verdict": "一句话总评 ≤40字，点出最核心的行为问题",
    "points": [
      {"text": "具体行为偏差，必引 context 里的真实数字，≤55字", "tag": "edge|bias|warning"}
    ]
  },
  "bear_cases": [
    {"ticker": "代码", "thesis": "空头论点 ≤55字", "falsifier": "什么数据/价位证明这空头错 ≤35字", "watch": "盯哪个位/事件 ≤25字"}
  ],
  "hidden_concentration": {
    "headline": "一句话点穿名义分散下的真实集中 ≤40字",
    "factor": "主导因子名（如 AI/半导体高 beta）",
    "exposure_pct": 88,
    "detail": "哪些持仓同因子联动 + 风险 ≤70字"
  }
}
```

内容要求：
- **behavioral_review.points 4-5 条**，覆盖：① `calibration_by_driver` 各源 edge 差（哪个该多信/降权）；② active 操作 alpha vs hold baseline（过度操作问题）；③ `calibration_by_trigger` 哪类 trigger 最该信/最该改；④ 任何过度自信信号（高 confidence 低 win_rate）。`tag`：edge=正面发现 / bias=认知偏差 / warning=要警惕。
- **bear_cases 2-3 个**，选**最重仓或最高杠杆**的持仓（看 context 仓位权重 + leveraged_etf）。
- **hidden_concentration**：看 sector_exposure + leveraged_etf + 持仓权重，识别表面分散实际同因子；`exposure_pct` 给该因子占组合的估算整数。
- 全部中文，口吻直接、像私人交易教练，指出问题不安慰。

### Step 5: 跑 postflight（验证 + commit）

```bash
python3 /root/.openclaw/workspace/scripts/harness/brief_postflight.py
```

输出 JSON：
```json
{
  "status": "pass|warn|fail",
  "issues": [...],
  "wechat_prefix": "...",
  "commit_ok": true,
  "commit_msg": "committed"
}
```

- `pass` — 全部 OK，已 `git commit`
- `warn` — 有非 critical 问题（≤4 个），已 commit 但标 `(validation warnings)`
- `fail` — 缺文件/JSON 解析错/critical 字段缺失，**不 commit**

### Step 6: 发 WeChat

> ⚠️ **投递机制 = announce（务必照做，否则会空转死循环）**：这个 cron 是 announce 模式 —— 你**把消息作为本轮的最终回复文本直接输出，就等于发到了 WeChat**。
> - **不要调用任何 message / send 工具**；**不要在思考里反复确认"我该用 message 工具还是直接回复"** —— 没有工具这一步，直接输出文本即投递。
> - 写完最终文本**立即结束本轮**，不要再追加思考。
> - 2026-05-31 实测教训：agent 在"用工具 vs 直接回复"上反复纠结 → 模型陷入复读死循环、16 分钟没发出任何东西。指令明确就不会卡。
> - **长度**：WeChat 单条上限 16KB。完整 brief 目标 ≤14KB；若内容偏长，**精简 Tier 1 大表的注释/重复语句**压到 14KB 内，不要靠截断。

把 postflight 输出的 `wechat_prefix`（warn/fail 时是警告 banner，pass 时是空串）拼到完整 brief 前面，作为最终回复输出。

```
{wechat_prefix}{完整 markdown，第一段是 ≤150 字 TL;DR}
```

**TL;DR 段格式**（手机第一屏 actionable，仅 WeChat 版有，落盘版没有）：

```
📊 盘前深度简报｜{日期 周X} 08:00 HKT  (USDHKD={rate})

▎TL;DR
Book: USD${total} ({pct}%) | HK leg {hk}HKD | US leg {us}USD
今日 3 个动作：
1. {ticker} {action} {trigger} (conf {%})
2. ...
↓ 完整报告 ↓
```

WeChat plugin (`@tencent-weixin/openclaw-weixin`) 单 chunk 16,384 bytes (16KB)；完整 brief ~12KB **一次发完整版完全够装**，不需要 compact 压缩。

## Style rules

- 表格优先（3+ 数据点必表格化）
- ⚠️ stale 任何数据必前置标注
- 没有"小心地"、"建议关注"这种废话 — 拍 buckets，拍价位
- 每个 claim 钉到具体 ticker + 数字，没有泛论
- Bull/Bear/Aggressive/Conservative 必须真的不同观点
- Judge 不重复 Bull/Bear，是合成不是复述
- **FX 换算永远显式标注 source + timestamp**（context.json 里已有）

## 集中度阈值表（解读 context.json `concentration` 字段）

### 算法（preflight 已经算了，这里只是参考）

对每个 leg（HK / US 分开）：
1. weight = `current_value / leg_total_current_value`
2. **HHI** = Σ weight² （0-1，越高越集中）
3. **Top 2 concentration** = 最大两仓 weight 之和

### 阈值

| HHI | Top 2 | 状态 |
|---|---|---|
| < 0.15 | < 40% | 健康 ✅ |
| 0.15-0.25 | 40-60% | 偏集中，可接受 |
| 0.25-0.40 | 60-75% | 集中风险 ⚠️ |
| > 0.40 | > 75% | 危险集中，单一事件可炸 book 🔴 |

### 输出格式（加在 book 段后，必填）

```
▎集中度风险 (2026-05-16 实测)
HK: HHI 0.418 🔴 危险 | 00100 57.2% + 07226 28.8% = Top2 86.0%
   → 单一事件风险高（00100 财报雷 / 07226 流动性问题）
   → 若 00100 或 07226 单日 -15%，HK book 立即 -8.5% 到 -12.9%
US: HHI 0.171 偏集中 | SOXL 22.2% + ROBN 21.1% = Top2 43.3%
   → 多仓分散但 SOXL 3x 杠杆 + ROBN 2x 杠杆双高仓需注意
```

历史教训：港股 book 双仓集中 86% 是 2026-05-16 之前 brief **漏报的盲点** — preflight 现在
强制算这个，brief 必须显式引用 `concentration.{hk,us}.verdict`。

## ⚠️ 货币铁律（context.json 已换算，但你输出时仍要双视角）

港币 + 美元 **不能直接相加**。book 段必须**两个 view 都给**：

```
真实总浮盈亏: USD${book.usd_total_pnl}  ≈  HKD${book.hkd_total_pnl}
   (USDHKD = {fx.rate}, 来源 {fx.source}, 抓取于 {fx.fetched_at})
  ├─ HK 段：HKD${book.hk_leg_hkd}  ≈  USD${book.hk_leg_hkd / fx.rate}
  └─ US 段：USD${book.us_leg_usd}  ≈  HKD${book.us_leg_usd * fx.rate}
```

历史教训：2026-05-16 那次"合计 -4,423"直接把 -4936 HKD 和 +513 USD 相加 → 毫无意义。kcn 当场指出。
