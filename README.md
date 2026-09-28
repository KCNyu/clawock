<div align="center">

<h1><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/logo-lockup.svg" alt="clawock" height="48"></h1>

### AI argues. Code settles. The losses stay on the page.

[![PyPI](https://img.shields.io/pypi/v/clawock?label=PYPI&style=flat-square&logo=pypi&logoColor=white&labelColor=252b35&color=4b91c8)](https://pypi.org/project/clawock/)
[![npm](https://img.shields.io/npm/v/clawock-dsh?label=NPM&style=flat-square&logo=npm&logoColor=white&labelColor=252b35&color=4b91c8)](https://www.npmjs.com/package/clawock-dsh)
[![Tests](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/ci.yml?label=TESTS&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/ci.yml)
[![Live Data](https://img.shields.io/github/actions/workflow/status/KCNyu/clawock/dashboard-artifact-gate.yml?label=DATA&style=flat-square&logo=githubactions&logoColor=white&labelColor=252b35&color=738391)](https://github.com/KCNyu/clawock/actions/workflows/dashboard-artifact-gate.yml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fkcnyu.github.io%2Fclawock%2Fassets%2Fdata%2Fcoverage.json&style=flat-square&logo=python&logoColor=white&labelColor=252b35)](https://github.com/KCNyu/clawock/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/LICENSE-MIT-aab5bf?style=flat-square&labelColor=252b35)](https://github.com/KCNyu/clawock/blob/master/LICENSE)

[**Live dashboard**](https://kcnyu.github.io/clawock/) &nbsp;·&nbsp; [**Daily briefs**](https://kcnyu.github.io/clawock/briefs.html) &nbsp;·&nbsp; [**Evidence**](https://kcnyu.github.io/clawock/#reflect) &nbsp;·&nbsp; [**简体中文**](https://github.com/KCNyu/clawock/blob/master/README.zh.md)

<a href="https://kcnyu.github.io/clawock/">
  <img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/social-card.png" alt="clawock — portable investment decision workflows for any external AI agent, proven on a live HK and US desk" width="820">
</a>

<sub><i>“The market doesn't care how confident the model was.”</i></sub>

<a href="https://kcnyu.github.io/clawock/"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dashboard.gif" alt="clawock dashboard cycling through its tabs" width="820"></a>

| **<!-- CW_M:days -->134<!-- /CW_M:days -->** | **<!-- CW_M:rows -->936<!-- /CW_M:rows -->** | **<!-- CW_M:settled -->152<!-- /CW_M:settled -->** | **44** | **5** | **0** |
|:---:|:---:|:---:|:---:|:---:|:---:|
| days live on a real HK + US account | decisions on the public ledger | episodes settled by code | data modules across 8 layers | agent harnesses, one contract | scores the model wrote for itself |

<sub>Real positions, real P&amp;L — <!-- CW_M:return_pct -->−22.33%<!-- /CW_M:return_pct --> since day one, published exactly as it is — graded in the open. Numbers and still previews refresh weekly; the dashboard GIF is refreshed on manual dispatch. The live dashboard updates through the trading day.</sub>

</div>

```bash
pip install clawock                        # the decision workflow + CLI (Python ≥ 3.11)
dsh plugin --profile web add clawock-dsh   # optional: the DeepSeek Harness panel
```

Every trading day, clawock turns raw market information into decisions that get graded:

- **Collect.** 44 fetch and compute modules across 8 layers: quotes, SEC and HKEX filings, capital flow, bilingual news, Reddit and influencer feeds, with multi-source fallback. Python fetches; the model only reads the assembled context.
- **Compute factors.** Quant factors, cross-sectional ranks, peer residuals and a trend × volatility leverage dial, all computed deterministically in Python.
- **Backtest.** A factor's clustered bootstrap interval has to clear 50% before it may influence a decision; the cross-sectional layer is pre-registered; the leverage dial is scored out of sample. What fails is published in the [Reflect view](https://kcnyu.github.io/clawock/#reflect).
- **Decide.** Four analyst lenses, a bull and a bear, three risk voices and a judge argue over the same context and write `plan.json`.
- **Settle.** Python settles every decision against real prices. The model never touches its own score, and every result lands on the public scorecard.

The whole pipeline plugs into the agent you already use — each logo opens that harness's runnable example, and [the full loop](#run-it-on-your-own-book) is below:

<div align="center">
<table>
<tr>
<td align="center" valign="top" width="120"><a href="https://github.com/KCNyu/clawock/blob/master/examples/claude-code/CLAUDE.md"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harness/claude-code.svg" width="56" height="56" alt="Claude Code"><br><b>Claude Code</b></a></td>
<td align="center" valign="top" width="120"><a href="https://github.com/KCNyu/clawock/blob/master/examples/codex/AGENTS.md"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harness/codex.svg" width="56" height="56" alt="Codex"><br><b>Codex</b></a></td>
<td align="center" valign="top" width="120"><a href="https://github.com/KCNyu/clawock/blob/master/examples/openclaw/SKILL.md"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harness/openclaw.svg" width="56" height="56" alt="OpenClaw"><br><b>OpenClaw</b></a></td>
<td align="center" valign="top" width="120"><a href="https://github.com/KCNyu/clawock/blob/master/examples/dsh/README.md"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harness/deepseek-harness.svg" width="56" height="56" alt="DeepSeek Harness"><br><b>DeepSeek Harness</b></a></td>
<td align="center" valign="top" width="120"><a href="https://github.com/KCNyu/clawock/blob/master/examples/cli/run.sh"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/harness/any-cli.svg" width="56" height="56" alt="Any CLI"><br><b>Your own / CLI</b></a></td>
</tr>
</table>
</div>

---

## What this is

This started as one account, not a package. A multi-agent desk debates the
evidence on a real brokerage account with separate Hong Kong and US books and
proposes trades; the account owner still places the orders. What comes out of
that is the record: real positions, a growing decision history, and a public
scorecard the model has no say in — not a get-rich bot, and not a
copy-trading service.

clawock is the part of that desk pulled out to be reusable: certified evidence,
a required opposing case, checked money and FX arithmetic, and outcomes linked
back to the decision that caused them. Your runtime keeps the model call, chat,
memory, tools, permissions and credentials.

To try it without installing anything, open a Codespace and run
`examples/cli/minimal-run/run.sh` — a clean virtualenv, no credentials, no
broker, the same script CI runs against every published wheel.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/KCNyu/clawock)

### What makes it different

- **A workflow plugin, not another agent.** clawock owns only the decision contract — files and a CLI — so it moves between the runtimes above unchanged.
- **The loop continues after the answer.** Evidence, the opposing case, thesis, decision, execution, and observed outcome share one lineage. Measured results can propose bounded parameter changes, but never silently rewrite strategy.
- **Real money, graded in public.** One live Hong Kong + US brokerage account, with a public scorecard that keeps every eligible result — the losses included, and the fact that the active calls haven't beaten buy-and-hold. Each published headline names the ledger slice, window and commit it was computed from, and `clawock scorecard-provenance --check` recomputes it from `memory/decisions.jsonl` — a re-graded row inside a published window shows up as a mismatch.
- **The model can't grade itself.** LLMs propose trades; Python settles them and computes the scorecard.
- **One thesis, one episode.** Repeated opinions on the same thesis count once. Each episode is settled from canonical vendor bars, with declared gap-fill rules when a session is missing.
- **The ledger has to reconcile.** A money-conservation check runs before every push; if cash, positions, and P&L don't balance, nothing is published.
- **Built to keep running.** Scheduled Hong Kong and US sessions produce the daily briefs and refresh the live dashboard through the trading day.

For the canonical EN/ZH rendering of every project term — composite, regime, DSR, CSCV, triple barrier, run card and the rest — see the [glossary](https://github.com/KCNyu/clawock/blob/master/docs/glossary.md).

## How it works

The external agent reads and reasons; clawock owns the portable decision
workflow and the deterministic truth around it.

![clawock product architecture — external runtimes own models, conversation, memory and tools while the package supplies portable workflows, certified context, deterministic reconciliation, evaluation and bounded improvement](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/product-architecture.svg)

The second diagram is the deployed KCNyu desk — that boundary applied to one live portfolio.

![KCNyu live-desk architecture — Python builds reconciled market context, OpenClaw agents debate the trade, clawock contracts gate the decision, and a public scorecard closes the loop](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/architecture.svg)

## The information layer

The widest part of the system is data collection: **44 fetch and compute modules across 8 layers**, with **bilingual Hong Kong + US coverage**. Each run consumes only the subset relevant to its market and session — collection stays broad, the decision layer stays constrained.

Coverage is bilingual, but it is not symmetric, and the asymmetry is in research breadth rather than in the basics. Quotes, fundamentals, news and cash-flow reconciliation all have real Hong Kong branches. Two research-breadth capabilities do not: same-industry peers are discovered automatically for US names and read from a curated map for Hong Kong ones ([`peer_discovery.py`](https://github.com/KCNyu/clawock/blob/master/src/clawock/market_data/peer_discovery.py) — the mechanism is verified, the flag stays off until the peer-residual rules are re-registered against the wider universe), and US trading halts arrive as a structured feed while a Hong Kong suspension arrives as an announcement that the triage rules mark for a human ([`mover_evidence.py`](https://github.com/KCNyu/clawock/blob/master/src/clawock/market_data/mover_evidence.py)). So: Hong Kong base coverage on par, Hong Kong research breadth behind US.

![clawock information flow — eight layers and 44 modules feed a deterministic Python preflight; the complete context is kept for audit while the daily brief reads a generation-bound core and selected bundles; Python validates and settles before publish](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/information-flow.svg)

<details>
<summary><b>All 8 layers, row by row</b> — modules and primary sources</summary>

<br>

| Layer | Modules | Primary sources |
|---|:---:|---|
| 1 · Market | 7 | Tencent · Yahoo · Eastmoney · Polygon |
| 2 · Fundamentals & filings | 3 | SEC EDGAR · Eastmoney datacenter · HKEX |
| 3 · Capital flow | 1 | Eastmoney push2his |
| 4 · News & catalysts (bilingual) | 6 | Eastmoney · Finnhub · Google News · Yahoo · 10jqka · exchange filings |
| 5 · Macro & sentiment | 3 | Yahoo · Reddit · CNN · social feeds |
| 6 · Quant & risk | 9 | deterministic math over price history |
| 7 · Book & FX integrity | 6 | Frankfurter · the reconciliation ledger · local invariants |
| 8 · Backtest & calibration | 9 | local snapshots + canonical bars |

The fetch layer degrades gracefully: every live Eastmoney call routes through **one throttled gateway**, critical paths (quotes, FX) use **multi-source fallback**, and an empty fetch **keeps the prior value** instead of overwriting a good series with a blank. Public sources include Tencent, stooq, yfinance, Frankfurter, SEC EDGAR (including its full-text search), HKEXnews, Finnhub, Nasdaq, Eastmoney, 10jqka, Polygon, Alpha Vantage, Reddit, Google News, and Yahoo Finance RSS — full command and provider catalog in [the command reference](https://github.com/KCNyu/clawock/blob/master/docs/reference/commands.md), whose inventory is generated from the same registries this table is checked against. Which module sits in which layer is itself an artifact — [`config/information-layers.json`](https://github.com/KCNyu/clawock/blob/master/config/information-layers.json), where every packaged command is either in a layer or listed with the reason it is not collection — and CI checks the table above against it, so a module that moves cannot leave its count standing.

</details>

### What each run actually receives

No run gets everything: each job's preflight assembles only the blocks it can act on, and the model reads those files rather than fetching for itself (the flow diagram above). For the daily brief the complete context stays an audit record while the model reads a generation-bound core plus loadable bundles. Pre-open gets the most and writes the day's plan; open/midday/close reports travel light; intraday check-ins (every 30 minutes a market is open) sit in between, with no research production and no evidence-graph rebuild.

<details>
<summary><b>The full block breakdown</b> — row by row, by cadence</summary>

<br>

| | Pre-open brief | Open / midday / afternoon / close | Intraday check-in |
|---|---|---|---|
| **When** | 08:03 HKT, weekdays | HK 09:30 · 12:00 · 13:30 · 16:00 · US open and close | every 30 min while a market is open |
| **Blocks** | 41 | 18 | 47 |
| **Position truth** | holdings, book totals, concentration, leverage look-through | fresh quote block | fresh quote block |
| **Risk** | guardrail, discipline ledger, β/vol/drawdown, breakeven math | risk section only when signals demand it | signal counts and detail |
| **Signals** | quant factors and their hit-rate review, cross-sectional factor, peer residual, T+0 setups, the close-confirmed opportunity radar (which names closed above their prior 20-day high, and why an empty add side is empty) | peer/sector scan | peer/sector scan, T+0 setups, anomaly flags, entry setups and early-trend candidates re-run on the open bar, price-surface opportunity radar |
| **News and events** | evidence graph, Chinese-language company news, catalyst calendar, macro, Reddit and social feeds, live filings and news since the last close (HKEXnews, EDGAR full-text, Google News, Yahoo) | catalyst probe on flagged names, live filings and news for every holding | catalyst probe on flagged names, live filings, news and 7×24 flashes for every holding every slot |
| **Research state** | thesis registry, research work queue (reviews due, overdue promises, ungated positions) | thesis and red lines for flagged names | thesis and red lines for flagged names |
| **History** | retrospective, decision metrics, reflections, data-integrity report | — | heartbeat slot state |
| **Today's plan** | writes it | the morning's still-open decisions for this leg, and which of their trigger prices the current quote already satisfies | the morning's still-open decisions for this leg, and which of their trigger prices the current quote already satisfies — checked arithmetically and printed in the block, not left for the model to notice |

Block counts are the top-level context sections each cadence emits, pinned by CI (`tests/test_readme_parity.py`) against the preflights' own context dicts — packet-identifying envelope keys (`context_id` / `generation_id`) are not counted, which is why a written artifact carries one key more than this number.

The catalyst probe is the narrow, time-sensitive one: it fires **only for names that already moved**, reads exchange and regulator filings first (SEC acceptance timestamps, HKEX announcements), classifies each item as interrupt, context or noise, and states `no_recent_filing` explicitly rather than letting an empty block read as "nothing happened".

</details>

### Influencer radar

Twice every trading day, eight public sources — Trump, Musk, Cathie Wood / ARK,
Serenity, 段永平, 洪灏, Michael Burry, Pelosi — are scanned over a 48-hour window,
filtered by an LLM and linked to actual holdings, so the pre-open brief already
says who said what and whether it touches the book; misses are published as
misses. Sources, per-source budgets and a worked hit/miss example:
[docs/influencer-radar.md](https://github.com/KCNyu/clawock/blob/master/docs/influencer-radar.md).

## How it decides

Analysis resolves into explicit, gated strategy decisions — and one stock can carry several at once.

- **Several strategies, graded separately.** `core_position`, `risk_rebalance`, `intraday_t`, `event_trade`, and `tactical_entry` can coexist on the same name, because a long-term thesis and an intraday trade can legitimately disagree. Each is graded in its own episode.
- **Attribution-first.** Every decision is tagged by its dominant driver, and that driver's edge is measured *dynamically* from the record — no hit rate is hard-coded into the logic.
- **Falsify, don't confirm.** In a risk-on tape the default is HOLD. A bullish story doesn't trigger a buy until it clears a disconfirming check and an "is this already priced in?" test on the last few days' move.
- **Regime over timing.** Leverage isn't timed; a 200-day-trend × volatility dial sets the cap. The backtested lesson: the edge was in *de-leveraging in the wrong regime*, not in calling tops.
- **Adds need two independent evidence families.** Price-relative (factor rank plus curated-peer residual), point-in-time news, or a confirmed un-overheated 20-day breakout — any two authorise a capped exploration slice; validated authority needs both a price and an information side, so a price pattern can never promote a leveraged name, and negative information blocks the add outright.

## The debate

The daily deep brief runs a structured **multi-agent debate**, adapted from [TradingAgents](https://github.com/TauricResearch/TradingAgents) for separate Hong Kong and US books. More agents isn't the point: the protocol **demands an opposing case**, and the Judge **attributes each resolution** to a named strategy frame.

![clawock's multi-agent debate — one evidence pack feeds four analyst lenses; two researchers argue opposing bull and bear cases and record where they disagree; three risk voices and a judge name the strategy frame and resolve it into plan.json, which enters the next session's grading loop](https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/debate-flow.svg)

- **Bull vs Bear, on the record.** Two researchers must **genuinely disagree on at least one position** and write it down, so unanimity reads as a flag, not evidence. The Bear is the devil's advocate: it attacks the session's *strongest* consensus view, never the weakest.
- **Risk voices + a Judge.** Aggressive, Conservative and Neutral argue their corner; the first mover rotates every four trading days so the framing cannot calcify. The Judge names the strategy frame behind each decision and writes `plan.json`, which enters the next session's grading.

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
- **Shadow portfolio (simulated · not live).** Two cash + inventory books replay the same timeline: one follows every triggered active call, the other buys and holds. Their cumulative difference is reported as *simulated timing alpha*, **gross** — fills are `qty x price`, so it carries no commission and no spread. A **net** figure is published beside it, never instead of it: the same replay with a pre-registered haircut deducted at each fill (`config/cost-model.json`), whose assumptions ride in the payload with every number they moved. They are assumptions, not observations — nothing here reads a broker invoice — and market impact is deliberately not modelled. It keeps USD and HKD separate, exposes how few calls were ever actually executed, and discloses the unadjusted-bar bias. Source: `assets/data/shadow_portfolio.json`. It is a policy simulation, not a claim about what the live account earned.

</details>

## What we tested, and what failed

The scorecard reports what happened. This reports what was checked — and what did not survive the check.

A layer has to clear a stated bar before it is allowed to influence a decision, and the bar is set before the result is known:

- **Factor edges** must have a two-way clustered bootstrap interval that does not straddle 50%. An interval that straddles it means the sample is too small, which is a different statement from "the factor does not work" — both keep it out of decisions, and the distinction is published.
- **The cross-sectional layer** is pre-registered. Only snapshots recorded after registration count toward activation, so a retrospective result can never switch it on.
- **The leverage dial** is scored out of sample: thresholds are calibrated on a leading window and graded on the next one, and its timing is tested against a null that circularly shifts the same exposure path against returns — preserving its shape and time-in-market while destroying only the alignment. The dial is a **risk-budget control, not a timing signal**: its durable claim is less exposure in hostile regimes, while calling turns is exactly the part that cannot be distinguished from chance.

Results are published whether or not they flatter the system: on the sample available the dial's timing cannot be distinguished from chance, and Reflect says so — and says whether that is a failure to reject or a refutation. The Reflect evidence section is **generated from the artifacts**, and any backtest figure quoted in the repository must cite a run card that still contains it; CI fails on either drift.

[**Evidence and refutation**](https://kcnyu.github.io/clawock/#reflect)

## What the code enforces

The model writes opinions. The arithmetic that could corrupt the record runs in Python and is unit-tested.

That path is covered by a large unit-test suite — it's what keeps the system stable. Currencies never sum (HKD and USD are shown separately, rate and timestamp stamped), risk caps are checked every brief (single name ≤60% hard cap with a 35% review band for the non-leveraged core, ≤35% for leveraged single names, correlated cluster ≤70%, portfolio β ≤3.0, stop at −18%), and a thesis moves only on new evidence, never on a price move alone.

<details>
<summary><b>All twelve rules, what the code actually does for each</b></summary>

<br>

| Rule | What the code does |
|---|---|
| **Currencies never sum** | HKD and USD are shown in both views with the rate + timestamp stamped; adding them naively is a meaningless number. |
| **Risk caps, checked every brief** | Single name: leveraged ≤35% hard; non-leveraged core ≤60% hard with a 35–60% review band (advisory, never a forced sale). Correlated cluster ≤70% (measured correlation clusters, applied when coverage is sufficient), leverage-ETF sleeve ≤50%, portfolio β ≤3.0, stop at −18%. Each breach has a durable age, acknowledgement, expiring override and execution-evidence record; same-risk adds freeze until compliance. Execution stays human. |
| **Concentration per leg** | `HHI = Σ wᵢ²` per book; top2 is the combined weight of the two largest holdings. The brief uses HHI alone, taking the first matching bucket: `≤0.15` ✅ · `≤0.25` 🟡 · `≤0.40` 🟠 · otherwise 🔴. The dashboard takes the first matching pair: `HHI<0.15 and top2<40%` ✅ · `HHI<0.25 and top2<60%` 🟡 · `HHI<0.40 and top2<75%` 🟠 · otherwise 🔴. Never blended across currencies. |
| **Leverage judged by regime** | A 200-day-trend × volatility dial caps the leverage-ETF sleeve (×1 / ×0.5 / ×0) as a risk-budget control, not a timing signal — its measured value is less exposure in hostile regimes, and its timing cannot be distinguished from chance (see the testing section); daily-reset 2×/3× products skip fundamentals entirely. |
| **Return on peak principal** | Return % uses peak net deposits from the cash-flow ledger, not `cost − realized` — a realized win must not fake a higher return. |
| **News needs an evidence graph** | Filings, issuer/exchange news, calendars, and headlines are deduplicated into expiring event IDs. A reliable, novel, negative event with price/volume or validated peer confirmation may drive defensive action. Positive surprise or accelerating attention can only join price-relative evidence in a capped add exploration; it cannot trade alone. |
| **Unproven signals get an exploration boundary** | A quant factor cannot claim validated authority until it clears prospective activation. While warming up, a pre-registered interaction can collect one capped tranche per ticker/policy; the ledger keeps that evidence grade distinct. |
| **Add authority needs two independent families** | Factor and peer residual count as one price-relative family, not two votes. Any two independent families — price-relative, point-in-time news surprise/attention, or a confirmed un-overheated 20-day breakout — authorise a capped exploration slice; validated tranches still require decision-usable evidence on both the price and the information side, so a price pattern can never promote a leveraged name. |
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

From an empty directory to a published decision — the same block
[`examples/cli/workflow-run/run.sh`](https://github.com/KCNyu/clawock/blob/master/examples/cli/workflow-run/run.sh)
runs on every pull request against the wheel alone (clean virtualenv, emptied environment):

```bash
pip install clawock
clawock workflow install investment-decision --workspace ./my-book
clawock init ./my-book --workflow investment-decision
cd my-book && mkdir -p .clawock/work
clawock run prepare > .clawock/work/request.json
# your agent reads the request and writes decision.json
clawock run publish --request .clawock/work/request.json --artifact decision.json=decision.json
```

You need Python ≥ 3.11 and an agent that can read a file and write
`decision.json`; the model call stays entirely in your runtime. No model at hand?
`bash examples/cli/minimal-run/run.sh` smokes the whole lifecycle without one.
Drop the opposing evidence from `decision.json` and `publish` refuses it (exit code 1):

```json
{
  "status": "rejected",
  "validation_issues": [
    {"code": "insufficient_opposing_evidence", "message": "requires at least 1 opposing evidence item(s)"},
    {"code": "unsupported_bear_case", "message": "bear_case must cite opposing evidence"},
    ...
  ]
}
```

### Same contract, whatever the harness looks like

Every harness drives the same three steps — prepare, write `decision.json`,
publish — through its own interface. **Claude Code** is a terminal loop; this
is a real run of the [`examples/claude-code`](https://github.com/KCNyu/clawock/blob/master/examples/claude-code/CLAUDE.md) instruction:

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/claude-code-terminal.png" alt="Claude Code running the investment-decision workflow end to end: clawock init, clawock run prepare, Claude writing decision.json, clawock run publish returning status: published" width="820"></p>

**OpenClaw** runs it unattended. This desk's scheduler holds one job per
brief, session report and intraday check-in; each prompt is
`clawock … preflight` → the model writes → `clawock … postflight`:

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/openclaw-cron.png" alt="OpenClaw's live cron list on the desk host: nine clawock jobs (pre-open brief, HK and US session reports, intraday check-ins) with their cron expressions, the clawock preflight → postflight lifecycle each one runs, last status ok and run time" width="820"></p>

<sub>Rendered from the host's real <code>openclaw cron list --json</code> by <code>site/tools/shoot_openclaw_cron.js</code>; job ids, delivery targets and prompts are left out.</sub>

**Codex** reads the same steps from [`examples/codex/AGENTS.md`](https://github.com/KCNyu/clawock/blob/master/examples/codex/AGENTS.md);
**DeepSeek Harness** gets a native panel (next section). Whichever harness a
conversation runs in, its verdict lands through one command —
`clawock record --source <harness>` (bear case and invalidation conditions
mandatory) — so nobody edits `decisions.jsonl` by hand.

The package owns lifecycle, strategies, scheduling, watchdogs, context assembly,
validation and CLI; it does not reimplement an agent loop. `clawock doctor` and
`clawock context audit` name the capabilities a foreign workspace is missing
instead of pretending it is ready to run this live desk.

## The DeepSeek Harness plugin

One command installs the investment-decision skill plus two native surfaces in
the dsh web GUI — [npm](https://www.npmjs.com/package/clawock-dsh) ·
[package README](https://github.com/KCNyu/clawock/blob/master/examples/dsh/packages/clawock-dsh/README.md):

```bash
dsh plugin --profile web add clawock-dsh
```

**Decision Mind** — every real fill beside the plan written at the time. The
spine is `portfolio.json` trades; each row carries the soft-paired decision
(±3 days from `decisions.jsonl`) and a T+1 verdict from the canonical
`memory/bars/` close — 卖飞/卖对 on reduces, 涨/跌 on adds. Click a fill and it
unfolds into plan → real fill → T+1 → P&L. Fills with no plan say so; USD and
HKD never mix. The public dashboard's Reflect card renders the same traces from
a separate implementation, pinned together by `tests/test_decision_trace_parity.py`.

<p align="center"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-decision-mind.png" alt="Decision Mind plugin — decision traces: real fills with soft-paired decisions and T+1 verdicts, expandable to a plan → execution → result timeline" width="860"></p>

<table>
<tr>
<td width="46%" valign="top"><img src="https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/site/assets/dsh-dispatch-queue.png" width="360" alt="The whole sidebar provider panel on a live host: Claude and Codex subscription quota windows (5h and week, with reset times) above each agent's running task, the DeepSeek and MiniMax balances, the OpenCode free pool, recently ended tasks with delivery receipts and cost, patrol rounds, and the ops footer / 真实主机上的整块侧栏 provider 面板:Claude 与 Codex 订阅额度窗口(5 小时与周,带重置时间)在各自运行中的任务上方,DeepSeek 与 MiniMax 余额,OpenCode 免费池,最近结束的任务(送达回执与费用),巡检轮次,以及 ops 页脚"></td>
<td valign="top">

**Provider panel — quota, balances and the task queue in one cell.** The
sidebar's folded rows (bottom-left in the shot above) open into this panel:

- **Quota windows** for the Claude and Codex subscriptions — 5-hour and weekly use, with reset times.
- **Balances** for DeepSeek and MiniMax; the OpenCode free pool and its next model.
- **The dispatch queue** on a host that runs clawock's agent-dispatch: each agent's running and queued tasks with model, start, duration and cost.
- **Recently ended** tasks with WeChat/Telegram delivery receipts, and **patrol** rounds.
- Click a row for its detail layer — retry, re-prioritise, switch model or cancel, all through the versioned ops entry ([task-queue.md](https://github.com/KCNyu/clawock/blob/master/docs/architecture/task-queue.md)); the footer turns red when merged ops code is not installed.

</td>
</tr>
</table>

## Explore the system

- [**Live dashboard**](https://kcnyu.github.io/clawock/) — positions, risk, and the code-graded scorecard; on phones, swipe between the six views and the tab rail follows the current page.
- [**Daily briefs**](https://kcnyu.github.io/clawock/briefs.html) — the published morning reads.
- [**Decision Map**](https://kcnyu.github.io/clawock/#reflect) — a dated signal snapshot beside each decision, with coverage and age shown in Reflect ([reading guide](https://github.com/KCNyu/clawock/blob/master/docs/decision-map.md)).
- [**Examples by harness**](https://github.com/KCNyu/clawock/blob/master/examples/README.md) — one decision run, five harnesses: pure CLI, OpenClaw, Claude Code, Codex, DeepSeek Harness, plus the npm DSH plugin.
- [**Schedule**](https://github.com/KCNyu/clawock/blob/master/docs/operations/cron-schedules.md) — the generated cron table.
- [**Command reference**](https://github.com/KCNyu/clawock/blob/master/docs/reference/commands.md) — every installed command, generated from the registries, plus the hand-written provider and harness detail.
- [**Project docs**](https://github.com/KCNyu/clawock/blob/master/docs/README.md) — current architecture, product guides, operations, reference, and legal notes.

### Research surfaces

| Question | Entry point | Data/runtime contract | Reuse scope |
|---|---|---|---|
| Analyze a US company | [`us-stock-analysis`](https://github.com/KCNyu/clawock/blob/master/skills/us-stock-analysis/SKILL.md) | Local quote fallback, SEC filings, fundamentals, news | Reusable with the clawock workspace |
| Analyze a Hong Kong company | [`hk-stock-analysis`](https://github.com/KCNyu/clawock/blob/master/skills/hk-stock-analysis/SKILL.md) | Tencent/Eastmoney quote checks, HK fundamentals, market context | Reusable with the clawock workspace |
| Review the current portfolio | [`portfolio-risk-review`](https://github.com/KCNyu/clawock/blob/master/skills/portfolio-risk-review/SKILL.md) for one pass; [`portfolio-swarm-review`](https://github.com/KCNyu/clawock/blob/master/skills/portfolio-swarm-review/SKILL.md) for debate | `portfolio.json`, fresh quotes, risk and decision ledgers | Specific to the configured portfolio |
| Stress-test a supply-chain thesis | [`serenity-skill`](https://github.com/KCNyu/clawock/blob/master/skills/serenity-skill/SKILL.md) | Current public evidence plus its local scorecard | Reusable as a manual research framework |
| Review a reported quarter and hold management to account | [`earnings-review`](https://github.com/KCNyu/clawock/blob/master/skills/earnings-review/SKILL.md) | First-party filings/HKEX announcements, structured XBRL or Eastmoney verification, provenance gate | Reusable; artifacts live in `memory/earnings/` |
| Decide whether a new name is worth researching | [`entry-gate`](https://github.com/KCNyu/clawock/blob/master/skills/entry-gate/SKILL.md) | Workspace quote pipelines, instrument registry, evidence source grading, deterministic hard vetoes | Reusable; artifacts live in `memory/entry-gates/` |

They chain one way — entry gate → first-party earnings evidence → canonical thesis → the decision, risk and settlement loop — each step writing a versioned artifact the next reads. They are workspace-native routes that expect clawock's scripts, data contracts and memory/SOP files, not standalone one-command products.

Built with [Claude Code](https://claude.com/claude-code), the [openclaw](https://openclaw.com) cron daemon, a static Jekyll + GitHub Pages frontend, and Python. Market, news, macro, and sentiment come from documented public sources with multi-source fallback; see [third-party data and service terms](https://github.com/KCNyu/clawock/blob/master/docs/legal/third-party-data.md) before reusing any fetched content.

<details>
<summary><b>Under the hood</b> — models, write coordination, and integrity gates</summary>

<br>

**Models.** Model selection belongs to the external runtime, not clawock. The
tracked schedule contract lists MiniMax-M3.1-Flash-Preview as primary and GPT-6 Luna among the
fallbacks for brief, report, and intraday jobs; the live OpenClaw instance can
change its routing independently. Provider credentials stay outside this public
repository. No provider key is stored here.

**Write reconciliation.** Dashboard outputs are one derived generation published on the [data plane](https://github.com/KCNyu/clawock/blob/master/docs/architecture/data-plane.md): Pages serves the static shell and a cold-start snapshot, while later browser polls read the seven required generation files from the `data-plane` branch. An eighth evidence file is published when available. Scan sidecars and other runtime state have their own producers. The rule: isolate scan-sidecar writers, serialize dashboard builders that share a host, and keep one publication implementation.

- **The frontend reads scan sidecars directly.** Macro / sentiment / news / influencer feeds are fetched file-by-file at load, so a GitHub Action only ever commits its own disjoint sidecar — writers can't conflict, and a scan appears the instant its commit lands, with no rebuild.
- **Dashboard builders share one lock and one contract.** On-host rebuilds serialize on a shared `flock`; every builder runs the same semantic-diff helper, so clock-only rewrites are restored and the complete generation is published together to the data plane.
- **`master` writers push through `ops/publish/safe_push.sh`.** It retries a rebase, aborts on a real conflict, and the push hook rejects committed conflict markers. The dashboard generation uses the separate validated data-plane publisher.
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
