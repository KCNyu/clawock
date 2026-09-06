---
name: daily-deep-brief
description: kcn 每个工作日 08:00 HKT 跑一次的盘前全 swarm 深度分析。harness 化：`clawock brief preflight` 计算并编译 typed decision packet，LLM 只写 plan 与受限 judgment（纯文本判断，不写版式），`clawock brief postflight` 校验后由 `brief_render` 渲染报告与微信卡、生成 Pages projection、commit 并自动投递微信。**输出**：结构化 plan、受限 judgment JSON，harness 渲染的 markdown 报告与紧凑微信卡。**只在每日 8 点 cron 触发时使用；手动深度分析仍走 portfolio-swarm-review。**
---

# Daily Deep Brief (08:00 HKT, weekday)

8 点这个时点：HK 开盘前 ~90 分钟，US 已收盘 ~4 小时。盘前是 deep think 最好的窗口 —
有完整夜间消息面，没有盘中执行压力。

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
**已经做完并已投递**的一轮判成 `error`（真实案例：2026-08-18，简报全部产出、
`wechat_sent: true`、commit+push 都成了，运行时 `trace.artifacts.finalStatus` 也是
`success`，但 08:14 那条 exec 非零退出，整轮仍被记成红）。

**`2>/dev/null` 只吞 stderr，不改退出码。** 这是最容易踩的一条：

```bash
# ❌ 踩过的原文（2026-08-18）：末尾那个文件当天不存在 → head exit 1 → 整回合判红
ls -la memory/2026-08-17* 2>/dev/null; echo "---"; \
  head -c 2500 memory/2026-08-17-pre-open.md 2>/dev/null; echo "==="; \
  head -c 1500 memory/2026-08-17.md 2>/dev/null

# ✅ 读"可能不存在"的文件时，自己兜底退出码
ls -la memory/2026-08-17* 2>/dev/null || true; echo "---"; \
  head -c 2500 memory/2026-08-17-pre-open.md 2>/dev/null || true; echo "==="; \
  head -c 1500 memory/2026-08-17.md 2>/dev/null || true
```

三条硬规则：

1. **凡是读可选文件/通配符（日报、昨日 notes、`.tmp/` 产物）都要 `|| true`。**
   日期型文件天生可能缺（当天没写 notes、休市、上游没产出），缺失**不是错误**。
2. **`;` 串起来的复合命令，最后一条决定退出码** —— 前面成不成功都不算。
   拿不准就在整条命令末尾补 `; true`。
3. **`grep`/`test`/`head`/`ls` 用作"看一眼"而不是"判定"时，一律兜底。**
   `grep -q` 找不到东西返回 1 是正常语义，不该让一轮简报变红。

配套的窄规则见 Step 5 的「送达确认铁律」（#558）：那条禁的是 postflight 之后
再去读 marker 确认送达；本节是它的一般形式 —— **别让"看一眼"的退出码决定一轮的成败。**

## 6-step 流程（严格按顺序）

### Step 1: 跑 preflight（一行命令搞定所有确定性活）

```bash
clawock brief preflight
```

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
- manifest 的 `tools.decision_packet` —— harness 编译的 typed 决策边界；技术分类、量化可用性、风险动作、证据 ID 与 action bounds 都由代码拥有。

### Step 2: 只读 decision packet summary（唯一常驻输入）

当 packet 某票出现 `technical.setups` 并考虑加仓时，先读
[`references/technical-playbooks.md`](references/technical-playbooks.md)。只允许使用该
reference 的三种技术 staged setup，或 packet 编译出的 `alpha_confirmation`；
具体触发、失效、手数和上限仍以本次 packet 为准。`alpha_confirmation` 不是
第四种技术 alpha：量化横截面/同业残差负责 price-relative 选名，新闻 surprise
或 attention acceleration 提供独立的 point-in-time information family，技术价位
只安排未来 1–5 个本地交易日的执行。Bull/Bear 可反证、否决或降档，不能凭措辞
创造 authority、提高 tier 或改股数。

**证据族现在有三个(#1086)**：`price_relative`(因子/同业残差)、
`point_in_time_information`(一手披露)、**`technical_breakout`**(收盘站上前 20 日高
且 z < `early_no_chase_zscore`)。第三族是 #856 回测里**唯一四周期全绿**的形态
(H20 55.9% avg +16.25%；港股 H20 59.4% avg +38.7%)，此前只喂给盘中消息、
对决策没有任何权重。

三条边界不许越：**门槛仍是两族**(突破单独不授权任何东西)；突破**不算 validated**
(validated 仍要两侧都有 `usable_for_decisions` 的证据)；因此**杠杆腿不会被价格形态
提拔**，`leveraged_requires_validated_evidence` 照旧。授权成立时
`add_authority.technical_reasons` 会写明是哪一次突破——**引用它，不要自己重算价位**。

`quant.early_trend.observed=true` 是 harness 已发现的提前布局候选：必须让 Bull 写最强的
可证伪提前布局论点，让 Bear 写 priced-in/拥挤/来源质量反驳，Judge 再给
`candidate|wait|reject`。Judge 只能把 deterministic candidate 保留、等待或否决；不得把
`observed=false` 的票辩成 candidate。优先核对 `primary_event_ids`；只有新闻转载时必须把
`needs_primary_evidence` 原样保留，不能冒充一手催化。

```bash
/root/.local/bin/clawock tool decision_packet_summary \
  --workspace /root/.openclaw/workspace \
  --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json
```

summary 包含 book/concentration、每票 deterministic status、技术/因子可用性、风险计数、allowed actions 与 evidence IDs。它不要求模型加载原始持仓交易流水或整张因子表。

需要分析某票时才查该票；需要单一维度时必须带 `--section`：

```bash
/root/.local/bin/clawock tool decision_packet_query \
  --workspace /root/.openclaw/workspace \
  --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json \
  --arg ticker=00100 --arg section=technical
```

可选 section：`facts|technical|thesis|execution|quant|sentiment|history|information|evidence|risk|status|constraints`。一次查询硬上限 24 KiB，并同时校验 manifest hash 与 generation。正常分析禁止 `cat brief-context-{date}.json`，也禁止为了省一次查询而整份读 core/research/market bundle。

> **为什么走 `clawock tool`**：工具注册表是这套上下文协议唯一机器可读的定义（`clawock tool --list` 直接吐 JSON schema），而 24 KiB 预算是在注册表里强制的。协议实现随 `clawock` wheel 安装；workspace 只提供本次生成的数据，不再提供可执行 Python 源码。输出含 `_meta.generation_id` 代次钉扎。

### Step 2.5: 按消费者 lazy-load bundles

bundle 是审计深钻，不是默认模型输入。只有 packet 没有提供某个报告必须字段时才加载；每个 bundle 最多一次，紧挨消费者读取。

```bash
# 风险情景 / 解套数学使用前
/root/.local/bin/clawock tool context_bundle --workspace /root/.openclaw/workspace --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json --arg bundle=risk_detail
# EDGAR / 同行明细确需原始研究记录时
/root/.local/bin/clawock tool context_bundle --workspace /root/.openclaw/workspace --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json --arg bundle=research
# 需要查看事件图完整 provenance 时（action 权限仍以 packet constraints 为准）
/root/.local/bin/clawock tool context_bundle --workspace /root/.openclaw/workspace --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json --arg bundle=evidence
# 需要市场级而非 per-ticker 的宏观/名人记录时
/root/.local/bin/clawock tool context_bundle --workspace /root/.openclaw/workspace --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json --arg bundle=market
# Retrospective / Decision v2 校准段使用前
/root/.local/bin/clawock tool context_bundle --workspace /root/.openclaw/workspace --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json --arg bundle=calibration
```

bundle 路由：

- `risk_detail`: `breakeven_math`, `risk_metrics`
- `research`: `quant_signals`, `cross_sectional_factor`, `peer_residual`, `t0_setups`, `us_fundamentals`, `peer_scan` 及对应 review
- `evidence`: `catalysts`, `news_evidence_graph`
- `market`: `macro`, `sentiment`, `influencer`, `em_news`, `watch_list`
- `calibration`: `retrospective`, `decision_metrics`, `reflections`

`market.watch_list`（#556）：非持仓 AI 观察池（智谱 02513 / 迅策 03317 等）的**价格面观察**——仅当突破/接近突破/5d 大涨时才有行。写「新机会」节时读取它，但**观察池名字绝不产生 add 授权、绝不进决策**（不进 plan / `_constraints`）。

manifest 若出现 `extras`，表示新 feature 被隔离而没有偷长常驻 core；只有下面明确要求消费该字段时才读。任一 bundle 的 `_meta.generation_id` 与 manifest 不同，立即停止，不得把不同 preflight run 的事实拼在一起。

### Step 3: Swarm 分析（你的创造性工作）

按下面这个 3-tier 流程做分析。所有数字只能从本次 generation 的 packet 查询或确有必要时加载的 bundle 取；技术指标、因子分数、风险分类和 action bounds 一律引用 harness 结果，不重新计算。

#### Required reads (delta vs `AGENTS.md` baseline)

`AGENTS.md` 已要求每个 session 都读 SOUL.md / USER.md / MEMORY.md / TOOLS.md，**这里不重复**。仅追加：

1. `portfolio.json` — 持仓 ground truth（preflight 已刷过价）
2. `memory/{昨天 YYYY-MM-DD}-pre-open.md` 如果存在 — 上次 thesis 和 next-session plan
3. `INVESTMENT_SOP.md` — 启动顺序参考

`context.research_surface` 同样只读，但**必须被消费**：
- `reviews_due` 非空 → 在简报里点名该票 + 披露日期，并说明下一步走 `earnings-review` skill（不要在简报里现编财报数字）。
- `overdue_commitments` 非空 → 写成管理层可信度的负面证据，引用 `commitment_id` 与逾期天数。
- `ungated_positions` 非空 → 明确写「该仓位没有过建仓前研究闸」，这是流程事实不是行情判断。
- `errors` 非空 → 当作数据完整性问题优先报，不要继续引用失效 artifact 里的任何数字。
这四类都不要求你去修 artifact；简报只负责让它们不再无声。

当前持仓 thesis 只读 `context.thesis_registry`，daily brief 不在每天晨报里重写 canonical baseline。`status=unknown` 只表示缺基线，不得靠模型记忆或昨天文案补造历史；需要变更时必须走 registry validator/drift evaluator，并为每个 improved/weakened 维度附本次新增 evidence ID。

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

#### 🔭 投资哲学多棱镜（借鉴 UZI-Skill 的投资人广度，蒸馏成 6 个哲学透镜）

对**最重仓 + 最有争议的 2-3 个持仓**（不是全部，省 token 但 kcn token 充足可放宽到 4-5 个），各用下面 6 个透镜扫 1 行——目的是**用多视角逼出盲点**，不是凑 66 个角色扮演的戏：

| 透镜 | 问的问题（一行） |
|---|---|
| 💰 价值 (Graham/Buffett) | 现价 vs 内在价值/护城河？跌了是便宜还是变质？ |
| 🚀 成长 (Fisher/Wood) | 营收/TAM 拐点还在吗？故事兑现到哪步？ |
| 📈 动量/趋势 | 价在 200 日线哪侧？资金在进还是出？ |
| 🔬 逆向 (Burry/contrarian) | 共识是什么？哪里可能 priced-in/拥挤？反方最强论点？ |
| 🌍 宏观 (Dalio) | regime/利率/流动性对它是顺风还是逆风？ |
| 🧮 量化 | quant_signals 表里的因子状态（**只引用，不心算**）？ |

**铁律**：①透镜是**信息覆盖**（LLM 强项，喂给 Tier 2/3），**不是额外的投票** —— Judge 仍按既有规则决策、catalyst-gate 仍管主动 call。②透镜**分歧本身是信号**：6 个里若价值说买、动量说卖，写明这个张力，别假装统一。③别为每个持仓都跑全套（token 与噪音权衡），抓关键票。

#### ⚡ 板块全景（必跑 — context.json 不覆盖）

每日 Tier 1 后必做一段板块横向扫描，目标回答："你持仓在板块里**领涨/落后/中位**？归因是什么？"

- 板块来源是动态的：读 `memory/peer-map.json`，**每个 active ticker 的 `theme` 字段就是它的板块名**（如 "HK AI 大模型" / "HK 科技指数 2x leveraged (HSTECH 标的)" / "商业航天"）。持仓变了，板块自动跟变 — 不要在 SKILL.md / 报告里写死任何特定 ticker
- 对每个去重后的 theme 跑一次 web search — **本 skill（盘前深度简报）已放开 `tavily-search`，优先用它**（`TAVILY_API_KEY` 已配置）；tavily 无结果或超时再退回内置 web search。⚠️ 免费档 1000 credits/月是全局共享，本 skill 每天只 1 次、按去重后的 theme 数搜（通常 ≤10 次/天），别对同一 theme 重复搜。**调用必须带 `--bucket brief`**（走本 skill 的月度配额 300；不带 bucket 会落 default 桶只有 60，很快被硬护栏挡回）：
  - HK 板块 → `node /root/.openclaw/workspace/skills/tavily-search/scripts/search.mjs "今日 HK {theme} 涨幅榜 板块异动" --topic news --days 2 --bucket brief`
  - US 板块 → `node /root/.openclaw/workspace/skills/tavily-search/scripts/search.mjs "{sector ETF 如 SOXX/QQQ/ARK} 今日成分涨跌" --topic news --days 2 --bucket brief`
  - 护栏是硬闸：额度用尽时脚本返回 "Web search unavailable" 并 exit 0，**别当报错**，退回内置搜索即可
- 每个板块输出：Top 3-5 涨幅 + 你持仓票在榜单中的位置（领涨/落后/中位）
- **归因句必带**：落后是因为(a) 利好时点（盘后才公布）/ (b) 早盘异常抛压 / (c) β 错配 / (d) 个股逻辑滞后？
- 结论写进 `judgment.narrative.sector_read`（纯文本，引 ≥3 个具体涨跌幅 + 1 个明确归因）；报告里的板块表由 harness 从 `context.peer_scan` 渲染，逐票那句判断写在该票的 `peer_read`
- ⚠️ **持仓自己的数字** (RSI/MA/PnL) 仍然从 core 取，板块这段只 search 板块/同行公开行情
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

**Devil's advocate（#1101）**：Bear 除组装"减仓 + 砍仓"案外，必须**点名攻击当前最强共识**——即 Tier 1 表里最被看好的票 / 最强势的多头论点，并写明攻击的是哪个结论。不许只挑软柿子；若确实无强共识，明说"无强共识，攻击次强"并给出理由。目的：压制群体思维与锚定，别让辩论顺着第一个观点滑下去。

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
- **视角轮换（#1101）**：三位风险官的首位表态权每 4 个交易日轮换（Aggressive → Conservative → Neutral → 循环），当日首位 voice 写进 `judgment.narrative.risk_voice_first`（harness 据此排序）。轮换只改表态顺序与框架设定，**不改** kcn 激进偏好的权重规则。

输出策略级 decision。**同一股票同一天允许多条决策**，例如 `core_position` 继续持有，同时 `intraday_t` 做日内 T；两者不能互相覆盖。

| action | 含义 |
|---|---|
| `cut` | thesis 破，挂卖单 |
| `trim_on_rebound` | thesis 弱化，等强势 |
| `hold_and_watch` | thesis 完好，无操作 |
| `t_only` | 不留隔夜信念，fade 极值 |
| `add_only_on_trigger` | 明确触发条件后加仓 |

每条 decision：ticker + `strategy_id` + action + 1 行具体理由 + 1 行触发条件。

**每个 decision 必须带 `driven_by`**——这个策略决策主要由哪个数据源驱动（写进 v2 ledger，按 episode 计算 edge）：

| driven_by | 含义 |
|---|---|
| `technical` | 价格/MA/RSI/缺口/量价(默认值；纯图表驱动归这里) |
| `catalyst` | 硬事件：财报/指引/SEC/EDGAR/M&A/产品发布(catalysts + 新闻里的硬催化) |
| `sentiment` | 软情绪：Reddit 热度 / Google News 情绪 / 散户温度 |
| `influencer` | Trump 原帖 / Musk 言论 / Serenity(AI半导体供应链选股) |
| `macro` | VIX/利率/DXY/指数 regime |
| `peer` | 相对强弱 / 板块轮动(同行扫描驱动) |
| `risk_rule` | 组合上限、杠杆、β 等政策型再平衡 |

规则：**只填主导那一个**(不是把所有沾边的都列上)。若是技术面为主、消息面只是佐证 → 填 `technical`。这个字段决定我们能不能回答"消息面值不值得听",所以要诚实归因,别把图表驱动的 call 贴成 catalyst 来给自己加分。

#### 📊 driven_by / strategy 的动态 edge（REQUIRED）

只读 `context.decision_metrics.by_driver` 与 `by_strategy`，禁止把 README 或旧报告里的点时数字当当前事实。比较 `n_episodes`、`avg_benefit_pct` 和 `cluster_ci95`：n 小或 CI 跨 0 时只能说“方向性”，不能声称显著。`risk_rule` 是政策执行，不当作择时信号夸奖。

#### 🎚️ 分层 confidence 校准与 sizing（REQUIRED）

原始 `confidence` 只保留为作者当时判断的审计字段，不能直接当胜率或仓位倍数。主动 call 必须在 `context.decision_metrics.hierarchical_calibration.current_group_calibrators` 中匹配 `action + driver + condition + regime`；该表由严格按 `plan_date` 前向、同日整体延后更新的 beta-binomial 校准器产生，稀疏小组会收缩到更宽层级。

- `abstain=true`：历史证据不足，`signal_size_multiplier=0`。一般信号不得扩仓；唯一的冷启动例外是 packet 批准、thesis gate 通过且仍有 `remaining_tranches` 的技术 setup，可做 **一个 `min_tranche_shares` 探索批次**来积累前瞻样本，不能放大到 `suggested/max`，也不能连开第二批。
- 找不到完全匹配行：按 abstain 处理，不得自行拿相邻小组的点估计冒充。**该表只装 `evidence_sufficient=true` 的行**（证据不足的整批省略，避免每轮重发一张全是 abstain 的后验表）；省略了多少、分别因为什么，看同级的 `current_group_calibrator_count` / `current_group_calibrators_omitted` / `omitted_abstain_reasons`。表变短说明证据变薄，不是数据丢了。上述最小探索批次是为了打破“没有样本所以永远不能产生样本”的闭环，不是把缺证据说成有 edge。
- `edge_supported=false`：证据已够但 95% 下界未过 50%，不得再用冷启动例外，也不得用它扩大主动仓位。
- 只有 `edge_supported=true` 才能把原拟主动股数乘以 `signal_size_multiplier`；报告同时公开 calibrated probability、CI 和 resolved level。
- 组合硬闸的 `risk_rebalance + risk_rule` 是政策执行，不是预测；即使校准器 abstain，也必须执行硬闸要求的降集中/降杠杆动作，禁止拿“无择时 edge”否决风控。

#### 🌡️ 牛 / 熊 / 震荡 regime（REQUIRED，保留）

Bull/Bear 是决策框架的一部分，不能因升级账本而删除：

- Tier 2 仍必须分别写 Bull case 与 Bear case，并且至少在一个持仓或一个策略上形成真分歧。
- 当前 regime 仍由 `context.macro.regime` 和可用的市场趋势数据判断为 `risk_on` / `neutral` / `risk_off`；报告必须写判断依据，数据 stale 时明确降置信度。
- `risk_on`：`core_position` 默认让利润奔跑；没有证伪催化时不要因短线波动反复 cut。`intraday_t` 与 `risk_rebalance` 可独立存在，不能覆盖 core thesis。
- `risk_off`：提高防御权重，杠杆与集中风险优先由 `risk_rebalance` 处理；`tactical_entry` 需要更强的价格/事件触发。
- `neutral`：按各 strategy 自己的 condition 执行，不把同股不同时间尺度压成一个动作。
- 复盘时按 `strategy_id` 分层看牛熊适应性；在 v2 尚无足够 regime episode 样本前，保留定性判断并注明样本不足，绝不引用旧 v1 的静态百分比冒充当前结果。

这意味着“牛市 core 持有 + 同日 intraday T”“熊市 core 未证伪 + risk_rebalance 降杠杆”都可以同时成立；它们是不同策略，不是自相矛盾。

#### 🚦 仓位/杠杆硬闸(REQUIRED — 优先级高于 driven_by 与 regime guard)

**回撤复盘的最大教训:亏不是因为"没听 LLM",是因为组合构造**(US β≈4.4、73% 杠杆 ETF、HK 85% 单因子)。任何一个 driven_by 面都没提前叫出来——这不是信号问题,是**风控纪律层缺失**。所以在所有 driven_by/regime 逻辑之上,先过一道仓位硬闸。

preflight 已算好,直接读 `context.risk_guardrail`:
- `breaches[]` — 每条 = 一个超限的硬闸(single_name / factor_concentration / leveraged_exposure / beta),带 `detail` + 现成 `action`(含具体减仓金额)。
- `hard_stop_watch[]` — 杠杆 ETF 浮亏跌破 −18% 的硬止损触发。
- `directive` — 本次总指令；`caps` — 当前阈值（非杠杆单名 35–60% review、>60% mandatory；杠杆单名 35%；实测多票相关 cluster 70% 且覆盖≥80%；杠杆 ETF 50%；US β 3.0；杠杆止损 −18%）。Top2 仅展示，不再冒充同因子。
- `context.risk_discipline.records[]` — 同一 breach 的持久状态：`breach_id`、严重度、`age_days`、首次/最后变化、required reduction、acknowledgement、限时 override、execution evidence。每日重新生成的 plan 不是状态账本。

硬性规则:
- **每一条 breach 和 hard_stop 必须在 Judge 段落出一个对应的具体动作**(trim 到 ≤cap / cut),不准忽略、不准"观望"。直接采用 `action` 文案或给等价方案。
- 每条 open 记录必须引用 `breach_id + age_days + acknowledgement/execution 状态`；未确认的老 breach 要明确升级，不得每天当新提醒重写。
- 当天 plan 内的 `override.status=active` **不能**豁免硬闸。只有 durable ledger 里带非空 reason 且未过 TTL 的 `status=overridden` 才有效；创建例外必须由用户明确决定，可用 `/root/.local/bin/clawock risk override BREACH_ID --reason '...' --ttl-hours N`。确认已看见用 `risk ack ... --note '...'`，成交证据用 `risk confirm ... --evidence '...'`；这些命令只记账，绝不下单。
- 任何 critical/high breach 未关闭且未 durable override 时，禁止新增同一标的、杠杆或因子暴露。卖出不受阻；同一份 plan 中可证明净降 factor exposure 的 2x→1x 配对换仓不受阻。
- 这些减仓 **strategy_id=`risk_rebalance`、driven_by=`risk_rule`**（纪律性再平衡，不是择时预测），并在 rationale 注明组合政策依据。
- **这是 risk_on HOLD 默认的唯一豁免**:证伪铁律已写明纪律性再平衡正常走;别因为 regime=risk_on 就把降杠杆/降集中也按住。牛市里恰恰要借强减杠杆,不是等回调后。
- **降 β/降杠杆优先削杠杆 ETF**(β 的主要来源),不要去砍高信念单票的 thesis。
- **杠杆ETF解套口径(kcn 2026-06-11 定)**:杠杆 ETF 的 breach/hard_stop 动作 = **2x→1x 同因子换仓而非清仓**(映射在 `brief_preflight.LEV_1X_SWAP`:07226→03033、PLTU→PLTR、ROBN→HOOD、MSFU→MSFT)——敞口不变、反弹一点不踏空,但停掉日内重置 decay;`context.risk_guardrail.reentry_rule` 满足(🧭转 green,标的收复 200 线)才允许 1x→2x 换回。**现货(非杠杆)套牢 kcn 方针=持有等待合法**(现货等待免费,2x 等待收费),对现货超限的最低要求是"不补仓、借反弹分批",别反复催清仓。
- **换仓的买腿怎么写(#1075)**:2x→1x 是**一砍一买两条腿**,买腿由**风控规则**授权,不需要
  技术 setup。目标票的 `constraints.swap_mandate` 就是那份授权(`from_ticker` / `breach_id` /
  `max_value` / `currency`);此时它的 `allowed_actions` 会含 `add_only_on_trigger`,直接用,
  别因为它没有 setup 就退回 hold。三条硬约束:①只能买 mandate 指名的那一只 ②金额不超
  `max_value` ③**两条腿必须共享同一个 `transaction_group_id`**,否则 decision_audit 会把买腿
  当成裸买、对着错的基准结算。目标票自己也在 breach 时 mandate 为 `null`——那就是不许换过去。
- **目标已清仓的处方也要写出来**:packet 顶层 `swap_mandates` 列出全部处方,含 `target_held:false`
  的(例:RKLX→RKLB,RKLB 6/13 已清)。它们在 `tickers` 里没有行,但**必须在本段点名**——
  一条看不见的处方,没人能有意否决它。
- **standing 判词**:每条 breach 的 `risk[].standing`。`decision_overdue=true` 表示它已经站了
  ≥`threshold_days` 天而 execute / acknowledge / override **三个出口一个都没走过**。这时不要
  再写第 N 遍同样的提醒,写成一个要求:要么执行,要么用 `risk ack` 留痕"看见了、接受它继续开着",
  要么用 `risk override --reason` 记下**为什么决定不做**。实测 2026-08-26:三条 hard_stop 站了
  42 天、同一条砍单发了 136 次、执行 0 次,而 `override` 字段一次没用过——账本读起来像"没人看",
  真相是有人每天看、每天决定不做。
- 若 `breach_count=0` → 本段写"✅ 仓位硬闸无触发",照常决策。
- **解套/回本数字只准引用 `context.breakeven_math`**(preflight 已算好:每只浮亏持仓回本所需涨幅、2x 的横盘 decay ≈σ²/12 每月、半年窗含 drag 等效标的涨幅),禁止自己心算或编造。解读纪律见其 `note`:直线涨→2x 回本更快;横盘→2x 每月白付 decay;再跌→2x 双倍挨打——换 1x 买的是后两种情景的保护,不是回本速度,别说反。
- **技术面判断只准引用 `context.quant_signals` 中 `status=fresh` 的行**(每只持仓的趋势/动量/RSI/zscore20/吊灯止损线/vol_target_weight,杠杆 ETF 按标的算)；`stale/missing/retired` 行只用于披露数据缺口，禁止据此形成判断，也禁止自创"看图"结论。**因子话语权由 `context.quant_signal_review` 决定**(信号每日留痕 vs T+1/T+5 前瞻收益自动对账):必须公示 `n_events/n_dates/n_tickers`;`usable=false` 或聚类 CI 跨 50% 的因子只能当背景展示不入决策；`decision_direction=reverse` 仅在反向 CI 整体低于 50% 时成立，禁止因 raw hit_rate<50% 自动反向。T+0 牌面同样只在 `sample_sufficient=true AND edge_supported=true` 时可入决策；样本够多但 Wilson CI 不支持原方向仍是 `usable=false`，不得自动反向交易。`driven_by=technical` 的整体战绩一律读取 `context.decision_metrics.by_driver.technical` 的实时计算值，禁止引用固定百分比。这是自迭代环——哪个因子可信,数据说了算,每天自动更新。
- **跨截面因子只读 `context.cross_sectional_factor`**。这是同行/1x 标的的行业中性研究层；只有 `activation.usable_for_decisions=true` 才能影响动作。为 false 时，排名、杠杆 decay 对比和回溯结果只能作为明确标注的研究背景，不得写进 Judge 理由、不得改变 confidence；尤其禁止用 retrospective CI 代替预注册后的 prospective 证据。
- **同行残差只读 `context.peer_residual`**。leader continuation、laggard avoidance、mean reversion 三条规则分别看 `rule_activation.<rule>.usable_for_decisions`，不得互相借样本；为 false 时，即使 `held.<ticker>.triggered_rules` 有触发也不得用于换股/加减仓。港股 peer 只能来自人工 `peer-map.json`，禁止补写或调用自动 HK 同行发现。

> 心智:driven_by 三档管"该信哪个信号",仓位硬闸管"不管信号多强,单名/单因子/杠杆都不许超过这条线"。后者是回撤的真正解药。

#### ⚖️ 消息面权重铁律(硬催化 vs 软情绪 — REQUIRED 遵守)

不是所有消息面都等价。**硬催化是真信号,软情绪是高噪声、均值回归。** 两者对决策的权限不同:

| 类别 | 包含 | 对决策的权限 |
|---|---|---|
| **硬催化** (hard) | 财报/指引 surprise、SEC/调查、EDGAR 文件、M&A、产品发布/召回、评级机构正式上下调、明确的政策落地 | **可以翻 bucket**(hold→cut 等),可作为主导 `driven_by` |
| **软情绪** (soft) | Reddit 提及数/热度、Google News 标题情绪、散户温度、Trump/Musk 喊话(无落地)、"看好/看空"类口风 | **只能动 confidence ±10pp,不能单独翻 bucket** |

硬性规则:
- **`context.news_evidence_graph` 存在时，只有 `actionable_escalation=true` 的事件能驱动主动 catalyst 动作**，并把其 `event_id` 原样写入 plan 的 `evidence_event_id`。事件必须是一手/可靠、仍有效、足够新颖、负面证伪且获价量或已校准同行残差确认；任一 blocker 存在就只能 display/watch —— 但落成 `watch`/`hold_and_watch` 时**仍然可以**把该事件的 `event_id` 写进 `evidence_event_id` 并保留 `driven_by=catalyst`（被动档只要求事件真实，见 plan.json 字段表）。
- 同一 novelty cluster 的重复摘要不会增加 conviction；过期事件不能复活。`positive/confirming` 事件一律 hold-only。
- Tavily 新闻搜索只准处理 `tavily_resolution_queue` 里列出的 event ID 和 query；队列外的日常旧闻/低影响摘要不得消耗 Tavily。未解决不等于可交易，搜索结果仍需下一轮图谱门控。
- **软情绪单独存在时,bucket 必须维持技术面/基本面给出的那个**;软情绪只允许把该 action 的 confidence 上下微调最多 ±10pp,且要在 rationale 写明"软情绪佐证/背离,confidence ±X"。
- **只有硬催化能驱动一次 bucket 翻转**(尤其翻成 cut/trim/add)。若你想下主动 call 但手里只有软情绪 → 降级为 `hold_and_watch` + 设触发价观察,别直接动手。
- influencer(Trump/Musk/Serenity)默认归 **软情绪**;仅当其言论对应**已落地的政策/行政令/具体合同**才升级为硬催化。Serenity 是 KOL 选股(常为微盘/光通信小票),按 [[serenity-skill]] 的证据阶梯属"弱证据线索",只动 confidence、需一手来源(财报/合同/公告)证实后才可加权。
- 自检:若某 action 的 `driven_by` 是 `sentiment` 或 `influencer` 且 bucket ∈ {cut,trim_on_rebound,add_only_on_trigger} → **这违反铁律,改回 hold_and_watch 或换硬证据**。
- **前瞻事件的日期只能引用 `context.catalysts`，禁止推测。** 财报/FOMC/宏观在 `earnings`/`fomc`/`macro_events`；公司级预定事件（港股通生效日、解禁日、mainnet 上线、指数调整生效日）在 **`scheduled_events`**（真源 `memory/scheduled_catalysts.json`，手工维护）。
  - `date_confidence=confirmed` → 可直接写该日期；`estimated` → 写日期但必须标「预计」；**`date` 为 `null`（`unconfirmed`）→ 只能写「生效日未确认」，不准用「下周一」「下个月」「9 月」这类自己推出来的说法**。
  - `scheduled_events` 里没有的公司级预定事件 → **当作日期未知处理**，同时在 `▎待补` 提示把它加进 `memory/scheduled_catalysts.json`，别在正文里编一个。
  - 为什么是铁律：2026-08-06 的简报对同一个 MiniMax 港股通事件给出了**三个互相矛盾的日期**（「下周一生效」/「next month」/「9 月生效」），而正文正在拿这个日期决定要不要 trim。没有结构化真源时，模型每天重猜且没有任何东西会红。

#### 🛡️ 消息面证伪不证实(牛市最关键 — REQUIRED)

牛市里你已经满仓在涨。**利好新闻 ≠ 该动作**——你已经持有,继续骑就行;利好不需要你"为了兑现它"去减仓。**唯一该让你主动出手的是利空的个股级硬催化。**

每条进入决策的新闻先打一个标签(在 ▎社交舆情速读 / ▎名人异动 段标注):
- **confirming**(印证你已有持仓方向的利好)→ **不触发任何 cut/trim/add**。最多维持 hold,别拿它当减仓"锁利"或加仓"追高"的理由。
- **disconfirming**(动摇持仓 thesis 的利空)→ 只有当它是**硬催化**(见上节)时,才允许驱动 cut/trim。

硬性规则:
- **不准用利好新闻 justify 主动减仓/加仓**(牛市 churn 的头号来源)。"催化已兑现/已在价"是观望理由,不是出手理由——若真要动,driven_by 必须是 `technical`(估值/技术过热),不能挂成 catalyst。
- 想加仓(add)同样要硬触发:明确回踩支撑价 + 量价确认,不是"利好所以追"。
- 一条新闻若你判为 confirming 又想据此出手 → 停,这是矛盾,改 hold_and_watch。
- 例外:止盈/再平衡这类**纪律性**减仓与新闻无关，走 `strategy_id=risk_rebalance` + `driven_by=risk_rule`，rationale 写明是纪律不是消息。

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

把 calibration bundle 的 `retrospective` 字段渲染成下面这段，**插在 brief 顶部**（TL;DR 之后，Header 之前）：

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
据 regime 收敛主动操作：
- **risk_on** → core_position 默认 HOLD；择时 cut/trim 需要 disconfirming 硬催化。`risk_rebalance` 是独立策略，可因组合政策在 risk_on 中减杠杆，不与 core thesis 混为一谈。
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
- 信号判断必须连到**你今天对这个票的具体 strategy/action**（一致 / 矛盾要点出来）
- **每条信号判断结尾标 `[confirming]` 或 `[disconfirming]`**（见"消息面证伪不证实"铁律）：confirming 利好**不得**驱动 cut/trim/add；只有 disconfirming 的硬催化能驱动减仓
- "异常关注"段：扫所有 ticker 的 news_top + reddit_top 文本，命中负面关键词 (`miss/SEC/probe/fraud/lawsuit/downgrade/halt/recall/short report`) 必列；无命中写"无"
- sentiment 数据 age_hours > 36 整段写"⚠️ sentiment 数据 stale, 跳过本段"

#### ▎名人异动/政策风向 (REQUIRED if `context.influencer.counts.total > 0` 且 age_hours ≤ 36)

从 `context.influencer` 抓数。这是 Trump 原帖 + Musk 言论(新闻代理) + Serenity(AI/半导体供应链选股，Substack 公开帖)，LLM 已筛市场相关性并交叉匹配过持仓。三档优先级：**撞持仓 > 新机会 > 板块相关**。

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
- Serenity 条目来自 Substack(一手但低频，几周才一篇)，多为微盘/小票选股 idea：当"新机会"线索看，**别当买入指令**，措辞强调需自查基本面/一手证据(见 [[serenity-skill]])
- influencer 数据 age_hours > 36 或 counts.total=0 整段写"⚠️ 名人异动数据 stale/无信号, 跳过本段"；postflight 不 fail

#### ▎Confidence / episode 校准（REQUIRED）

calibration bundle 的 `decision_metrics` 是 v2 唯一口径：只结算**条件实际触发**的决策；同一 `ticker + strategy_id` 的连续同类决策合并为一个 episode，只取一次代表样本，避免每日重复建议放大样本量。

格式：
```
▎Decision v2 校准

过去 30 天：已结算 {settled_episodes} 个 episode
- 主动决策：n=N，平均 benefit=X%，date-cluster CI=[L,U]
- 信心校准：嘴上平均 {mean_confidence}，实际胜率 {base_rate}；Brier {brier} vs 闭眼总报 {base_rate} 的 {brier_baseline_loo}
- 按 strategy / action / driven_by 点出最强与最弱各一项
- 执行状态：**要动手的** {execution_by_kind.active.rate}（{followed}/{known}）与 **不用动的** {execution_by_kind.passive.rate} 分开写；执行率不等于建议质量。两条腿各自的 `{stranded}` **必须同句写出来**（「另有 N 条永远验不了，不在分母」）——那是窗口早已关闭、`_detect_followed` 每次重试都答 unknown 的行，标的从没进过 holdings，被丢掉的样本偏向「没执行」，所以裸报的执行率系统性偏高
```

规则：
- `settled_episodes < 5`：明确写样本未填满，只作方向性参考。
- 主动 `cluster_ci95` 跨 0：不许声称有稳定 edge。
- **Brier 禁止裸报**。`0.295` 单独写会被读成「接近 0，还行」。只准写成对 `brier_baseline_loo`（闭眼总报基准率的留一法常数预测）的比较。`brier_beats_baseline=false` 时说「信心值校准不合格」或「过度自信」，**不许说「信心值没有信息量」**——Brier 分解里 resolution 仍 >0，是 reliability 把它吃掉了，说「没信息量」是过度指控。
- **禁止报「听 AI 赚了多少钱」类金额**。`decision_money_impact` 已于 2026-07-15 撤下且**不再写入 dashboard.json**：它把从没执行过的 call 也算进去。重建对照账本前，任何「多赚/少赚 X 元」都是编的。
- **胜率必须带 coverage**。`coverage_active.episodes_unresolved` 是判不了的 episode 数（休市/需人工核实/标的无交易）。只报胜率不报这个数=把难题藏进分母外。
- **禁止拿 active 胜率和 passive 胜率横比**。两者是不同样本池（不同标的/日期/暴露），相减不测量任何东西——「主动跑赢/跑输躺平」这类话一律不许写。
- confidence 必须参考同 strategy/action 的 episode 战绩；样本小则收敛到中性，不得因同一股票连续多日重复 call 而虚增信心。
- 同一天同一股票可以有多个 strategy；分别写、分别触发、分别评估，禁止压成一条综合 action。
- `event` / `manual` 条件若无可验证触发证据，状态为 `not_evaluable`，不进入胜率和 Brier。
- `execution` 与 `evaluation` 分离：建议是否有利和 kcn 是否执行是两个问题，报告时不得混写。

#### ▎决策记忆 (reflections — REQUIRED if `context.reflections` 非空)

`context.reflections[ticker]` 是每个持仓的历史同类决策战绩(`bucket_history` 如 "清×9 胜3" / `recent` / `lesson`)。**给某标的下主动 call 前必须先看它的 reflection**:
- 若该票 `bucket_history` 显示你**反复做某动作且多半错**(如 ROBN "清×9 胜3")→ 这次别再机械重复,要么换论据要么降级为 hold,并在 rationale 里引"过去 N 次清 ROBN 错 M 次"。
- `win_rate < 0.5` 的票 → 主动 call 需要比平时更强的新证据才出手。

#### Next-Session Plan（可交易，不是观察清单）

**决策优先(decision-first)**:先用 `reflections` + `decision_metrics` 为每个持仓按 strategy 定 action + condition + confidence，**再**写叙事论证决策。决策是主角，叙事是理由。宁可 1-3 个高确信主动策略，其余 core hold，也不要 8 个摊薄的逐票评级。

格式：
```
1. {时点 + 时区}: {具体观察 / 触发}
2. {时点 + 时区}: ...
```

包含：
- HK 开盘前 09:00 HKT 查什么消息
- HK 开盘后 09:30 HKT 关注哪个票什么价位
- US 盘前（09:30 ET 之前）查什么
- US 开盘后 09:30 ET 关注什么
- Book-level metric 红线（例：港股浮亏到 X% 触发 forced derisk）

### Step 4: 写输出文件（B plan / C judgment / D insights —— A 报告与 E 微信卡由 harness 渲染）

#### A. 报告与微信卡：**你不写，harness 渲染**

`memory/{YYYY-MM-DD}-pre-open.md` 与 `memory/.tmp/brief-card-{YYYY-MM-DD}.txt`
由 `clawock.harness.brief_render` 从**本次 context + 你的 judgment + 校验后的 plan**
渲染，postflight 自动跑，不需要你调用。

**不要写这两个文件。** 你手写的稿子会在 postflight 里被渲染结果覆盖——它不会
进产品，只会浪费一轮 token。

为什么这么分（2026-08-31，kcn 定）：报告过去由模型逐行手写，于是①版式每天重新
发明一遍，同一张表昨天七列今天六列；②该留在辩论段的推演渗进表格里，读者要在一堆
过程文字里找"09:30 到底做什么"。现在**模型只出想法，harness 只出版式**：标题层级、
表格、排序、数字格式、段落顺序全部在代码里，每天同一个位置放同一件事。

因此：

- 你写的每一段判断都通过 **B（plan）** 和 **C（judgment）** 进入报告，别处不进。
- judgment 的文字字段**必须是纯文本**：不许出现 `|`、`#`、`**`、` ``` `、`▎`、
  行首 `-`/`*`/`1.`/`>`。这不是文风要求——渲染器正在画那张表，你的竖线会落进单元格里
  把那一行撑成多一列。postflight 会直接判非法并指出是哪个字段。
- 事实、指标、风控闸、集中度、回本数学、同行涨跌、宏观读数、校准表全部由 harness
  从 context 取；**你不需要把它们抄进 judgment**，抄了也不会被用。
- 体量不再由你控制：渲染结果通常 18–22KB，远在 28KB 预算内。原来那套"分段预算 +
  写完 `wc -c`"的自查随本节一起退役。

本地想看渲染结果（不写盘）：

```bash
clawock brief render --dry-run
```

#### B. 结构化 plan → `memory/{YYYY-MM-DD}-plan.json`

postflight 严格 schema 校验：

```json
{
  "schema_version": 2,
  "date": "2026-05-18",
  "context_generation_id": "照抄 manifest.generation_id",
  "fx_rate_usdhkd": 7.8315,
  "fx_source": "Frankfurter",
  "regime": {"us": "trending-up", "hk": "trending-down"},
  "book": {
    "usd_total_pnl": -117.0,
    "hkd_total_pnl": -918.0,
    "hk_leg_hkd": -4936.0,
    "us_leg_usd": 513.0
  },
  "decisions": [
    {
      "strategy_id": "risk_rebalance",
      "thesis_id": "reduce-leveraged-beta",
      "ticker": "ROBN",
      "action": "cut",
      "condition": {"type": "open", "price": null, "note": "周一开盘任意价"},
      "size": {"pct": 50, "shares": 20, "capital": 3200},
      "confidence": 0.82,
      "expected_move_pct": -6.5,
      "driven_by": "risk_rule",
      "regime": "risk_off",
      "contested": true,
      "rationale": "降低杠杆 beta；这是组合政策型再平衡，不是预测",
      "thesis_invalidation": "若 crypto rev 环比转正 / DAU 回升 → 论点失效，停止减仓",
      "debate": {
        "bull": "crypto rev 若回暖，减到 50% 会踏空反弹",
        "bear": "杠杆 beta 在 risk_off 下放大回撤，DAU 连续两季下滑无止跌迹象",
        "attacked_consensus": "攻击的是「AI 板块整体还有一波」这条最强共识",
        "frames": ["technical_breakdown", "relative_strength"],
        "judge": "纪律优先：政策型减仓不等预测兑现",
        "evidence_ids": ["risk:leveraged_exposure:07226", "quant:07226:dist_ma200_pct"]
      }
    },
    {
      "strategy_id": "intraday_t",
      "thesis_id": "robn-intraday-mean-reversion",
      "ticker": "ROBN",
      "action": "t_only",
      "condition": {"type": "price_above", "price": 16.2, "note": "冲高缩量时做 T"},
      "size": {"pct": 15, "shares": 6},
      "confidence": 0.61,
      "driven_by": "technical",
      "evidence_event_id": null,
      "regime": "neutral",
      "contested": false,
      "rationale": "与 core/risk_rebalance 分开的日内策略"
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
- `strategy_id` ∈ {`core_position`, `risk_rebalance`, `intraday_t`, `event_trade`, `tactical_entry`}；迁移历史才允许 `legacy_unknown`
- `context_generation_id`：必填，逐字符照抄本次 `manifest.generation_id`；postflight 会递归检查 plan 内所有 `*generation_id`，跨代引用直接 fail。
- 每条 `action` 必须出现在该 ticker packet 的 `constraints.allowed_actions`；卖出股数不得超过 `max_sell_shares`，catalyst 只能引用 `actionable_evidence_ids`。postflight 会二次校验，模型不能扩大边界。
- `action` ∈ {`cut`, `trim_on_rebound`, `hold_and_watch`, `t_only`, `add_only_on_trigger`, `add_on_breakout`, `watch`}
- `condition.type` ∈ {`open`, `price_above`, `price_below`, `index_breakdown`, `event`, `manual`}
- `driven_by` ∈ {`technical`, `catalyst`, `sentiment`, `influencer`, `macro`, `peer`, `risk_rule`}（每个 decision 必填）
- `evidence_event_id`：`driven_by=catalyst` 时必填，分两档 —— **主动** call（`cut`/`trim_on_rebound`/`t_only`/`add_only_on_trigger`/`add_on_breakout`）必须精确匹配 `context.news_evidence_graph.events` 中同 ticker 且 `actionable_escalation=true` 的事件（不许拿未升级事件去交易）；**被动** `hold_and_watch`/`watch` 只要求匹配同 ticker 的**真实**事件，不要求 `actionable_escalation=true`（「昨天出了财报所以我盯着」是正当归因）。`driven_by` 不是 `catalyst` 的 decision 填 `null`。
  - ⚠️ 被动决策若归因 `catalyst` 就**必须**给出真实 `event_id`，不能填 `null` —— 归因得可核。给不出具体事件，就说明它其实不是 catalyst 驱动，改用 `technical`/`risk_rule` 等如实标注。**不要为了过闸而改标 `driven_by`**：这个字段直接决定 `by_driver` 胜率归属（主动和被动都进桶），洗标签就是在污染自己的 edge 统计。
- `regime` ∈ {`risk_on`, `neutral`, `risk_off`}（每个 decision 必填；按本报告已判定的当前 regime 留痕，迁移旧数据才允许 `unknown`）
- `confidence` ∈ [0.0, 1.0]
- `size.shares`（整数，**主动 call（`cut`/`trim_on_rebound`/`t_only`/`add_only_on_trigger`/`add_on_breakout`）必填**；`hold_and_watch`/`watch` 不需要)：股数是这条 call 日后唯一能被折算成钱的凭据。面板上那条金额曲线已撤（见上条铁律），但**重建一套可信对照账本必须有股数，当天没填就永远补不回来**。宁可给保守估数也别留空。填**你真的会动的股数**,不是仓位上限。
- 所有 add 都必须逐字填写 packet setup 的 `technical_setup_id`、`technical_campaign_id`、`invalidation_price`、`condition.valid_for_sessions` 与 `tranche_number=next_tranche_number`。`alpha_confirmation` 的 `driven_by` 应按真正主导证据写 `peer`/`catalyst`/`sentiment`，不能因为技术只负责 timing 就洗成 `technical`。exploration 只是 0.25 target tranche 的前瞻采样，不是 validated；每日重置杠杆产品不能走 exploration。港股 `size.shares` 必须为 `lot_size` 的整手倍数；美股当前只支持整数股。已有 open add 或 `remaining_tranches=0` 时不得重复开单。
- `contested` ∈ {`true`, `false`}（每个 decision 必填）：Tier 2 的 Bull 与 Bear 是否真的在该策略上分歧。
- `debate`（object，主动 call 应填，`hold_and_watch`/`watch` 选填）：**把已经发生的辩论落成可核对的结构**（#1117）。Bull/Bear/devil's advocate/Judge frame 这四件事你本来就在 markdown 里写，但读者只能看到结论，无法核对反方是否真的存在——「我们辩过」在没有记录之前只是一句自述。字段：
  - `bull` / `bear`：这条 decision 上双方最强的一句话（各 ≤600 字符，超出截断）。`bear` 是这块的重点：赢的那面本来就在 `rationale` 里。
  - `attacked_consensus`：本轮 devil's advocate（见 § Tier 2 铁律）点名攻击的那条最强共识。与该票无关时可省略，别为了填而编。
  - `frames`：`Judge — strategy frames` 表里为这条 action 选的 1–3 个 frame，逐字照抄枚举值。
  - `judge`：Judge 的合成判词一句话（不是 Bull/Bear 的复述）。
  - `evidence_ids`（≤6 条，选填）：这场辩论**站在**哪几条 context 证据上（#1141）。只认三个能被解析的命名空间，postflight 逐条对着本次 context 核，**核不上的直接丢掉并记一条 degradation**（不会让流水线变红，但会被数出来）：
    - `news:<event_id>` —— `context.news_evidence_graph.events[].event_id`
    - `risk:<type>` 或 `risk:<type>:<ticker>` —— `context.risk_guardrail` 的 breach / hard_stop / concentration_review
    - `quant:<ticker>:<field>` —— `context.quant_signals.rows[<ticker>]` 上一个非空字段（如 `quant:SPCH:dist_ma200_pct`）
    **没有可引的证据就不填**，别为了填而造 id：造出来的引用比不引更糟，它看起来像证据。portable workflow lane 早就要求每个 case 带 `evidence_ids`（`workflows/validators.py`），这里是把同一条纪律接到日报这条 lane 上。
  - **不会因为格式错误让 08:00 流水线变红**：postflight 的 normalizer 会裁剪超长文本、丢弃未知键与不在枚举内的 frame，整块为空则记为「没写」。但缺席是被数出来的——dashboard 的 `debate_coverage.bear_case_pct` 就是这条纪律的实测曲线，别用空块凑覆盖率。
- `expected_move_pct`（number，选填，带符号，单位 %）：**这条 decision 预期这只票走多远**（#1159）。`confidence` 说的是「多有把握」，`invalidation_price` 说的是「论点在哪死」，**没有一个字段说「走多远」**——所以「方向对、幅度错了四倍」这句话这本账本目前对自己讲不出来。填了之后按 t1 对 `underlying_return_t1_pct` 打分（这只票自己的收益，不是 `benefit_t1_pct` 那个相对不动的反事实）。
  - 是**预测**不是目标价，也不是止损距离：写 `-8` 表示「我预期它跌 8%」。`0` 是合法且可打分的预测（「预期它不动」），和不填不是一回事。
  - |值| > 100 会被丢弃（打字过滤，不是风控），丢弃不会让流水线变红。
  - **没有把握就不要填**：这条和 `debate.evidence_ids` 同一条纪律——编一个数比不填更糟，它看起来像预测。覆盖率发布在 dashboard 的 `magnitude_metrics.coverage_pct`，必填与否以后对着这条序列谈。
- `thesis_invalidation`（string，主动 cut/trim/add 必填；hold 选填）：**借鉴 UZI-Skill 的 thesis-tracking**——这个仓位的论点**会被什么具体催化推翻**？把 catalyst-gate(cut #1)落地成「论点+失效条件」：你只在这个**失效催化真的发生**时动手，而不是技术面波动。例：「crypto rev 环比转正则停止减仓」。这逼着每个主动 call 绑定一个可被证伪的硬催化，而非"看着toppy"。
- `thesis_id` 必须沿用 `context.thesis_registry.theses.<ticker>.thesis_id`（resolved 时）；registry 为 `unknown` 时保留已有 decision ID，不得新造一个“看起来像历史”的 canonical thesis。`context.retrospective.decisions[].thesis_ref` 是只读解析结果。

**condition.type 详解**（决定 retrospective 怎么算触发）：

| 值 | 含义 | 模拟触发逻辑 |
|---|---|---|
| `open` | 开盘任意价 | 永远触发（trigger_price 一般 null） |
| `price_above` | 价格突破上方 | `day_high >= trigger_price` |
| `price_below` | 价格跌破下方 | `day_low <= trigger_price` |
| `index_breakdown` | 指数破位 | trigger_condition 字段说明哪个指数 + 哪个值 |
| `event` | 事件型（财报/公告） | 有结构化证据才触发，否则 not_evaluable |
| `manual` | 完全靠人判断 | 无结构化证据则 not_evaluable |

禁止输出顶层 `actions`。postflight 会生成稳定的 `decision_id` / `episode_id` 并写入 `memory/decisions.jsonl`。同股同日的不同 strategy 必须保留为不同 decision；同策略连续同 action 才可归入同一 episode。

#### C. 受限判断 overlay → `memory/.tmp/brief-judgment-{YYYY-MM-DD}.json`

先生成模板，再只回填观点字段：

```bash
/root/.local/bin/clawock tool decision_packet_judgment_template \
  --workspace /root/.openclaw/workspace \
  --arg manifest=/root/.openclaw/workspace/memory/.tmp/brief-context-$(date +%Y-%m-%d)/manifest.json
```

**schema v3（2026-08-31）**：这份文件现在同时是 Pages projection 的判断层
**和整篇报告的文字来源**——Tier 2/3、板块解读、大盘解读、校准解读、下一时段计划
都从这里渲染。写漏一个字段，就是发布出去的报告里空一段。

顶层只允许 `schema_version/context_generation_id/portfolio_assessment/
portfolio_counterargument/narrative/ticker_judgments`。

每票只允许（前九个字段照旧，后四个是 Tier 1 那张表里 harness 算不出来的格）：

```json
{
  "ticker": "00100",
  "verdict": "bullish|neutral|bearish|mixed",
  "confidence": 0.62,
  "disposition": "candidate|wait|reject",
  "assessment": "你的评价",
  "counterargument": "最强反方",
  "rationale": "为何在冲突信号中这样判断",
  "falsifier": "什么事实会推翻当前候选/等待判断",
  "next_evidence": "下一步要找的一手披露或价格确认",
  "fundamentals": "Tier 1 · 基本面格：EDGAR/财报/ETF 标的口径",
  "cross_market": "Tier 1 · 跨市场格：跟随还是背离",
  "sentiment_read": "Tier 1 · 情绪格：这条消息面对决策的权限（硬催化/软情绪）",
  "peer_read": "同行扫描那一行的判断：领先/落后说明什么"
}
```

`narrative`（整篇报告的辩论层，全部必填）：

```json
{
  "regime_read": "Header 那行 regime 的解读",
  "bull": "Tier 2 多头案（引 ≥2 个具体数据点）",
  "bear": "Tier 2 空头案（同上）",
  "devils_advocate": "点名攻击当前最强共识",
  "attacked_consensus": "被攻击的那条共识，一句话",
  "risk_voice_first": "aggressive|conservative|neutral（今日首位表态，4 个交易日轮换）",
  "aggressive": "Tier 3 · 抓 upside",
  "conservative": "Tier 3 · 保本 derisk",
  "neutral": "Tier 3 · 对每个争议票拍一边",
  "sector_read": "板块全景的归因结论",
  "macro_read": "大盘速读的一句判断",
  "calibration_read": "Decision v2 校准表怎么读",
  "next_session": ["下一时段第 1 步", "第 2 步"],
  "data_holes": ["还缺什么数据（可空数组）"]
}
```

三条硬规则：

1. **纯文本**。任何字段出现 `|`、`#`、`**`、` ``` `、`▎` 或行首 `-`/`*`/`1.`/`>`
   都会被 postflight 判非法并点名字段——版式是 harness 的活（见 A 节）。
2. **不写事实**。禁止加入价格、RSI、MA、因子分、股数、action、evidence 内容；
   harness 已经从 context 把它们渲染进表里，你重复一遍只会有对不上的风险。
3. `risk_voice_first` 只决定三位风险官的**表态顺序**，不改 kcn 激进偏好的权重规则。

postflight 严格校验后才把这些文字并入 `assets/data/brief_projection.json`；
overlay 缺失/非法时 Pages 仍发布 deterministic rows，只把 `judgment_status` 标为
missing/invalid——但报告的辩论段会因此空着，所以这不是"可选项"。

#### D. LLM 复盘 sidecar → `memory/.tmp/insights-{YYYY-MM-DD}.json`

build_dashboard 会读它，让 dashboard 上 **行为复盘 / 唱反调 Pre-mortem / 隐藏集中度** 三张卡同步刷新（缺失/解析失败容错，卡自动隐藏，不影响 brief 投递）。这是 dashboard 上唯一由你（LLM）写的"对决策本身的反思"层 —— 数字算不出来、只有你能写。

**铁律（accuracy）**：所有数字只能引本次 manifest 所属的 `core.json` / 已加载 bundle 里**真实出现过的** win_rate / Brier / 仓位权重 / HHI / pnl%。完整 audit 只用于 postflight 交叉校验，不能靠整份 cat 绕过预算。**绝不编造 context 里没有的具体美元金额或未发生的交易**。宁可不写一条，也不要编数字。

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
- **behavioral_review.points 4-5 条**，覆盖：① `decision_metrics.by_driver`；② `by_strategy`；③ `by_condition`；④ active episode 的 cluster CI；⑤ execution 与 advice 是否出现偏差。`tag`：edge=正面发现 / bias=认知偏差 / warning=要警惕。
- **bear_cases 2-3 个**，选**最重仓或最高杠杆**的持仓（看 context 仓位权重 + leveraged_etf）。
- **hidden_concentration**：看 sector_exposure + leveraged_etf + 持仓权重，识别表面分散实际同因子；`exposure_pct` 给该因子占组合的估算整数。
- 全部中文，口吻直接、像私人交易教练，指出问题不安慰。

#### E. 微信卡：harness 渲染，不用你写

`memory/.tmp/brief-card-{YYYY-MM-DD}.txt` 与报告一起由 `brief_render` 生成：
标题行 + 核心结论（取 `judgment.portfolio_assessment`）+ Book/HHI + 今日动作
（取 plan 的 decisions，含 driven_by 与 confidence）+ 触发位（plan 的
`watch_levels`）+ 完整报告链接。**别再手写这个文件**——写了会被覆盖。

想让卡上那句"核心结论"更准，改的是 `judgment.portfolio_assessment`，不是卡本身。

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

**改完任何一条 issue，立刻重跑一次 postflight 拿新 status，再决定还要不要继续改。**
不要在一次 `fail` 之后一路埋头修到自己认为"干净"为止 —— 修掉 critical 那条以后往往
已经是 warn，剩下的 issue 不阻塞交付。

> **2026-07-27 教训**：旧规则把 35.8KB 和表格 critical 混在同一个 issues 列表里，模型误把
> 体量当硬闸，事后一路裁到 23.7KB，既浪费时间/tokens 又引入编辑错误。新规则把体量单独记录：
> 28–40KB 是结构化 `advisory`，不计入 issues、不让已交付成品变黄；≥40KB 才是实际 `warn`。
> 无论哪档都保留完整正文，绝不在 postflight 后硬截断。**2026-08-31 起体量不再由模型控制**：报告由 `brief_render` 渲染，通常 18–22KB；这条闸留着是为了在渲染器或持仓规模变化时仍能报警。

### 投递（Step 5 postflight 内自动，你什么都不用做）

> **🔒 投递已解耦——你绝不要手动发微信、绝不调任何 message/send 工具、也不要把卡片当回复文本贴出来。**
>
> pass/warn 时 **`brief_postflight` 自己**会用 fresh-token 短连接把渲染出的
> `brief-card-{date}.txt` 投到 kcn 微信（cron 已设 `delivery=none`，这是唯一微信路径），
> 并同步 Telegram，把两路结果记到 `memory/.tmp/brief-sent-{date}.json`。
> `brief_watchdog`（08:30）只在 Telegram marker 缺失/失败时补投 Telegram，不重发微信。
>
> **为什么这样改（2026-06-08）**：旧的 `delivery=announce` 在长 turn 末尾用 turn 起点抓的 token 投递，brief turn 恒 >160s（173–975s）→ token 必过期 → 静默丢、`delivered=true` 是假信号（见 memory: openclaw-wechat-longturn-token-expiry）。短命 message send 每次抓新 token，且独立于 turn 时长，kcn 实测可靠（同 intraday 架构）。
>
> **你的职责到 Step 5 跑完 postflight 为止**：产出 B/C/D 三个文件（plan / judgment / insights）+ 跑 postflight，报告与微信卡由 postflight 内的 `brief_render` 生成。看到 `wechat_sent: true` 即大功告成，**立即结束本轮，不要再追加任何思考或内容**。
>
> **🔒 送达确认铁律（2026-08-15 起，#558）**：
> postflight **之后禁止**用 exec / list / show 去读 `memory/.tmp/` 下的 marker、claim、sent 文件"眼见为实"确认送达。
> 送达由 postflight 的 marker + watchdog 兜底负责，`wechat_sent: true` / postflight 输出里的投递摘要就是权威。
> 违例形态（2026-08-10~14 复发 ≥5 次）：`Exec failed: list files in memory/.tmp/report-sent-*.json` → 整回合被判 error → 该槽位投递缺口（#544）。**postflight 说送到了就是送到了，不要二次确认。**
>
> 这条是窄规则（只管 postflight 之后的送达确认）。**一般形式见文档开头的「Exec 铁律：退出码就是整回合的判据」** —— 2026-08-18 同一机制换个位置又发生了一次（Step 3 读昨日 notes，末尾 `head` 读到不存在的文件 exit 1，简报已投递却仍判红）。

## Style rules

- 表格优先（3+ 数据点必表格化）
- ⚠️ stale 任何数据必前置标注
- 没有"小心地"、"建议关注"这种废话 — 拍 strategy/action，拍条件与价位
- 每个 claim 钉到具体 ticker + 数字，没有泛论
- Bull/Bear/Aggressive/Conservative 必须真的不同观点
- Judge 不重复 Bull/Bear，是合成不是复述
- **FX 换算永远显式标注 source + timestamp**（core 里已有）

## 集中度阈值表（解读 core 的 `concentration` 字段）

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

## ⚠️ 货币铁律（core 已换算，但你输出时仍要双视角）

港币 + 美元 **不能直接相加**。book 段必须**两个 view 都给**：

```
真实总浮盈亏: USD${book.usd_total_pnl}  ≈  HKD${book.hkd_total_pnl}
   (USDHKD = {fx.rate}, 来源 {fx.source}, 抓取于 {fx.fetched_at})
  ├─ HK 段：HKD${book.hk_leg_hkd}  ≈  USD${book.hk_leg_hkd / fx.rate}
  └─ US 段：USD${book.us_leg_usd}  ≈  HKD${book.us_leg_usd * fx.rate}
```

历史教训：2026-05-16 那次"合计 -4,423"直接把 -4936 HKD 和 +513 USD 相加 → 毫无意义。kcn 当场指出。
