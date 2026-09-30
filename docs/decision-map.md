# Decision Map

**What it is.** One board — the Decision Map card in the dashboard's Reflect view (the old `/decimap/` page now redirects there) — that puts the decision ledger and the six registered signal
histories (`clawock.evaluation.signal_panel.SOURCES`) on the same table: for each decision, the signal values as of that
decision's own plan date; for each signal, the decisions it was standing next to
and what happened afterwards.

**What it is not.** It writes no decision, changes no ledger contract, and
promotes no correlation into an activation. `usable_for_decisions` gates are
untouched. A signal appearing next to `cut` may have caused the cut, or may
simply have been on the table that day; the page says so where it shows the
matrix.

## Reading it

### Coverage is the first number, not the last

A source that could see 12% of the book's decisions is **not a source with a
weak effect — it is a source that was not there**. The ledger starts on
2026-05-17 and most histories start later: setup (`t0_setups`) 05-16, quant
06-11, factor, bar and peer 07-24, news 07-26. Measured on 2026-09-30 over 953
decisions, `setup.range_pos` sees 89.5% of them because its history is the only
one older than the ledger; every other source sees at most 47% (quant and peer),
and bar, factor and news about 30% — some single signals under 20%.

### Snapshot age

The join is one-sided and bounded: a snapshot is used only when its `as_of` is
strictly before the plan date and within `MAX_SNAPSHOT_AGE_SESSIONS` (5) of it.
Without that, the drawer would show a full row of values for every decision and
quietly attribute July's factor regime to a June judgement. A same-day snapshot
is excluded too: it carries that session's close, which a plan written at 08:00
HKT could not see (#1911). Every card publishes the median and maximum age it
actually used; on the live data (2026-09-30) the median is 1 on every card — the
joined values are the previous session's, the latest a pre-open plan could read.

## The payload

`assets/data/decision_map.json`, schema 2 (`SCHEMA_VERSION`), written by `clawock decision-map`.

**Columnar, twice over.** When this shipped (741 decisions, 33 signals, 11
fields), repeating every signal name inside each entry — and then the field
names on top — was 80% of the payload and none of
the information. `signal_order` and the `decisions` field names name each column
once; every decision is a position in parallel arrays, and
`decision_snapshots[i]` is the signal row for `decisions.decision_id[i]`.

**Degradation.** The budget is 200,000 bytes, self-imposed so the page loads on a
phone — the same reason `dashboard.json` has a hard gate at that number. The
chain drops prose first (recoverable from the ledger), then the *signal row* of
older decisions (not the decisions themselves, which would break their own
timeline markers), then the timelines. The aggregates are last because they are
the only part computed from every decision: dropping them would change the
numbers rather than the amount of detail. The level in force is always printed
in the page's status bar — a page that silently shows less than it says it does
is worse than one that shows a banner.

Measured on 2026-08-30: 175,135 bytes at `recent_decisions_only` — every
decision's metadata and timeline, with the signal snapshot kept for the most
recent 300.

## Where it runs

`clawock decision-map` runs immediately after `dashboard-build` in
`_harness_common`, on the same cadence, and `brief_postflight` stages the output.

It is deliberately **not** part of the dashboard's generation.
`clawock.publish.outputs` owns a five-file write set that is swapped in
atomically; a sixth file whose failure is survivable does not belong inside a
contract whose whole point is that all five land or none do. The map is a
read-only view — a broken one costs a page, not a number — so its return code is
recorded and never gates the publish. This is a deliberate deviation from the
PRD (#1191), which asked for it to be part of `dashboard-build`.

---

Since #1420 the map lives in the dashboard's Reflect view rather than as a
separate page. Its tests are `tests/test_decision_map.py` and
`tests/decimap_board.spec.js`.
