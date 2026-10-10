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

## Proposals and the three checks

A plan decision is a proposal. It is checked in three channels
(`decision/receipts.py`), and each finding carries a code from its own channel.

| Channel | Codes | Question | Effect |
|---|---|---|---|
| fact | `FACT_*` | Is the artifact true? A cited event, setup or receipt that does not exist; a price nobody observed; a receipt computed after the plan date. | refuses the plan |
| feasibility and authorisation | `FEAS_*`, `AUTH_*` | Can it be done as written? Cash, inventory, board lots, an add already open, an obligation in force, an authorisation not given. | refuses the action |
| strategy | `STRAT_*` | Would the registered policy have done it? | recorded as an objection; never refuses |

`packet.review_plan` returns every finding. `validate_plan_constraints` is its
blocking subset. `bind_policy_review` stamps the strategy channel onto each
decision as `policy_review` (`agrees_with_policy`, `objections[]`, and a pending
`authorization` where one applies). The proposal is filed as written. The page
and the card print the departure beside the call under 「与登记策略不同」.

### What a row opens

Each ticker row carries two lists.

| Field | Meaning |
|---|---|
| `constraints.open_actions` | actions a plan may write. Bounded by obligations, existing authorisations and feasibility |
| `constraints.closed_actions` | for each closed action: channel, code and reason |
| `constraints.allowed_actions` | actions the registered policy would take. Writing an open action outside this list is a strategy objection |

What closes an action:

| Code | Condition |
|---|---|
| `AUTH_OBLIGATION_IN_FORCE` | a hard stop or regime de-lever is forced on the name; only its actions are open |
| `AUTH_ADD_FROZEN_BY_BREACH` | any risk breach is open on the name: adds and T trades are closed |
| `AUTH_LEVERAGED_ADD` | a daily-reset leveraged product without validated evidence |
| `AUTH_EXCEEDS_ROOM` | an add larger than `position_room_shares` (cash and the single-name cap) |
| `AUTH_NO_SWAP_MANDATE` | a buy labelled `risk_rule` on a name no breach prescribes |
| `FEAS_ADD_ALREADY_OPEN`, `FEAS_BOARD_LOT_UNKNOWN`, `FEAS_PRICE_MISSING`, `FEAS_NO_ROOM`, `FEAS_NOTHING_TO_SELL` | the order cannot be formed |
| `FEAS_EXCEEDS_CASH` | the adds of one leg together exceed that leg's cash |

The packet carries the set as `authorization`: each rule's code, what it
binds, the parameter it reads, the current caps and a `version` hashed from all
of them. Every reviewed decision records `policy_review.authorization_version`,
so changing a cap or a rule is a visible change of version.

The authorisations above are the ones that existed before this split. None was
added, loosened or removed by it: the split changed which channel a rule
reports in, and stopped registered strategy rules from refusing.

What is now an objection instead of a refusal: an entry that matches no
registered setup, or differs from the one it names; a size above the policy's
tranche; a discretionary sell with no escalated event; an active call without a
catalyst, setup or risk rule; a catalyst call citing a real event the
news-evidence policy did not escalate; a judgment that nominates a candidate
the add policy did not.

### Names the book does not hold

| Section | Who is in it | What can be written |
|---|---|---|
| `swap_targets` | the target of a hard-stop or regime swap | the paired buy leg of that mandate |
| `proposal_universe` | every unheld name with stored daily bars no older than 7 days | `watch`, or `add_only_on_trigger` as a proposal |

A proposal on an unheld name is priced at the stated close or quote, sized in
whole shares or board lots, and held to the leg's cash. Its review carries
`authorization: entry_gate_required`: it is an evaluable proposal, not an
order. A name without stored bars cannot be settled and cannot be a decision.

### Proposal fields

Model-owned, optional, normalised by `ledger.normalize_proposal`.

| Field | Content |
|---|---|
| `hypothesis` | what the model believes and why it matters now |
| `method` | how it got there, in free text; not a menu |
| `forecast` | `{event, probability, horizon_sessions}`: a statement that can be scored |
| `alternatives` | options weighed and not chosen, holding included |
| `tool_receipts` | ids of `compute` receipts the decision stands on |

An add that names no registered setup must state `hypothesis` and
`invalidation_price`. A cited receipt must exist, replay, and stand at a session
no later than the plan date (`brief_postflight.tool_receipt_issues`).
`simulated_entry_price`, when given, must be the packet's price for the name or
the plan's own trigger.

## Fixed parameters in policy configuration

Eight strategy-related config files hold 127 numeric leaves (thresholds,
weights, sizes, windows), not counting `schema_version` and the leverage multiple
of an instrument, which is product metadata. They parameterise the registered
rules. They are not facts about the market. A registered rule's output reaches a decision as an
objection (see above), not as a refusal.

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
