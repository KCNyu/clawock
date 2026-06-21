<div align="center">

# 📈 clawock

### An LLM swarm that watches my **real** HK + US money every trading day — and grades itself the next morning.

[![Pages](https://img.shields.io/github/deployments/KCNyu/clawock/github-pages?label=live%20dashboard&logo=github&color=4fa8ff)](https://kcnyu.github.io/clawock/)
[![Harness Regression](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=harness&logo=githubactions&color=26a69a)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![Cron Health](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/cron-health.yml?label=cron%20health&logo=githubactions&color=26a69a)](https://github.com/KCNyu/clawock/actions/workflows/cron-health.yml)
[![Weekly Health](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/weekly-health.yml?label=weekly%20health&logo=githubactions&color=26a69a)](https://github.com/KCNyu/clawock/actions/workflows/weekly-health.yml)
[![License: Personal](https://img.shields.io/badge/license-personal--use-orange?color=ef5350)](#-license)

[**🎯 Live Dashboard**](https://kcnyu.github.io/clawock/) · [**📅 Daily Briefs**](https://kcnyu.github.io/clawock/briefs.html) · [**How it works ↓**](#-the-60-second-version)

**English** · [**简体中文**](README.zh.md)

<br>

<a href="https://kcnyu.github.io/clawock/">
  <img src="docs/dashboard-preview.png" alt="clawock dashboard" width="800">
</a>

<sub>Real positions. Real P&L. The page updates after every cron run; this screenshot refreshes weekly via a <a href="https://github.com/KCNyu/clawock/actions/workflows/screenshot-refresh.yml">GitHub Action</a> so it never drifts.</sub>

<br><br>

🪞 **Grades its own trades** — and admits they lose to buy-and-hold &nbsp;·&nbsp; 💸 **Real money**, not a paper sim &nbsp;·&nbsp; 🗣️ **Bull-vs-bear AI debate** every morning &nbsp;·&nbsp; 🛡️ **Python does the math** so the LLM can't fudge the score &nbsp;·&nbsp; 🌏 **Bilingual** HK + US &nbsp;·&nbsp; 🌐 **Live public dashboard**

<sub>If "an AI that's honest about being wrong" is your kind of thing — ⭐ it.</sub>

</div>

---

> **TL;DR** — A multi-agent LLM runs a real Hong-Kong + US stock portfolio, debates bull-vs-bear each morning, and back-tests its own calls every night. Its verdict on itself, in public: the active calls *lose to simply holding*. The honesty is the point.

## 🎰 The 60-second version

I gave an LLM a real brokerage portfolio — a Hong Kong leg and a US leg, actual money — and wired up a small machine around it.

Every trading day, on its own, the system:

- 🌅 wakes up **~10 times** (HK open, mid, close → US open, intraday, overnight, close),
- 📥 pulls fresh prices, FX, volatility, earnings calendars, macro (VIX/DXY/10Y), Reddit + news sentiment, even **Trump/Musk market-movers**,
- 🧠 hands the clean data to the best-available LLM — playing a blunt persona named **Rick** — to write the take,
- 📲 pushes a briefing to my **WeChat**, and
- 🌐 refreshes a **public dashboard** you can open right now.

That's the gimmick: *a whole AI desk that trades alongside me and never sleeps.*

But here's the part most "AI trader" demos skip 👇

## 🪞 It grades its own homework — and admits it's losing

Every brief doesn't just talk. It commits a structured **`plan.json`**: each call gets a trigger, a confidence number, and a simulated entry price. The next morning the system reads it back, checks which triggers actually fired, simulates the P&L, and logs the result to a rolling scorecard.

So I can tell you, with receipts, how the AI is *actually* doing:

| What the AI did | Sample | Hit rate | Honest verdict |
|---|---|---:|---|
| **cut / trim / add** (active calls) | — | **< 45%** | worse than a coin flip |
| high-conviction calls (confidence ≥ 0.75) | — | **42%** | overconfident |
| **just `hold`** | — | **76%** | this is β, not α |
| 🔴 "chasing a high" warning | n=22 | 50% | flags the move, can't time it |
| 🟡 "oversold, might bounce" | n=77 | 36% | catching knives |

> Read that again: on this sample, **the model's active signals underperform simply holding.** The system *says so itself*, in public, because the scorecard is computed in Python and the LLM isn't allowed to fudge it. The honesty is the feature — most of the value of an "AI analyst" is knowing when to ignore it.

**There's now a curve for it.** A counterfactual *"if you'd followed every call"* backtest (the LLM only advises — execution is always mine) reuses the same direction-signed benefit% the scorecard already logs, and plots it against a `do-nothing = 0` baseline on the **Reflect** tab. The active-only line sits **−33pp below doing nothing** (T+1; −46pp at T+5), while the "all signals" line's +474pp is almost entirely `hold` = market β. You can *watch* the active calls bleed relative to a hold.

<sub>Numbers are point-in-time from `memory/calibration.csv`, `quant_signal_review.json`, `t0_setup_review.json` and move as samples grow. Factors with n < 20 are shown but **barred from influencing decisions** until they earn it.</sub>

**The scorecard is built not to fool itself.** Three guards stop a noisy number from masquerading as edge:

- **95% confidence intervals on every rate.** "catalyst 72%" is really `[59–82]` at n=54; a band that straddles 50% (macro, peer) is flagged `edge_significant: false` — statistically indistinguishable from a coin flip.
- **A risk-adjusted verdict, not just hit-rate.** By *frequency* the active book looks +6pp ahead of holding. By *return* it's **−0.57pp** — and the gap isn't significant — against a portfolio β of 4.4. So a leveraged-beta "win" is never mistaken for skill.
- **Catalyst-gate discipline.** Only `catalyst` has a CI-proven edge, so an active cut/trim/add must name the hard catalyst that justifies it (and the one that would *invalidate* its thesis). The dashboard tracks how many actually do — currently ~20%, i.e. most active calls are still filter-grade technicals.

---

## 🎯 How it actually decides

Behind the persona is a fixed decision framework — not freeform vibes. Every call is attributed, gated, and bucketed before it's allowed to count.

**1. Attribution-first — and the edge is measured.** Every call is tagged by *what drove it*, then scored over time. On the live record:

| Driver | Hit rate | How it's used |
|---|---:|---|
| **catalyst** (earnings, FOMC, dated event) | **69%** (n=61) | the only driver allowed to *initiate* an action |
| **technical** (trend / RSI / levels) | **59%** (n=116) | a filter, never the thesis |
| macro | 50% (n=20) | context; a coin-flip on its own |
| **peer / 抱团 read-across** | **40%** (n=10) | the worst — herd reasoning is actively distrusted |

**2. Hard catalyst vs. soft sentiment.** Soft sentiment (Reddit, mood, a single tweet) can only nudge a *confidence* number — it can never flip the action bucket. Only a hard, dated catalyst can.

**3. Falsify, don't confirm.** In a risk-on tape the default is `HOLD`. A *confirming* bullish story doesn't trigger a buy; the model first has to clear a disconfirming check and a "is this already priced in?" test (the last-5-day move).

**4. Conviction is capped by hard risk gates.** However sure it feels: single name ≤35%, Top-2 ≤70%, leverage-ETF sleeve ≤50%, portfolio β ≤3.0, stop at −18%. Position size is bounded by construction, not by mood.

**5. Leverage is dialed by regime, not timed.** A 200-day-trend × volatility dial sets a multiplier (×1 / ×0.5 / ×0) on the leverage-ETF cap. The backtest lesson behind it: the alpha was in *de-leveraging in the wrong regime*, not in calling tops.

**6. Quant signals must earn the right to speak.** A factor layer (MA cross, 12-1 momentum, RSI-14, z-score, ATR chandelier stop, vol-target sizing) runs in Python — but each factor is **barred from influencing a decision until it clears n≥20 and proves a hit rate.** Unproven factors are shown, never obeyed.

Everything resolves into an action bucket with an explicit trigger — `cut` / `trim-on-rebound` / `hold` / `T-only` / `add-only-on-trigger`. That bucket list *is* the `plan.json` graded the next morning: **the strategy and the scorecard are the same object.**

---

## 🗣️ Every morning, the desk argues with itself

The 08:00 deep brief isn't one model's monologue — it's a structured **multi-agent debate**, borrowed from [TradingAgents](https://github.com/TauricResearch/TradingAgents) and adapted for a dual-leg book:

- **Tier 1 — four analyst lenses.** Fundamental / technical / sentiment / sector-rotation each read the *same* `context.json` and merge into one table. Numbers only, no vibes.
- **Tier 2 — Bull vs Bear.** Two researchers build opposing cases (hold/add vs trim/cut), each citing ≥2 concrete Tier-1 data points. The hard rule: **they must genuinely disagree on at least one position** — unanimous agreement means the debate failed and is thrown out.
- **Tier 3 — three risk voices + a Judge.** Aggressive, Conservative and Neutral each argue their corner; a **Judge** weighs them, names which strategy frame is driving each decision, and resolves the argument into concrete bucketed actions with triggers.

The goal isn't consensus — it's **forcing a real bear case to exist before anything is held**, so the book never just talks itself into its own positions. The Judge's verdict *is* the `plan.json` that gets graded the next morning.

---

## 📅 What a day actually looks like

```
03:00  🌙  memory "dreaming" — promote yesterday's lessons into long-term notes
08:00  📊  daily deep brief   — multi-tier analysis + a judge model, ships to WeChat
09:30  🇭🇰  HK open  → 10:00–11:30 / 14:00–15:30 intraday → 12:00 mid → 16:00 close
21:30  🇺🇸  US open  → 22:00–02:30 intraday (incl. overnight) → 04:00 close
            ↑ every run also refreshes the public dashboard
weekend 🛰️  macro / sentiment / influencer / news scans keep the page warm
```

All times HKT. Markets closed? A **holiday + weekend gate** skips the run instead of burning tokens and writing a stale price as if it were live.

---

## 🛡️ Why it doesn't quietly break

Running real automation for months taught me that the hard part isn't the prompt — it's everything that goes wrong *around* it. Three ideas carry the whole thing:

<table>
<tr><td width="33%" valign="top">

**1. Harness pattern**

Every job is `preflight (Python) → LLM → postflight (Python)`. Deterministic work — prices, FX, HHI, signal counting — runs 100% in code. The LLM only writes the *opinion*. Forget FX, miss a snapshot, skip a >3% mover → postflight catches it and flags the report.

</td><td width="33%" valign="top">

**2. Self-learning loop**

`plan.json` today → graded tomorrow. The scorecard feeds confidence calibration back into the next brief, so the model is continuously confronted with its own track record instead of vibing forever.

</td><td width="33%" valign="top">

**3. Defense in depth**

Four independent layers — cron → GitHub Action backstop → system-crontab watchdogs → health sentinels. A single LLM stall, a missed cron, or a flaky data source **never silently drops a report**.

</td></tr>
</table>

<details>
<summary><b>🔧 Under the hood</b> — model chain, write reconciliation, the genuinely tricky bits</summary>

<br>

**Models.** Interactive chat runs on Claude (via the `claude-cli` runtime, reusing my Claude Code login — no key in the repo). The unattended briefs/reports run on a pinned **`MiniMax-M3`** with a fallback chain behind it (`GLM → DeepSeek → GPT → Claude → Haiku`). Mixed protocols: Claude/MiniMax speak `anthropic-messages` (thinking is its own block); GLM/DeepSeek/OpenAI speak `openai-completions`. A third-party reasoning model **must** be registered with `"reasoning": true` or its thinking silently locks off — a trap I paid for once.

**Write reconciliation (the one genuinely hard part).** Four independent writers push to `master`: the cron daemon, ~11 GitHub Actions, system-crontab backstops, and ad-hoc sessions. They overlap on `assets/data/dashboard.json`. With no central lock:

- GH Actions serialize among themselves via `concurrency: group: data-write`.
- Each data-producing Action **rebuilds `dashboard.json` only when its own sub-file changes**, so the published page never lags its own macro/sentiment/influencer blocks (matters most on weekends).
- The local harness pulls the other way: `sync_gha_data_files()` does `fetch + checkout origin/master -- <file>` *before* rebuilding, embedding the freshest remote data without touching the rest of the tree.
- Everyone pushes through `safe_push.sh` — rebase-retry, abort (don't loop) on a real conflict; a committed conflict marker is **rejected at the push hook** so a broken `dashboard.json` can never reach Pages.

The residual risk is two writers racing between rebuild and push; it self-heals on the next rebuild and is never authoritative for portfolio numbers — those live in `portfolio.json`, written under an **advisory `flock` + read-fresh-then-overlay** (`mutate_json`) so concurrent fetchers serialize and can't lose each other's updates (closing the load-modify-write race class), with atomic `os.replace` underneath.

</details>

---

## 📐 House rules the code enforces

The constraints `postflight` won't let the model violate. Quant readers will recognize why each exists:

- **🪙 FX — HKD and USD never sum directly.** Totals are always shown in both views with the rate + timestamp stamped (`USDHKD = 7.83, source Frankfurter, <ts>`). Adding two currencies naively is a meaningless number.
- **🔢 Manual-entry guards.** The few hand-typed values (cash balances, gold-fund reconciliation) get fat-finger checks: a cash number that jumps ≥5× vs the last snapshot, or a gold avg-cost that diverges from NAV, is flagged before it silently corrupts total assets.
- **📊 Concentration — HHI per leg.** `HHI = Σ wᵢ²`, plus Top-2 weight. Buckets: `<0.15` ✅ · `0.15–0.25` 🟡 · `0.25–0.40` 🟠 · `>0.40` 🔴. Computed per leg, never blended.
- **🎲 Leverage ETFs — judge the underlying.** Tickers whose name carries a leverage marker (`倍`, `Direxion`, `T-Rex`, `ProShares`, `2X/3X Long`, …) skip fundamentals entirely — for a daily-reset 2×/3× product, fundamentals are noise; a **regime dial** (200-day trend × volatility) caps how much leverage is allowed instead.
- **💵 Return basis — peak net principal.** Return % uses `true_principal` = peak net deposit from the cash-flow ledger, *not* `cost − realized`. A realized win shrinks `cost − realized` and fakes a higher return; the ledger basis doesn't move.

---

## 🧬 Stack & sources

[Claude Code](https://claude.com/claude-code) · [openclaw](https://openclaw.com) (cron daemon) · [ECharts 5.5](https://echarts.apache.org/) · Jekyll + GitHub Pages · Python 3.11 · pure-static frontend

**Public data** Tencent · stooq · yfinance · Frankfurter · SEC EDGAR · Finnhub · Nasdaq · Eastmoney · Polygon · Alpha Vantage · Reddit JSON · Google News RSS · Trump Truth Social feed

<sub>The news layer is deliberately **bilingual**: Finnhub + Google News (English/US) *and* Eastmoney company news + 7×24 快讯 (Chinese/HK), since half the book is Hong Kong and HK catalysts surface in Chinese sources first. Information breadth is the one axis kept wide on purpose — it's what an LLM is best at — separate from the deliberately-narrow decision layer.</sub>

<details>
<summary><b>📂 Repository layout</b></summary>

<br>

```
clawock/
├─ index.html  briefs.md                    ← Pages landing
├─ assets/data/        built by harness + GH Actions, never hand-edited
│   ├─ dashboard.json  risk.json  catalysts.json  fx.json
│   ├─ macro.json  sentiment.json  influencer_feed.json  us_news_digest.json
│   ├─ quant_signals.json  quant_signal_review.json     ← factor scorecard
│   └─ t0_setups.json  t0_setup_review.json             ← intraday setup scorecard
├─ portfolio.json                           ← single source of truth (atomic writes)
├─ MEMORY.md  DREAMS.md                      ← iron rules + nightly "dreaming" promotion
├─ memory/
│   ├─ {date}-pre-open.md  {date}-plan.json  ← brief output + structured plan
│   ├─ calibration.csv                       ← the self-grading scorecard
│   └─ snapshots/{date}.json
├─ scripts/
│   ├─ data/      fetchers · build_dashboard.py · risk/quant/regime/t0 compute · safe_push.sh
│   └─ harness/   {brief,report,intraday}_{pre,post}flight.py · watchdogs
└─ skills/{name}/SKILL.md
```

</details>

---

## ⚠️ Disclaimer

This repo contains **real, live trading positions** — that's the whole point of sharing it, and also the reason to take everything in it with a fistful of salt. It is a personal record and a portable workspace. It is **not investment advice**, not a recommendation, and **not something you should copy** — the scorecard above literally shows the active calls underperforming a hold. Every number is point-in-time and may be stale by the time you read it. `Rick` is opinionated by design; that doesn't make him right.

## 📄 License

Personal-use repository. No license granted for derivative trading systems, automated copy-trading, or commercial use. The *patterns* (harness layout, fallback-chain design, HHI formulation, atomic IO, the self-grading loop) may be adapted under any compatible open-source license if reused independently.

---

<div align="center">

### ⭐ Star it if "an AI that's honest about being wrong" is your kind of thing.

[**🎯 Live Dashboard**](https://kcnyu.github.io/clawock/) &nbsp;·&nbsp; [**📅 Daily Briefs**](https://kcnyu.github.io/clawock/briefs.html) &nbsp;·&nbsp; [**简体中文**](README.zh.md)

<sub>Built and maintained by <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> and Rick · 2026</sub>

</div>
