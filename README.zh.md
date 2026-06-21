<div align="center">

# 📈 clawock

### 一群 LLM,每个交易日盯着我**真金白银**的港股 + 美股仓位 —— 而且第二天早上会给自己打分。

[![Pages](https://img.shields.io/github/deployments/KCNyu/clawock/github-pages?label=live%20dashboard&logo=github&color=4fa8ff)](https://kcnyu.github.io/clawock/)
[![Harness Regression](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=harness&logo=githubactions&color=26a69a)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![Cron Health](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/cron-health.yml?label=cron%20health&logo=githubactions&color=26a69a)](https://github.com/KCNyu/clawock/actions/workflows/cron-health.yml)
[![Weekly Health](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/weekly-health.yml?label=weekly%20health&logo=githubactions&color=26a69a)](https://github.com/KCNyu/clawock/actions/workflows/weekly-health.yml)
[![License: Personal](https://img.shields.io/badge/license-personal--use-orange?color=ef5350)](#-许可)

[**🎯 实时仪表盘**](https://kcnyu.github.io/clawock/) · [**📅 每日简报**](https://kcnyu.github.io/clawock/briefs.html) · [**它怎么跑的 ↓**](#-60-秒看懂)

[**English**](README.md) · **简体中文**

<br>

<a href="https://kcnyu.github.io/clawock/">
  <img src="docs/dashboard-preview.png" alt="clawock dashboard" width="800">
</a>

<sub>真实持仓,真实盈亏。页面在每次 cron 运行后更新;这张截图每周由 <a href="https://github.com/KCNyu/clawock/actions/workflows/screenshot-refresh.yml">GitHub Action</a> 自动刷新,永不过期。</sub>

</div>

---

## 🎰 60 秒看懂

我把一个真实的券商组合 —— 一条港股腿、一条美股腿,真金白银 —— 交给一个 LLM,然后在它周围搭了台小机器。

每个交易日,它自己:

- 🌅 醒来 **约 10 次**(港股开盘、午盘、收盘 → 美股开盘、盘中、隔夜、收盘),
- 📥 抓最新价格、汇率、波动率、财报日历、宏观(VIX/DXY/10Y)、Reddit + 新闻舆情,甚至 **Trump/Musk 的市场异动**,
- 🧠 把洗干净的数据交给当前可用的最佳 LLM —— 扮演一个嘴很直的人格 **Rick** —— 写出观点,
- 📲 把简报推到我的**微信**,并
- 🌐 刷新一个**公开仪表盘**(你现在就能打开)。

这就是噱头所在:*一整张永不打烊、和我一起盯盘的 AI 交易台。*

但大多数"AI 炒股"演示会跳过下面这一段 👇

## 🪞 它会给自己打分 —— 而且承认自己在亏

每份简报不只是嘴上说说。它会提交一个结构化的 **`plan.json`**:每个判断都带触发条件、置信度、模拟入场价。第二天早上,系统读回它,核对哪些触发条件真的命中、模拟盈亏,把结果记进一张滚动战绩表。

所以我能拿着账本告诉你,这个 AI *实际上*表现如何:

| AI 做了什么 | 样本 | 命中率 | 诚实结论 |
|---|---|---:|---|
| **cut / trim / 加仓**(主动判断) | — | **< 45%** | 不如掷硬币 |
| 高信心判断(置信度 ≥ 0.75) | — | **42%** | 过度自信 |
| **只是 `hold`** | — | **76%** | 这是 β,不是 α |
| 🔴「追高」警示 | n=22 | 50% | 能标出动作,择不准时点 |
| 🟡「超卖,或许反弹」 | n=77 | 36% | 在接飞刀 |

> 再读一遍:在这个样本上,**模型的主动信号跑输了单纯持有。** 系统*自己公开说了*,因为这张战绩表是用 Python 算的,LLM 没权限作弊。诚实本身就是功能 —— 一个"AI 分析师"大半的价值,在于知道什么时候该无视它。

<sub>数字来自 `memory/calibration.csv`、`quant_signal_review.json`、`t0_setup_review.json`,随样本增长而变动。n < 20 的因子只展示、**禁止进入决策**,直到它用命中率挣到话语权。</sub>

---

## 📅 一天到底长什么样

```
03:00  🌙  记忆「做梦」—— 把昨天的教训提升进长期笔记
08:00  📊  每日深度简报 —— 多层分析 + 一个裁判模型,推送到微信
09:30  🇭🇰  港股开盘 → 10:00–11:30 / 14:00–15:30 盘中 → 12:00 午盘 → 16:00 收盘
21:30  🇺🇸  美股开盘 → 22:00–02:30 盘中(含隔夜)→ 04:00 收盘
            ↑ 每次运行都会顺手刷新公开仪表盘
周末   🛰️  宏观 / 舆情 / 影响力 / 新闻扫描,让页面保持新鲜
```

全部 HKT。休市怎么办?一道**节假日 + 周末闸**会跳过运行,而不是烧 token、把一个隔夜旧价当成实时价写进去。

---

## 🛡️ 为什么它不会悄悄崩

把真实自动化跑了几个月,我学到:难的不是 prompt,而是它*周围*所有会出错的东西。三个想法撑起了整套系统:

<table>
<tr><td width="33%" valign="top">

**1. Harness 模式**

每个 job 都是 `preflight(Python)→ LLM → postflight(Python)`。确定性的活 —— 价格、FX、HHI、信号计数 —— 100% 在代码里跑。LLM 只负责写*观点*。忘了 FX、漏了快照、跳过 >3% 异动 → postflight 抓出来并给报告打标记。

</td><td width="33%" valign="top">

**2. 自学习闭环**

今天的 `plan.json` → 明天被打分。战绩表把置信度校准反馈回下一份简报,让模型不断被自己的真实战绩打脸,而不是永远凭感觉。

</td><td width="33%" valign="top">

**3. 纵深防御**

四层独立兜底 —— cron → GitHub Action 兜底 → 系统 crontab 看门狗 → 健康哨兵。单点 LLM stall、漏跑的 cron、抽风的数据源,**都不会让一份报告被静默丢掉**。

</td></tr>
</table>

<details>
<summary><b>🔧 引擎盖下面</b> —— 模型链、写入对账、真正棘手的部分</summary>

<br>

**模型。** 交互式聊天跑在 Claude 上(走 `claude-cli` runtime,复用我的 Claude Code 登录态 —— 仓库里没有 key)。无人值守的简报/报告跑在 pin 死的 **`MiniMax-M3`** 上,后面挂一条 fallback 链(`GLM → DeepSeek → GPT → Claude → Haiku`)。协议混合:Claude/MiniMax 走 `anthropic-messages`(thinking 是独立 block);GLM/DeepSeek/OpenAI 走 `openai-completions`。第三方 reasoning 模型**必须**注册 `"reasoning": true`,否则 thinking 会静默锁 off —— 这个坑我踩过一次。

**写入对账(唯一真正难的地方)。** 四类独立写者都 push 到 `master`:cron 守护进程、约 11 个 GitHub Actions、系统 crontab 兜底、临时 session。它们在 `assets/data/dashboard.json` 上重叠。在没有中心锁的前提下:

- GH Actions 之间靠 `concurrency: group: data-write` 互相串行。
- 每个产数据的 Action **只在自己的子文件确有变化时重建 `dashboard.json`**,这样发布出去的页面永远不落后于它自己的 macro/sentiment/influencer 块(周末最关键)。
- 本地 harness 反方向拉:`sync_gha_data_files()` 在重建*之前*对 GH 写的文件做 `fetch + checkout origin/master -- <file>`,嵌入最新远端数据又不动工作区其余部分。
- 所有人都经 `safe_push.sh` push —— rebase 重试、遇真冲突 abort(不死循环);提交进来的冲突标记会在 **push hook 被拒**,所以坏掉的 `dashboard.json` 永远到不了 Pages。

残余风险是两个写者在重建和 push 之间打架;它在下一次重建时自愈,且永不作为组合数字的权威来源 —— 那些数字活在 `portfolio.json` 里,原子写入。

</details>

---

## 📐 代码强制的「铁律」

`postflight` 不允许模型违反的约束。量化的读者一看就懂每条为什么存在:

- **🪙 FX —— HKD 和 USD 绝不直接相加。** 总额永远以两种口径展示,并盖上汇率 + 时间戳(`USDHKD = 7.83,来源 Frankfurter,<ts>`)。两种货币裸加是个毫无意义的数。
- **📊 集中度 —— 每条腿单独算 HHI。** `HHI = Σ wᵢ²`,外加 Top-2 权重。分档:`<0.15` ✅ · `0.15–0.25` 🟡 · `0.25–0.40` 🟠 · `>0.40` 🔴。逐腿计算,绝不混算。
- **🎲 杠杆 ETF —— 看标的本身。** 名字带杠杆标记(`倍`、`Direxion`、`T-Rex`、`ProShares`、`2X/3X Long`……)的标的直接跳过基本面 —— 对每日重置的 2×/3× 产品,基本面是噪音;改用一个**杠杆刻度盘**(200 日趋势 × 波动率)来限制允许的杠杆上限。
- **💵 回报口径 —— 峰值净本金。** 回报 % 用 `true_principal` = 现金流账本里的峰值净投入,*不是* `cost − realized`。一笔已实现盈利会缩小 `cost − realized`、虚抬回报;账本口径不动。

---

## 🧬 技术栈与数据源

[Claude Code](https://claude.com/claude-code) · [openclaw](https://openclaw.com)(cron 守护进程)· [ECharts 5.5](https://echarts.apache.org/) · Jekyll + GitHub Pages · Python 3.11 · 纯静态前端

**公开数据** 腾讯 · stooq · yfinance · Frankfurter · SEC EDGAR · Finnhub · Nasdaq · 东财 · Polygon · Alpha Vantage · Reddit JSON · Google News RSS · Trump Truth Social feed

<details>
<summary><b>📂 仓库结构</b></summary>

<br>

```
clawock/
├─ index.html  briefs.md                    ← Pages 着陆页
├─ assets/data/        由 harness + GH Actions 生成,绝不手改
│   ├─ dashboard.json  risk.json  catalysts.json  fx.json
│   ├─ macro.json  sentiment.json  influencer_feed.json  us_news_digest.json
│   ├─ quant_signals.json  quant_signal_review.json     ← 因子战绩表
│   └─ t0_setups.json  t0_setup_review.json             ← 盘中牌面战绩表
├─ portfolio.json                           ← 唯一真值源(原子写入)
├─ MEMORY.md  DREAMS.md                      ← 铁律 + 每夜「做梦」提升
├─ memory/
│   ├─ {date}-pre-open.md  {date}-plan.json  ← 简报输出 + 结构化计划
│   ├─ calibration.csv                       ← 自我打分的战绩表
│   └─ snapshots/{date}.json
├─ scripts/
│   ├─ data/      抓取器 · build_dashboard.py · risk/quant/regime/t0 计算 · safe_push.sh
│   └─ harness/   {brief,report,intraday}_{pre,post}flight.py · 看门狗
└─ skills/{name}/SKILL.md
```

</details>

---

## ⚠️ 免责声明

本仓库包含**真实、在场的交易持仓** —— 这正是分享它的意义所在,也正是你该对里面一切持保留态度的原因。它是一份个人记录、一个可移植的工作区。它**不是投资建议**、不是推荐、**更不是你该照抄的东西** —— 上面那张战绩表白纸黑字写着:主动判断跑输了单纯持有。每个数字都是时点值,你读到时可能已经过期。`Rick` 生来就爱下断言;那不代表他是对的。

## 📄 许可

个人使用仓库。不授予任何衍生交易系统、自动跟单或商业用途的许可。其中的*模式*(harness 结构、fallback 链设计、HHI 公式、原子 IO、自我打分闭环)若独立复用,可在任意兼容的开源许可下改编。

---

<div align="center">
<sub>由 <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> 与 Rick 构建维护 · 2026</sub>
</div>
