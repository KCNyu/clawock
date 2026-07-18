<div align="center">

# 📈 clawock

### Multi-agent LLMs debate a **real HK + US stock portfolio**. Code controls the risk.

[![Dashboard](https://img.shields.io/github/deployments/KCNyu/clawock/github-pages?label=DASHBOARD&style=flat-square&logo=githubpages&logoColor=white&labelColor=173f3b&color=2a8c78)](https://kcnyu.github.io/clawock/)
[![CI](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=CI&style=flat-square&logo=githubactions&logoColor=white&labelColor=173f3b&color=2a8c78)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![License](https://img.shields.io/badge/LICENSE-MIT-c97835?style=flat-square&labelColor=173f3b)](LICENSE)

[**🎯 Live Dashboard**](https://kcnyu.github.io/clawock/) · [**📅 Daily Briefs**](https://kcnyu.github.io/clawock/briefs.html) · [**How it works ↓**](#-the-60-second-version)

**English** · [**简体中文**](README.zh.md)

<br>

<a href="https://kcnyu.github.io/clawock/">
  <img src="assets/social-card.png" alt="clawock — an autonomous AI trading desk that grades its own calls" width="820">
</a>

<sub>Real positions · real P&amp;L · refreshed weekly</sub>

<br>

<a href="https://kcnyu.github.io/clawock/"><img src="assets/dashboard.gif" alt="clawock dashboard cycling through its six tabs" width="300"></a>

<sub>Hero · Holdings · Risk · Signals · Plan · <b>Reflect</b>. Updated when the interface changes.</sub>

<br><br>

**Multi-agent stock analysis** &nbsp;·&nbsp; **Code-enforced risk gates** &nbsp;·&nbsp; **Public self-grading** &nbsp;·&nbsp; **Real HK + US portfolio**

</div>

---

> **TL;DR** — Multi-agent LLMs analyze a real Hong Kong + US stock portfolio. Python enforces the risk rules, settles each call, and publishes the scorecard without manual edits. Active calls have yet to show an edge.

## 🎰 The 60-second version

clawock is an autonomous multi-agent LLM desk attached to a real brokerage portfolio with separate Hong Kong and US books.

Every trading day, the system:

- 🌅 runs scheduled briefs, market reports, and intraday monitors,
- 📥 pulls fresh prices, FX, volatility, earnings calendars, macro (VIX/DXY/10Y), Reddit + news sentiment, even **Trump/Musk market-movers**,
- 🧠 gives the normalized context to a multi-agent analysis and debate workflow,
- 🛡️ applies deterministic risk, schema, and ledger gates in Python,
- 📲 delivers the brief to **WeChat**, and
- 🌐 updates the **public dashboard**.

## 🪞 It grades strategy episodes, not repeated daily calls

Every brief commits a v2 `plan.json`. A stock may carry several simultaneous decisions — for example a long-term `core_position`, an `intraday_t`, and a `risk_rebalance` — because different horizons can legitimately disagree on the same day.

The authoritative ledger is `memory/decisions.jsonl`. Each decision has a stable ID, strategy, condition, size, confidence, driver, execution state, and evaluation state. Triggers and marks come from `memory/bars/` — unadjusted daily bars from a single canonical vendor feed (not an exchange feed), counted on each market's own trading calendar, and an unfinished session never grades anything. A gap straight through a trigger fills at the open, not at the trigger: pretending otherwise hands the call a move that was never available. Sessions that were shut, conditions needing human evidence, and instruments that did not trade are published as ungradeable rather than dropped from the denominator. Consecutive reaffirmations of the same strategy/action form one episode, so repeating “hold” for five mornings does not manufacture five samples — and re-anchoring a trigger to where the stock has since moved is still a reaffirmation, not a new call. An episode scores as the mean of its own settled calls rather than an elected member of them — episodes that made several calls routinely disagree with themselves, and letting the first or last one speak for the group swings the active win rate across the 50% line on nothing but the choice of member.

The Reflect dashboard reports:

- cumulative episode win rate against a 50% directional-hit line;
- stated confidence against the realised rate, graded against a leave-one-out constant forecast — the bar a confidence field has to clear before it means anything;
- date-cluster bootstrap intervals, so same-day calls are not treated as independent evidence; and
- follow-through split into the calls that asked for an action and the ones that asked for nothing, because "following" a HOLD is sitting still and mechanically inflates the blended rate. The dashboard renders the current active, passive, and blended values separately.

**The record prices timing only — now literally.** A single-event diagnostic asks how much better or worse the trigger fill was than executing at that session's close. It strictly pairs the same ticker, date, direction and share count, then reports median bps with a paired confidence interval clustered by date × ticker. It deliberately never draws a cumulative money curve.

### 🧪 Shadow Portfolio · Policy Replay

This asks the broader counterfactual. Two cash + inventory books replay the same timeline from the same seed: one follows every triggered active recommendation; the other buys and holds. Both are marked at the canonical close, and their cumulative difference is reported as **simulated timing alpha**. Cash and inventory constraints prevent repeated recommendations from selling the same lot twice. The Drill card is explicitly labelled **simulated · not live**, exposes `fill_counts.real_trade` because most recommendations were never actually executed, keeps USD and HKD books separate, and discloses the bias from unadjusted bars. Its source is the sidecar `assets/data/shadow_portfolio.json`; it is a policy simulation, not a claim about what the live account earned.

The risk caps and the HOLD discipline are outside both timing diagnostics, and on this book they are the parts that carry their weight — `assets/data/guardrail_history.jsonl` accumulates the evidence for them.

The LLM only submits decisions; it cannot write or amend its own evaluation. IDs, triggers, grouping and metrics are computed mechanically by Python from the recorded data. That isolation stops the model from grading itself — it does **not** make the market inputs, the trigger verdicts, or the metric definitions correct. Treat the record as a diagnostic, not as proof of return.

<p align="center"><img src="assets/shadow-backtest.png" alt="decision v2: cumulative episode win rate against a 50% directional-hit line" width="760"></p>

<sub>Cumulative episode win rate against a 50% directional-hit reference — how often the direction was right, not what it earned. Migrated v1 calls remain in the v2 episode ledger. Refreshed weekly by GitHub Actions.</sub>

---

## 🎯 Decision policy

Every call follows the same attributed, gated, and strategy-specific decision framework.

**1. Attribution-first — and the edge is measured dynamically.** Every decision is tagged by its dominant driver. Current sample size, average benefit, win rate, and date-cluster interval come from `decision_metrics.by_driver`; no point-in-time hit rate is hard-coded here.

**2. Hard catalyst vs. soft sentiment.** Soft sentiment (Reddit, mood, a single tweet) can only nudge a *confidence* number — it can never flip the action bucket. Only a hard, dated catalyst can.

**3. Falsify, don't confirm.** In a risk-on tape the default is `HOLD`. A *confirming* bullish story doesn't trigger a buy; the model first has to clear a disconfirming check and a "is this already priced in?" test (the last-5-day move).

**4. Conviction is capped by hard risk gates.** However sure it feels: single name ≤35%, Top-2 ≤70%, leverage-ETF sleeve ≤50%, portfolio β ≤3.0, stop at −18%. Position size is bounded by construction, not by mood.

**5. Leverage is dialed by regime, not timed.** A 200-day-trend × volatility dial sets a multiplier (×1 / ×0.5 / ×0) on the leverage-ETF cap. The backtest lesson behind it: the alpha was in *de-leveraging in the wrong regime*, not in calling tops.

**6. Quant signals must earn the right to speak.** A factor layer (MA cross, 12-1 momentum, RSI-14, z-score, ATR chandelier stop, vol-target sizing) runs in Python — but each factor is **barred from influencing a decision until it clears n≥20 and proves a hit rate.** Unproven factors are shown, never obeyed.

Everything resolves into one or more strategy decisions with explicit conditions. Same-stock `core_position`, `risk_rebalance`, `intraday_t`, `event_trade`, and `tactical_entry` decisions may coexist; each is graded in its own episode.

---

## 🗣️ Multi-agent decision desk

The 08:00 deep brief uses a structured **multi-agent debate**, adapted from [TradingAgents](https://github.com/TauricResearch/TradingAgents) for separate Hong Kong and US books:

- **Tier 1 — four analyst lenses.** Fundamental / technical / sentiment / sector-rotation each read the *same* `context.json` and merge into one table. Every claim must cite numeric context.
- **Tier 2 — Bull vs Bear.** Two researchers build opposing cases (hold/add vs trim/cut), each citing ≥2 concrete Tier-1 data points. The hard rule: **they must genuinely disagree on at least one position** — unanimous agreement means the debate failed and is thrown out.
- **Tier 3 — three risk voices + a Judge.** Aggressive, Conservative and Neutral each argue their corner; a **Judge** weighs them, names which strategy frame is driving each decision, and resolves the argument into concrete strategy decisions with conditions.

At least one position must receive a substantive opposing case. The Judge resolves the debate into `plan.json`, which enters the next session's grading pipeline.

---

## 📅 Daily operating schedule

```
03:00  🌙  memory "dreaming" — promote yesterday's lessons into long-term notes
08:00  📊  daily deep brief   — multi-tier analysis + a judge model, ships to WeChat
09:30  🇭🇰  HK open  → 10:00–11:30 / 14:00–15:30 intraday → 12:00 mid → 16:00 close
09:30 ET 🇺🇸  US open → split intraday monitors → 16:00 ET close
            ↑ every successful reporting postflight publishes dashboard changes
off-host 🛰️  pre-brief macro / sentiment / influencer scans + pre-US-open news digest
weekly  🧪  archive / health / review / visual refresh jobs
```

HK times are HKT; US session times are ET and their HKT cron expressions switch automatically with New York DST. The exact generated table is in [CRON_SCHEDULES.md](CRON_SCHEDULES.md). A **holiday + weekend gate** skips closed sessions.

---

## 🏗️ System architecture

Clawock separates probabilistic judgment from deterministic control. Agents analyze the portfolio and propose decisions; Python owns prices, risk limits, ledger identity, settlement, scoring, and publication.

![clawock architecture — Python builds reconciled market context, a multi-agent LLM debates the trade, code records the decision, and a public scorecard closes the loop](assets/architecture.svg)

The upper path turns reconciled market state into a versioned decision. The lower loop grades settled calls against canonical bars and returns the score to the next brief. Watchdogs, reconciliation, delivery fallback, and safe publication operate outside the model.

---

## 🛡️ Reliability controls

Three controls keep model output separate from system integrity:

<table>
<tr><td width="33%" valign="top">

**1. Harness pattern**

Every **market-reporting** job is `preflight (Python) → LLM → postflight (Python)`. Deterministic work — prices, FX, HHI, signal counting — runs 100% in code. The LLM only writes the *opinion*. Forget FX, miss a snapshot, skip a >3% mover → postflight catches it and flags the report. The money math is **unit-tested**, and a **pre-push gate refuses to publish a book that doesn't reconcile**. That catches a ledger contradicting itself; it does not make the market data feeding it correct.

</td><td width="33%" valign="top">

**2. Self-learning loop**

`plan.json` today → graded tomorrow. The scorecard returns confidence calibration and realised outcomes to the next brief.

</td><td width="33%" valign="top">

**3. Defense in depth**

Four overlapping layers — OpenClaw schedules the primary jobs; a GitHub Action can replace a missing morning brief; system-crontab watchdogs mirror confirmed misses to Telegram; health workflows make schedule/data drift visible. They do not promise delivery under every multi-channel outage, but a single LLM stall is no longer silent.

</td></tr>
</table>

**Fail closed, in code:**

- If portfolio risk cannot be computed, the risk card renders **“⚠️ can't compute”**, never a green “✅ none.”
- The 09:05 brief judge validates `plan.json`; a file that merely exists does not count as a valid plan.
- The off-host brief fallback trims whole structured sections and publishes a manifest. If a required ledger is missing, it emits zero actions instead of improvising from partial context.

<details>
<summary><b>🔧 Under the hood</b> — runtime, write coordination, and integrity gates</summary>

<br>

**Models.** Interactive chat currently runs on Claude; unattended market jobs pin **`MiniMax-M3`**. Provider credentials and the runtime fallback policy live outside this public repository and can change without rewriting the harness. Off-host LLM workflows call MiniMax M3 over Anthropic Messages and can fall back to Xiaomi MiMo while that optional key remains available. No provider key is stored here.

**Write reconciliation.** The three dashboard-build outputs — `dashboard.json`, `decision_audit.json`, and `shadow_portfolio.json` — are derived, while the cron daemon, off-host workflows, system-crontab publishers and ad-hoc sessions can all update `master`. The ownership rule is: **isolate scan-sidecar writers, and serialize dashboard builders that share a host.**

- **The frontend reads the scan sidecars directly.** `macro / sentiment / influencer_feed / us_news_digest / em_news` are no longer embedded into `dashboard.json`; `index.html` fetches each file itself at load. So a GitHub Action only ever commits its *own* disjoint sidecar — those writers can't conflict, and a scan appears on the page the instant its commit lands, with no rebuild. (GH Actions still serialize among themselves via `concurrency: group: data-write`.)
- **The dashboard-build outputs share one ownership contract and one on-host lock.** Local harness postflights and the flock-guarded `publish_dashboard.sh` crontab share the host's `/tmp/dashboard_publish.lock`, so those on-host rebuilds cannot interleave. Every builder runs the same semantic-diff helper: clock-only rewrites are restored, while real changes to any of the three generated files are staged together. The off-host `brief-fallback` workflow reuses the same helper, but its identically named lock is runner-local and cannot serialize against the host lock.
- **Schedules have a checked contract.** Runtime truth comes from `openclaw cron list --json`; [`config/cron-schedules.json`](config/cron-schedules.json) drives the [generated schedule table](CRON_SCHEDULES.md), DST synchronization, payload/watchdog checks and CI health. Mode 7 publishes a slot heartbeat, so health no longer treats intraday as untrackable.
- **Everyone pushes through `safe_push.sh`** — rebase-retry, abort (don't loop) on a real conflict; a committed conflict marker is **rejected at the push hook** so a broken `dashboard.json` can never reach Pages.
- **Portfolio numbers are gated at the door.** `portfolio.json` — the single source of truth — is written under an advisory `flock` + read-fresh-then-overlay (`mutate_json`, atomic `os.replace`), closing the load-modify-write race class. A **pre-push hook blocks any push whose book fails a money-conservation identity** (`TCV = Σ value`, `cash = baseline + trades + adjustments`, `cost = moving-weighted`), so an un-reconciled edit can't reach Pages — and those pure derivations are pinned by a `pytest` suite in CI.

</details>

---

## 📐 House rules the code enforces

The following constraints are enforced by `postflight`:

- **🪙 FX — HKD and USD never sum directly.** Totals are always shown in both views with the rate + timestamp stamped (`USDHKD = 7.83, source Frankfurter, <ts>`). Adding two currencies naively is a meaningless number.
- **🔢 Manual-entry guards.** The few hand-typed values (cash balances, gold-fund reconciliation) get fat-finger checks: a cash number that jumps ≥5× vs the last snapshot, or a gold avg-cost that diverges from NAV, is flagged before it silently corrupts total assets.
- **📊 Concentration — HHI per leg.** `HHI = Σ wᵢ²`, plus Top-2 weight. Buckets: `<0.15` ✅ · `0.15–0.25` 🟡 · `0.25–0.40` 🟠 · `>0.40` 🔴. Computed per leg, never blended.
- **🎲 Leverage ETFs — judge the underlying.** Tickers whose name carries a leverage marker (`倍`, `Direxion`, `T-Rex`, `ProShares`, `2X/3X Long`, …) skip fundamentals entirely — for a daily-reset 2×/3× product, fundamentals are noise; a **regime dial** (200-day trend × volatility) caps how much leverage is allowed instead.
- **💵 Return basis — peak net principal.** Return % uses `true_principal` = peak net deposit from the cash-flow ledger, *not* `cost − realized`. A realized win shrinks `cost − realized` and fakes a higher return; the ledger basis doesn't move.

---

## 🧬 Stack & sources

[Claude Code](https://claude.com/claude-code) · [openclaw](https://openclaw.com) (cron daemon) · [ECharts 5.5](https://echarts.apache.org/) · Jekyll + GitHub Pages · Python 3.11 · pure-static frontend

**Public data** Tencent · stooq · yfinance · Frankfurter · SEC EDGAR · Finnhub · Nasdaq · Eastmoney · Polygon · Alpha Vantage · Reddit JSON · Google News RSS · Trump Truth Social feed

<sub>The news layer is **bilingual**: Finnhub + Google News for US coverage, and Eastmoney company news + 7×24 快讯 for Hong Kong coverage. Information collection stays broad; the decision layer stays constrained.</sub>

<details>
<summary><b>📊 Data toolkit — 26 endpoints across 8 layers, with per-host reachability</b></summary>

<br>

Fetchers prefer documented public endpoints and use **multi-source fallback** where available; an empty fetch keeps the prior value instead of overwriting it. Provider terms and access requirements still apply. The **Reach** marks are measured on the live server IP: ✅ stable · 🟡 flaky / rate-limited · 🔴 unavailable from this host.

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

**Request hygiene** — all live Eastmoney calls route through one wrapper `_em_http.em_get()`: in-process serialization (≥1s gap + jitter), one reused `Session`, bounded retries, then graceful `None`. See [third-party data and service terms](THIRD_PARTY_DATA.md) before operating or redistributing any fetched content. Full per-file catalog: [`scripts/data/README.md`](scripts/data/README.md).

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

This repository contains **real trading positions**. It is a personal record and portable workspace, not investment advice, a recommendation, or a copy-trading system. The public scorecard is not manually edited, active calls have yet to show an edge, and every number may be stale by the time you read it.

## 📄 License and third-party data

Original code is licensed under the [MIT License](LICENSE). Adapted third-party code retains its original license and attribution in [NOTICE](NOTICE) and [`THIRD_PARTY_LICENSES/`](THIRD_PARTY_LICENSES/). Third-party market data, news, social posts, filings, trademarks, and API access are not relicensed by MIT; see [Third-party data and services](THIRD_PARTY_DATA.md). This project is not an automated copy-trading service.

---

<div align="center">

### ⭐ Follow the live experiment

[**🎯 Live Dashboard**](https://kcnyu.github.io/clawock/) &nbsp;·&nbsp; [**📅 Daily Briefs**](https://kcnyu.github.io/clawock/briefs.html) &nbsp;·&nbsp; [**简体中文**](README.zh.md)

<sub>Built and maintained by <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> and Rick · 2026</sub>

</div>
