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

WS = workspace_root()
DATA = WS / 'assets' / 'data'
LEDGER = WS / 'memory' / 'decisions.jsonl'
OUT = DATA / 'decision_map.json'

#: 2 adds `kpi` and `signal_panel` (#1194). Bumped rather than left alone
#: because the payload gained blocks the page now reads unconditionally: a
#: checkout carrying a version-1 file next to version-2 code is a stale artifact,
#: and the published-payload test says so instead of skipping quietly.
SCHEMA_VERSION = 2

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

#: Columns whose values come from a small vocabulary and were published as 741
#: copies of a dozen strings. Measured on the live ledger: `strategy_id` 12.1KB,
#: `action` 10.3KB for seven distinct words, `plan_date` 9.6KB for 73 dates,
#: `driven_by` 8.6KB, `outcome` 5.6KB, `ticker` 5.5KB for eighteen names — 51KB
#: of a 200KB budget spent on repetition. Each becomes a vocabulary published
#: once plus a column of integers into it, which is the same argument
#: `signal_order` already makes one level up.
CODED_COLUMNS = ('ticker', 'plan_date', 'action', 'driven_by', 'strategy_id',
                 'outcome')

#: What a card shows from the panel. Copied verbatim — a rounding here would be
#: a third version of the number, differing from the panel in the last digit for
#: no reason a reader could discover.
PANEL_FIELDS = ('mean_ic', 'ic_cluster_ci95', 'n_observations', 'n_sessions',
                'status', 'ic_clears_zero')


def _code(values) -> tuple[list, list[int]]:
    """(vocabulary, indices). Order of first appearance, so it is stable."""
    vocabulary, position, out = [], {}, []
    for value in values:
        key = (type(value).__name__, value)
        if key not in position:
            position[key] = len(vocabulary)
            vocabulary.append(value)
        out.append(position[key])
    return vocabulary, out


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



def panel_scores(data_dir: Path | None = None, evaluation: dict | None = None) -> dict:
    r"""IC, its interval and the selection PBO — read from `signal_panel`.

    Computing them here would give the site a second implementation of the same
    number, and two implementations of one number are two things that can
    disagree: the panel would report a signal's t5 IC as +0.19 while the card
    beside the decisions it stood next to said +0.17, and nobody could say which
    was wrong. `evaluation.signal_panel.evaluate` is the only place in this
    repository a rank IC is computed. This republishes the fields the cards
    render, unrounded and unrecomputed — `grep -rn 'spearman\|rank_ic'` over
    this module is empty by construction, and a test keeps it that way.

    The cost is about thirty seconds inside the dashboard publish — twenty for
    the panel and roughly seven more since the refuters joined it (#1167) —
    which is the price of the numbers being the same numbers. `evaluation` is
    injectable so a test does not pay it twice.
    """
    from clawock.evaluation import signal_panel

    if evaluation is None:
        evaluation = signal_panel.evaluate_cached(signal_panel.build_panel(
            Path(data_dir or DATA)))
    coverage = evaluation['coverage']
    by_signal = {
        signal: {horizon: {field: sections[horizon][field] for field in PANEL_FIELDS}
                 for horizon in HORIZONS}
        for signal, sections in evaluation['signals'].items()
    }
    selection = {
        horizon: {field: evaluation['selection'][horizon].get(field)
                  for field in ('status', 'pbo', 'n_splits')}
        for horizon in HORIZONS
    }
    return {
        'as_of': coverage['last_session'],
        'first_session': coverage['first_session'],
        'sessions': coverage['sessions'],
        'rows': coverage['rows'],
        'selection': selection,
        # Counts, not the per-signal p-values: thirty-three signals times three
        # horizons of placebo detail is a payload this page cannot afford, and
        # the reader's first question is how many of them survive being
        # shuffled. `clawock signal-panel --json` has the rest.
        'refutation': evaluation['refutation_summary'],
        'by_signal': by_signal,
        'method': evaluation['method'],
        'interval_caveat': evaluation['interval_caveat'],
        'source': 'clawock signal-panel (evaluation.signal_panel.evaluate)',
    }


def build(ledger_rows=None, data_dir: Path | None = None,
          panel: dict | None = None) -> dict:
    """Assemble the payload. Pure — writing is a separate step."""
    data_dir = Path(data_dir or DATA)
    panel = panel if panel is not None else panel_scores(data_dir)
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
    # Per *kind*, keyed by decision so one decision that joined three of a
    # kind's signals counts once. Summing the signal rows in the browser would
    # count it three times, and the roll-up would claim a coverage the kind
    # does not have — which is the one number this page exists to keep honest.
    per_kind = defaultdict(lambda: defaultdict(dict))
    kind_decisions = defaultdict(set)
    age_by_kind = defaultdict(list)
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
            kind = signal.split('.', 1)[0]
            if decision_id not in kind_decisions[kind]:
                kind_decisions[kind].add(decision_id)
                age_by_kind[kind].append(joined['ages'][signal])
            per_kind[kind][action][decision_id] = {
                horizon: outcomes.get(horizon) for horizon in HORIZONS}

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

    def _card(name, joined_count, ages, buckets, **extra):
        return {
            'signal': name,
            'decisions_joined': joined_count,
            'decision_coverage_pct': round(
                100 * joined_count / max(1, len(lookup)), 2),
            # The number that separates "weak effect" from "was not there".
            'median_snapshot_age_sessions': (round(statistics.median(ages), 1)
                                             if ages else None),
            'max_snapshot_age_sessions': max(ages) if ages else None,
            # Only the actions this signal was actually standing next to. Most
            # of the 33 x 7 grid is empty — a factor rank has never been beside
            # a `reject` — and publishing the empty cells cost half the card
            # section to say "count: 0" 150 times.
            'by_action': {action: _bucket(buckets[action])
                          for action in actions if buckets.get(action)},
            **extra,
        }

    kind_cards = []
    for kind in sorted(per_kind):
        kind_cards.append(_card(
            kind, len(kind_decisions[kind]), age_by_kind[kind],
            {action: list(rows_by_id.values())
             for action, rows_by_id in per_kind[kind].items()},
            source_kind=kind,
            signals=sorted(name for name in per_signal
                           if name.split('.', 1)[0] == kind),
        ))

    cards = []
    for signal in sorted(per_signal):
        cards.append(_card(
            signal, coverage[signal], age_by_signal[signal], per_signal[signal],
            source_kind=signal.split('.', 1)[0],
            # From the panel, not from here. A card whose signal never entered a
            # scorable cross-section has no panel entry, and `null` says that
            # rather than implying a measurement of zero.
            panel=panel['by_signal'].get(signal),
        ))

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
    codes = {}
    for field in CODED_COLUMNS:
        codes[field], columns[field] = _code(columns[field])

    index_of = {key: index for index, key in enumerate(ordered_ids)}
    timelines = {ticker: [index_of[event['decision_id']] for event in events
                          if event['decision_id'] in index_of]
                 for ticker, events in timelines.items()}

    dates = sorted(entry['plan_date'] for entry in lookup.values() if entry['plan_date'])
    joined_any = sum(1 for entry in lookup.values() if entry['at'])
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
        # The board's parent rows. Kind coverage is over the kind's *distinct*
        # decisions, so it is never the sum of its signals' — a decision that
        # joined `quant.rsi14` and `quant.trend` is one decision quant saw.
        'source_kind_cards': kind_cards,
        # One line, always on. Every number in it is echoed here rather than
        # counted in the browser, so "the banner says 741" and "the payload
        # holds 741" is a comparison a reader can make without reading the JS.
        'kpi': {
            'decisions': len(lookup),
            'sessions': len(set(dates)),
            'ticker_sessions': len({(entry['ticker'], entry['plan_date'])
                                    for entry in lookup.values()}),
            'tickers': len(timelines),
            'signals_referenced': len(cards),
            'decisions_with_any_signal': joined_any,
            # The headline number of the whole page, and the one that is easiest
            # to read as a verdict on the signals: it is not. A decision with no
            # joined snapshot is one the registered histories did not exist for
            # yet, not one the signals had nothing to say about.
            'decision_signal_coverage_pct': round(
                100 * joined_any / max(1, len(lookup)), 1),
            'panel_as_of': panel['as_of'],
            'reading': ('this counts a decision with at least one joined '
                        'snapshot; no single source reaches half the book, and '
                        'the per-source figure on each card is the one that says '
                        'whether that source was there'),
        },
        # IC, its interval and the selection PBO, computed once by
        # `clawock signal-panel` and republished — never recomputed here.
        'signal_panel': {key: panel[key] for key in (
            'as_of', 'first_session', 'sessions', 'rows', 'selection',
            'refutation', 'method', 'interval_caveat', 'source')},
        'info_source_cards': cards,
        # Indices into `decisions`, not copies of it. The duplicated form spent
        # 88KB restating an action and an outcome that were already there, and
        # gave the page two places to read the same fact from.
        'ticker_timelines': {ticker: sorted(indices)
                             for ticker, indices in sorted(timelines.items())},
        'decisions': columns,
        # `decisions[field][i]` is an index into `codes[field]` for every field
        # named here, and a value for every field that is not.
        'codes': codes,
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
    # Between the two because of what it costs to recover. The panel block is
    # 15KB and it is the only part of this payload that another command will
    # reprint on demand (`clawock signal-panel`); the timelines and the drawer
    # are the page. Without this step the fall from "the map is a little
    # shorter" to "the map is a table of aggregates" was a single 9KB stumble.
    ('no_panel_scores', 'per-signal IC and interval dropped; run '
                        '`clawock signal-panel` for them'),
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
            payload['info_source_cards'] = [
                {key: value for key, value in card.items() if key != 'panel'}
                for card in payload['info_source_cards']]
            payload['signal_panel'] = dict(payload['signal_panel'],
                                           dropped='payload budget')
        elif level == 'no_panel_scores':
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
