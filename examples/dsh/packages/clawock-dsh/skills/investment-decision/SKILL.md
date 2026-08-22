---
name: investment-decision
description: Run a clawock investment decision — read the prepared request, research with the host's own tools, write decision.json with evidence and an explicit bull/bear debate, and let Python validate and settle. Use when the user asks for an investment decision or a clawock run request is present.
---

# clawock investment-decision

You are the model side of a clawock decision run. DeepSeek Harness owns
conversation, memory and tools; clawock owns the decision contract. Your job
is one file in, one file out: read a request, research, write a decision, let
Python validate it. The model can never grade itself.

```
prepare ──► request.json ──► you: research + write decision.json ──► publish ──► receipt
(certified │                       (collect evidence,                │       (Python settles:
 context + │                        run the bull/bear debate,          │        evidence counts, debate
 gates)    │                        pick a bounded action)             │        links, money/FX to the cent)
           └───────────────────────────────────────────────────────────┘
```

## Prerequisites

`clawock` must be installed (Python ≥ 3.11):

```bash
python -m pip install clawock
```

If a workspace is not initialized yet, create it **with the workflow pinned** —
that flag is what turns `decision.json` into the enforced contract:

```bash
clawock init ./book --workflow investment-decision
clawock workflow install investment-decision --workspace ./book
```

The second command copies the readable contract (including
`references/decision-contract.md` and the JSON Schema) into
`./book/.agents/skills/investment-decision/` — a standard Agent Skill
location that DeepSeek Harness also discovers.

## The loop

### 1. Prepare

```bash
clawock run prepare --workspace ./book
```

Read the emitted request file (the `request_file` path printed on stdout,
e.g. `.clawock/work/<run_id>/request.json`). It contains:

- `task` — the decision contract (evidence, opposing case, bounded action,
  reconciled amounts)
- `context.documents` — the certified context, per-file sha256 fingerprints
  (anything you cite must come from here or from your own research, and must
  be observed no later than `as_of`)
- `workflow.parameters` — gates: `min_supporting_evidence`,
  `min_opposing_evidence`, `max_confidence_without_primary_source`

### 2. Research, then debate, then decide

Research with the host's normal tools (web search, file reads, the live
dashboard at <https://kcnyu.github.io/clawock/> as `source_class: market`
evidence). Collect **both** sides on purpose — the workflow has an opposing
minimum, and `publish` refuses a decision whose bear case is a strawman:

1. Gather supporting evidence (filings/financials → `primary`, reputable
   secondary analysis → `secondary`, market data → `market`).
2. Actively seek the strongest counterargument you can find or construct —
   a genuine bear case, not a token objection. Record it as `opposing`
   evidence.
3. State the thesis and its invalidation conditions **before** choosing an
   action.
4. If the action proposes an order, compute both money identities from the
   context (quantity × unit price; × FX) — never invent prices, FX or sizes.

Write `decision.json` at the workspace root — artifact paths are resolved
against the workspace root, not the request directory:

```json
{
  "schema_version": 1,
  "workflow": {"id": "investment-decision", "version": "1.1.0"},
  "decision_id": "example-2026-08-08",
  "as_of": "2026-08-08T08:00:00+00:00",
  "subject": {"ticker": "EXAMPLE", "market": "US", "currency": "USD"},
  "evidence": [
    {"id": "filing-growth", "stance": "supporting",
     "summary": "The latest filed revenue figure grew year over year.",
     "source": "issuer filing", "source_class": "primary",
     "observed_at": "2026-08-08T07:30:00+00:00"},
    {"id": "valuation-risk", "stance": "opposing",
     "summary": "The current market multiple is above its stated range.",
     "source": "market data snapshot", "source_class": "market",
     "observed_at": "2026-08-08T07:45:00+00:00"}
  ],
  "debate": {
    "bull_case": {"summary": "Filed growth supports continued monitoring.",
                  "evidence_ids": ["filing-growth"]},
    "bear_case": {"summary": "Valuation leaves insufficient margin of safety.",
                  "evidence_ids": ["valuation-risk"]}
  },
  "thesis": {
    "statement": "Momentum is constructive, but price does not compensate for valuation risk.",
    "confidence": 0.7,
    "invalidation_conditions": ["Filed growth reverses"]
  },
  "decision": {
    "action": "watch",
    "rationale": "The opposing valuation evidence blocks an entry.",
    "evidence_ids": ["filing-growth", "valuation-risk"],
    "order": null
  }
}
```

Rules that are enforced by `clawock run publish`, not by this file:

1. `debate.bull_case` and `debate.bear_case` are both required and each cites
   evidence; the bear case must cite opposing-stance evidence — publish
   refuses without it. Python checks that linkage, not sincerity: make the
   bear case a genuine counterargument, never a strawman — that honesty is
   your contract.
2. Every `evidence` row needs a `stance` (`supporting` | `opposing` |
   `context`), a `source_class` (`primary` | `secondary` | `market` |
   `agent`) and an `observed_at` no later than `as_of`.
3. All `evidence_ids` references must exist (decision and both debate cases);
   conclusions in `thesis.statement` and `decision.rationale` should be
   backed by cited evidence.
4. If you propose an order, the currency amounts must reconcile to the cent;
   let the numbers come out of the context, never invent them.
5. Confidence above `max_confidence_without_primary_source` requires a cited
   primary source.

The sibling files next to this SKILL.md carry the full contract:
`references/decision-contract.md` (with `assets/order.example.json`, an
order-carrying decision whose two money identities reconcile). Introspect
the exact artifact shape any time: `clawock workflow schema
investment-decision decision.json`.

### 3. Publish and report

```bash
clawock run publish \
  --workspace ./book \
  --request ./book/.clawock/work/<run_id>/request.json \
  --artifact decision.json=./book/decision.json
```

Report the receipt's `status` and `run_id`, and if `status` is `published`,
show the user a compact decision card:

```
Subject      EXAMPLE (US/USD)          decision_id example-2026-08-08
Bull         Filed growth supports continued monitoring.        [1 citing]
Bear         Valuation leaves insufficient margin of safety.    [1 citing]
Thesis       Momentum constructive, price does not compensate for risk.
Confidence   0.70  ·  Action watch  ·  Invalidation: filed growth reverses
Receipt      published  ·  run_id <run_id>  ·  certificate pinned
```

Never edit the receipt, never re-grade the decision, never "improve" the
artifact after publish — Python settles.

## Before publish: self-check

Run this checklist before invoking `publish` — Python re-checks all of it
anyway, but a clean first pass beats a rejected receipt:

- both `debate.bull_case` and `debate.bear_case` present, each citing
  existing `evidence_ids`, the bear case citing `opposing` rows
- every cited `evidence_id` exists; no duplicates
- every evidence row has `stance`, `source`, `source_class`, and
  `observed_at` no later than `as_of`
- one `primary` row is cited whenever `confidence` exceeds the cap
- an order (if any) satisfies `gross_amount_quote = quantity × unit_price`
  and `gross_amount_base = gross_amount_quote × fx_quote_to_base`, to the
  cent

## If publish rejects

The receipt lists `validation_issues` with `code` + `message`. Repair only
the named issue and retry against the **same** prepared request; re-run
`prepare` only if the context or workflow certificate changed.

| typical `code` | meaning | fix |
|---|---|---|
| `unknown_fields` / `missing_fields` | a field name is wrong or extra | align with the JSON example above; no `reasoning`, no `opposing_case` |
| `insufficient_supporting_evidence` / `insufficient_opposing_evidence` | gate minimums not met | add more evidence rows with that `stance` |
| `unsupported_bear_case` / `unsupported_bull_case` | debate case cites the wrong stance | point `bear_case` at `opposing` rows, `bull_case` at `supporting` rows |
| `missing_evidence_reference` | `evidence_ids` names an unknown row | only cite `id`s that exist in `evidence` |
| `gross_amount_mismatch` / `fx_amount_mismatch` | order arithmetic wrong | recompute `quantity × unit_price` and `× fx_quote_to_base` to the cent |
| `confidence_without_primary_source` | confidence above the cap, no primary cited | add a `primary` row and cite it in `decision.evidence_ids` |
| `future_evidence` | `observed_at` after `as_of` | backdate or fix timestamps |

## Where things land

| path | contents |
|---|---|
| `<workspace>/decision.json` | your artifact (read by publish) |
| `<workspace>/.clawock/work/<run_id>/request.json` | the certified request |
| `<workspace>/.clawock/runs/<run_id>/` | receipt + manifest (the settlement record) |

## Learn from outcomes

After the stated horizon, record price/FX outcome evidence and run
`clawock workflow evaluate investment-decision --decision ... --outcome ...`.
The result reconciles price and FX before assigning a basis-point score — it
is evidence for the next decision, not portfolio P&L.

## Record conversation verdicts

A conversation verdict (加仓/减仓/建仓/清仓/观望) is a decision — write it
to the shared decision-mind ledger, the same `memory/decisions.jsonl` the
daily OpenClaw brief writes to, so both sides can read it and the daily
settlement round-trips it:

```bash
clawock record \
  --subject 00100 --market HK --currency HKD \
  --action reject --confidence 0.65 --driven-by fundamental \
  --bull "营收 +159% YoY,入通/海外霸榜催化" \
  --bear "净利率 -2368%,资不抵债,z+2.8σ 反转" \
  --thesis "高增长救不了资不抵债,先活下来" \
  --invalidation "站回 340" --invalidation "缩量企稳" \
  --emotion averaging_down --note "浮亏 -40% 的摊本冲动被压过,忍住没加"
```

`--source` defaults to `conversation` for DSH; other harnesses pass their
own — OpenClaw `--source openclaw`, Claude Code `--source claude`, Codex
`--source codex`. One ledger, one record command, every harness calls it;
nobody edits `decisions.jsonl` directly.

Rules: the bear case and at least one observable invalidation condition are
mandatory (the command rejects weak records); be honest about emotion
pressure — `fomo`/`revenge`/`averaging_down` are the exact patterns this
ledger exists to surface. Full schema (in the repository, not in the npm
tarball):
<https://github.com/KCNyu/clawock/blob/master/docs/decision-mind-ledger.md>

## Learn more

Live proof on a real HK + US desk: <https://kcnyu.github.io/clawock/>
The same contract from other harnesses (OpenClaw skill, Claude Code
instruction, Codex AGENTS.md, pure CLI):
<https://github.com/KCNyu/clawock/tree/master/examples/dsh/packages/clawock-dsh>