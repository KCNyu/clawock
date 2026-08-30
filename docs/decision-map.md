# Decision Map

**What it is.** One page that puts 741 decisions and the five registered signal
histories on the same table: for each decision, the signal values as of that
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
weak effect — it is a source that was not there**. Measured on 2026-08-30, no
registered source can see more than 42% of the decisions and most see 11–20%,
because the ledger starts on 2026-05-17 and the histories start later (quant
06-11, factor and peer 07-24, news 07-26).

### Snapshot age

The join is one-sided and bounded: a snapshot is used only when its `as_of` is
at or before the plan date and within `MAX_SNAPSHOT_AGE_SESSIONS` (5) of it.
Without that, the drawer would show a full row of values for every decision and
quietly attribute July's factor regime to a June judgement. Every card publishes
the median and maximum age it actually used; on the live data the median is 0 —
when the join fires, it fires on the same session.

## The payload

`assets/data/decision_map.json`, schema 1, written by `clawock decision-map`.

**Columnar, twice over.** Repeating up to 33 signal names inside each of 741
entries — and then 11 field names on top — was 80% of the payload and none of
the information. `signal_order` and the `decisions` field names name each column
once; every decision is a position in parallel arrays, and
`decision_snapshots[i]` is the signal row for `decisions.decision_id[i]`.

**Degradation.** The budget is 200,000 bytes, self-imposed so the page loads on a
phone — the same reason `dashboard.json` has a hard gate at that number. The
chain drops prose first (recoverable from the ledger), then the *signal row* of
older decisions (not the decisions themselves, which would break their own
timeline markers), then the timelines. The aggregates are last because they are
the only part computed from all 741 decisions: dropping them would change the
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
`clawock.publish.outputs` owns a four-file write set that is swapped in
atomically; a fifth file whose failure is survivable does not belong inside a
contract whose whole point is that all four land or none do. The map is a
read-only view — a broken one costs a page, not a number — so its return code is
recorded and never gates the publish. This is a deliberate deviation from the
PRD (#1191), which asked for it to be part of `dashboard-build`.
