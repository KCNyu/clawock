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

</div>

---

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

<sub>Numbers are point-in-time from `memory/calibration.csv`, `quant_signal_review.json`, `t0_setup_review.json` and move as samples grow. Factors with n < 20 are shown but **barred from influencing decisions** until they earn it.</sub>

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

The residual risk is two writers racing between rebuild and push; it self-heals on the next rebuild and is never authoritative for portfolio numbers — those live in `portfolio.json` with atomic writes.

</details>

---

## 📐 House rules the code enforces

The constraints `postflight` won't let the model violate. Quant readers will recognize why each exists:

- **🪙 FX — HKD and USD never sum directly.** Totals are always shown in both views with the rate + timestamp stamped (`USDHKD = 7.83, source Frankfurter, <ts>`). Adding two currencies naively is a meaningless number.
- **📊 Concentration — HHI per leg.** `HHI = Σ wᵢ²`, plus Top-2 weight. Buckets: `<0.15` ✅ · `0.15–0.25` 🟡 · `0.25–0.40` 🟠 · `>0.40` 🔴. Computed per leg, never blended.
- **🎲 Leverage ETFs — judge the underlying.** Tickers whose name carries a leverage marker (`倍`, `Direxion`, `T-Rex`, `ProShares`, `2X/3X Long`, …) skip fundamentals entirely — for a daily-reset 2×/3× product, fundamentals are noise; a **regime dial** (200-day trend × volatility) caps how much leverage is allowed instead.
- **💵 Return basis — peak net principal.** Return % uses `true_principal` = peak net deposit from the cash-flow ledger, *not* `cost − realized`. A realized win shrinks `cost − realized` and fakes a higher return; the ledger basis doesn't move.

---

## 🧬 Stack & sources

[Claude Code](https://claude.com/claude-code) · [openclaw](https://openclaw.com) (cron daemon) · [ECharts 5.5](https://echarts.apache.org/) · Jekyll + GitHub Pages · Python 3.11 · pure-static frontend

**Public data** Tencent · stooq · yfinance · Frankfurter · SEC EDGAR · Finnhub · Nasdaq · Eastmoney · Polygon · Alpha Vantage · Reddit JSON · Google News RSS · Trump Truth Social feed

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
<sub>Built and maintained by <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> and Rick · 2026</sub>
</div>
