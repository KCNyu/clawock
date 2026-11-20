# Session recap and risk follow-ups

Report and intraday cards include **盘前至本档**. The brief carries the open
risk review queue and market cards carry newly seen or changed entries in
**风险待复查**. The market views are bound to the preflight generation and the
watchdog can carry them in its data fallback. Review visibility is separate
from today's orders and from acknowledgement in the risk ledger.

## Recap from the current plan version

`decision/session_review.build` reads `memory/<session-date>-plan.json`,
`memory/decisions.jsonl`, and `memory/.tmp/intraday-delivered-state-<market>.json`.
HK uses the HKT date; US uses the ET date. A US close after HKT midnight still
reads the preceding HKT day's plan. No nearest-date fallback is allowed.

- The plan date must match the session and its decision ids must be present and
  unique. The context retains the source path and exact SHA256. A revised plan
  becomes the new comparison baseline; this is not an immutable record of the
  first morning message or a price-return comparison.
- Execution comes only from the decision ledger. Matching requires id, plan date,
  ticker, leg, action, condition and size. Authored execution in the plan is ignored.
  Active actions are counted separately from hold/watch. Missing, mismatched or
  unreadable execution is unknown, never an unfilled order or proof of a trade.
- Current hits reuse the existing plan-trigger evaluator. Only conditions present
  in this session's plan and quotes verified as refreshed count. A hit is not a
  fill; an absent hit does not prove the condition never fired earlier today.
- Previously delivered signals require a matching session and non-future slot.
  The existing seen set supplies historical observations, not current risk state.
  Missing/wrong-session records are unavailable, not a claim of no signals.

The structured view holds at most 12 rows per collection and explicit omitted
counts; aggregate counts cover all plan decisions. Cards show at most three names
per detail line. This is a compact progress recap, not a full trade or news timeline.
Hold and watch counts stay in context and are omitted from the card.

## Review the existing risk ledger

`decision/risk.followups` reads `memory/risk_breaches.json`. Every unresolved record
on the selected leg remains visible; acknowledgement does not imply risk resolution.
It orders records by the following review categories:

| Category | Evidence | What to review |
|---|---|---|
| Due | expired/invalid override, existing must-reissue flag, or reached adaptive forced date | reassess the risk and its disposition |
| Verify | execution evidence/confirmation while the breach remains open, or missing adaptive review date | check the evidence and detector result |
| Undecided | no recorded acknowledgement, override or execution | record a disposition through the existing workflow |
| Scheduled | a valid active override or a future adaptive forced date | revisit at the existing deadline |
| Watch | acknowledged but still unresolved | monitor for risk resolution |

An active override is validated with the existing `override_is_active` policy at
read time, rather than trusting its cached status. Adaptive forced dates use the
ledger's UTC calendar date. These are deadlines already in the ledger, not new
policy thresholds. Acknowledgement/confirmation/override still use their existing
commands and evidence rules. This projection never performs those writes.

The view retains ledger update time and per-record last observation time.
Missing or corrupt ledger data is identified as unavailable. The daily brief
shows the unresolved queue once. The report and intraday paths compare each
breach with its last delivered state in `memory/.tmp/risk-card-notices.json`.
New or reopened breaches, severity changes, crossing the existing 10-day
undecided threshold, acknowledgements, reassessment requests and deadline
transitions can surface again. Age alone does not count as a change. Market
cards show up to three changes. Additional changes stay eligible until a card
actually carries them.

Primary delivery or a successful watchdog send advances the receipt for the
rows sent. The brief also advances it. The review lookup and the receipt
store leave the risk ledger itself alone.

```bash
clawock risk followups --leg HK
clawock risk followups --leg US --json
```

The CLI shows up to 100 items (with any omitted count). `TOOLS.md` routes interactive
review requests here. Full records remain in `clawock risk list` and the existing
ledger. These review items are separate from **待你处理** orders and **欠着的账**
unacknowledged breaches; they deliberately include acknowledged/overridden risks
whose next review would otherwise be easy to miss.
