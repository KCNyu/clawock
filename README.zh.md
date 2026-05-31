<div align="center">

# 📈 clawock

**Harness 驱动的港股 + 美股组合分析** · 多智能体 LLM 群 · 自学习每日简报 · 实时仪表盘

[![Pages](https://img.shields.io/github/deployments/KCNyu/clawock/github-pages?label=pages&logo=github&color=4fa8ff)](https://kcnyu.github.io/clawock/)
[![Harness Regression](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=harness&logo=githubactions&color=26a69a)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![Health Check](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/weekly-health.yml?label=weekly%20health&logo=githubactions&color=26a69a)](https://github.com/KCNyu/clawock/actions/workflows/weekly-health.yml)
[![Cron Health](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/cron-health.yml?label=cron%20health&logo=githubactions&color=26a69a)](https://github.com/KCNyu/clawock/actions/workflows/cron-health.yml)
[![Sentiment](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/sentiment-scan.yml?label=sentiment&logo=reddit&color=f59e0b)](https://github.com/KCNyu/clawock/actions/workflows/sentiment-scan.yml)
[![License: Personal](https://img.shields.io/badge/license-personal--use-orange?color=ef5350)](#-许可)

[**🎯 实时仪表盘**](https://kcnyu.github.io/clawock/) · [**📅 每日简报**](https://kcnyu.github.io/clawock/briefs.html) · [**🧠 架构**](#-架构)

[**English**](README.md) · **简体中文**

<br>

<a href="https://kcnyu.github.io/clawock/">
  <img src="docs/dashboard-preview.png" alt="clawock dashboard" width="780">
</a>

<sub>截图每周由 <a href="https://github.com/KCNyu/clawock/actions/workflows/screenshot-refresh.yml">GH Action</a> 刷新;实时页面的数据在每次 cron 运行后更新。</sub>

</div>

---

## ✨ 这是什么

一个真实的个人投资工作区。

每个交易日,cron 守护进程([openclaw](https://openclaw.com))唤醒,从一条 fallback 链里挑出当前可用的最佳
LLM,让它扮演 `Rick` 这个人格,分析一个真实组合的港股腿 + 美股腿。模型把简报推送到微信,并刷新一个
公开仪表盘。

三点让它区别于一般的"AI 交易"演示:

1. **Harness 模式** —— 每个 cron job 被切成 `preflight(Python)→ LLM(综合)→ postflight(校验 + 提交)`。
   刷价、FX 换算、HHI 计算、信号计数这类确定性活 100% 在 Python 里跑。LLM 只被允许做无法脚本化的部分:
   写观点。漏快照、忘 FX、漏报 >3% 异动 —— 全被抓出来、报告打标记。
2. **自学习闭环** —— 每份简报提交一个结构化 `plan.json`。次日 preflight 读回它,算出哪些触发条件命中、
   模拟盈亏,把置信度校准反馈给 LLM。
3. **纵深防御** —— 四层独立兜底(cron → GH Action 兜底 → 系统 crontab 看门狗 → 健康哨兵),
   单点 LLM stall、漏跑的 cron、抽风的数据源,都不会让一份报告被静默丢掉。

---

## 🏗 架构

<div align="center">
  <img src="docs/architecture.png" alt="clawock harness pipeline" width="100%">
</div>

**确定性工作**(价格 · FX · HHI · 信号)100% 在 Python 里跑,LLM 跳不过去。
LLM 只拥有**综合**这一步。postflight 抓漏掉的快照、漏报的异动、违禁话术。

### LLM fallback 链

```
primary    xiaomi/mimo-v2.5-pro          (Anthropic-messages 协议 · thinking: high · 1M ctx)
fallbacks  → minimax/MiniMax-M2.7        (openai-completions · 200k ctx · thinking: medium)
           → glm/glm-5.1
           → deepseek/deepseek-v4-pro
           → openai/gpt-5.5
           → anthropic/claude-sonnet-4-6
           → anthropic/claude-haiku-4-5
           → openai-proxy/gpt-5.5
```

协议是**混合的**:小米 MiMo 和 Claude 系列走 `anthropic-messages`(thinking 是独立 block);
MiniMax / GLM / DeepSeek / OpenAI 走 `openai-completions`。第三方 reasoning 模型**必须**注册
`"reasoning": true`,否则 thinking 会静默锁 off。直接调 LLM 的 GH Action(brief 兜底、新闻摘要、
影响力雷达、周度复盘)绕过 gateway,经 `scripts/data/xiaomi_llm.py` 打 Xiaomi → MiniMax。

### 写入对账(唯一真正难的地方)

四类独立写者都 push 到 `master`:openclaw cron 守护进程、11 个 GitHub Actions、系统 crontab 兜底、
临时 session。它们在 `assets/data/` 上重叠 —— 尤其 `dashboard.json`。在没有中心锁的前提下保持它
一致,是唯一真正棘手的点:

- **GH Actions 之间互相串行**,靠 `concurrency: group: data-write`。
- **每个产数据的 GH Action 在自己的子文件确有变化时重建 `dashboard.json`**,这样*发布出去的*仪表盘
  永远不会落后于它自己的 `macro` / `sentiment` / `influencer_feed` 块(周末没有 intraday 重建时最关键)。
- **本地 harness 反方向拉**:`sync_gha_data_files()` 在 `build_dashboard.py` *之前*对 GH 写的文件做
  `fetch + checkout origin/master -- <file>`,所以本地重建嵌入的是最新远端数据,又不动工作区其余部分。
- **所有提交者都经 `safe_push.sh` push** —— rebase 重试、遇真冲突 abort(不死循环)。
  脚本带 `rebase.autoStash`,所以脏的宿主工作区也不会卡住 rebase。

残留风险是两个写者在重建→push 之间抢 `dashboard.json`;它会在下次重建时自愈,且对组合数字从不具
权威性(那些活在 `portfolio.json` 里)。

---

## ⚙ Cron 全景

### openclaw 调度器 —— 11 个 job(`Asia/Shanghai` 时区,= HKT)

| 时间 (HKT) | Job | Mode | Harness |
|---|---|---|---|
| **03:00** 每日 | 记忆 dreaming 促进 | _core,无 LLM_ | 由 `commit_dreaming.sh` 在 03:20 提交 |
| **08:00** 工作日 | 📊 盘前深度简报 | `daily-deep-brief`(Tier 1/2/3 + Judge) | `brief_preflight` / `brief_postflight` |
| **09:30** 工作日 | 港股开盘报告 | Mode 6 | `report_* --market hk --phase open` |
| **10:00–11:30 + 14:00–15:30** /30 分钟 | 港股盘中盯盘 | Mode 7 | `intraday_* --market hk` |
| **12:00** 工作日 | 港股午盘 | Mode 6 | `--market hk --phase mid` |
| **13:30** 工作日 | 港股午后 | Mode 6 | `--market hk --phase pm` |
| **16:00** 工作日 | 港股收盘 | Mode 6 | `--market hk --phase close` |
| **21:30** 工作日 | 美股开盘(≈09:30 ET) | Mode 6 | `--market us --phase open` |
| **22:00–23:30** /30 分钟 | 美股盘中(早段) | Mode 7 | `intraday_* --market us` |
| **00:00–02:30** 周二–六 | 美股盘中(隔夜) | Mode 7 | `intraday_* --market us` |
| **04:00** 周二–六 | 美股收盘(≈16:00 ET) | Mode 6 | `--market us --phase close` |

### 韧性层 —— 系统 crontab(宿主上无 LLM 的兜底)

| 时间 (HKT) | 兜底 | 守的是什么 |
|---|---|---|
| 09:45 / 12:12 / 16:15 / 13:42 工作日 · 04:20 / 21:45 | `report_watchdog.py` ×6 | 报告 cron 的 LLM stall/失败时,把确定性的 `raw_wechat_block` 直送微信 |
| **03:20** 每日 | `commit_dreaming.sh` | 提交 + push core 追加进 `MEMORY.md` / `DREAMS.md` 但从不提交的 dreaming 促进 |
| **03:30** 每日 | `gc_sessions.py` | 清理过期 trajectory / bak / 过期 handoff(否则约 9 GB/年) |

### GitHub Actions —— 11 个 workflow

| Workflow | 何时 (HKT) | 写什么 / 做什么 |
|---|---|---|
| `brief-fallback.yml` | 08:25 工作日 | openclaw **没**产出简报时,用 Xiaomi 重新生成 |
| `sentiment-scan.yml` | 05:30 工作日 | `sentiment.json`(Reddit + Google News)→ 重建 `dashboard.json` |
| `macro-scan.yml` | 05:45 工作日 | `macro.json`(VIX / 10Y / DXY / Fear&Greed)→ 重建 `dashboard.json` |
| `influencer-scan.yml` | 05:40 + 20:50 工作日 | `influencer_feed.json`(Trump Truth Social + Musk 代理,LLM 过滤)→ 重建 `dashboard.json` |
| `news-digest.yml` | 21:00 工作日 | `us_news_digest.json`(Xiaomi 提炼,GNews 兜底) |
| `eod-archive.yml` | 周六 06:00 | `memory/archive/eod-history.csv` —— 只追加的审计流水 |
| `cron-health.yml` | 17:00 工作日 | 只读:应跑 cron 次数 vs 实际 commit 数 → 漂移则红 badge + 邮件 |
| `weekly-health.yml` | 周一 07:00 | 只读深检:脚本能否编译、schema、失效 cron 路径、挂掉的数据源 |
| `weekly-review.yml` | 周日 22:00 | 经 Xiaomi 出周度组合复盘 → 微信 |
| `screenshot-refresh.yml` | 周一 06:00 | `docs/dashboard-{preview,mobile}.png`,让 README 预览图不超过 7 天 |
| `harness-regression.yml` | push / PR 时 | 只读 schema + 编译门禁 |

> GH Actions 的 scheduled cron 经常晚 **1–2 小时**触发 —— 没有任何 job 依赖紧耦合的先后顺序。
> pre-brief 的数据 job(sentiment/macro/influencer)被安排在 08:00 简报*前约 2 小时*(而非 30 分钟),
> 正是为吸收这个延迟;brief 兜底则在 openclaw 简报*之后*等 25 分钟才认定它缺席。

> **三处调度的单一视图:** `./check_crons.sh --timeline` 把 openclaw + GH Actions + 系统 crontab 合并成
> 一张归一到 HKT 的时间线 —— 并应用 UTC→HKT 的星期跨日修正,所以一条写成 `* * 1-5`(UTC)的 GH Action
> 会显示在它*真实*的 HKT 触发日上。(运行历史:`./check_crons.sh`。)

---

## 📂 仓库结构

```
clawock/
├─ index.html  briefs.md  README.md          ← Pages 落地页 + 本文件
├─ assets/                                   ← Pages 静态资源
│  └─ data/                  由 harness postflight + GH Actions 构建,永不手改
│     ├─ dashboard.json        v2.x schema(CSS/JS 自 v2 起内联进 index.html)
│     ├─ risk.json             β/Vol/DD/Sharpe(portfolio_risk_metrics.py)
│     ├─ catalysts.json        14天财报 + FOMC + macro(fetch_catalysts.py)
│     ├─ us_news_digest.json   Xiaomi 提炼(news-digest.yml)
│     ├─ macro.json            VIX / DXY / Fed RSS(macro-scan.yml)
│     ├─ sentiment.json        Reddit + Google News(sentiment-scan.yml)
│     ├─ influencer_feed.json  Trump / Musk 异动源,LLM 过滤(influencer-scan.yml)
│     └─ fx.json               USDHKD(fetch_fx.py,4h 缓存)
│
├─ portfolio.json                            ← 唯一真源(原子写)
├─ MEMORY.md  DREAMS.md                       ← 铁律 + dreaming 促进(03:20 自动提交)
├─ memory/
│  ├─ {YYYY-MM-DD}.md           session / 手写笔记
│  ├─ {YYYY-MM-DD}-pre-open.md  盘前深度简报输出
│  ├─ {YYYY-MM-DD}-plan.json    结构化 plan(次日回溯输入)
│  ├─ snapshots/{date}.json     每日组合快照
│  └─ archive/eod-history.csv   每周 EOD 归档(GH Action)
│
├─ scripts/
│  ├─ data/                     fetcher + build_dashboard.py + portfolio_risk_metrics.py +
│  │                            fetch_{macro,sentiment,catalysts,fx,influencer_feed}.py +
│  │                            xiaomi_llm.py + gh_action_*(GH Action LLM 入口) +
│  │                            safe_push.sh + commit_dreaming.sh + gc_sessions.py + safe_io(原子) +
│  │                            cron_timeline.py(合并调度视图) + shoot_dashboard.js(截图)
│  ├─ harness/                  preflight + postflight 成对(4 对) + report_watchdog.py + _harness_common
│  └─ legacy/                   被取代的脚本,留作参考
│
├─ skills/{name}/SKILL.md       Claude Code skill 正文
└─ _layouts/default.html        Jekyll 布局 · 所有 md 页面以仪表盘暗色主题渲染
```

---

## 🚀 快速开始

```bash
# 1. 刷新美股价格(7 路 fallback)
python3 scripts/data/analyze_us_stocks.py

# 2. 刷新港股价格(腾讯 → stooq → yfinance)
python3 scripts/data/analyze_hk_stocks.py

# 3. 手动跑一份简报
python3 scripts/harness/brief_preflight.py    # 产出 memory/.tmp/brief-context-*.json
# …(LLM 写 memory/{date}-pre-open.md + plan.json)…
python3 scripts/harness/brief_postflight.py   # 校验、重建 dashboard、提交

# 4. 本地预览仪表盘
python3 scripts/data/build_dashboard.py
python3 -m http.server 8080
# → http://localhost:8080/
```

API key(Finnhub、Alpha Vantage、Polygon……)放在 `.api_keys`(已 gitignore)。
所有脚本无 key 也能跑 —— 只是数据质量降级。

---

## 📜 铁律

> postflight 强制执行的约束。否则扫代码的读者根本看不出它们的存在。

### 🪙 FX —— HKD + USD 绝不直接相加

港股腿以 HKD 计价,美股腿以 USD 计价。粗暴相加得到一个无意义的数。
Book 总额必须**双视角**呈现,并标注汇率 + 时间戳:

```
Total P&L: USD${X}  ≈  HKD${Y}      (USDHKD = 7.83, source Frankfurter, 2026-05-16T12:00Z)
  ├─ HK leg: HKD${a}  ≈  USD${a / 7.83}
  └─ US leg: USD${b}  ≈  HKD${b * 7.83}
```

### 📊 集中度 —— HHI

各腿分别计算:
- `weight_i = current_value_i / leg_total_value`
- `HHI = Σ weight²` · `Top2 = 两个最大权重之和`

| HHI | Top 2 | 状态 |
|---|---|---|
| < 0.15 | < 40% | ✅ 健康 |
| 0.15 – 0.25 | 40 – 60% | 🟡 中等 |
| 0.25 – 0.40 | 60 – 75% | 🟠 偏集中 |
| > 0.40 | > 75% | 🔴 危险 |

### 🎲 杠杆 ETF 启发式

preflight 对名称含杠杆标记的标的跳过 SEC EDGAR —— `倍`、`Direxion`、`T-Rex`、`Defiance`、`ProShares`、`2X Long`、`3X Long`、`Daily Target`。
杠杆 ETF 的基本面是噪声 —— 看底层标的。

### 💵 回报率分母 —— 峰值净投入

回报率用 `true_principal` = 现金流账本里的**峰值净投入**,不是 `cost − realized`。
已实现盈利会缩小 `cost − realized` 从而虚高回报率;账本基准不会动。

---

## 🤖 自学习闭环

第 N 天 → 第 N+1 天:每份 daily-deep-brief 提交 `memory/{date}-plan.json`,带结构化动作
(触发条件、置信度、模拟入场)。次日清晨的 preflight 读回它,算出哪些触发条件真的命中、模拟盈亏,
把结果记入一张滚动的置信度校准表,再反馈进下一份简报的置信度判断。

Plan schema(截断,完整版见任一 `memory/*-plan.json`):

```jsonc
{
  "date": "2026-05-16",
  "buckets": { "cut": [...], "trim_on_rebound": [...], "hold_and_watch": [...],
               "t_only": [...], "add_only_on_trigger": [...] },
  "actions": [{
    "ticker":       "07226",
    "bucket":       "trim_on_rebound",
    "trigger_type": "price_above",
    "trigger":      "trim 1000 shares if price > 4.85",
    "confidence":   0.62,
    "simulated_entry_price": 4.49
  }],
  "context": { "hhi_us": 0.21, "hhi_hk": 0.34, "fx": 7.83 }
}
```

次日清晨 preflight 读回它,对每个动作计算:
1. **触发条件命中了吗?**(对照实际价格走势)
2. **模拟盈亏** —— 若在触发点执行该动作
3. **置信度校准** —— 记入滚动统计

设计深受 [TauricResearch/TradingAgents v0.2.4](https://github.com/TauricResearch/TradingAgents) 的
持久化决策记忆启发,针对港股 + 美股双腿组合做了改造。

---

## 🧬 技术栈

[Claude Code](https://claude.com/claude-code) · [openclaw](https://openclaw.com) ·
[ECharts 5.5](https://echarts.apache.org/) · Jekyll + GitHub Pages · Python 3.11 · 纯静态前端

**公开数据源** 腾讯 · stooq · yfinance · Frankfurter · SEC EDGAR · Finnhub · Nasdaq API ·
东方财富 · Polygon · Alpha Vantage · Reddit JSON · Google News RSS · Trump Truth Social feed

---

## ⚠️ 免责声明

本仓库包含**真实交易仓位**。公开分享仅为个人记录与可移植工作区之用 —— **不构成投资建议**、
不是推荐、不是任何你该照抄的东西。每个数字都是时点值,你读到时可能已经过时。
人格(`Rick`)被刻意设计得有主见 —— 那不代表它对。

---

## 📄 许可

个人使用仓库。不授予用于衍生交易系统、自动跟单或商业用途的许可。
代码模式(harness 布局、fallback 链设计、HHI 公式、原子 IO)若独立复用,可在你选择的任何兼容
开源许可下改编。

---

<div align="center">
<sub>由 <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> 与 Rick 构建维护 · 2026</sub>
</div>
