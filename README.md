<div align="center">

<img src="assets/logo-mark.svg" alt="clawock logo" width="58">

# clawock

### An autonomous AI trading desk that grades its own calls — and publishes the losses.

Multi-agent LLMs debate a real Hong Kong + US stock portfolio. Python enforces every risk limit, settles each call against the tape, and ships the scorecard with no manual edits.

**The finding so far: the active calls have yet to beat buy-and-hold — and the dashboard says so out loud.**

[![Dashboard](https://img.shields.io/github/deployments/KCNyu/clawock/github-pages?label=DASHBOARD&style=flat-square&logo=githubpages&logoColor=white&labelColor=252b35&color=4b91c8)](https://kcnyu.github.io/clawock/)
[![CI](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=CI&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![License](https://img.shields.io/badge/LICENSE-MIT-aab5bf?style=flat-square&labelColor=252b35)](LICENSE)

[**Live dashboard**](https://kcnyu.github.io/clawock/) &nbsp;·&nbsp; [**Daily briefs**](https://kcnyu.github.io/clawock/briefs.html) &nbsp;·&nbsp; [**简体中文**](README.zh.md)

<br>

<a href="https://kcnyu.github.io/clawock/">
  <img src="assets/social-card.png" alt="clawock — an autonomous AI trading desk that grades its own calls" width="820">
</a>

<br>

<a href="https://kcnyu.github.io/clawock/"><img src="assets/dashboard.gif" alt="clawock dashboard cycling through its tabs" width="300"></a>

<sub>Real positions, real P&amp;L, graded in the open. Previews refresh weekly; the live dashboard updates through the trading day.</sub>

</div>

---

## What this is

clawock is a public experiment in **disciplined, self-grading** automated investing — not a get-rich bot and not a copy-trading service.

An autonomous multi-agent desk analyzes a real brokerage account with separate Hong Kong and US books. It monitors, debates, and proposes trades on its own; it does **not** place orders or move your money. The point of the project is the honesty layer around it: the model can argue for a trade, but it cannot grade its own homework. Python owns the prices, the risk limits, the ledger, the settlement, and the scoreboard.

## How it works

The desk separates **probabilistic judgment** from **deterministic control**. LLMs read the market and argue the trade; code decides what is allowed, what actually happened, and what the record says.

![clawock architecture — Python builds reconciled market context, a multi-agent LLM debate proposes the trade, code records and gates the decision, and a public scorecard closes the loop](assets/architecture.svg)

Every trading day the system pulls fresh prices, FX, volatility, earnings and macro context plus news and social sentiment; hands that normalized context to a multi-agent debate; applies deterministic risk, schema, and ledger gates in Python; delivers a brief to WeChat; and updates the public dashboard.

## The public scorecard

Every call is settled mechanically and published — wins, losses, and the cases that can't be graded. Nothing is hand-tuned after the fact.

1. **Record** — the model submits a versioned decision with its strategy, condition, size, and confidence. The authoritative ledger is `memory/decisions.jsonl`.
2. **Trigger** — Python evaluates it against canonical unadjusted daily bars, counted on each market's own calendar. An unfinished session grades nothing, and a gap straight through a trigger fills at the open — never at a price that was never available.
3. **Group** — repeated calls of the same strategy collapse into one *episode*, so holding a position for five mornings does not manufacture five samples.
4. **Grade & publish** — code settles the outcome, scores it against a plain directional baseline, and renders it. Shut sessions, calls that need human evidence, and instruments that didn't trade are shown as ungradeable, not dropped from the denominator.

The model submits decisions; it can never write or amend its own evaluation. That isolation stops the desk from grading itself — it does **not** make the market data or the metric definitions correct. **Treat the record as a diagnostic, not as proof of return.**

<p align="center"><img src="assets/shadow-backtest.png" alt="cumulative episode win rate against a 50% directional-hit line" width="760"></p>

<sub>Cumulative episode win rate against a 50% directional-hit line — how often the direction was right, not what it earned. Refreshed weekly by GitHub Actions; live figures live on the <a href="https://kcnyu.github.io/clawock/">Reflect tab</a>.</sub>

<details>
<summary><b>How the grading handles the hard cases</b></summary>

<br>

- **Incomplete sessions & missing bars.** Triggers and marks come from `memory/bars/` — unadjusted daily bars from a single canonical vendor feed, not an exchange feed. An unfinished session never grades anything.
- **Reaffirmations.** Consecutive restatements of the same strategy/action are one episode. Re-anchoring a trigger to where the stock has since moved is still a reaffirmation, not a new call.
- **Episode aggregation.** An episode scores as the *mean* of its own settled calls, not an elected member — letting the first or last call speak for the group can swing the active win rate across the 50% line on nothing but that choice.
- **Confidence calibration.** Stated confidence is graded against a leave-one-out constant forecast — the bar a confidence number has to clear before it means anything — with date-cluster bootstrap intervals so same-day calls aren't counted as independent evidence.
- **Timing, priced separately.** A single-event diagnostic asks how much better or worse the trigger fill was than that session's close, strictly paired by ticker/date/direction/shares. It deliberately never draws a cumulative money curve.
- **Shadow portfolio (simulated · not live).** Two cash + inventory books replay the same timeline: one follows every triggered active call, the other buys and holds. Their cumulative difference is reported as *simulated timing alpha*. It keeps USD and HKD separate, exposes how few calls were ever actually executed, and discloses the unadjusted-bar bias. Source: `assets/data/shadow_portfolio.json`. It is a policy simulation, not a claim about what the live account earned.

</details>

## The decision room

The daily deep brief runs a structured **multi-agent debate**, adapted from [TradingAgents](https://github.com/TauricResearch/TradingAgents) for separate Hong Kong and US books.

- **Analyst lenses.** Fundamental, technical, sentiment, and sector-rotation agents read the *same* context and merge into one table. Every claim must cite numeric context.
- **Bull vs Bear.** Two researchers build opposing cases, each citing concrete analyst data points. They must genuinely disagree on at least one position — unanimous agreement means the debate failed and is thrown out.
- **Risk voices + a Judge.** Aggressive, Conservative, and Neutral each argue their corner; a Judge weighs them, names the strategy frame driving each decision, and resolves the argument into `plan.json`, which enters the next session's grading pipeline.

## What the code enforces

The model writes opinions. Everything that could corrupt the record runs in Python, is unit-tested, and fails closed.

| Rule | What the code does |
|---|---|
| **Currencies never sum** | HKD and USD are shown in both views with the rate + timestamp stamped; adding them naively is a meaningless number. |
| **Risk caps by construction** | Single name ≤35%, Top-2 ≤70%, leverage-ETF sleeve ≤50%, portfolio β ≤3.0, stop at −18%. Size is bounded by code, not by conviction. |
| **Concentration per leg** | `HHI = Σ wᵢ²` per book: `<0.15` ✅ · `0.15–0.25` 🟡 · `0.25–0.40` 🟠 · `>0.40` 🔴. Never blended across currencies. |
| **Leverage judged by regime** | A 200-day-trend × volatility dial caps the leverage-ETF sleeve (×1 / ×0.5 / ×0); daily-reset 2×/3× products skip fundamentals entirely. |
| **Return on peak principal** | Return % uses peak net deposits from the cash-flow ledger, not `cost − realized` — a realized win must not fake a higher return. |
| **Soft sentiment can't flip a trade** | A tweet or a mood only nudges a confidence number; only a hard, dated catalyst can change the action. In a risk-on tape the default is HOLD. |
| **Unproven signals are shown, never obeyed** | A quant factor layer runs in code but is barred from influencing a decision until it clears a minimum sample and proves a hit rate. |

Reliability rides on the same principle. Every market-reporting job is **preflight (Python) → LLM → postflight (Python)**: deterministic work runs entirely in code, and postflight refuses to publish a book that doesn't reconcile. If risk can't be computed, the card renders **"⚠️ can't compute,"** never a green "none." Overlapping schedulers, a fallback workflow, and watchdogs mean a single LLM stall is no longer silent — though nothing here promises delivery under every outage.

## Daily rhythm

```
overnight  memory "dreaming" — promote yesterday's lessons into long-term notes
morning    deep brief — multi-tier debate + a judge, ships to WeChat
HK session open → scheduled intraday monitors → close
US session open → split intraday monitors → close
             ↑ every successful reporting run publishes dashboard changes
around it  pre-brief macro / sentiment / event scans, then a pre-US-open news digest
weekly     archive, health, review, and visual-refresh jobs
```

Hong Kong times run on HKT; US session times follow ET and their cron expressions shift automatically with New York DST. A holiday + weekend gate skips closed sessions. The exact generated table is in [CRON_SCHEDULES.md](CRON_SCHEDULES.md).

## Explore the system

- [**Live dashboard**](https://kcnyu.github.io/clawock/) — positions, risk, and the self-graded scorecard.
- [**Daily briefs**](https://kcnyu.github.io/clawock/briefs.html) — the published morning reads.
- [**Schedule**](CRON_SCHEDULES.md) — the generated cron table.
- [**Data scripts**](scripts/data/README.md) — the fetcher and compute catalog.

Built with [Claude Code](https://claude.com/claude-code), the [openclaw](https://openclaw.com) cron daemon, a static Jekyll + GitHub Pages frontend, and Python. Market, news, macro, and sentiment come from documented public sources with multi-source fallback; see [third-party data and service terms](THIRD_PARTY_DATA.md) before reusing any fetched content.

<details>
<summary><b>Under the hood</b> — models, write coordination, and integrity gates</summary>

<br>

**Models.** Interactive chat currently runs on Claude; unattended market jobs pin a fixed model over the Anthropic Messages API with an optional fallback. Provider credentials and the fallback policy live outside this public repository and can change without rewriting the harness. No provider key is stored here.

**Write reconciliation.** The dashboard-build outputs — `dashboard.json`, `decision_audit.json`, `shadow_portfolio.json` — are derived, while a cron daemon, off-host workflows, crontab publishers, and ad-hoc sessions can all update `master`. The rule: isolate scan-sidecar writers, and serialize dashboard builders that share a host.

- **The frontend reads scan sidecars directly.** Macro / sentiment / news / influencer feeds are fetched file-by-file at load, so a GitHub Action only ever commits its own disjoint sidecar — writers can't conflict, and a scan appears the instant its commit lands, with no rebuild.
- **Dashboard builders share one lock and one contract.** On-host rebuilds serialize on a shared `flock`; every builder runs the same semantic-diff helper, so clock-only rewrites are restored and real changes to the three generated files are staged together.
- **Everyone pushes through `safe_push.sh`** — rebase-retry, abort on a real conflict, and a committed conflict marker is rejected at the push hook so a broken `dashboard.json` can never reach Pages.
- **Portfolio numbers are gated at the door.** `portfolio.json` — the single source of truth — is written under an advisory `flock` with read-fresh-then-overlay and atomic replace. A pre-push hook blocks any push whose book fails a money-conservation identity (`TCV = Σ value`, `cash = baseline + trades + adjustments`, `cost = moving-weighted`), and those derivations are pinned by a `pytest` suite in CI.
- **Schedules have a checked contract.** Runtime truth comes from the live cron list; a tracked config drives the generated schedule table, DST sync, payload/watchdog checks, and CI health.

</details>

<details>
<summary><b>Repository layout</b></summary>

<br>

```
clawock/
├─ index.html  briefs.md                    ← Pages landing
├─ assets/data/        built by harness + GH Actions, never hand-edited
│   ├─ dashboard.json  risk.json  catalysts.json
│   ├─ macro.json  sentiment.json  *_news*.json  influencer_feed.json  ← scan sidecars, fetched straight by the frontend
│   └─ *_review.json  guardrail_history.jsonl                          ← factor / setup scorecards + what the caps flagged
├─ portfolio.json                           ← single source of truth (atomic writes)
├─ tests/                                    ← decision-v2 + money-conservation regression gates
├─ MEMORY.md  DREAMS.md                      ← iron rules + nightly "dreaming" promotion
├─ memory/
│   ├─ {date}-pre-open.md  {date}-plan.json  ← brief output + structured plan
│   ├─ decisions.jsonl                       ← authoritative decision/episode ledger
│   ├─ bars/{ticker}.json                    ← canonical unadjusted OHLC — what settles triggers
│   └─ snapshots/{date}.json
├─ scripts/
│   ├─ data/      fetchers · build_dashboard.py · risk/quant/regime compute · safe_push.sh
│   └─ harness/   {brief,report,intraday}_{pre,post}flight.py · watchdogs
└─ skills/{name}/SKILL.md
```

</details>

---

## Scope, disclaimer, and license

This repository holds **real trading positions**. It is a personal record and portable workspace — **not investment advice, a recommendation, or a copy-trading system**. The desk analyzes and proposes; it does not place orders for you. The public scorecard is not manually edited, the active calls have yet to show an edge, and every number may be stale by the time you read it.

Original code is under the [MIT License](LICENSE). Adapted third-party code keeps its own license and attribution in [NOTICE](NOTICE) and [`THIRD_PARTY_LICENSES/`](THIRD_PARTY_LICENSES/). Third-party market data, news, social posts, filings, trademarks, and API access are **not** relicensed by MIT — see [Third-party data and services](THIRD_PARTY_DATA.md).

<div align="center">
<br>

**[Live dashboard](https://kcnyu.github.io/clawock/)** &nbsp;·&nbsp; **[Daily briefs](https://kcnyu.github.io/clawock/briefs.html)** &nbsp;·&nbsp; **[简体中文](README.zh.md)**

<sub>Built and maintained by <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> and Rick · 2026</sub>

</div>
