# How the desk works

The [README](https://github.com/KCNyu/clawock/blob/master/README.md) says what clawock does for you and how to start. This
page is the detail behind it: what is collected, what each run reads, how a
decision is gated, how a call is graded, what was tested and failed, and which
rules live in code. The figures are in the README; the words they summarise are here.

[简体中文](https://github.com/KCNyu/clawock/blob/master/docs/how-the-desk-works.zh.md)

## What makes it different

- **A workflow plugin, not another agent.** clawock owns only the decision contract — files and a CLI — so it moves between the runtimes above unchanged.
- **The loop continues after the answer.** Evidence, the opposing case, thesis, decision, execution, and observed outcome share one lineage. Measured results can propose bounded parameter changes, but never silently rewrite strategy.
- **Real money, graded in public.** One live Hong Kong + US brokerage account, with a public scorecard that keeps every eligible result — the losses included, and the fact that the active calls haven't beaten buy-and-hold. Each published headline names the ledger slice, window and commit it was computed from, and `clawock scorecard-provenance --check` recomputes it from `memory/decisions.jsonl` — a re-graded row inside a published window shows up as a mismatch.
- **The model can't grade itself.** LLMs propose trades; Python settles them and computes the scorecard.
- **One thesis, one episode.** Repeated opinions on the same thesis count once. Each episode is settled from canonical vendor bars, with declared gap-fill rules when a session is missing.
- **The ledger has to reconcile.** A money-conservation check runs before every push; if cash, positions, and P&L don't balance, nothing is published.
- **Built to keep running.** Scheduled Hong Kong and US sessions produce the daily briefs and refresh the live dashboard through the trading day.


## The information layer

The widest part of the system is data collection: **46 fetch and compute modules across 8 layers**, with **bilingual Hong Kong + US coverage**. Each run consumes only the subset relevant to its market and session — collection stays broad, the decision layer stays constrained.

Coverage is bilingual, but it is not symmetric, and the asymmetry is in research breadth rather than in the basics. Quotes, fundamentals, news and cash-flow reconciliation all have real Hong Kong branches. Two research-breadth capabilities do not: same-industry peers are discovered automatically for US names and read from a curated map for Hong Kong ones ([`peer_discovery.py`](https://github.com/KCNyu/clawock/blob/master/src/clawock/market_data/peer_discovery.py) — the mechanism is verified, the flag stays off until the peer-residual rules are re-registered against the wider universe), and US trading halts arrive as a structured feed while a Hong Kong suspension arrives as an announcement that the triage rules mark for a human ([`mover_evidence.py`](https://github.com/KCNyu/clawock/blob/master/src/clawock/market_data/mover_evidence.py)). So: Hong Kong base coverage on par, Hong Kong research breadth behind US.

**All 8 layers, row by row**

| Layer | Modules | Primary sources |
|---|:---:|---|
| 1 · Market | 8 | Tencent · Yahoo · Eastmoney · Polygon · Nasdaq |
| 2 · Fundamentals & filings | 3 | SEC EDGAR · Eastmoney datacenter · HKEX |
| 3 · Capital flow | 1 | Eastmoney push2his |
| 4 · News & catalysts (bilingual) | 6 | Eastmoney · Finnhub · Google News · Yahoo · 10jqka · exchange filings |
| 5 · Macro & sentiment | 3 | Yahoo · Reddit · CNN · social feeds |
| 6 · Quant & risk | 9 | deterministic math over price history |
| 7 · Book & FX integrity | 6 | Frankfurter · the reconciliation ledger · local invariants |
| 8 · Backtest & calibration | 10 | local snapshots + canonical bars |

The fetch layer degrades gracefully: every live Eastmoney call routes through **one throttled gateway**, critical paths (quotes, FX) use **multi-source fallback**, and an empty fetch **keeps the prior value** instead of overwriting a good series with a blank. Public sources include Tencent, stooq, yfinance, Frankfurter, SEC EDGAR (including its full-text search), HKEXnews, Finnhub, Nasdaq, Eastmoney, 10jqka, Polygon, Alpha Vantage, Reddit, Google News, and Yahoo Finance RSS — full command and provider catalog in [the command reference](https://github.com/KCNyu/clawock/blob/master/docs/reference/commands.md), whose inventory is generated from the same registries this table is checked against. Which module sits in which layer is itself an artifact — [`config/information-layers.json`](https://github.com/KCNyu/clawock/blob/master/config/information-layers.json), where every packaged command is either in a layer or listed with the reason it is not collection — and CI checks the table here against it, so a module that moves cannot leave its count standing.

### What each run actually receives

No run gets everything: each job's preflight assembles only the blocks it can act on, and the model reads those files rather than fetching for itself. For the daily brief the complete context stays an audit record while the model reads a generation-bound core plus loadable bundles. Pre-open gets the most and writes the day's plan; open/midday/close reports travel light; intraday check-ins (every 30 minutes a market is open) sit in between, with no research production and no evidence-graph rebuild.

**The full block breakdown**

| | Pre-open brief | Open / midday / afternoon / close | Intraday check-in |
|---|---|---|---|
| **When** | 08:03 HKT, weekdays | HK 09:30 · 12:00 · 13:30 · 16:00 · US open and close | every 30 min while a market is open |
| **Blocks** | 44 | 19 | 47 |
| **Position truth** | holdings, book totals, concentration, leverage look-through | fresh quote block, naming any row this run could not refresh | fresh quote block |
| **Risk** | guardrail, discipline ledger, β/vol/drawdown, breakeven math | risk section only when signals demand it | signal counts and detail |
| **Signals** | quant factors and their hit-rate review, cross-sectional factor, peer residual, T+0 setups, the close-confirmed opportunity radar (which names closed above their prior 20-day high, and why an empty add side is empty) | peer/sector scan | peer/sector scan, T+0 setups, anomaly flags, entry setups and early-trend candidates re-run on the open bar, price-surface opportunity radar |
| **News and events** | evidence graph, Chinese-language company news, catalyst calendar, macro, Reddit and social feeds, live filings and news since the last close (HKEXnews, EDGAR full-text, Google News, Yahoo) | catalyst probe on flagged names, live filings and news for every holding | catalyst probe on flagged names, live filings, news and 7×24 flashes for every holding every slot |
| **Research state** | thesis registry, research work queue (reviews due, overdue promises, ungated positions) | thesis and red lines for flagged names | thesis and red lines for flagged names |
| **History** | retrospective, decision metrics, reflections, data-integrity report | — | heartbeat slot state |
| **Today's plan** | writes it | the morning's still-open decisions for this leg, and which of their trigger prices the current quote already satisfies | the morning's still-open decisions for this leg, and which of their trigger prices the current quote already satisfies — checked arithmetically and printed in the block, not left for the model to notice |

Block counts are the top-level context sections each cadence emits, pinned by CI (`tests/test_readme_parity.py`) against the preflights' own context dicts — packet-identifying envelope keys (`context_id` / `generation_id`) are not counted, which is why a written artifact carries one key more than this number.

The catalyst probe is the narrow, time-sensitive one: it fires **only for names that already moved**, reads exchange and regulator filings first (SEC acceptance timestamps, HKEX announcements), classifies each item as interrupt, context or noise, and states `no_recent_filing` explicitly rather than letting an empty block read as "nothing happened".

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

- **Bull vs Bear, on the record.** Two researchers must **genuinely disagree on at least one position** and write it down, so unanimity reads as a flag, not evidence. The Bear is the devil's advocate: it attacks the session's *strongest* consensus view, never the weakest.
- **Risk voices + a Judge.** Aggressive, Conservative and Neutral argue their corner; the first mover rotates every four trading days so the framing cannot calcify. The Judge names the strategy frame behind each decision and writes `plan.json`, which enters the next session's grading.

## The public scorecard

Every call is settled mechanically and published — wins, losses, and the cases that can't be graded. Nothing is hand-tuned after the fact.

1. **Record** — the model submits a versioned decision with its strategy, condition, regime, size, and confidence. The authoritative ledger is `memory/decisions.jsonl`.
2. **Trigger** — Python evaluates it against canonical unadjusted daily bars, counted on each market's own calendar. An unfinished session grades nothing, and a gap straight through a trigger fills at the open — never at a price that was never available.
3. **Group** — repeated calls of the same strategy collapse into one *episode*, so holding a position for five mornings does not manufacture five samples.
4. **Grade & publish** — code settles the outcome, scores it against a plain directional baseline, and renders it. Shut sessions, calls that need human evidence, and instruments that didn't trade are published as ungradeable — out of the win-rate denominator, but kept visible in the coverage count instead of silently dropped.

The model submits decisions; it can never write or amend its own evaluation. That isolation stops the desk from grading itself — it does **not** make the market data or the metric definitions correct. **Treat the record as a diagnostic, not as proof of return.**

**How the grading handles the hard cases**

- **Incomplete sessions & missing bars.** Triggers and marks come from `memory/bars/` — unadjusted daily bars from a single canonical vendor feed, not an exchange feed. An unfinished session never grades anything.
- **Reaffirmations.** Consecutive restatements of the same strategy/action are one episode. Re-anchoring a trigger to where the stock has since moved is still a reaffirmation, not a new call.
- **Episode aggregation.** An episode scores as the *mean* of its own settled calls, not an elected member — letting the first or last call speak for the group can swing the active win rate across the 50% line on nothing but that choice.
- **Confidence calibration.** Stated confidence remains an audit field. A strictly prequential beta-binomial hierarchy estimates action × driver × condition × regime probabilities from earlier dates only, shrinks sparse groups toward broader priors, and abstains from signal sizing when evidence or the posterior lower bound is insufficient.
- **Timing, priced separately.** A single-event diagnostic asks how much better or worse the trigger fill was than that session's close, strictly paired by ticker/date/direction/shares. It deliberately never draws a cumulative money curve.
- **Shadow portfolio (simulated · not live).** Two cash + inventory books replay the same timeline: one follows every triggered active call, the other buys and holds. Their cumulative difference is reported as *simulated timing alpha*, **gross** — fills are `qty x price`, so it carries no commission and no spread. A **net** figure is published beside it, never instead of it: the same replay with a pre-registered haircut deducted at each fill (`config/cost-model.json`), whose assumptions ride in the payload with every number they moved. They are assumptions, not observations — nothing here reads a broker invoice — and market impact is deliberately not modelled. It keeps USD and HKD separate, exposes how few calls were ever actually executed, and discloses the unadjusted-bar bias. Source: `assets/data/shadow_portfolio.json`. It is a policy simulation, not a claim about what the live account earned.

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

**All twelve rules, what the code actually does for each**

| Rule | What the code does |
|---|---|
| **Currencies never sum** | HKD and USD are shown in both views with the rate + timestamp stamped; adding them naively is a meaningless number. |
| **Risk caps, checked every brief** | Single name: leveraged ≤35% hard; non-leveraged core ≤60% hard with a 35–60% review band (advisory, never a forced sale). Correlated cluster ≤70% (measured correlation clusters, applied when coverage is sufficient), leverage-ETF sleeve ≤50%, portfolio β ≤3.0, stop at −18%. Exceeding a cap is never a forced sale: the brief must answer each one (a trim, or a hold with its reason); only the −18% stop and a leverage-regime swap, the two rules that name where the money goes, are mandatory. Each breach has a durable age, acknowledgement, expiring override and execution-evidence record; same-risk adds freeze until compliance. Execution stays human. |
| **Concentration per leg** | `HHI = Σ wᵢ²` per book; top2 is the combined weight of the two largest holdings. The brief uses HHI alone, taking the first matching bucket: `≤0.15` ✅ · `≤0.25` 🟡 · `≤0.40` 🟠 · otherwise 🔴. The dashboard takes the first matching pair: `HHI<0.15 and top2<40%` ✅ · `HHI<0.25 and top2<60%` 🟡 · `HHI<0.40 and top2<75%` 🟠 · otherwise 🔴. Never blended across currencies. |
| **Leverage judged by regime** | A 200-day-trend × volatility dial caps the leverage-ETF sleeve (×1 / ×0.5 / ×0) as a risk-budget control, not a timing signal — its measured value is less exposure in hostile regimes, and its timing cannot be distinguished from chance (see the testing section); daily-reset 2×/3× products skip fundamentals entirely. |
| **Return on peak principal** | Return % uses peak net deposits when both legs track them; a missing leg falls back to `cost − realized`, with the mixed basis shown beside the result. |
| **News needs an evidence graph** | Filings, issuer/exchange news, calendars, and headlines are deduplicated into expiring event IDs. A reliable, novel, negative event with price/volume or validated peer confirmation may drive defensive action. Positive surprise or accelerating attention can only join price-relative evidence in a capped add exploration; it cannot trade alone. |
| **Unproven signals get an exploration boundary** | A quant factor cannot claim validated authority until it clears prospective activation. While warming up, a pre-registered interaction can collect one capped tranche per ticker/policy; the ledger keeps that evidence grade distinct. |
| **Add authority needs two independent families** | Factor and peer residual count as one price-relative family, not two votes. Any two independent families — price-relative, point-in-time news surprise/attention, or a confirmed un-overheated 20-day breakout — authorise a capped exploration slice; validated tranches still require decision-usable evidence on both the price and the information side, so a price pattern can never promote a leveraged name. |
| **Published research numbers need two sources** | Long-form numbers carry a provenance manifest: exact Decimal arithmetic, two independent sources per figure, and a tolerance cap the manifest cannot raise for itself. A single-sourced or disagreeing figure blocks release of the artifact that quotes it. |
| **A thesis moves only on new evidence** | Assumptions, red lines and valuation anchors live in versioned JSON. A dimension may change only with evidence observed after the last check; a price move can reprice valuation but cannot touch business, moat or management; triggering *and* clearing a red line both need evidence. A missing baseline stays `unknown` instead of being reconstructed from prose. |
| **Earnings quality is computed, not asserted** | Cash conversion, working-capital gaps, dilution, SBC share and guidance outcomes are derived in code from at least four comparable periods. A basis or currency switch mid-history is an error, a missing input reads `unavailable` with a reason, and footnote claims require a primary issuer document. |
| **A new name passes a gate before a research run** | Information richness is graded separately from investment quality, so thin sourcing returns `gray_needs_evidence`, never a rejection. Four hard vetoes resolve before any check is tallied, their industry exceptions are encoded per sector rather than improvised, and quotes must come from the workspace pipelines. |

Reliability rides on the same principle. Every market-reporting job is **preflight (Python) → LLM → postflight (Python)**: the deterministic work runs in code, and a pre-push gate refuses to publish a book that doesn't reconcile. If risk can't be computed, the card says **"risk unavailable,"** never a green "none." Overlapping schedulers, a fallback workflow, and watchdogs mean a single LLM stall is no longer silent — though nothing here promises delivery under every outage.

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

## Under the hood

The package owns lifecycle, strategies, scheduling, watchdogs, context assembly,
validation and CLI; it does not reimplement an agent loop. `clawock doctor` and
`clawock context audit` name the capabilities a foreign workspace is missing
instead of pretending it is ready to run this live desk.

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

## Repository layout

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
