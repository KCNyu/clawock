<div align="center">

<h1><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/logo-lockup.svg" alt="clawock" height="48"></h1>

### AI argues. Code settles. The losses stay on the page.

A real Hong Kong + US brokerage account, run day after day by agents that
debate every call before it happens, then settled by code the model never
touches. Every result gets published, wins and losses both. Install the same
decision workflow into your own agent, in any harness: OpenClaw, Claude Code,
Codex, DeepSeek Harness, or one you write yourself.

[![PyPI](https://img.shields.io/pypi/v/clawock?label=PYPI&style=flat-square&logo=pypi&logoColor=white&labelColor=252b35&color=4b91c8)](https://pypi.org/project/clawock/)
[![npm](https://img.shields.io/npm/v/clawock-dsh?label=NPM&style=flat-square&logo=npm&logoColor=white&labelColor=252b35&color=4b91c8)](https://www.npmjs.com/package/clawock-dsh)
[![Tests](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/harness-regression.yml?label=TESTS&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![Live Data](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/dashboard-artifact-gate.yml?label=DATA&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/dashboard-artifact-gate.yml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fkcnyu.github.io%2Fclawock%2Fassets%2Fdata%2Fcoverage.json&style=flat-square&logo=python&logoColor=white&labelColor=252b35)](https://github.com/KCNyu/clawock/actions/workflows/harness-regression.yml)
[![License](https://img.shields.io/badge/LICENSE-MIT-aab5bf?style=flat-square&labelColor=252b35)](https://github.com/KCNyu/clawock/blob/master/LICENSE)

[**Live dashboard**](https://kcnyu.github.io/clawock/) &nbsp;·&nbsp; [**Daily briefs**](https://kcnyu.github.io/clawock/briefs.html) &nbsp;·&nbsp; [**Evidence**](https://kcnyu.github.io/clawock/evidence.html) &nbsp;·&nbsp; [**简体中文**](https://github.com/KCNyu/clawock/blob/master/README.zh.md)

<br>

<a href="https://kcnyu.github.io/clawock/">
  <img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/social-card.png" alt="clawock — portable investment decision workflows for any external AI agent, proven on a live HK and US desk" width="820">
</a>

<sub><i>“The market doesn't care how confident the model was.”</i></sub>

<a href="https://kcnyu.github.io/clawock/"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dashboard.gif" alt="clawock dashboard cycling through its tabs" width="300"></a>

<sub>Real positions, real P&amp;L, graded in the open. Previews refresh weekly; the live dashboard updates through the trading day.</sub>

</div>

---

## What this is

This started as one account, not a package. A multi-agent desk debates the
evidence on a real brokerage account with separate Hong Kong and US books and
proposes trades; the account owner still places the orders. What comes out of
that is the record: real positions, a growing decision history, and a public
scorecard the model has no say in — not a get-rich bot, and not a
copy-trading service.

**clawock is the part of that desk we pulled out and made reusable: an
agent-native, harness-agnostic investment decision-workflow plugin with a
verifiable harness.** OpenClaw, Claude Code, Codex, DeepSeek Harness, or
another external runtime keeps the model call, the conversation, memory,
planning, tools, permissions and credentials. clawock installs the workflow on
top of that: it certifies evidence, forces an opposing case, checks the money
and FX arithmetic, links outcomes back to the decision that caused them, and
keeps every improvement proposal reviewable and reversible. Swap harnesses and
the decision contract stays put — it's just files and a CLI. See
[`examples/`](https://github.com/KCNyu/clawock/blob/master/examples/README.md) for the
same run done from a pure CLI, an OpenClaw skill, a Claude Code instruction, a Codex AGENTS.md,
and a DeepSeek Harness agent.

Install it with `pip install clawock`, or
[run it on your own book](#run-it-on-your-own-book) without this repository at
all. The model proposes; Python owns the prices, the risk limits, the ledger,
the settlement, and the grading.

### What makes it different

- **A workflow plugin, not another agent — and not another harness.** The external runtime keeps its model, chat, memory, skills engine, tool loop, and permissions; clawock makes the investment-decision contract portable across runtimes and across harnesses. The harness debate (OpenClaw vs Codex vs DeepSeek Harness) is a debate clawock does not participate in.
- **The loop continues after the answer.** Evidence, the opposing case, thesis,
  decision, execution, and observed outcome share one lineage. Measured results
  can propose bounded parameter changes, but never silently rewrite strategy.
- **Real money, graded in public.** One live Hong Kong + US brokerage account, with a public scorecard that keeps every eligible result — the losses included, and the fact that the active calls haven't beaten buy-and-hold.
- **The model can't grade itself.** LLMs propose trades; Python settles them and computes the scorecard.
- **One thesis, one episode.** Repeated opinions on the same thesis count once. Each episode is settled from canonical vendor bars, with declared gap-fill rules when a session is missing.
- **The ledger has to reconcile.** A money-conservation check runs before every push; if cash, positions, and P&L don't balance, nothing is published.
- **Built to keep running.** Scheduled Hong Kong and US sessions produce bilingual briefs and refresh the live dashboard through the trading day.

## How it works

The product boundary is simple: the external agent reads and reasons; clawock
owns the portable decision workflow and the deterministic truth around it.

![clawock product architecture — external runtimes own models, conversation, memory and tools while the package supplies portable workflows, certified context, deterministic reconciliation, evaluation and bounded improvement](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/product-architecture.svg)

The KCNyu deployment then applies that product boundary to one live portfolio.
This second diagram is the deployed KCNyu desk, not the reusable package boundary.

![KCNyu live-desk architecture — Python builds reconciled market context, OpenClaw agents debate the trade, clawock contracts gate the decision, and a public scorecard closes the loop](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/architecture.svg)

Every trading day the system pulls fresh prices, FX, volatility, earnings and macro context plus news and social sentiment; hands that normalized context to a multi-agent debate; applies deterministic risk, schema, and ledger gates in Python; delivers a brief to WeChat; and updates the public dashboard.

## The information layer

Reading the market is most of what the LLM does, so the widest part of the system is data collection. The repository catalogs **41 fetch and compute modules across 8 layers**, with **bilingual Hong Kong + US coverage** — live quotes, SEC + Eastmoney filings, capital flow, earnings calendars, macro (VIX / DXY / 10Y), Reddit and news sentiment, and market-moving social feeds. Each brief consumes the subset relevant to that market and session. Collection stays broad; the decision layer stays constrained.

![clawock information flow — eight layers of fetch and compute modules are assembled by a deterministic Python preflight into a fingerprinted context.json; the LLM reads the file and writes its analysis; Python postflight validates and settles before publish](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/information-flow.svg)

<details>
<summary><b>All 8 layers, row by row</b> — modules and primary sources</summary>

<br>

| Layer | Modules | Primary sources |
|---|:---:|---|
| 1 · Market | 7 | Tencent · Yahoo · Eastmoney · Polygon |
| 2 · Fundamentals & filings | 3 | SEC EDGAR · Eastmoney datacenter · HKEX |
| 3 · Capital flow | 1 | Eastmoney push2his |
| 4 · News & catalysts (bilingual) | 5 | Eastmoney · Finnhub · Google News · exchange filings |
| 5 · Macro & sentiment | 3 | Yahoo · Reddit · CNN · social feeds |
| 6 · Quant & risk | 9 | deterministic math over price history |
| 7 · Book & FX integrity | 6 | Frankfurter · the reconciliation ledger · local invariants |
| 8 · Backtest & calibration | 7 | local snapshots + canonical bars |

The fetch layer degrades gracefully: every live Eastmoney call routes through **one throttled gateway**, critical paths (quotes, FX) use **multi-source fallback**, and an empty fetch **keeps the prior value** instead of overwriting a good series with a blank. Public sources include Tencent, stooq, yfinance, Frankfurter, SEC EDGAR, Finnhub, Nasdaq, Eastmoney, Polygon, Alpha Vantage, Reddit, and Google News — full command and provider catalog in [the command reference](https://github.com/KCNyu/clawock/blob/master/docs/reference/commands.md), whose inventory is generated from the same registries this table is checked against. Which module sits in which layer is itself an artifact — [`config/information-layers.json`](https://github.com/KCNyu/clawock/blob/master/config/information-layers.json), where every packaged command is either in a layer or listed with the reason it is not collection — and CI checks the table above against it, so a module that moves cannot leave its count standing.

</details>

### What each run actually receives

Collection is broad, but no run gets everything. Each scheduled job's preflight assembles only the blocks that job can act on, writes them to a context file, and the model reads that file rather than fetching for itself.

```
sources
  ──► preflight (Python, deterministic)
  ──► context.json
  ──► LLM prose
  ──► postflight (Python)
  ──► publish
```

Pre-open gets the most: full position truth, risk, signals, the evidence
graph, research state, and it writes the day's plan. The open/midday/close
runs travel light — a fresh quote, risk only when signals demand it. Intraday
check-ins (every 30 minutes a market is open) sit in between: more signal
detail, but no research production and no evidence-graph rebuild, because that
is a daily artifact and would be stale by construction.

<details>
<summary><b>The full block breakdown</b> — row by row, by cadence</summary>

<br>

| | Pre-open brief | Open / midday / afternoon / close | Intraday check-in |
|---|---|---|---|
| **When** | 08:00 HKT, weekdays | HK 09:30 · 12:00 · 13:30 · 16:00 · US open and close | every 30 min while a market is open |
| **Blocks** | 37 | 16 | 29 |
| **Position truth** | holdings, book totals, concentration, leverage look-through | fresh quote block | fresh quote block |
| **Risk** | guardrail, discipline ledger, β/vol/drawdown, breakeven math | risk section only when signals demand it | signal counts and detail |
| **Signals** | quant factors and their hit-rate review, cross-sectional factor, peer residual, T+0 setups | peer/sector scan | peer/sector scan, T+0 setups, anomaly flags, entry setups and early-trend candidates re-run on the open bar, price-surface opportunity radar |
| **News and events** | evidence graph, Chinese-language company news, catalyst calendar, macro, Reddit and social feeds | catalyst probe on flagged names | catalyst probe on flagged names |
| **Research state** | thesis registry, research work queue (reviews due, overdue promises, ungated positions) | thesis and red lines for flagged names | thesis and red lines for flagged names |
| **History** | retrospective, decision metrics, reflections, data-integrity report | — | heartbeat slot state |
| **Today's plan** | writes it | the morning's still-open decisions for this leg | the morning's still-open decisions for this leg |

The catalyst probe is the narrow, time-sensitive one: it fires **only for names that already moved**, reads exchange and regulator filings first (SEC acceptance timestamps, HKEX announcements), classifies each item as interrupt, context or noise, and states `no_recent_filing` explicitly rather than letting an empty block read as "nothing happened".

</details>

### Influencer radar

The system scans **Trump (Truth Social, first-party) and Musk (news
aggregation)** one to two times a day on the HK/US session clock, then an LLM
filters the noise and links what's left to actual holdings and sectors: stance
(endorse / oppose), relevance, and a plain-language summary. Who said what,
and whether it touches your book, is already sitting in the pre-open brief —
nobody has to go scroll social media for it.

A concrete example: on 2026-08-13 Trump announced a de minimis tariff-loophole
ruling; the radar matched it to retail/e-commerce and linked it to the Hang
Seng Tech position, and the summary landed in the next day's brief. The scan
the day before (2026-08-14) found 3 posts and **zero holding hits** — an empty
result is published as an empty result, not skipped. What's shown above is one
hit; misses go in the brief exactly as often as they happen.

## How it decides

Analysis resolves into explicit, gated strategy decisions — and one stock can carry several at once.

- **Several strategies, graded separately.** `core_position`, `risk_rebalance`, `intraday_t`, `event_trade`, and `tactical_entry` can coexist on the same name, because a long-term thesis and an intraday trade can legitimately disagree. Each is graded in its own episode.
- **Attribution-first.** Every decision is tagged by its dominant driver, and that driver's edge is measured *dynamically* from the record — no hit rate is hard-coded into the logic.

### Low-frequency add campaigns

Adding to a position needs two independent signals to agree: a price/peer
signal (factor rank plus curated-peer residual) and a separate, point-in-time
news signal (reliable positive surprise or accelerating attention) — not one
moving average mistaken for alpha. Negative information or peer-laggard
evidence blocks it outright, sizing stays capped and tranche-based (a warming
policy earns a small exploration slice, not validated authority), and a small
rank wobble can't churn permission off and on.
- **Falsify, don't confirm.** In a risk-on tape the default is HOLD. A bullish story doesn't trigger a buy until it clears a disconfirming check and an "is this already priced in?" test on the last few days' move.
- **Regime over timing.** Leverage isn't timed; a 200-day-trend × volatility dial sets the cap. The backtested lesson: the edge was in *de-leveraging in the wrong regime*, not in calling tops.

## The debate

The daily deep brief runs a structured **multi-agent debate**, adapted from [TradingAgents](https://github.com/TauricResearch/TradingAgents) for separate Hong Kong and US books. More agents isn't the point: the protocol **demands an opposing case**, and the Judge **attributes each resolution** to a named strategy frame.

![clawock's multi-agent debate — one evidence pack feeds four analyst lenses; two researchers argue opposing bull and bear cases and record where they disagree; three risk voices and a judge name the strategy frame and resolve it into plan.json, which enters the next session's grading loop](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/debate-flow.svg)

- **Analyst lenses.** Fundamental, technical, sentiment, and sector-rotation agents read the *same* context and merge into one table. Every claim must cite numeric context.
- **Bull vs Bear.** Two researchers build opposing cases, each citing concrete analyst data points. The protocol asks them to **genuinely disagree on at least one position** and to record it, so unanimous agreement reads as a flag rather than evidence.
- **Risk voices + a Judge.** Aggressive, Conservative, and Neutral each argue their corner. A Judge weighs them, **names the strategy frame driving each decision**, and resolves the argument into `plan.json` — which enters the next session's grading pipeline.

## The public scorecard

Every call is settled mechanically and published — wins, losses, and the cases that can't be graded. Nothing is hand-tuned after the fact.

1. **Record** — the model submits a versioned decision with its strategy, condition, regime, size, and confidence. The authoritative ledger is `memory/decisions.jsonl`.
2. **Trigger** — Python evaluates it against canonical unadjusted daily bars, counted on each market's own calendar. An unfinished session grades nothing, and a gap straight through a trigger fills at the open — never at a price that was never available.
3. **Group** — repeated calls of the same strategy collapse into one *episode*, so holding a position for five mornings does not manufacture five samples.
4. **Grade & publish** — code settles the outcome, scores it against a plain directional baseline, and renders it. Shut sessions, calls that need human evidence, and instruments that didn't trade are published as ungradeable — out of the win-rate denominator, but kept visible in the coverage count instead of silently dropped.

The model submits decisions; it can never write or amend its own evaluation. That isolation stops the desk from grading itself — it does **not** make the market data or the metric definitions correct. **Treat the record as a diagnostic, not as proof of return.**

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/shadow-backtest.png" alt="cumulative episode win rate against a 50% directional-hit line" width="760"></p>

<sub>Cumulative episode win rate against a 50% directional-hit line — how often the direction was right, not what it earned. The buy-and-hold comparison is the Shadow Portfolio under Holdings; this is a different question. Refreshed weekly by GitHub Actions; live figures are on the <a href="https://kcnyu.github.io/clawock/#drill">Holdings tab</a>.</sub>

<details>
<summary><b>How the grading handles the hard cases</b></summary>

<br>

- **Incomplete sessions & missing bars.** Triggers and marks come from `memory/bars/` — unadjusted daily bars from a single canonical vendor feed, not an exchange feed. An unfinished session never grades anything.
- **Reaffirmations.** Consecutive restatements of the same strategy/action are one episode. Re-anchoring a trigger to where the stock has since moved is still a reaffirmation, not a new call.
- **Episode aggregation.** An episode scores as the *mean* of its own settled calls, not an elected member — letting the first or last call speak for the group can swing the active win rate across the 50% line on nothing but that choice.
- **Confidence calibration.** Stated confidence remains an audit field. A strictly prequential beta-binomial hierarchy estimates action × driver × condition × regime probabilities from earlier dates only, shrinks sparse groups toward broader priors, and abstains from signal sizing when evidence or the posterior lower bound is insufficient.
- **Timing, priced separately.** A single-event diagnostic asks how much better or worse the trigger fill was than that session's close, strictly paired by ticker/date/direction/shares. It deliberately never draws a cumulative money curve.
- **Shadow portfolio (simulated · not live).** Two cash + inventory books replay the same timeline: one follows every triggered active call, the other buys and holds. Their cumulative difference is reported as *simulated timing alpha*. It keeps USD and HKD separate, exposes how few calls were ever actually executed, and discloses the unadjusted-bar bias. Source: `assets/data/shadow_portfolio.json`. It is a policy simulation, not a claim about what the live account earned.

</details>

## What we tested, and what failed

The scorecard reports what happened. This reports what was checked — and what did not survive the check.

A layer has to clear a stated bar before it is allowed to influence a decision, and the bar is set before the result is known:

- **Factor edges** must have a two-way clustered bootstrap interval that does not straddle 50%. An interval that straddles it means the sample is too small, which is a different statement from "the factor does not work" — both keep it out of decisions, and the distinction is published.
- **The cross-sectional layer** is pre-registered. Only snapshots recorded after registration count toward activation, so a retrospective result can never switch it on.
- **The leverage dial** is scored out of sample: thresholds are calibrated on a leading window and graded on the next one, and its timing is tested against a null that circularly shifts the same exposure path against returns — preserving its shape and time-in-market while destroying only the alignment.

Results are published whether or not they flatter the system. The dial's permutation test is the current example: on the sample available, its timing cannot be distinguished from chance, and that is stated on the page rather than left out of it. A failure to reject is not a refutation, and the page says which one it is.

Two properties keep this from decaying into copy. The page is **generated from the artifacts**, so it cannot quietly drift from them. And any backtest figure quoted in the repository has to cite a run card that still contains it — a stale citation points at real evidence that no longer says what the claim says, which reads as credible and is wrong. CI fails on both.

[**Evidence and refutation**](https://kcnyu.github.io/clawock/evidence.html)

## What the code enforces

The model writes opinions. The arithmetic that could corrupt the record runs in Python and is unit-tested.

That path is covered by a large unit-test suite — it's what keeps the system stable. Currencies never sum (HKD and USD are shown separately, rate and timestamp stamped), risk caps are checked every brief (single name ≤35%, Top-2 ≤70%, portfolio β ≤3.0, stop at −18%), and a thesis moves only on new evidence, never on a price move alone.

<details>
<summary><b>All twelve rules, what the code actually does for each</b></summary>

<br>

| Rule | What the code does |
|---|---|
| **Currencies never sum** | HKD and USD are shown in both views with the rate + timestamp stamped; adding them naively is a meaningless number. |
| **Risk caps, checked every brief** | Single name ≤35%, Top-2 ≤70%, leverage-ETF sleeve ≤50%, portfolio β ≤3.0, stop at −18%. Each breach has a durable age, acknowledgement, expiring override and execution-evidence record; same-risk adds freeze until compliance. Execution stays human. |
| **Concentration per leg** | `HHI = Σ wᵢ²` per book: `<0.15` ✅ · `0.15–0.25` 🟡 · `0.25–0.40` 🟠 · `>0.40` 🔴. Never blended across currencies. |
| **Leverage judged by regime** | A 200-day-trend × volatility dial caps the leverage-ETF sleeve (×1 / ×0.5 / ×0); daily-reset 2×/3× products skip fundamentals entirely. |
| **Return on peak principal** | Return % uses peak net deposits from the cash-flow ledger, not `cost − realized` — a realized win must not fake a higher return. |
| **News needs an evidence graph** | Filings, issuer/exchange news, calendars, and headlines are deduplicated into expiring event IDs. A reliable, novel, negative event with price/volume or validated peer confirmation may drive defensive action. Positive surprise or accelerating attention can only join price-relative evidence in a capped add exploration; it cannot trade alone. |
| **Unproven signals get an exploration boundary** | A quant factor cannot claim validated authority until it clears prospective activation. While warming up, a pre-registered interaction can collect one capped tranche per ticker/policy; the ledger keeps that evidence grade distinct. |
| **Add authority needs quant × information** | Factor and peer residual count as one price-relative family, not two votes. A second point-in-time news surprise/attention family must agree before an exploration or validated tranche exists; technical prices only time that already-authorized capital. |
| **Published research numbers need two sources** | Long-form numbers carry a provenance manifest: exact Decimal arithmetic, two independent sources per figure, and a tolerance cap the manifest cannot raise for itself. A single-sourced or disagreeing figure blocks release of the artifact that quotes it. |
| **A thesis moves only on new evidence** | Assumptions, red lines and valuation anchors live in versioned JSON. A dimension may change only with evidence observed after the last check; a price move can reprice valuation but cannot touch business, moat or management; triggering *and* clearing a red line both need evidence. A missing baseline stays `unknown` instead of being reconstructed from prose. |
| **Earnings quality is computed, not asserted** | Cash conversion, working-capital gaps, dilution, SBC share and guidance outcomes are derived in code from at least four comparable periods. A basis or currency switch mid-history is an error, a missing input reads `unavailable` with a reason, and footnote claims require a primary issuer document. |
| **A new name passes a gate before a research run** | Information richness is graded separately from investment quality, so thin sourcing returns `gray_needs_evidence`, never a rejection. Four hard vetoes resolve before any check is tallied, their industry exceptions are encoded per sector rather than improvised, and quotes must come from the workspace pipelines. |

Reliability rides on the same principle. Every market-reporting job is **preflight (Python) → LLM → postflight (Python)**: the deterministic work runs in code, and a pre-push gate refuses to publish a book that doesn't reconcile. If risk can't be computed, the card says **"risk unavailable,"** never a green "none." Overlapping schedulers, a fallback workflow, and watchdogs mean a single LLM stall is no longer silent — though nothing here promises delivery under every outage.

</details>

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

Hong Kong times run on HKT; US session times follow ET and their cron expressions shift automatically with New York DST. A holiday + weekend gate skips closed sessions. The exact generated table is in [docs/operations/cron-schedules.md](https://github.com/KCNyu/clawock/blob/master/docs/operations/cron-schedules.md).

## Run it on your own book

The package lifecycle is no longer welded to this account's directory. It is
published to PyPI through GitHub trusted publishing — no API token, and the
release job proves a clean environment can install the exact artifact and finish
a run before it uploads:

```bash
python -m pip install clawock
clawock workflow install investment-decision --workspace ./my-decision
clawock init ./my-decision --workflow investment-decision
clawock run prepare --workspace ./my-decision
```

You need Python ≥ 3.11 and an agent that can read a file and write
`decision.json` — any harness works, and the model call stays entirely in your
runtime. The emitted request is for the external agent to consume. The agent
writes `decision.json`; `clawock run publish` validates it and emits the
correlated generation receipt. The packaged example can smoke the lifecycle
without a model (`bash examples/cli/minimal-run/run.sh`), and
[`examples/`](https://github.com/KCNyu/clawock/blob/master/examples/README.md) shows the
same run driven from a pure CLI, an OpenClaw skill, a Claude Code instruction, a Codex AGENTS.md,
and a DeepSeek Harness agent — the harness never touches the contract.

### Same contract, whatever the harness looks like

Two harnesses, two completely different interfaces, one `decision.json` on
each side. Claude Code stays a terminal loop — prepare, read, write, publish:

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/claude-code-terminal.png" alt="Claude Code running the investment-decision workflow end to end: clawock init, clawock run prepare, Claude writing decision.json, clawock run publish returning status: published" width="820"></p>

DeepSeek Harness gets a native panel instead — one command installs the skill
plus a conversation-view tab:

```bash
dsh plugin --profile web add clawock-dsh
```

The **Decision Mind** tab is one view, not three tabs: the spine is your real
fills (`portfolio.json` trades), each row carries the soft-paired decision
(±3 days from `decisions.jsonl`) as the "why", and the T+1 verdict comes from
the canonical `memory/bars/` close inside the T+1 window (never a snapshot
price) — 卖飞/卖对 on reduces, 涨/跌 on adds, 持平 in the dead zone. Click a
fill and the trace unfolds — plan → real fill (stated 与计划同向/反向, with
`execution.status` preserved only as the plan's own 账本自评 label) → T+1 →
P&L (本笔已实现 and 该持仓当前浮动 never share one label) — with the
rationale and note in semantic colors, plus an emotion-pressure field on the
small number of records that logged one so far. Fills with no plan say so
explicitly, instead of making one up. Currency is never mixed: USD and HKD
stay apart and only combine through the desk's published FX rate. The same
trace data powers the public dashboard's Reflect card, but the two sides are
separate implementations pinned together by `tests/test_decision_trace_parity.py`:

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-decision-mind.png" alt="Decision Mind plugin — decision traces: real fills with soft-paired decisions and T+1 verdicts, expandable to a plan → execution → result timeline" width="860"></p>

Conversation verdicts land in the same ledger through one command from any
harness: `clawock record --source <harness>` (bear case and invalidation
conditions mandatory, emotion pressure self-reported). Nobody edits
`decisions.jsonl` by hand — one ledger, one record command, every harness
calls it.

For the KCNyu compatibility surface, `clawock doctor`, `clawock context audit`,
and `CLAWOCK_WORKSPACE` still inspect or point at an operational book. They name
missing capabilities instead of pretending every foreign workspace is ready to
run this live desk.

The package owns lifecycle implementation, strategies, scheduling, watchdogs,
generation-pinned artifacts, context assembly, validation and CLI. It does not
reimplement an agent loop: OpenClaw is the unattended runtime used by this desk
today, while another runner can consume the same context/tool contracts. The
`kcnyu` profile and workspace declare this desk's books, resources and schedules;
`doctor` and `context audit` state those capabilities instead of pretending every
foreign workspace is production-ready.

## Explore the system

- [**Live dashboard**](https://kcnyu.github.io/clawock/) — positions, risk, and the self-graded scorecard.
- [**Daily briefs**](https://kcnyu.github.io/clawock/briefs.html) — the published morning reads.
- [**Examples by harness**](https://github.com/KCNyu/clawock/blob/master/examples/README.md) — one decision run, five harnesses: pure CLI, OpenClaw, Claude Code, Codex, DeepSeek Harness, plus the npm DSH plugin.
- [**Schedule**](https://github.com/KCNyu/clawock/blob/master/docs/operations/cron-schedules.md) — the generated cron table.
- [**Command reference**](https://github.com/KCNyu/clawock/blob/master/docs/reference/commands.md) — every installed command, generated from the registries, plus the hand-written provider and harness detail.
- [**Project docs**](https://github.com/KCNyu/clawock/blob/master/docs/README.md) — operations, reference, legal notes, and archived designs.

### Research surfaces

| Question | Entry point | Data/runtime contract | Reuse scope |
|---|---|---|---|
| Analyze a US company | [`us-stock-analysis`](https://github.com/KCNyu/clawock/blob/master/skills/us-stock-analysis/SKILL.md) | Local quote fallback, SEC filings, fundamentals, news | Reusable with the clawock workspace |
| Analyze a Hong Kong company | [`hk-stock-analysis`](https://github.com/KCNyu/clawock/blob/master/skills/hk-stock-analysis/SKILL.md) | Tencent/Eastmoney quote checks, HK fundamentals, market context | Reusable with the clawock workspace |
| Review the current portfolio | [`portfolio-risk-review`](https://github.com/KCNyu/clawock/blob/master/skills/portfolio-risk-review/SKILL.md) for one pass; [`portfolio-swarm-review`](https://github.com/KCNyu/clawock/blob/master/skills/portfolio-swarm-review/SKILL.md) for debate | `portfolio.json`, fresh quotes, risk and decision ledgers | Specific to the configured portfolio |
| Stress-test a supply-chain thesis | [`serenity-skill`](https://github.com/KCNyu/clawock/blob/master/skills/serenity-skill/SKILL.md) | Current public evidence plus its local scorecard | Reusable as a manual research framework |
| Review a reported quarter and hold management to account | [`earnings-review`](https://github.com/KCNyu/clawock/blob/master/skills/earnings-review/SKILL.md) | First-party filings/HKEX announcements, structured XBRL or Eastmoney verification, provenance gate | Reusable; artifacts live in `memory/earnings/` |
| Decide whether a new name is worth researching | [`entry-gate`](https://github.com/KCNyu/clawock/blob/master/skills/entry-gate/SKILL.md) | Workspace quote pipelines, instrument registry, evidence source grading, deterministic hard vetoes | Reusable; artifacts live in `memory/entry-gates/` |

These surfaces chain in one direction — entry gate, then first-party earnings evidence, then the canonical thesis and its evidence-only drift, then the existing decision, risk and settlement loop. Each step writes a versioned artifact the next one reads, so a later stage can never quietly re-derive an earlier one from prose.

These are workspace-native research routes, not standalone one-command products. They expect clawock's scripts, data contracts, and memory/SOP files; the published portfolio and its operating history remain specific to this deployment.

Built with [Claude Code](https://claude.com/claude-code), the [openclaw](https://openclaw.com) cron daemon, a static Jekyll + GitHub Pages frontend, and Python. Market, news, macro, and sentiment come from documented public sources with multi-source fallback; see [third-party data and service terms](https://github.com/KCNyu/clawock/blob/master/docs/legal/third-party-data.md) before reusing any fetched content.

<details>
<summary><b>Under the hood</b> — models, write coordination, and integrity gates</summary>

<br>

**Models.** Model selection belongs to the external runtime, not clawock. The
live OpenClaw instance can pin a primary and fallback independently for each
scheduled job; provider credentials and routing policy stay outside this public
repository and can change without rewriting the workflow. No provider key is
stored here.

**Write reconciliation.** Dashboard outputs are one derived generation published on the data plane, while scan sidecars and other runtime state have their own producers. The rule: isolate scan-sidecar writers, serialize dashboard builders that share a host, and keep one publication implementation.

- **The frontend reads scan sidecars directly.** Macro / sentiment / news / influencer feeds are fetched file-by-file at load, so a GitHub Action only ever commits its own disjoint sidecar — writers can't conflict, and a scan appears the instant its commit lands, with no rebuild.
- **Dashboard builders share one lock and one contract.** On-host rebuilds serialize on a shared `flock`; every builder runs the same semantic-diff helper, so clock-only rewrites are restored and the complete generation is published together to the data plane.
- **Everyone pushes through `ops/publish/safe_push.sh`** — rebase-retry, abort on a real conflict, and a committed conflict marker is rejected at the push hook so a broken generation can never reach Pages.
- **Portfolio numbers are gated at the door.** `portfolio.json` — the single source of truth — is written under an advisory `flock` with read-fresh-then-overlay and atomic replace. A pre-push hook blocks any push whose book fails a money-conservation identity (`TCV = Σ value`, `cash = baseline + trades + adjustments`, `cost = moving-weighted`), and those derivations are pinned by a `pytest` suite in CI.
- **Schedules have a checked contract.** Runtime truth comes from the live cron list; a tracked config drives the generated schedule table, DST sync, payload/watchdog checks, and CI health.

</details>

<details>
<summary><b>Repository layout</b></summary>

<br>

| Path | Owner |
|---|---|
| `src/clawock/` | Complete product: harness, strategies, scheduling, providers, workflows, schemas and CLI |
| `config/profiles/` | Declarative desk profiles; values and resource references only |
| `site/` | Jekyll/dashboard source, browser code, SVGs, screenshots and social assets |
| `ops/{host,publish,ci,growth,pages}/` | Explicit host, publication, CI, growth and Pages wiring; never a generic data bucket |
| `docs/`, `tests/` | Product/runbook documentation and invariant checks |
| root context files, `skills/`, `memory/` | OpenClaw compatibility surface; kept at runtime-required paths |
| `portfolio.json`, `assets/data/` | Live ledger and generated publication state; never package contents |
| `LICENSE`, `NOTICE`, `THIRD_PARTY_LICENSES/` | Standard legal/package entry points copied by Pages staging |

</details>

---

## Scope, disclaimer, and license

This repository holds **real trading positions**. It is a personal record and portable workspace — **not investment advice, a recommendation, or a copy-trading system**. The desk analyzes and proposes; it does not place orders for you. No individual outcome is hand-picked — settlement rules and methodology changes are versioned in code — the active calls have yet to show an edge, and every number may be stale by the time you read it.

Original code is under the [MIT License](https://github.com/KCNyu/clawock/blob/master/LICENSE). Adapted third-party code keeps its own license and attribution in [NOTICE](https://github.com/KCNyu/clawock/blob/master/NOTICE) and [`THIRD_PARTY_LICENSES/`](https://github.com/KCNyu/clawock/tree/master/THIRD_PARTY_LICENSES). Third-party market data, news, social posts, filings, trademarks, and API access are **not** relicensed by MIT — see [Third-party data and services](https://github.com/KCNyu/clawock/blob/master/docs/legal/third-party-data.md).

<div align="center">
<br>

**[Live dashboard](https://kcnyu.github.io/clawock/)** &nbsp;·&nbsp; **[Daily briefs](https://kcnyu.github.io/clawock/briefs.html)** &nbsp;·&nbsp; **[简体中文](https://github.com/KCNyu/clawock/blob/master/README.zh.md)**

<sub>Built and maintained by <a href="https://github.com/KCNyu">Shengyu Li (kcn)</a> and Rick · 2026</sub>

</div>
