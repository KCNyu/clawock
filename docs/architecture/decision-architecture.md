# Decision architecture: observations, proposals, evaluation

How a decision is produced and who owns each part of it. The split:

| Part | Owner | What it is |
|---|---|---|
| Observations | code | dated, sourced measurements and records: quotes, bars, filings, plan rows, trades |
| Computation | code, on the model's request | a formula the model chose, executed on stored data, returned with a receipt |
| Rule outputs | registered rules | screens, scores, grades and candidate states: one registered opinion about the observations |
| Hypothesis and trade-off | model | what matters, why, what would disprove it, and what to do |
| Accounting | code | cash, inventory, board lots, executions, settlement |

A rule output is a true record of what a rule concluded and an arguable reading
of the market. It is shown to the model as an opinion. It is not grounds for
withholding the observation underneath it.

## Observations and rule outputs

The model's inputs carry both kinds of statement, and each surface says which is
which.

- Brief packet: `judgment_contract.rule_outputs` lists, per section of a ticker
  row, the fields that are a rule's conclusion (`technical.tag`, `setups`, the
  factor composite, `add_authority`, `status.label`, …). The rest of a row is a
  measurement or a record.
- Intraday context: `context/intraday_layers.py` classifies every field as
  `observation`, `policy`, `mixed` or `control` (`field_semantics`). The core
  packet's `index.rule_outputs` names the `policy` and `mixed` fields present in
  the slot.

A validation flag such as `activation.usable_for_decisions=false` describes the
registered composite or rule: its forward validation has not passed. It does not
describe the measurements the composite was built from. The brief may use a
verified measurement; when it cites an unvalidated composite or an inactive rule
it says so in the same sentence.

## Tools

Both are reached through `clawock tool <name> --arg key=value`.

### `observations`

`--arg ticker=<T> --arg kind=bars|factors|events`

| Kind | Returns | Source |
|---|---|---|
| `bars` | stored daily OHLC with session, source, adjustment and fetch time; `n` sessions (default 20, max 120), optional `as_of` | `memory/bars/<T>.json`; any registry ticker, held or not |
| `factors` | every measured factor value under `measurements`; composite, ranks, weights and validation state under `policy_opinion` | `assets/data/cross_sectional_factor.json` |
| `events` | every recorded event for the ticker, escalated or not; each split into `observed` and `policy_opinion` (reliability score, direction, novelty, escalation) | `assets/data/news_evidence_graph.json` |

An empty `events` result says so in `missing`: no recorded event is not the same
as no news.

### `compute`

`--arg 'expression=…' [--arg as_of=YYYY-MM-DD] [--arg unit=…]`

Runs an expression the model wrote on the stored daily bars. The model chooses
the series, the window, the comparison and the formula.

- Series: `close("T")`, `open("T")`, `high("T")`, `low("T")`. Series combine
  with `+ - * /`, aligned on shared sessions.
- Reducers: `last`, `lag`, `sma`, `ema`, `highest`, `lowest`, `ret`, `vol`,
  `zscore`, `drawdown`, `rsi`, `beta`, `corr`; per ticker: `atr`, `atr_pct`,
  `range_pos`; scalars: `abs`, `min`, `max`.
- The expression must reduce to one number.

The language is a whitelist over Python's expression grammar, parsed and walked
by `market_data/compute.py`. It has no names, attributes, subscripts or imports
and is never passed to the interpreter.

Each result is a receipt:

| Field | Meaning |
|---|---|
| `receipt_id` | hash of the expression, the cut, the inputs and the value |
| `as_of` | the session the value stands at; nothing later was read |
| `value` / `value_pct` / `value_pp` / `value_multiple` / `value_sigma` | the number, under a key that names its unit |
| `inputs[]` | per ticker: fields read, first and last session, count, source, adjustment, hash of the bars |

`compute.verify(receipt)` recomputes at the same cut and compares the value, the
input hash and the id. Bars are append-only, so a mismatch means stored history
was repaired afterwards or the receipt was not produced by this tool.

A receipt proves that the inputs existed, that nothing after `as_of` was read
and that the arithmetic replays. It does not prove the hypothesis the feature
was computed for.

Receipts are written to `memory/.tmp/compute-receipts/`. Each postflight adds
the receipts computed since its context was generated to the sources of its
numeric gate (`validation.with_compute_receipts`), so prose may quote a computed
value.

Limits are a service contract, not a trading rule: 400 characters, 80 syntax
nodes, windows of 1–400 sessions. The store starts in 2025-12 and holds no
volume; a window longer than the history is refused with `insufficient history`.

## Fixed parameters in policy configuration

Eight strategy-related config files hold 127 numeric leaves (thresholds,
weights, sizes, windows), not counting `schema_version` and the leverage multiple
of an instrument, which is product metadata. They parameterise the registered
rules. They are not facts about the market.

| Config | Leaves | Role |
|---|---:|---|
| `factor-universe.json` | 17 | weights and activation checks of the registered factor composite |
| `add-alpha-policy.json` | 32 | evidence sufficiency, ranking, confirmation, tranche sizes of the registered add rule |
| `news-evidence-policy.json` | 49 | event gates, overlay parameters, expiry windows, source reliability scores |
| `peer-residual-rules.json` | 10 | activation and direction of the three peer rules |
| `left-side-policy.json` | 6 | the registered left-side ladder (observe mode) |
| `intraday-strategy-policies.json` | 2 | the two P0 escalation thresholds |
| `research-governance.json` | 4 | review windows and staleness |
| `stock-discovery.json` | 7 | screen thresholds and queue limits |
