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
  <img src="assets/social-card.png" alt="clawock — an autonomous AI trading desk that grades its own calls" width="820">
</a>

<sub>Real positions. Real P&L. The social card + live scorecard image refresh weekly via a <a href="https://github.com/KCNyu/clawock/actions/workflows/screenshot-refresh.yml">GitHub Action</a>.</sub>

<br>

<a href="https://kcnyu.github.io/clawock/"><img src="assets/dashboard.gif" alt="clawock dashboard cycling through its six tabs" width="300"></a>

<sub>📱 Cycling all six tabs — Hero · Holdings · Risk · Signals · Plan · <b>Reflect</b> (the self-grading scorecard). The 8MB product demo is regenerated manually when the UI changes; weekly runs refresh only the two live PNGs.</sub>

<br><br>

🪞 **Grades its own calls** — and publishes the number unedited, daily &nbsp;·&nbsp; 💸 **Real money**, not a paper sim &nbsp;·&nbsp; 🗣️ **Bull-vs-bear AI debate** every morning &nbsp;·&nbsp; 🛡️ **Python scores it, not the LLM** — the model can't grade itself &nbsp;·&nbsp; 🌏 **Bilingual** HK + US &nbsp;·&nbsp; 🌐 **Live public dashboard**

<sub>If "an AI that's honest about being wrong" is your kind of thing — ⭐ it.</sub>

</div>

---

> **TL;DR** — A multi-agent LLM runs a real Hong-Kong + US stock portfolio, debates bull-vs-bear each morning, and back-tests its own calls every night. Its verdict on itself is public, updates every session, and is not edited when it stings — the active calls have yet to show an edge. The honesty is the point.

## 🎰 The 60-second version

I gave an LLM a real brokerage portfolio — a Hong Kong leg and a US leg, actual money — and wired up a small machine around it.

Every trading day, on its own, the system:

- 🌅 runs **10 market automation lanes** (brief + HK/US reports + split intraday monitors), with high-frequency lanes firing every 30 minutes,
- 📥 pulls fresh prices, FX, volatility, earnings calendars, macro (VIX/DXY/10Y), Reddit + news sentiment, even **Trump/Musk market-movers**,
- 🧠 hands the clean data to the best-available LLM — playing a blunt persona named **Rick** — to write the take,
- 📲 pushes a briefing to my **WeChat**, and
- 🌐 refreshes a **public dashboard** you can open right now.

That's the gimmick: *a whole AI desk that trades alongside me and never sleeps.*

But here's the part most "AI trader" demos skip 👇

## 🪞 It grades strategy episodes, not repeated daily calls

Every brief commits a v2 `plan.json`. A stock may carry several simultaneous decisions — for example a long-term `core_position`, an `intraday_t`, and a `risk_rebalance` — because different horizons can legitimately disagree on the same day.

The authoritative ledger is `memory/decisions.jsonl`. Each decision has a stable ID, strategy, condition, size, confidence, driver, execution state, and evaluation state. Triggers and marks come from `memory/bars/` — unadjusted daily bars from a single canonical vendor feed (not an exchange feed), counted on each market's own trading calendar, and an unfinished session never grades anything. A gap straight through a trigger fills at the open, not at the trigger: pretending otherwise hands the call a move that was never available. Sessions that were shut, conditions needing human evidence, and instruments that did not trade are published as ungradeable rather than dropped from the denominator. Consecutive reaffirmations of the same strategy/action form one episode, so repeating “hold” for five mornings does not manufacture five samples — and re-anchoring a trigger to where the stock has since moved is still a reaffirmation, not a new call. An episode scores as the mean of its own settled calls rather than an elected member of them — episodes that made several calls routinely disagree with themselves, and letting the first or last one speak for the group swings the active win rate across the 50% line on nothing but the choice of member.

The Reflect dashboard reports:

- cumulative episode win rate against a 50% directional-hit line;
- stated confidence against the realised rate, graded against a leave-one-out constant forecast — the bar a confidence field has to clear before it means anything;
- date-cluster bootstrap intervals, so same-day calls are not treated as independent evidence; and
- follow-through split into the calls that asked for an action and the ones that asked for nothing, because "following" a HOLD is sitting still and mechanically inflates the blended rate. The dashboard renders the current active, passive, and blended values separately.

**No "what listening to the AI earned" figure is published.** The snapshots lack a stable price vintage, intraday highs and lows can carry across sessions, and most calls have no real fill to check against — so executed and counterfactual outcomes cannot be reliably told apart. The bars now exist; what is still missing is real fill records and an explicit sell-at-close book to difference against, so the money view stays unpublished.

The record prices timing only. The risk caps and the HOLD discipline are not in it, and on this book they are the parts that carry their weight — `assets/data/guardrail_history.jsonl` started accruing the evidence for them on 2026-07-15.

The LLM only submits decisions; it cannot write or amend its own evaluation. IDs, triggers, grouping and metrics are computed mechanically by Python from the recorded data. That isolation stops the model from grading itself — it does **not** make the market inputs, the trigger verdicts, or the metric definitions correct. Treat the record as a diagnostic, not as proof of return.

<p align="center"><img src="assets/shadow-backtest.png" alt="decision v2: cumulative episode win rate against a 50% directional-hit line" width="760"></p>

<sub>Cumulative episode win rate against a 50% directional-hit reference — how often the direction was right, not what it earned. Migrated v1 calls remain in the v2 episode ledger. Refreshed weekly by GitHub Actions.</sub>

---

## 🎯 How it actually decides

Behind the persona is a fixed decision framework — not freeform vibes. Every call is attributed, gated, and bucketed before it's allowed to count.

**1. Attribution-first — and the edge is measured dynamically.** Every decision is tagged by its dominant driver. Current sample size, average benefit, win rate, and date-cluster interval come from `decision_metrics.by_driver`; no point-in-time hit rate is hard-coded here.

**2. Hard catalyst vs. soft sentiment.** Soft sentiment (Reddit, mood, a single tweet) can only nudge a *confidence* number — it can never flip the action bucket. Only a hard, dated catalyst can.

**3. Falsify, don't confirm.** In a risk-on tape the default is `HOLD`. A *confirming* bullish story doesn't trigger a buy; the model first has to clear a disconfirming check and a "is this already priced in?" test (the last-5-day move).

**4. Conviction is capped by hard risk gates.** However sure it feels: single name ≤35%, Top-2 ≤70%, leverage-ETF sleeve ≤50%, portfolio β ≤3.0, stop at −18%. Position size is bounded by construction, not by mood.

**5. Leverage is dialed by regime, not timed.** A 200-day-trend × volatility dial sets a multiplier (×1 / ×0.5 / ×0) on the leverage-ETF cap. The backtest lesson behind it: the alpha was in *de-leveraging in the wrong regime*, not in calling tops.

**6. Quant signals must earn the right to speak.** A factor layer (MA cross, 12-1 momentum, RSI-14, z-score, ATR chandelier stop, vol-target sizing) runs in Python — but each factor is **barred from influencing a decision until it clears n≥20 and proves a hit rate.** Unproven factors are shown, never obeyed.

Everything resolves into one or more strategy decisions with explicit conditions. Same-stock `core_position`, `risk_rebalance`, `intraday_t`, `event_trade`, and `tactical_entry` decisions may coexist; each is graded in its own episode.

---

## 🗣️ Every morning, the desk argues with itself

The 08:00 deep brief isn't one model's monologue — it's a structured **multi-agent debate**, borrowed from [TradingAgents](https://github.com/TauricResearch/TradingAgents) and adapted for a dual-leg book:

- **Tier 1 — four analyst lenses.** Fundamental / technical / sentiment / sector-rotation each read the *same* `context.json` and merge into one table. Numbers only, no vibes.
- **Tier 2 — Bull vs Bear.** Two researchers build opposing cases (hold/add vs trim/cut), each citing ≥2 concrete Tier-1 data points. The hard rule: **they must genuinely disagree on at least one position** — unanimous agreement means the debate failed and is thrown out.
- **Tier 3 — three risk voices + a Judge.** Aggressive, Conservative and Neutral each argue their corner; a **Judge** weighs them, names which strategy frame is driving each decision, and resolves the argument into concrete strategy decisions with conditions.

The goal isn't consensus — it's **forcing a real bear case to exist before anything is held**, so the book never just talks itself into its own positions. The Judge's verdict *is* the `plan.json` that gets graded the next morning.

---

## 📅 What a day actually looks like

```
03:00  🌙  memory "dreaming" — promote yesterday's lessons into long-term notes
08:00  📊  daily deep brief   — multi-tier analysis + a judge model, ships to WeChat
09:30  🇭🇰  HK open  → 10:00–11:30 / 14:00–15:30 intraday → 12:00 mid → 16:00 close
09:30 ET 🇺🇸  US open → split intraday monitors → 16:00 ET close
            ↑ every successful reporting postflight publishes dashboard changes
off-host 🛰️  pre-brief macro / sentiment / influencer scans + pre-US-open news digest
weekly  🧪  archive / health / review / visual refresh jobs
```

HK times are HKT; US session times are ET and their HKT cron expressions switch automatically with New York DST. The exact generated table is in [CRON_SCHEDULES.md](CRON_SCHEDULES.md). Markets closed? A **holiday + weekend gate** skips the run instead of burning tokens and writing a stale price as if it were live.

---

## 🏗️ The whole machine on one page

Not just "a cron daemon calling scripts." The *deterministic* half is — prices, FX, delivery and reconciliation should never ride on a model's mood. Ten scheduled market jobs run as isolated agent turns; the eleventh scheduled agent job promotes memory and sits outside the trading harness. The morning brief then fans into its debate swarm, while watchdogs and reconciliation code supervise shared state. **Deterministic scaffolding, agentic judgment — that split *is* the architecture:**

![clawock architecture — deterministic preflight settles triggers and metrics, the LLM writes multi-strategy decisions, postflight assigns stable IDs and episodes, and the ledger feeds the dashboard/backtest](assets/architecture.svg)

The **solid path** (schedulers → harness → shared state → gates → publish) is the deterministic backbone that runs whether or not a model behaves. Market agents write *opinions*; code owns prices, IDs, settlement, delivery markers and publication. The **dotted edges** are the parts people forget: the watchdog that catches a stalled turn, and the self-learning loop that grades yesterday's `plan.json` and feeds the score back in. That's what makes it a multi-agent desk, not a scripted report generator.

---

## 🛡️ Why it doesn't quietly break

Running real automation for months taught me that the hard part isn't the prompt — it's everything that goes wrong *around* it. Three ideas carry the whole thing:

<table>
<tr><td width="33%" valign="top">

**1. Harness pattern**

Every **market-reporting** job is `preflight (Python) → LLM → postflight (Python)`. Deterministic work — prices, FX, HHI, signal counting — runs 100% in code. The LLM only writes the *opinion*. Forget FX, miss a snapshot, skip a >3% mover → postflight catches it and flags the report. The money math is **unit-tested**, and a **pre-push gate refuses to publish a book that doesn't reconcile**. That catches a ledger contradicting itself; it does not make the market data feeding it correct.

</td><td width="33%" valign="top">

**2. Self-learning loop**

`plan.json` today → graded tomorrow. The scorecard feeds confidence calibration back into the next brief, so the model is continuously confronted with its own track record instead of vibing forever.

</td><td width="33%" valign="top">

**3. Defense in depth**

Four overlapping layers — OpenClaw schedules the primary jobs; a GitHub Action can replace a missing morning brief; system-crontab watchdogs mirror confirmed misses to Telegram; health workflows make schedule/data drift visible. They do not promise delivery under every multi-channel outage, but a single LLM stall is no longer silent.

</td></tr>
</table>

<details>
<summary><b>🔧 Under the hood</b> — model chain, write reconciliation, the genuinely tricky bits</summary>

<br>

**Models.** Interactive chat currently runs on Claude; unattended market jobs pin **`MiniMax-M3`**. Provider credentials and the runtime fallback policy live outside this public repository and can change without rewriting the harness. Off-host LLM workflows call MiniMax M3 over Anthropic Messages and can fall back to Xiaomi MiMo while that optional key remains available. No provider key is stored here.

**Write reconciliation (the one genuinely hard part).** `dashboard.json` is 100% derived, yet many actors touch `master` — the cron daemon, off-host workflows, system-crontab publishers and ad-hoc sessions. Months of race-condition incidents converged on one rule: **one writer per file.**

- **The frontend reads the scan sidecars directly.** `macro / sentiment / influencer_feed / us_news_digest / em_news` are no longer embedded into `dashboard.json`; `index.html` fetches each file itself at load. So a GitHub Action only ever commits its *own* disjoint sidecar — those writers can't conflict, and a scan appears on the page the instant its commit lands, with no rebuild. (GH Actions still serialize among themselves via `concurrency: group: data-write`.)
- **`dashboard.json` has exactly one publisher path.** Only the local harness postflights and a flock-guarded `publish_dashboard.sh` crontab rebuild it; both hold the same `/tmp/dashboard_publish.lock`, so two rebuilds can never interleave. The publisher re-commits the dashboard **only on a semantic diff** (wall-clock fields stripped); an intraday heartbeat may produce its own small sidecar-only commit without smuggling in a clock-only dashboard change.
- **Schedules have a checked contract.** Runtime truth comes from `openclaw cron list --json`; [`config/cron-schedules.json`](config/cron-schedules.json) drives the [generated schedule table](CRON_SCHEDULES.md), DST synchronization, payload/watchdog checks and CI health. Mode 7 publishes a slot heartbeat, so health no longer treats intraday as untrackable.
- **Everyone pushes through `safe_push.sh`** — rebase-retry, abort (don't loop) on a real conflict; a committed conflict marker is **rejected at the push hook** so a broken `dashboard.json` can never reach Pages.
- **Portfolio numbers are gated at the door.** `portfolio.json` — the single source of truth — is written under an advisory `flock` + read-fresh-then-overlay (`mutate_json`, atomic `os.replace`), closing the load-modify-write race class. A **pre-push hook blocks any push whose book fails a money-conservation identity** (`TCV = Σ value`, `cash = baseline + trades + adjustments`, `cost = moving-weighted`), so an un-reconciled edit can't reach Pages — and those pure derivations are pinned by a `pytest` suite in CI.

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
<summary><b>📊 Data toolkit — 26 endpoints across 8 layers, with per-host reachability</b></summary>

<br>

Every fetcher is **no-key-first** (public endpoints before any API key; the one that needs a key — Finnhub — has a key-free fallback) and **multi-source** (a dead primary falls through to the next; an empty fetch keeps the prior value instead of overwriting). The **Reach** marks are measured on the live server IP, not claimed: ✅ stable · 🟡 flaky / rate-limited · 🔴 IP-banned here (code kept — works from another IP).

| Layer | Endpoints | Primary sources |
|---|:---:|---|
| 1 · Market | 5 | Tencent gtimg · Yahoo v8 · Eastmoney fund |
| 2 · Fundamentals & filings | 2 | SEC EDGAR · Eastmoney datacenter |
| 3 · Capital flow | 1 | Eastmoney push2his |
| 4 · News | 3 | Eastmoney · Finnhub · Google News |
| 5 · Macro & sentiment | 4 | Yahoo · Reddit · Truth Social |
| 6 · Quant & risk | 4 | deterministic math + fetched price history |
| 7 · FX & integrity | 2 | Frankfurter · local invariants |
| 8 · Backtest & calibration | 5 | local snapshots + daily bars |

- **1 · Market** — `fetch_us_stocks` US live prices, multi-provider chain ✅ · `analyze_us_stocks` US refresh + RSI ✅ · `analyze_hk_stocks` HK live + HSI/HSTECH + news + signals ✅ · `fetch_benchmark_history` SPY/HSI/HSTECH daily bars ✅ · `fetch_gold_dca` gold-fund 000217 NAV ✅
- **2 · Fundamentals** — `fetch_us_filings` 10-K/10-Q · Form 4 · 13F · XBRL (SEC EDGAR) ✅ · `fetch_fundamentals_em` US/HK statements + key metrics ✅
- **3 · Capital flow** — `fetch_fundflow_em` daily main/large/mid/small net order flow 🟡
- **4 · News** — `fetch_em_news` HK company news + 7×24 flash (Chinese) ✅ · `gh_action_news_digest` US holdings news → actionable bullets ✅ · `fetch_catalysts` next-14-day earnings/events 🟡
- **5 · Macro & sentiment** — `fetch_macro` VIX + macro read ✅ · `fetch_sentiment` Reddit WSB/stocks/investing 🟡 · `fetch_influencer_feed` Trump/Musk market-movers 🟡 · `fetch_peers` peer prices + 5-day P&L ✅
- **6 · Quant & risk** (deterministic math over fetched price histories; no LLM) — `compute_quant_signals` dual-MA/momentum/RSI/ATR/vol-target ✅ · `compute_regime` leverage dial (200DMA + vol band) ✅ · `compute_t0_setups` T+0 setup grading + chase detection ✅ · `portfolio_risk_metrics` β / Cov-Var / drawdown / concentration ✅
- **7 · FX & integrity** — `fetch_fx` USDHKD, 3-route fallback ✅ · `preflight_integrity` money-conservation gate (TCV/PNL/FX/cash) ✅
- **8 · Backtest & decision audit** — `decision_v2` episode backtest · `backtest_hstech_regime` · `backtest_us_leverage` · `backtest_combined_regime` · `quant_signal_review` + `t0_setup_review` ✅

**Anti-ban** — all live Eastmoney calls route through one wrapper `_em_http.em_get()`: in-process serialization (≥1s gap + random jitter), single reused `Session`, 3 retries then graceful `None`. Full per-file catalog: [`scripts/data/README.md`](scripts/data/README.md).

</details>

<details>
<summary><b>📂 Repository layout</b></summary>

<br>

```
clawock/
├─ index.html  briefs.md                    ← Pages landing
├─ assets/data/        built by harness + GH Actions, never hand-edited
│   ├─ dashboard.json  risk.json  catalysts.json
│   ├─ macro.json  sentiment.json  influencer_feed.json  us_news_digest.json  ← scan sidecars, fetched straight by the frontend
│   ├─ quant_signals.json  quant_signal_review.json     ← factor scorecard
│   ├─ t0_setups.json  t0_setup_review.json             ← intraday setup scorecard
│   └─ guardrail_history.jsonl                          ← what the risk caps flagged, per brief (accruing since 2026-07-15)
├─ portfolio.json                           ← single source of truth (atomic writes)
├─ tests/                                    ← decision-v2 + money-conservation regression gates
├─ MEMORY.md  DREAMS.md                      ← iron rules + nightly "dreaming" promotion
├─ memory/
│   ├─ {date}-pre-open.md  {date}-plan.json  ← brief output + structured plan
│   ├─ decisions.jsonl                       ← authoritative v2 decision/episode ledger
│   ├─ bars/{ticker}.json                    ← canonical unadjusted OHLC — what settles triggers
│   └─ snapshots/{date}.json
├─ scripts/
│   ├─ data/      fetchers · build_dashboard.py · risk/quant/regime/t0 compute · safe_push.sh
│   └─ harness/   {brief,report,intraday}_{pre,post}flight.py · watchdogs
└─ skills/{name}/SKILL.md
```

</details>

---

## ⚠️ Disclaimer

This repo contains **real, live trading positions** — that's the whole point of sharing it, and also the reason to take everything in it with a fistful of salt. It is a personal record and a portable workspace. It is **not investment advice**, not a recommendation, and **not something you should copy** — the live scorecard above is not edited to flatter the model, and the active calls have yet to show an edge. Every number is point-in-time and may be stale by the time you read it. `Rick` is opinionated by design; that doesn't make him right.

## 📄 License

Personal-use repository. No license granted for derivative trading systems, automated copy-trading, or commercial use. The *patterns* (harness layout, fallback-chain design, HHI formulation, atomic IO, the self-grading loop) may be adapted under any compatible open-source license if reused independently.

---

<div align="center">

### ⭐ Star it if "an AI that's honest about being wrong" is your kind of thing.

[**🎯 Live Dashboard**](https://kcnyu.github.io/clawock/) &nbsp;·&nbsp; [**📅 Daily Briefs**](https://kcnyu.github.io/clawock/briefs.html) &nbsp;·&nbsp; [**简体中文**](README.zh.md)

<sub>Built and maintained by <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> and Rick · 2026</sub>

</div>
