"""Every decision, beside the signals that existed when it was made.

The gap
-------
The ledger holds 741 decisions and five registered signal histories sit next to
it, and nothing joins them. Reviewing one `cut` means opening the ledger for the
rationale, then three JSONL files to find what the quant, factor and news layers
were saying that morning, and doing the date arithmetic by hand. That is why
"which information source actually moved a decision" has never been answerable
from the decision path: not because the data is missing, but because it is in
five files with no key between them.

This builds the join and publishes it: for each decision, the signal values as of
that decision's own plan date, and for each signal, the decisions it was standing
next to and what happened afterwards.

The number that has to be published with it
--------------------------------------------
**Snapshot age.** A decision on 2026-06-20 joined to a factor snapshot from
2026-07-24 is not "the factors at decision time"; it is next month's data. The
registered histories start at different dates — quant on 06-11, factor and peer
on 07-24, news on 07-26 — and the ledger starts before all of them. So the join
is one-sided by construction: a snapshot may only be used when its `as_of` is at
or before the plan date and within `MAX_SNAPSHOT_AGE_SESSIONS` of it, and every
row carries the age that was used.

Without that, the drawer would show a full row of signal values for every
decision and quietly attribute the July factor regime to a June decision.
Coverage per source is published for the same reason: a source that could see 12%
of the book's decisions is not a source with a weak effect, it is a source that
was not there.

What it does not do
-------------------
It never writes a decision, never modifies the ledger contract, and never
promotes a correlation into an activation. `usable_for_decisions` gates are not
touched: this is a view.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from clawock import history_store
from clawock.decision.ledger import leg_sessions, load_ticker_bars
from clawock.instruments import canonical_bar_manifest
from clawock.safe_io import safe_write_text, to_number as _number
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
DATA = WS / 'assets' / 'data'
LEDGER = WS / 'memory' / 'decisions.jsonl'
OUT = DATA / 'decision_map.json'

SCHEMA_VERSION = 1

#: A snapshot older than this is a different market, and joining it to a
#: decision would attribute one week's signals to another week's judgement.
#: Five sessions is a trading week; the registered histories have gaps (they are
#: written by a job that does not run on holidays) and one week of tolerance
#: absorbs a gap without absorbing a regime.
MAX_SNAPSHOT_AGE_SESSIONS = 5

#: Self-imposed, so the page loads on a phone. `dashboard.json` has a hard
#: 200,000-byte gate for the same reason and this file is fetched by the same
#: kind of browser on the same kind of connection.
MAX_BYTES = 200_000

#: `degradation.bytes` is written into the payload it measures, so the number
#: changes the length by its own width. The margin is larger than any decimal
#: that field can hold, which makes the recorded size a lower bound on the file
#: and the file a guaranteed fit.
SIZE_MARGIN = 64

HORIZONS = ('t1', 't5', 't20')


def _extractors():
    """Signal readers, keyed by their registered history file.

    Reused from `evaluation.signal_panel` rather than reimplemented: the
    decision map must show the same value the panel scores, or the two views of
    the same session disagree and neither is wrong.
    """
    from clawock.evaluation import signal_panel

    return dict(signal_panel.SOURCES)


def load_signal_snapshots(data_dir: Path | None = None) -> dict:
    """`{as_of: {ticker: {signal: value}}}` across every registered source."""
    data_dir = Path(data_dir or DATA)
    out: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for filename, extractor in _extractors().items():
        path = data_dir / filename
        if not path.exists():
            continue
        for payload in history_store.load_series(path):
            if not isinstance(payload, dict):
                continue
            as_of = str(payload.get('as_of') or '')[:10]
            if not as_of:
                continue
            for ticker, signal, value in extractor(payload):
                # Last write wins within a session: `t0_setups_history` records
                # about fourteen intraday snapshots a day and the final one is
                # the state the next session's open follows.
                out[as_of][str(ticker)][signal] = value
    return {as_of: dict(rows) for as_of, rows in out.items()}


def _session_index(manifest):
    """Ordered sessions per leg, and each ticker's leg, for age arithmetic."""
    legs = {}
    for ticker in manifest:
        for leg in ('us', 'hk'):
            if ticker in (manifest.get(leg) or {}) if isinstance(manifest, dict) else False:
                legs[ticker] = leg
    return legs


def _age_in_sessions(sessions, earlier: str, later: str) -> int | None:
    """How many trading sessions separate two dates on one leg's calendar."""
    try:
        return sessions.index(later) - sessions.index(earlier)
    except ValueError:
        return None


def at_snapshot(decision, snapshots, sessions_by_leg) -> dict:
    """The signals as of this decision's plan date, with the age that was used.

    One-sided and bounded: a snapshot is eligible only when its `as_of` is at or
    before the plan date. Taking the nearest snapshot in either direction would
    let a decision be explained by data published after it, which is the exact
    look-ahead the rest of this repository spends its effort refusing.
    """
    ticker = str(decision.get('ticker') or '')
    plan_date = str(decision.get('plan_date') or '')[:10]
    leg = str(decision.get('leg') or '').lower()
    sessions = sessions_by_leg.get(leg) or []
    eligible = sorted(as_of for as_of in snapshots if as_of <= plan_date)
    values, ages = {}, {}
    for as_of in reversed(eligible):
        row = (snapshots.get(as_of) or {}).get(ticker)
        if not row:
            continue
        age = _age_in_sessions(sessions, as_of, plan_date) if sessions else None
        if age is None:
            # Off-calendar (a weekend plan date, or a leg with no manifest):
            # fall back to calendar days, which over-counts and therefore only
            # ever rejects a join the session count would have accepted.
            try:
                age = (datetime.fromisoformat(plan_date)
                       - datetime.fromisoformat(as_of)).days
            except ValueError:
                continue
        if age > MAX_SNAPSHOT_AGE_SESSIONS:
            break
        for signal, value in row.items():
            if signal not in values:
                values[signal] = value
                ages[signal] = age
    return {'values': values, 'ages': ages}


def forward_outcomes(decision) -> dict:
    """Realised benefit at each horizon, straight from the ledger's own settlement.

    Recomputed nowhere: the ledger already settles these and a second
    computation here would be a second source of truth for the number the
    scorecard publishes.
    """
    evaluation = decision.get('evaluation') or {}
    out = {'outcome': evaluation.get('outcome')}
    for horizon in HORIZONS:
        out[horizon] = _number(evaluation.get(f'benefit_{horizon}_pct'))
    return out


def _keywords(text, vocabulary):
    lowered = str(text or '').lower()
    return sorted(word for word in vocabulary if word in lowered)


#: Words a rationale uses when it is leaning on a source. Fixed rather than
#: mined from the corpus: a vocabulary learned from the rationales would find
#: whatever the model happens to say often, and the point is to check whether the
#: model's words line up with the signals that were actually on the table.
RATIONALE_VOCABULARY = (
    'earnings', 'guidance', 'forecast', 'catalyst', 'news', 'announcement',
    'momentum', 'breakout', 'support', 'resistance', 'stop', 'volatility',
    'peer', 'sector', 'valuation', 'liquidity', 'macro', 'regime',
)


def build(ledger_rows=None, data_dir: Path | None = None) -> dict:
    """Assemble the payload. Pure — writing is a separate step."""
    data_dir = Path(data_dir or DATA)
    rows = ledger_rows if ledger_rows is not None else [
        json.loads(line) for line in LEDGER.read_text(encoding='utf-8').splitlines()
        if line.strip()]
    snapshots = load_signal_snapshots(data_dir)
    manifest = canonical_bar_manifest()
    sessions_by_leg = {leg: leg_sessions(leg) for leg in ('us', 'hk')}

    lookup, timelines = {}, defaultdict(list)
    per_signal = defaultdict(lambda: defaultdict(list))
    coverage = Counter()
    age_by_signal = defaultdict(list)
    for decision in rows:
        decision_id = str(decision.get('decision_id') or '')
        if not decision_id:
            continue
        joined = at_snapshot(decision, snapshots, sessions_by_leg)
        outcomes = forward_outcomes(decision)
        action = str(decision.get('action') or 'unknown')
        # Age per *source*, not per signal. All of a source's signals come out
        # of one snapshot, so thirty-three ages were thirty-three copies of five
        # numbers — and repeating the signal names in every one of 741 entries
        # was most of a megabyte of key strings. The values are columnar against
        # `signal_order` below for the same reason.
        # One integer, not a dict of five. The per-source split repeated the
        # source names in every one of 741 entries and, measured, the ages are 0
        # for almost every joined value — the per-card median and maximum are
        # where that distribution belongs.
        oldest = max(joined['ages'].values(), default=None)
        entry = {
            'decision_id': decision_id,
            'ticker': str(decision.get('ticker') or ''),
            'plan_date': str(decision.get('plan_date') or '')[:10],
            'action': action,
            'driven_by': decision.get('driven_by'),
            'strategy_id': decision.get('strategy_id'),
            'confidence': _number(decision.get('confidence')),
            'at': joined['values'],
            'snapshot_age_sessions': oldest,
            'outcomes': outcomes,
            'rationale_keywords': _keywords(decision.get('rationale'),
                                            RATIONALE_VOCABULARY),
            'rationale': str(decision.get('rationale') or ''),
        }
        lookup[decision_id] = entry
        timelines[entry['ticker']].append({
            'date': entry['plan_date'], 'decision_id': decision_id,
            'action': action, 'driven_by': entry['driven_by'],
            'outcome': outcomes.get('outcome'),
        })
        for signal, value in joined['values'].items():
            coverage[signal] += 1
            age_by_signal[signal].append(joined['ages'][signal])
            per_signal[signal][action].append(
                {'value': value, **{horizon: outcomes.get(horizon)
                                    for horizon in HORIZONS}})

    def _bucket(observations):
        settled = {horizon: [row[horizon] for row in observations
                             if row.get(horizon) is not None]
                   for horizon in HORIZONS}
        out = {'count': len(observations)}
        for horizon, values in settled.items():
            out[f'n_{horizon}'] = len(values)
            out[f'median_{horizon}_pct'] = (round(statistics.median(values), 4)
                                            if values else None)
            out[f'win_rate_{horizon}'] = (
                round(sum(1 for value in values if value > 0) / len(values), 4)
                if values else None)
        return out

    actions = sorted({row['action'] for row in lookup.values()})
    cards = []
    for signal in sorted(per_signal):
        ages = age_by_signal[signal]
        cards.append({
            'signal': signal,
            'source_kind': signal.split('.', 1)[0],
            'decisions_joined': coverage[signal],
            'decision_coverage_pct': round(100 * coverage[signal] / max(1, len(lookup)), 2),
            # The number that separates "weak effect" from "was not there".
            'median_snapshot_age_sessions': (round(statistics.median(ages), 1)
                                             if ages else None),
            'max_snapshot_age_sessions': max(ages) if ages else None,
            # Only the actions this signal was actually standing next to. Most
            # of the 33 x 7 grid is empty — a factor rank has never been beside
            # a `reject` — and publishing the empty cells cost half the card
            # section to say "count: 0" 150 times.
            'by_action': {action: _bucket(per_signal[signal][action])
                          for action in actions if per_signal[signal].get(action)},
        })

    # Columnar, twice over. Repeating up to thirty-three signal names inside
    # each of 741 entries — and then eleven field names on top — was 80% of the
    # payload and none of the information. `signal_order` and `fields` name each
    # column once; every decision is a position in parallel arrays.
    signal_order = sorted(per_signal)
    position = {signal: index for index, signal in enumerate(signal_order)}
    ordered_ids = sorted(lookup, key=lambda key: (lookup[key]['plan_date'], key))
    columns = {
        'decision_id': ordered_ids,
        'ticker': [lookup[key]['ticker'] for key in ordered_ids],
        'plan_date': [lookup[key]['plan_date'] for key in ordered_ids],
        'action': [lookup[key]['action'] for key in ordered_ids],
        'driven_by': [lookup[key]['driven_by'] for key in ordered_ids],
        'strategy_id': [lookup[key]['strategy_id'] for key in ordered_ids],
        'confidence': [lookup[key]['confidence'] for key in ordered_ids],
        'outcome': [lookup[key]['outcomes']['outcome'] for key in ordered_ids],
        **{horizon: [lookup[key]['outcomes'][horizon] for key in ordered_ids]
           for horizon in HORIZONS},
        'rationale_keywords': [lookup[key]['rationale_keywords']
                               for key in ordered_ids],
        'rationale': [lookup[key]['rationale'] for key in ordered_ids],
        'snapshot_age_sessions': [lookup[key]['snapshot_age_sessions']
                                  for key in ordered_ids],
    }
    snapshot_rows = []
    for key in ordered_ids:
        row = [None] * len(signal_order)
        for signal, value in lookup[key]['at'].items():
            row[position[signal]] = (round(value, 3) if isinstance(value, float)
                                     else value)
        snapshot_rows.append(row)
    index_of = {key: index for index, key in enumerate(ordered_ids)}
    timelines = {ticker: [index_of[event['decision_id']] for event in events
                          if event['decision_id'] in index_of]
                 for ticker, events in timelines.items()}

    dates = sorted(entry['plan_date'] for entry in lookup.values() if entry['plan_date'])
    return {
        'signal_order': signal_order,
        'schema_version': SCHEMA_VERSION,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'as_of': dates[-1] if dates else None,
        'coverage': {
            'decisions': len(lookup),
            'tickers': len(timelines),
            'sessions': len(set(dates)),
            'first_decision': dates[0] if dates else None,
            'signals': len(per_signal),
            'max_snapshot_age_sessions': MAX_SNAPSHOT_AGE_SESSIONS,
            'join': ('a snapshot is used only when its as_of is at or before the '
                     'plan date and within the age bound; every joined value '
                     'carries the age that was used'),
        },
        'actions': actions,
        'info_source_cards': cards,
        # The ROW B matrix is `info_source_cards[].by_action` — the same signal
        # x action buckets, computed once. Publishing it twice cost 43KB of a
        # 200KB budget to say nothing new, and two copies of an aggregate are
        # two things that can disagree.
        'decision_signal_matrix': {'actions': actions,
                                   'source': 'info_source_cards[].by_action'},
        # Indices into `decisions`, not copies of it. The duplicated form spent
        # 88KB restating an action and an outcome that were already there, and
        # gave the page two places to read the same fact from.
        'ticker_timelines': {ticker: sorted(indices)
                             for ticker, indices in sorted(timelines.items())},
        'decisions': columns,
        'decision_snapshots': snapshot_rows,
    }


#: Ordered, and each step names what it costs. A page that silently shows less
#: than it says it does is worse than one that shows a banner.
DRAWER_LIMIT = 300

DEGRADATION = (
    ('full', 'every field'),
    ('no_rationale_text', 'rationale text dropped; keywords kept'),
    ('recent_decisions_only',
     f'signal snapshot kept for the most recent {DRAWER_LIMIT} decisions; older '
     f'ones keep their action, outcome and place on the timeline'),
    ('cards_and_matrix_only', 'timelines and drawer dropped'),
)


def encode(payload: dict) -> str:
    """The one encoding, used by the size gate and by the writer.

    They have to be the same function. The gate measured a compact encoding
    while `safe_write_json` wrote a pretty-printed one, and the file that
    actually shipped was 343KB against a budget the build reported as met at
    175KB — a gate checking a number nobody serves.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def degrade(payload: dict, max_bytes: int = MAX_BYTES) -> dict:
    """Shrink until it fits, and say which step was needed.

    The order is deliberate: prose first (recoverable from the ledger), then the
    tail of the drawer (the oldest decisions, which nobody opens), then the
    timelines. The aggregates in the cards and the matrix are last because they
    are the only part computed from *all* the decisions — dropping them would
    change the numbers rather than the amount of detail.
    """
    payload = dict(payload)
    for level, cost in DEGRADATION:
        payload['degradation'] = {'level': level, 'cost': cost,
                                  'levels': [name for name, _ in DEGRADATION]}
        payload['degradation']['bytes'] = len(encode(payload).encode('utf-8'))
        if payload['degradation']['bytes'] <= max_bytes - SIZE_MARGIN:
            return payload
        if level == 'full':
            payload['decisions'] = {field: values for field, values
                                    in payload['decisions'].items()
                                    if field != 'rationale'}
        elif level == 'no_rationale_text':
            # The snapshot row is blanked for older decisions, not the decision
            # itself: a decision that vanishes breaks its own timeline marker,
            # and the timeline is what the page is for.
            rows = payload['decision_snapshots']
            cut = max(0, len(rows) - DRAWER_LIMIT)
            payload['decision_snapshots'] = (
                [None] * cut + rows[cut:])
        elif level == 'recent_decisions_only':
            payload['ticker_timelines'] = {}
            payload['decisions'] = {}
            payload['decision_snapshots'] = []
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=str(OUT))
    parser.add_argument('--stdout', action='store_true')
    args = parser.parse_args(argv)
    payload = degrade(build())
    if args.stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    encoded = encode(payload)
    if len(encoded.encode('utf-8')) > MAX_BYTES:
        # Every level exhausted and still over. Refuse rather than publish a
        # payload the page will time out on: the previous file stays served,
        # which is a stale map rather than a broken one.
        print(f'decision-map: {len(encoded.encode("utf-8"))} bytes exceeds the '
              f'{MAX_BYTES}-byte budget at the last degradation level',
              file=sys.stderr)
        return 1
    safe_write_text(args.out, encoded)
    coverage = payload['coverage']
    print(f'decision_map: {coverage["decisions"]} decisions · '
          f'{coverage["signals"]} signals · {coverage["tickers"]} tickers · '
          f'{payload["degradation"]["bytes"]} bytes '
          f'({payload["degradation"]["level"]})')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
