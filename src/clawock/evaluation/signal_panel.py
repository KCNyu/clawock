"""Does each information source carry weight? Measure it on the cross-section.

The question this answers
-------------------------
"Is the sentiment/news layer worth anything, and is the technical layer?" —
per source, with an interval, and honestly enough that "not yet" is a possible
answer.

Why the existing attribution cannot answer it
---------------------------------------------
`decision.ledger` already attributes settled outcomes by `driven_by`, and
`information_overlay` was built to answer exactly this question prospectively.
Measured on the live ledger (741 rows, lifetime):

* `information_overlay` has **zero** eligible decisions, ever. It counts
  `tactical_entry` adds carrying a v1 packet; there have been 7 such adds in the
  book's life and none of them carried one. The cohort is not small, it is empty,
  and running longer does not change that.
* `signal_provenance.sizing.contributors` has **never** fired — every one of the
  120 packets says `usable_for_decisions: false`.
* `by_driver` does have settled rows (technical 411, risk_rule 170, catalyst 95,
  macro 35, sentiment 16, peer 13) but 16 rows cannot carry a weight, and they
  are the decisions we happened to take — a source we never acted on scores
  nothing rather than scoring zero.

All three share one shape: they measure *decisions*, and this desk makes a few
dozen a month. A source's value is not a property of the decisions we took.

What this measures instead
--------------------------
The panel is the cross-section: one row per (session, ticker, signal), holding
the value that signal had **at that snapshot** and the forward return that
followed it. No decision has to have been taken. The registered histories are
already point-in-time — they were written each morning and never rewritten — so
the panel inherits that property rather than reconstructing it:

    quant_signals_history      rsi14, zscore20, mom_1m, dist_ma200_pct   (technical)
    t0_setups_history          range_pos                                 (technical)
    cross_sectional_factor     composite_score, market_percentile        (factor)
    peer_residual_history      triggered rule count                      (peer)
    news_evidence_history      signed score, novelty, source reliability (information)

Forward returns come from `memory/bars`, the immutable canonical store, and only
from sessions strictly after the snapshot.

How a source is scored
----------------------
Rank information coefficient: per session, Spearman between the signal's
cross-section and the forward returns of that same cross-section, then averaged
over sessions. IC rather than a hit rate as the headline, because a hit rate
needs a declared direction and half of these signals do not have one that can be
declared honestly (is a high RSI momentum or exhaustion?). IC's *sign* is the
answer to that question rather than an input to it.

Two properties make the number publishable rather than decorative:

* **the interval is clustered by session.** One busy day is one observation, not
  twenty. With 24 registered sessions the effective sample is 24, and the band
  says so;
* **the whole signal set goes through CSCV/PBO.** Picking the best of thirteen
  signals and reporting its IC is a search, and the probability of backtest
  overfitting is what separates "this source has weight" from "this source won a
  thirteen-way lottery".

Refuting the number instead of only bounding it
-----------------------------------------------
An interval answers "how precisely is this estimated". It does not answer "would
a signal carrying no information have produced this anyway", and on a
cross-section of a dozen names it cannot answer "is one name carrying it". Two
refuters do (#1167):

* **placebo** — permute which name held which value, within each session. The
  returns, the sessions and the tie pattern are untouched; only the pairing
  dies. The p-value is against that null, not a textbook one.
* **leave-one-ticker-out** — drop each name entirely and recompute. The span is
  informational; a *sign flip* is the finding.

The third refuter in that family, DoWhy's random-common-cause, does not map: it
adds an irrelevant covariate to an adjustment set, and a rank IC adjusts for
nothing. The reason the causal-inference port itself stayed closed is unchanged
and is worth restating beside its refuters — this ledger has no untreated arm,
so CATE and DML have nothing to identify. Refutation is the half of that
toolkit that survives without an intervention.

Nothing here changes a decision, a threshold, or a rule. It is a measurement,
and its status field never reaches `validated` — the strongest verdict available
is `diagnostic`, and `survives_refutation` is a statement about the sessions
observed, not a registration.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import defaultdict
from pathlib import Path

from clawock import seeds
from clawock import history_store
from clawock.decision.ledger import leg_sessions, load_ticker_bars
from clawock.decision.setup_review import wilson_ci
from clawock.evaluation import cscv
from clawock.evidence import run_card
from clawock.instruments import canonical_bar_manifest
from clawock.labeling import triple_barrier
from clawock.workspace import workspace_root

WS = workspace_root()
DATA = WS / 'assets' / 'data'
HORIZONS = (1, 5, 20)

#: A source is `collecting` until it clears both. Sessions matter more than rows:
#: the interval is clustered by session, so 500 rows over 6 days is 6 samples.
MIN_SESSIONS = 12
MIN_OBSERVATIONS = 60

#: Signals whose direction is registered rather than discovered, so a hit rate
#: means something for them. Everything else is scored by IC alone — the sign of
#: an IC is a finding, and turning a finding into a "hit rate" is how a search
#: gets published as a result.
DIRECTIONAL = {
    'factor.composite_score': 1,
    'factor.market_percentile': 1,
    'news.signed_score': 1,
    'news.actionable_count': 1,
    'peer.triggered_rules': 1,
    'quant.mom_1m': 1,
    'quant.dist_ma200_pct': 1,
}


def _rows_of(payload) -> dict:
    rows = payload.get('rows')
    return rows if isinstance(rows, dict) else {}


def _as_of(payload) -> str:
    return str(payload.get('as_of') or '')[:10]


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def quant_signals(payload) -> list[tuple[str, str, float]]:
    """(ticker, signal, value) from one registered quant-signal snapshot."""
    out = []
    for ticker, row in _rows_of(payload).items():
        if not isinstance(row, dict):
            continue
        for field in ('rsi14', 'zscore20', 'mom_1m', 'dist_ma200_pct',
                      'stop_distance_pct'):
            value = _number(row.get(field))
            if value is not None:
                out.append((str(ticker), f'quant.{field}', value))
    return out


def setup_signals(payload) -> list[tuple[str, str, float]]:
    out = []
    for ticker, row in _rows_of(payload).items():
        if not isinstance(row, dict):
            continue
        value = _number(row.get('range_pos'))
        if value is not None:
            out.append((str(ticker), 'setup.range_pos', value))
    return out


def factor_signals(payload) -> list[tuple[str, str, float]]:
    """The composite, its market percentile, and every constituent rank.

    The constituents are what make the composite diagnosable (#1133). Scoring
    only the weighted mean cannot separate the two explanations for a negative
    IC — one factor entering with a reversed polarity, or nine factors having an
    ordinary bad month — and those need different responses: the first is a
    defect with a regression test, the second is evidence to re-check when the
    panel is three times longer. Snapshots registered before the constituents
    were persisted simply contribute no constituent rows, which the panel's own
    per-signal session counts already make visible.
    """
    out = []
    for ticker, row in _rows_of(payload).items():
        if not isinstance(row, dict):
            continue
        for field in ('composite_score', 'market_percentile'):
            value = _number(row.get(field))
            if value is not None:
                out.append((str(ticker), f'factor.{field}', value))
        ranks = row.get('sector_neutral_ranks')
        if isinstance(ranks, dict):
            for factor, value in ranks.items():
                number = _number(value)
                if number is not None:
                    out.append((str(ticker), f'factor.rank.{factor}', number))
    return out


def bar_signals(payload) -> list[tuple[str, str, float]]:
    """Bar-derived liquidity and volatility estimators (#1172/#1173).

    Their own source, their own namespace. They are not constituents of the
    composite — `factor_weights` must exactly match the pre-registered
    `RAW_FACTORS` — and reading `bar.roll_spread_pct` as something the composite
    was built from would be wrong in the direction that matters.

    A `None` here is not a gap in coverage. Roll's spread has no real root when
    the serial covariance of price changes is positive, which happens on
    trending names; the row omits it rather than reporting zero, which would be
    the most liquid value in the cross-section, assigned to exactly the names
    where the model does not apply.
    """
    out = []
    for ticker, row in _rows_of(payload).items():
        if not isinstance(row, dict):
            continue
        for field, value in row.items():
            number = _number(value)
            if number is not None:
                out.append((str(ticker), f'bar.{field}', number))
    return out


def peer_signals(payload) -> list[tuple[str, str, float]]:
    """How many pre-registered peer rules fired for this name that session."""
    out = []
    for ticker, row in _rows_of(payload).items():
        if not isinstance(row, dict):
            continue
        rules = row.get('triggered_rules')
        if isinstance(rules, list):
            out.append((str(ticker), 'peer.triggered_rules', float(len(rules))))
    return out


def news_signals(payload) -> list[tuple[str, str, float]]:
    """Per-ticker aggregates of that morning's event graph.

    Summed rather than averaged for the signed score: two corroborating
    disclosures are more information than one, which is the claim the
    information layer makes about itself. Novelty and reliability are averaged —
    they describe each event, not the day.
    """
    events = payload.get('events')
    if not isinstance(events, list):
        return []
    signed = defaultdict(float)
    novelty = defaultdict(list)
    reliability = defaultdict(list)
    actionable = defaultdict(int)
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        ticker = str(event.get('ticker') or '').strip()
        if not ticker:
            continue
        seen.add(ticker)
        value = _number(event.get('information_signed_score'))
        if value is not None:
            signed[ticker] += value
        for field, bucket in (('novelty_score', novelty),
                              ('source_reliability', reliability)):
            number = _number(event.get(field))
            if number is not None:
                bucket[ticker].append(number)
        if event.get('actionable_escalation') is True:
            actionable[ticker] += 1
    out = []
    for ticker in sorted(seen):
        out.append((ticker, 'news.signed_score', signed.get(ticker, 0.0)))
        out.append((ticker, 'news.actionable_count', float(actionable.get(ticker, 0))))
        if novelty.get(ticker):
            out.append((ticker, 'news.novelty', statistics.fmean(novelty[ticker])))
        if reliability.get(ticker):
            out.append((ticker, 'news.source_reliability',
                        statistics.fmean(reliability[ticker])))
    return out


#: file -> extractor. Adding a source is one line plus its extractor; the panel
#: schema is long-format precisely so it does not change when one is added.
SOURCES = (
    ('quant_signals_history.jsonl', quant_signals),
    ('t0_setups_history.jsonl', setup_signals),
    ('cross_sectional_factor_history.jsonl', factor_signals),
    ('bar_signal_history.jsonl', bar_signals),
    ('peer_residual_history.jsonl', peer_signals),
    ('news_evidence_history.jsonl', news_signals),
)


def _leg_of(ticker: str, manifest) -> str | None:
    """The leg its canonical bars are filed under, or None when it has none.

    A signal on a ticker with no bar store is unscorable rather than zero: the
    HK/US session calendars differ, so a forward return has to be counted in the
    leg's own sessions, and there is nothing to count them in.
    """
    entry = (manifest or {}).get(ticker)
    if not isinstance(entry, dict):
        return None
    return str(entry.get('leg') or '').upper() or None


def forward_returns(ticker: str, leg: str, as_of: str,
                    horizons=HORIZONS) -> dict:
    """Close-to-close returns from the first session strictly after `as_of`.

    Entry is the first close the snapshot could not have seen, so a signal
    written before the open is never scored against a bar it already contained.
    """
    bars = load_ticker_bars(ticker)
    if not bars:
        return {}
    sessions = [day for day in leg_sessions(leg) if day in bars and day > as_of]
    if not sessions:
        return {}
    entry_day = sessions[0]
    entry = _number((bars.get(entry_day) or {}).get('close'))
    if not entry:
        return {}
    out = {}
    for horizon in horizons:
        if len(sessions) <= horizon:
            continue
        exit_day = sessions[horizon]
        exit_price = _number((bars.get(exit_day) or {}).get('close'))
        if exit_price is None:
            continue
        out[f't{horizon}'] = round(100 * (exit_price / entry - 1), 6)
    return out


#: Barriers in units of the name's own daily volatility. Two up, one down is
#: the asymmetry the book's own rule already has — a chandelier stop exits on a
#: single adverse move while a target is only reached by a sustained one — and
#: it is pre-registered here rather than searched.
BARRIER_PROFIT_MULTIPLE = 2.0
BARRIER_STOP_MULTIPLE = 1.0

_barrier_cache: dict = {}


def _bar_series(ticker: str, leg: str):
    """The name's bars as an ordered list, keyed by leg session, cached.

    `triple_barrier` walks forward bar by bar and needs highs and lows; the
    panel's own `load_ticker_bars` returns a date-keyed dict, and rebuilding the
    ordered list for ten thousand rows is the whole cost of the path-aware
    outcome.
    """
    key = (ticker, leg)
    if key not in _barrier_cache:
        bars = load_ticker_bars(ticker) or {}
        days = [day for day in leg_sessions(leg) if day in bars]
        series = []
        for day in days:
            bar = bars.get(day) or {}
            close = _number(bar.get('close'))
            high = _number(bar.get('high'))
            low = _number(bar.get('low'))
            if close is None:
                continue
            series.append({'date': day, 'close': close,
                           'high': high if high is not None else close,
                           'low': low if low is not None else close})
        volatility = triple_barrier.daily_volatility(
            [bar['close'] for bar in series])
        _barrier_cache[key] = (series, {bar['date']: index
                                        for index, bar in enumerate(series)},
                               volatility)
    return _barrier_cache[key]


def path_aware_returns(ticker: str, leg: str, as_of: str,
                       horizons=HORIZONS) -> dict:
    """The same forward windows, ended by whichever barrier is touched first.

    `forward_returns` above scores every signal against the close `h` sessions
    later, which is the outcome of a position this book does not hold: it runs a
    chandelier stop, and a breach is a standard exit rather than a paper loss to
    sit through. A name that fell 18% intraday on day two and closed the week up
    3% is `+3%` to that function and would have been `-18%` in the account.

    The barrier is the book's real one — `22d high - 3 x ATR(14)`, recomputed at
    every step so it trails — and intraday touches count, because a stop checked
    only at the close is not the stop being run.
    """
    series, index_of, volatility = _bar_series(ticker, leg)
    if not series:
        return {}
    entry_index = None
    for index, bar in enumerate(series):
        if bar['date'] > as_of:
            entry_index = index
            break
    if entry_index is None or entry_index >= len(volatility):
        return {}
    unit = volatility[entry_index]
    if not unit:
        return {}
    out = {}
    for horizon in horizons:
        if entry_index + horizon >= len(series):
            continue
        result = triple_barrier.apply_barriers(
            series, entry_index, horizon=horizon,
            profit_multiple=BARRIER_PROFIT_MULTIPLE,
            stop_multiple=BARRIER_STOP_MULTIPLE, volatility=unit,
            use_chandelier=True)
        if result:
            out[f'p{horizon}'] = round(100 * result['return'], 6)
            out[f'b{horizon}'] = result['barrier']
    return out


def build_panel(data_dir: Path | None = None, manifest=None) -> list[dict]:
    """Long-format panel: one row per (session, ticker, signal)."""
    data_dir = Path(data_dir or DATA)
    manifest = manifest if manifest is not None else canonical_bar_manifest()
    legs = {}
    deduped = {}
    for filename, extractor in SOURCES:
        path = data_dir / filename
        if not path.exists():
            continue
        for payload in history_store.load_series(path):
            if not isinstance(payload, dict):
                continue
            as_of = _as_of(payload)
            if not as_of:
                continue
            for ticker, signal, value in extractor(payload):
                if ticker not in legs:
                    legs[ticker] = _leg_of(ticker, manifest)
                leg = legs[ticker]
                if not leg:
                    continue  # no canonical bars: unscorable, counted in coverage
                forward = forward_returns(ticker, leg, as_of)
                if not forward:
                    continue
                forward.update(path_aware_returns(ticker, leg, as_of))
                # One observation per (session, ticker, signal). The T+0 setup
                # history writes ~14 intraday snapshots a day, so without this a
                # ticker enters that session's cross-section fourteen times and
                # the day's IC is mostly a ranking of how often each name was
                # sampled. Last snapshot wins: it is the one the next session's
                # open actually follows.
                deduped[(as_of, ticker, signal)] = {
                    'as_of': as_of, 'ticker': ticker, 'leg': leg,
                    'signal': signal, 'value': value, **forward}
    panel = list(deduped.values())
    panel.sort(key=lambda row: (row['as_of'], row['signal'], row['ticker']))
    return panel


def _spearman(pairs) -> float | None:
    """Rank correlation with mid-ranks for ties. None below three points."""
    if len(pairs) < 3:
        return None

    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            shared = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = shared
            i = j + 1
        return out

    xs = ranks([p[0] for p in pairs])
    ys = ranks([p[1] for p in pairs])
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None  # a flat cross-section carries no ranking that day
    return num / (dx * dy)


def session_pairs(rows, horizon: str) -> dict:
    """{session: [(signal value, forward return), ...]} for one horizon.

    Factored out of `daily_ics` so the refuters below rank exactly the rows the
    headline IC ranks. A refutation computed off a second, slightly different
    row set would refute a number nobody published.
    """
    by_day = defaultdict(list)
    for row in rows:
        value, forward = row.get('value'), row.get(horizon)
        if value is not None and forward is not None:
            by_day[row['as_of']].append((float(value), float(forward)))
    return by_day


def daily_ics(rows, horizon: str) -> dict:
    """{session: IC} for one signal at one horizon."""
    by_day = session_pairs(rows, horizon)
    out = {}
    for day, pairs in by_day.items():
        ic = _spearman(pairs)
        if ic is not None:
            out[day] = ic
    return out


def _cluster_ci(values_by_day: dict, samples: int = 2000, seed: int = seeds.seed('signal_panel_cluster_bootstrap')):
    """Bootstrap over sessions, not rows — one busy day is one observation."""
    import random

    days = sorted(values_by_day)
    if len(days) < 3:
        return None
    rnd = random.Random(seed)
    draws = []
    for _ in range(samples):
        picked = [values_by_day[rnd.choice(days)] for _ in days]
        draws.append(statistics.fmean(picked))
    draws.sort()
    return [round(draws[int(0.025 * (len(draws) - 1))], 4),
            round(draws[int(0.975 * (len(draws) - 1))], 4)]


def score_signal(rows, horizon: str) -> dict:
    ics = daily_ics(rows, horizon)
    scored = [row for row in rows if row.get(horizon) is not None]
    sessions = len(ics)
    # Sessions whose cross-section was constant (every name scored 0 that day)
    # rank nothing and are dropped by `daily_ics`. Counting them keeps a signal
    # that is usually flat — an event count, most days — from reading as broken
    # when it reports no sessions at all.
    flat = len({row['as_of'] for row in scored}) - sessions
    result = {
        'n_observations': len(scored),
        'n_sessions': sessions,
        'n_tickers': len({row['ticker'] for row in scored}),
        'mean_ic': round(statistics.fmean(ics.values()), 4) if ics else None,
        'ic_cluster_ci95': _cluster_ci(ics),
        'sessions_with_positive_ic': sum(1 for value in ics.values() if value > 0),
        'flat_sessions': flat,
    }
    signal = rows[0]['signal'] if rows else ''
    direction = DIRECTIONAL.get(signal)
    if direction:
        # Only where the direction was registered, never where it was learned.
        wins = sum(1 for row in scored
                   if (row['value'] * direction > 0 and row[horizon] > 0)
                   or (row['value'] * direction < 0 and row[horizon] < 0))
        graded = sum(1 for row in scored if row['value'] != 0 and row[horizon] != 0)
        result['directional_hit_rate'] = (
            round(wins / graded, 4) if graded else None)
        result['hit_rate_ci95'] = wilson_ci(wins, graded) if graded else None
    result['status'] = (
        'diagnostic'
        if sessions >= MIN_SESSIONS and len(scored) >= MIN_OBSERVATIONS
        else 'collecting')
    # An interval that clears zero on a diagnostic sample is the strongest thing
    # this can say, and it is still not "validated" — that word is reserved for
    # a rule that survived pre-registration, which no measurement here performs.
    band = result['ic_cluster_ci95']
    result['ic_clears_zero'] = (
        bool(band and (band[0] > 0 or band[1] < 0))
        if result['status'] == 'diagnostic' else False)
    return result


#: How many relabelings the placebo null draws. Same count as the session
#: permutation in `evaluation.drift`, for the same reason: enough resolution to
#: separate 0.02 from 0.2, few enough that the panel still fits inside the
#: decision-map build's budget.
PLACEBO_PERMUTATIONS = 500

#: A placebo needs sessions to permute within and names to permute across. Below
#: three names a session ranks nothing; below `MIN_SESSIONS` the panel is
#: `collecting` and the refuters stay silent rather than produce a p-value for a
#: number that is not being claimed yet.
MIN_PLACEBO_CROSS_SECTION = 3


def _midranks(values) -> list[float]:
    """Ranks with ties averaged — the same ladder `_spearman` builds."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = shared
        i = j + 1
    return out


def placebo_null(rows, horizon: str, *,
                 permutations: int = PLACEBO_PERMUTATIONS,
                 seed: int = seeds.seed('signal_panel_placebo_permutation')) -> dict | None:
    """Reshuffle which name held which value, keep the session and the returns.

    DoWhy calls this a placebo-treatment refuter and it is the one refuter from
    that family this panel can actually run (see the module note below). Within
    each session the signal's values are permuted across the names present that
    day; the forward returns, the session structure, the number of names and the
    tie pattern all stay exactly as they were. What is destroyed is the only
    thing the IC claims: that *this* name's value stood next to *this* name's
    return.

    Why the session bootstrap does not already answer this. The bootstrap
    resamples sessions to say how precisely the mean IC is estimated; it takes
    the per-session IC as given. The placebo asks the prior question — what IC
    would a signal with no cross-sectional information have produced on these
    sessions — and the answer is not the textbook one whenever the cross-section
    is small or the values are mostly tied. `news.actionable_count` and
    `peer.triggered_rules` are zero for most names on most days; a rank
    correlation built on twelve names of which nine are tied has a null far
    wider than `1/sqrt(n-1)`, and an interval that ignores that reads as
    evidence when it is arithmetic.

    Two-sided, because the sign of an IC here is a finding rather than a
    hypothesis: a signal that predicts the reverse of its intuition has still
    refuted its placebo.
    """
    import numpy as np

    days = []
    for day, pairs in sorted(session_pairs(rows, horizon).items()):
        if len(pairs) < MIN_PLACEBO_CROSS_SECTION:
            continue
        xs = np.asarray(_midranks([p[0] for p in pairs]), dtype=float)
        ys = np.asarray(_midranks([p[1] for p in pairs]), dtype=float)
        xc, yc = xs - xs.mean(), ys - ys.mean()
        sx, sy = float(np.sqrt(xc @ xc)), float(np.sqrt(yc @ yc))
        if sx == 0 or sy == 0:
            continue  # a flat cross-section ranks nothing, on any relabeling
        days.append((xc, yc / (sx * sy)))
    if len(days) < MIN_SESSIONS:
        return None

    observed = statistics.fmean(float(xc @ yhat) for xc, yhat in days)
    rng = np.random.default_rng(seed)
    draws = np.zeros(permutations, dtype=float)
    for xc, yhat in days:
        shuffled = rng.permuted(np.broadcast_to(xc, (permutations, xc.size)).copy(),
                                axis=1)
        draws += shuffled @ yhat
    draws /= len(days)

    at_least = int(np.count_nonzero(np.abs(draws) >= abs(observed)))
    ordered = np.sort(draws)
    return {
        'observed_mean_ic': round(observed, 4),
        'null_mean_ic': round(float(draws.mean()), 4),
        'null_ci95': [round(float(ordered[int(0.025 * (permutations - 1))]), 4),
                      round(float(ordered[int(0.975 * (permutations - 1))]), 4)],
        # +1 on both sides: the unpermuted labeling is itself one arrangement,
        # so this null cannot support a p-value of exactly zero.
        'p_value': round((at_least + 1) / (permutations + 1), 5),
        'permutations': permutations,
        'sessions': len(days),
    }


def leave_one_ticker_out(rows, horizon: str) -> dict | None:
    """Drop each name entirely and recompute the mean IC.

    DoWhy's data-subset refuter, moved to the axis this panel is actually thin
    on. Subsetting *sessions* is already covered — that is what the clustered
    bootstrap resamples — but every interval on this page is computed over a
    cross-section of roughly a dozen names, and none of them can see that one
    name is carrying the finding. A signal whose IC survives dropping any single
    name and one whose sign flips when a single name leaves are indistinguishable
    in the published column, and they are not the same claim.

    The span is reported rather than a pass/fail: a name whose removal moves the
    IC is not a defect, it is the size of this book's cross-section. A *sign
    flip* is the part worth naming.
    """
    tickers = sorted({row['ticker'] for row in rows if row.get(horizon) is not None})
    if len(tickers) < MIN_PLACEBO_CROSS_SECTION:
        return None
    full_ics = daily_ics(rows, horizon)
    if not full_ics:
        return None
    full = statistics.fmean(full_ics.values())

    without = {}
    for ticker in tickers:
        ics = daily_ics([row for row in rows if row['ticker'] != ticker], horizon)
        if ics:
            without[ticker] = statistics.fmean(ics.values())
    if len(without) < MIN_PLACEBO_CROSS_SECTION:
        return None

    worst = max(without, key=lambda t: abs(without[t] - full))
    flips = sorted(t for t, value in without.items()
                   if full != 0 and value * full < 0)
    return {
        'n_tickers': len(without),
        'full_mean_ic': round(full, 4),
        'ic_range': [round(min(without.values()), 4),
                     round(max(without.values()), 4)],
        'largest_swing': {'ticker': worst,
                          'mean_ic_without': round(without[worst], 4),
                          'delta': round(without[worst] - full, 4)},
        'sign_flips': flips,
    }


#: Verdicts, ordered worst-first. Deliberately not a boolean and deliberately
#: not the word "validated": clearing a placebo says the ranking carried
#: information on the sessions observed, which is a diagnostic finding, not a
#: rule that was registered before the data arrived.
REFUTATION_VERDICTS = (
    'collecting',            # not enough sessions to refute anything yet
    'fails_placebo',         # a relabeled signal produces this IC as often
    'one_name_flips_it',     # clears the placebo, but a single name owns the sign
    'survives_refutation',   # clears both, on this sample, at this horizon
)

#: Conventional, and pre-registered here rather than chosen after reading the
#: p-values. Nothing downstream branches on it — it labels a row.
PLACEBO_ALPHA = 0.05


def refute_signal(rows, horizon: str, score: dict) -> dict:
    """Both refuters plus the verdict that reads them together."""
    if score.get('status') != 'diagnostic':
        return {'verdict': 'collecting', 'placebo': None, 'leave_one_ticker_out': None}
    placebo = placebo_null(rows, horizon)
    stability = leave_one_ticker_out(rows, horizon)
    if placebo is None:
        verdict = 'collecting'
    elif placebo['p_value'] > PLACEBO_ALPHA:
        verdict = 'fails_placebo'
    elif stability and stability['sign_flips']:
        verdict = 'one_name_flips_it'
    else:
        verdict = 'survives_refutation'
    return {'verdict': verdict, 'placebo': placebo,
            'leave_one_ticker_out': stability}


def refutation_summary(signals: dict) -> dict:
    """Per horizon, how many signals each verdict claimed.

    This is the part that goes to the site. The per-signal detail is available
    from `clawock signal-panel --json`; the payload gets the count, because the
    reader's question at the top of a page is "how many of these thirteen
    survive being shuffled", not "what was `quant.rsi14`'s p-value".
    """
    out = {}
    for horizon in ('t1', 't5', 't20'):
        counts = {verdict: 0 for verdict in REFUTATION_VERDICTS}
        contested = []
        for signal, sections in signals.items():
            counts[sections['refutation'][horizon]['verdict']] += 1
            placebo = sections['refutation'][horizon]['placebo']
            # The two strongest things this panel says about a signal, said
            # about the same signal, disagreeing. `ic_clears_zero` is not
            # rewritten to mean "and it beat its placebo" — that would change a
            # published field's meaning under readers who already have it — so
            # the disagreement is named instead of resolved.
            if (placebo and sections[horizon].get('ic_clears_zero')
                    and placebo['p_value'] > PLACEBO_ALPHA):
                contested.append(signal)
        out[horizon] = {'signals': len(signals), **counts,
                        'interval_clears_zero_but_placebo_does_not': sorted(contested)}
    return out


#: Tertiles, not quintiles. The cross-section is about twenty-one names on a
#: good session; five buckets leaves four names each, and a "quintile return" of
#: four names is one name's bad week wearing a statistic's name.
QUANTILES = 3

#: Below this the session's cross-section cannot be split into `QUANTILES`
#: buckets with anything in them.
MIN_CROSS_SECTION = QUANTILES * 2


def _quantile_buckets(pairs, quantiles: int = QUANTILES):
    """Assign one session's (value, forward) pairs to near-equal buckets by value.

    Ties are broken by the order the sort produced rather than shared across the
    boundary. That is deliberate and it is the conservative choice: a signal that
    is constant across the cross-section gets buckets that differ only by noise,
    so its spread goes to zero rather than becoming undefined and dropping the
    session — which would silently restrict the measurement to the days the
    signal happened to be lively.
    """
    ordered = sorted(pairs, key=lambda pair: pair[0])
    edges = [round(len(ordered) * index / quantiles) for index in range(quantiles + 1)]
    return [ordered[edges[index]:edges[index + 1]] for index in range(quantiles)]


def quantile_structure(rows, horizon: str, *, quantiles: int = QUANTILES) -> dict:
    """Mean forward return by signal quantile, and the long-short spread (#1161).

    The rank IC beside this answers "does the ordering carry information". It
    cannot answer the question that decides how a signal would be used: **is the
    information on both ends, or one?** A signal whose top bucket outperforms
    while its bottom bucket is indistinguishable from the middle is a long-only
    screen; one whose bottom bucket carries everything is an avoid-list; only a
    signal with both ends live supports a long-short reading. An IC of the same
    magnitude is produced by all three.

    The spread interval is bootstrapped over sessions, like every other interval
    on this panel: a session where twenty names all moved together is one
    observation, not twenty.
    """
    by_day = defaultdict(list)
    for row in rows:
        value, forward = row.get('value'), row.get(horizon)
        if value is not None and forward is not None:
            by_day[row['as_of']].append((float(value), float(forward)))
    usable = {day: pairs for day, pairs in by_day.items()
              if len(pairs) >= MIN_CROSS_SECTION}
    if len(usable) < MIN_SESSIONS:
        return {'status': 'collecting', 'n_sessions': len(usable),
                'n_sessions_too_narrow': len(by_day) - len(usable),
                'quantiles': quantiles, 'spread': None, 'buckets': None}
    per_day_bucket_means = defaultdict(dict)
    for day, pairs in usable.items():
        for index, bucket in enumerate(_quantile_buckets(pairs, quantiles)):
            if bucket:
                per_day_bucket_means[day][index] = statistics.fmean(
                    forward for _, forward in bucket)
    buckets = {}
    for index in range(quantiles):
        values = {day: means[index] for day, means in per_day_bucket_means.items()
                  if index in means}
        buckets[f'q{index + 1}'] = {
            'mean_forward_return': round(statistics.fmean(values.values()), 6)
            if values else None,
            'n_sessions': len(values),
        }
    spread_by_day = {
        day: means[quantiles - 1] - means[0]
        for day, means in per_day_bucket_means.items()
        if 0 in means and quantiles - 1 in means
    }
    interval = _cluster_ci(spread_by_day) if spread_by_day else None
    monotone = [buckets[f'q{index + 1}']['mean_forward_return']
                for index in range(quantiles)]
    return {
        'status': 'diagnostic',
        'quantiles': quantiles,
        'n_sessions': len(usable),
        'n_sessions_too_narrow': len(by_day) - len(usable),
        'buckets': buckets,
        'spread': round(statistics.fmean(spread_by_day.values()), 6)
        if spread_by_day else None,
        'spread_ci95': interval,
        'spread_clears_zero': bool(interval and (interval[0] > 0 or interval[1] < 0)),
        # Which end carries it. Reported as the two halves of the spread rather
        # than as a verdict, because the reader's threshold for "one-sided" is
        # not this function's to pick.
        'top_minus_middle': (
            round(monotone[-1] - monotone[quantiles // 2], 6)
            if None not in monotone else None),
        'middle_minus_bottom': (
            round(monotone[quantiles // 2] - monotone[0], 6)
            if None not in monotone else None),
        'monotone': (all(monotone[index] <= monotone[index + 1]
                         for index in range(quantiles - 1))
                     or all(monotone[index] >= monotone[index + 1]
                            for index in range(quantiles - 1)))
        if None not in monotone else None,
    }


def persistence(rows, *, quantiles: int = QUANTILES) -> dict:
    """How fast the signal churns, and how fast its ordering decays (#1161).

    Two costs a mean IC hides. **Turnover** is how much of the top bucket has to
    be replaced between consecutive sessions — a signal with a real edge and 90%
    daily turnover pays for that edge in spread every day, and a report that
    prints the edge without the turnover is quoting a gross number. **Rank
    autocorrelation** is the same thing from the other side: how much of
    yesterday's ordering survives into today.

    Both are computed only across *consecutive registered sessions*, so a gap in
    the history is a gap rather than an artificially low turnover.
    """
    by_day = defaultdict(dict)
    for row in rows:
        if row.get('value') is not None:
            by_day[row['as_of']][row['ticker']] = float(row['value'])
    days = sorted(by_day)
    turnovers, autocorrelations = [], []
    for previous, current in zip(days, days[1:]):
        before, after = by_day[previous], by_day[current]
        shared = sorted(set(before) & set(after))
        if len(shared) >= MIN_CROSS_SECTION:
            autocorrelation = _spearman(
                [(before[ticker], after[ticker]) for ticker in shared])
            if autocorrelation is not None:
                autocorrelations.append(autocorrelation)
        for source, target, bucket in ((before, after, 'top'),):
            if len(source) < MIN_CROSS_SECTION or len(target) < MIN_CROSS_SECTION:
                continue
            def top_names(values):
                ordered = sorted(values, key=lambda name: values[name], reverse=True)
                return set(ordered[:max(1, len(ordered) // quantiles)])
            was, now = top_names(source), top_names(target)
            if now:
                turnovers.append(len(now - was) / len(now))
    return {
        'n_session_pairs': max(0, len(days) - 1),
        'top_bucket_turnover': round(statistics.fmean(turnovers), 4)
        if turnovers else None,
        'rank_autocorrelation': round(statistics.fmean(autocorrelations), 4)
        if autocorrelations else None,
        'reading': ('turnover is the share of the top bucket replaced between '
                    'consecutive registered sessions; an edge quoted without it '
                    'is a gross number'),
    }


def selection_pbo(panel, horizon: str, *, groups: int = 8) -> dict:
    """How much of the best-looking source is the thirteen-way search itself.

    Sessions are the unit: each CSCV group is a block of sessions, so a signal
    cannot be scored in-sample and out-of-sample on the same day.
    """
    all_signals = sorted({row['signal'] for row in panel})
    by_signal_day = {
        signal: daily_ics([row for row in panel if row['signal'] == signal], horizon)
        for signal in all_signals
    }
    # A balanced sub-panel, because a ranking needs every candidate scored on the
    # same day: a signal registered for five sessions would otherwise void every
    # split it appears in, and the estimator would report nothing at all rather
    # than reporting on the signals a chooser could actually choose between.
    signals = [signal for signal in all_signals
               if len(by_signal_day[signal]) >= MIN_SESSIONS]
    sessions = sorted(set.intersection(
        *(set(by_signal_day[signal]) for signal in signals))) if signals else []
    excluded = [signal for signal in all_signals if signal not in signals]
    if len(signals) < 3 or len(sessions) < groups * 2:
        return {'status': 'insufficient_sample', 'pbo': None,
                'reason': (f'{len(signals)} signals scored on all of '
                           f'{len(sessions)} shared sessions cannot fill '
                           f'{groups} groups'),
                'excluded_signals': excluded}
    matrix = [[by_signal_day[signal].get(day) for signal in signals]
              for day in sessions]

    def score(values):
        present = [value for value in values if value is not None]
        return statistics.fmean(present) if present else None

    result = cscv.probability_of_backtest_overfitting(
        matrix, score, n_groups=groups, embargo=1)
    result['signals'] = signals
    result['excluded_signals'] = excluded
    result['shared_sessions'] = len(sessions)
    result['unit'] = 'session'
    if result.get('status') == 'measured':
        result['selected_signals'] = {
            signals[int(index)]: count
            for index, count in (result.get('selection_counts') or {}).items()}
    return result


#: Every constituent of the cross-sectional composite enters with a positive
#: weight over a centered rank, so the composite's own construction declares each
#: one "higher is better". That declaration is what the measured IC sign is
#: compared against; it is read from the same weights the composite uses rather
#: than typed here twice.
def composite_polarity(signals, horizon: str, *, weights=None) -> dict:
    """Is the composite's negative IC one broken factor or a bad month? (#1133)

    The two explanations demand opposite responses — a reversed polarity is a
    defect to fix with a regression test, an adverse regime is evidence to
    re-check when the panel is three times longer — and at eighteen sessions
    they look identical from the composite alone. The discriminator is not
    statistical, it is structural: **a polarity error lives in one factor.** If
    one constituent carries essentially all of the negative IC while the rest
    straddle zero, the composite is broken. If five constituents are negative
    together, the cross-section simply ranked the other way this month, and
    inverting anything would be the exact search this repository refuses.

    Reports the split and the verdict; it never changes a sign.
    """
    weights = weights or {}
    rows = []
    for signal, horizons in signals.items():
        if not signal.startswith('factor.rank.'):
            continue
        row = horizons.get(horizon) or {}
        if row.get('mean_ic') is None or not row.get('n_sessions'):
            continue
        rows.append({
            'factor': signal[len('factor.rank.'):],
            'declared_direction': 'higher_is_better',
            'weight': weights.get(signal[len('factor.rank.'):]),
            'mean_ic': row['mean_ic'],
            'measured_direction': ('higher_is_better' if row['mean_ic'] > 0
                                   else 'higher_is_worse'),
            'agrees_with_declaration': row['mean_ic'] > 0,
            'ic_clears_zero': bool(row.get('ic_clears_zero')),
            'n_sessions': row['n_sessions'],
            'n_observations': row['n_observations'],
        })
    composite = (signals.get('factor.composite_score') or {}).get(horizon) or {}
    if not rows:
        return {'status': 'no_constituents',
                'reason': ('no snapshot in the registered history carries '
                           'sector_neutral_ranks; run '
                           '`clawock factors --backfill-history-ranks`'),
                'composite_mean_ic': composite.get('mean_ic'),
                'constituents': []}
    rows.sort(key=lambda row: row['mean_ic'])
    negative_clearing = [row for row in rows
                         if row['ic_clears_zero'] and row['mean_ic'] < 0]
    total_negative = sum(-row['mean_ic'] for row in rows if row['mean_ic'] < 0)
    worst_share = ((-rows[0]['mean_ic'] / total_negative)
                   if total_negative > 0 else None)
    if composite.get('mean_ic') is not None and composite['mean_ic'] >= 0:
        verdict = 'composite_is_not_negative_at_this_horizon'
    elif len(negative_clearing) >= 3:
        verdict = 'regime'
    elif len(negative_clearing) == 1 and worst_share is not None and worst_share > 0.6:
        verdict = 'polarity_suspect'
    else:
        verdict = 'inconclusive'
    return {
        'status': 'measured',
        'horizon': horizon,
        'composite_mean_ic': composite.get('mean_ic'),
        'composite_n_sessions': composite.get('n_sessions'),
        'constituents': rows,
        'n_constituents': len(rows),
        'n_negative_clearing_zero': len(negative_clearing),
        'worst_factor': rows[0]['factor'],
        'worst_factor_share_of_negative_ic': (round(worst_share, 4)
                                              if worst_share is not None else None),
        'verdict': verdict,
        'reading': {
            'polarity_suspect': ('one constituent carries the negative IC: read '
                                 'the composite construction for a reversed sign '
                                 'and pin the direction with a test'),
            'regime': ('several independent constituents ranked backwards '
                       'together: this is a month, not a defect; record it with '
                       'the session count and re-check when the panel is longer'),
            'inconclusive': ('neither concentrated nor broad; do not act on the '
                             'sign'),
            'composite_is_not_negative_at_this_horizon': (
                'nothing to discriminate at this horizon'),
        }[verdict],
        'discipline': ('this function never inverts a sign; at this sample size '
                       'that would be the search the repository refuses'),
    }


def _factor_weights() -> dict:
    """The registered composite weights, or {} when the config is unreadable.

    Read rather than restated: a second copy of the weights would drift, and the
    polarity table's whole claim is that it compares the measurement against the
    composite's own declaration.
    """
    try:
        return dict(json.loads(
            (WS / 'config' / 'factor-universe.json').read_text(encoding='utf-8')
        ).get('factor_weights') or {})
    except (OSError, ValueError):
        return {}


#: Signals whose *definition* contains the barrier's own rule. Scoring these
#: against a stop-based label is close to tautological: `quant.stop_distance_pct`
#: is literally the distance to the chandelier stop, so a name near it is stopped
#: out on the first adverse session by construction, and its -0.63 path-aware IC
#: is a restatement of the label rather than a finding about the signal. Named
#: here so the panel prints the warning instead of a reader having to notice.
CIRCULAR_AGAINST_BARRIER = {
    'quant.stop_distance_pct': 'the barrier is this signal, measured from the other side',
    'quant.rsi14': 'oversold names are the ones already near the trailing stop',
    'quant.zscore20': 'same drawdown, expressed in standard deviations',
    'quant.mom_1m': 'a falling month is a name that has already run down to its stop',
}


def _barrier_mix(panel) -> dict:
    """Which barrier ended each window, per horizon.

    Published because it is how the path-aware column is read: a horizon whose
    outcomes are 70% `stop` is describing a rule that mostly gets stopped out,
    and any IC computed over it is a statement about that fact as much as about
    the signal.
    """
    out = {}
    for horizon in HORIZONS:
        seen = {}
        for row in panel:
            barrier = row.get(f'b{horizon}')
            if barrier:
                seen[barrier] = seen.get(barrier, 0) + 1
        if seen:
            total = sum(seen.values())
            out[f'p{horizon}'] = {
                **seen,
                'stopped_share': round(seen.get('stop', 0) / total, 4),
            }
    return out


def evaluate(panel) -> dict:
    by_signal = defaultdict(list)
    for row in panel:
        by_signal[row['signal']].append(row)
    scores = {signal: {horizon: score_signal(rows, horizon)
                       for horizon in ('t1', 't5', 't20')}
              for signal, rows in by_signal.items()}
    signals = {
        signal: {
            **scores[signal],
            # Two refuters run against every diagnostic row (#1167). The
            # interval says how precisely the IC is estimated; these say
            # whether a relabeled signal would have produced it anyway, and
            # whether one name is carrying it.
            'refutation': {horizon: refute_signal(rows, horizon,
                                                  scores[signal][horizon])
                           for horizon in ('t1', 't5', 't20')},
            # The same signal against an outcome the book could have realised:
            # each window ended by whichever barrier is touched first, with the
            # production chandelier stop trailing underneath (#1164). The pair
            # is the point — a signal whose IC survives the stop and one whose
            # IC was an artefact of holding through the drawdown look identical
            # on the fixed-horizon column alone.
            'path_aware': {
                **{horizon: score_signal(rows, horizon)
                   for horizon in ('p1', 'p5', 'p20')},
                'circular_against_barrier': CIRCULAR_AGAINST_BARRIER.get(signal),
            },
            # Alphalens' two questions that a mean IC cannot answer (#1161):
            # where in the cross-section the information sits, and what holding
            # the signal would cost to maintain.
            'quantiles': {horizon: quantile_structure(rows, horizon)
                          for horizon in ('t1', 't5', 't20')},
            'persistence': persistence(rows),
        }
        for signal, rows in sorted(by_signal.items())
    }
    sessions = sorted({row['as_of'] for row in panel})
    return {
        'schema_version': 1,
        'method': ('cross-sectional rank IC per session, averaged; interval '
                   'bootstrapped over sessions; directional hit rate only where '
                   'the direction was registered in advance'),
        'barriers': _barrier_mix(panel),
        'coverage': {
            'rows': len(panel),
            'signals': len(by_signal),
            'sessions': len(sessions),
            'first_session': sessions[0] if sessions else None,
            'last_session': sessions[-1] if sessions else None,
            'tickers': len({row['ticker'] for row in panel}),
            'floors': {'min_sessions': MIN_SESSIONS,
                       'min_observations': MIN_OBSERVATIONS},
        },
        'signals': signals,
        'selection': {horizon: selection_pbo(panel, horizon)
                      for horizon in ('t1', 't5', 't20')},
        'refutation_summary': refutation_summary(signals),
        'composite_polarity': {
            horizon: composite_polarity(signals, horizon, weights=_factor_weights())
            for horizon in ('t1', 't5', 't20')},
        'claim': 'diagnostic_never_validated_alpha',
        # The one thing a reader will otherwise get wrong. The session bootstrap
        # treats sessions as exchangeable, which they are for t1 and are NOT for
        # t20: consecutive sessions share nineteen of their twenty forward days,
        # so 36 sessions of t20 carry nowhere near 36 independent observations
        # and the t20 bands are narrower than the evidence. Purged CSCV in
        # `selection` is the part that handles overlap; the per-signal interval
        # is not.
        'interval_caveat': (
            'intervals are clustered by session but not corrected for '
            'overlapping forward windows: t5 and especially t20 bands are '
            'optimistic, t1 is not affected'),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='clawock signal-panel',
        description='Score each registered signal source on the cross-section.')
    parser.add_argument('--horizon', default='t5', choices=('t1', 't5', 't20'),
                        help='horizon for the printed table (default t5)')
    parser.add_argument('--json', action='store_true', help='print the full result')
    parser.add_argument('--panel', action='store_true',
                        help='print the panel rows instead of the scorecard')
    parser.add_argument('--no-card', action='store_true')
    args = parser.parse_args(argv)
    started_at = time.monotonic()

    panel = build_panel()
    if args.panel:
        print(json.dumps(panel, ensure_ascii=False, indent=2))
        return 0
    result = evaluate(panel)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    coverage = result['coverage']
    print(f'panel {coverage["rows"]} rows · {coverage["signals"]} signals · '
          f'{coverage["sessions"]} sessions '
          f'{coverage["first_session"]} → {coverage["last_session"]} · '
          f'{coverage["tickers"]} tickers')
    print(f'\n--- {args.horizon} rank IC by signal '
          f'(interval clustered by session) ---')
    print(f'{"signal":<28}{"obs":>6}{"days":>6}{"mean IC":>9}'
          f'{"95% CI":>20}  status')
    for signal, horizons in result['signals'].items():
        row = horizons[args.horizon]
        band = row['ic_cluster_ci95']
        band_text = f'[{band[0]:+.3f}, {band[1]:+.3f}]' if band else '—'
        mark = ' *' if row['ic_clears_zero'] else ''
        mean = f'{row["mean_ic"]:+.4f}' if row['mean_ic'] is not None else '—'
        print(f'{signal:<28}{row["n_observations"]:>6}{row["n_sessions"]:>6}'
              f'{mean:>9}{band_text:>20}  {row["status"]}{mark}')

    selection = result['selection'][args.horizon]
    print(f'\n--- selection over {len(selection.get("signals") or [])} signals ---')
    if selection.get('status') != 'measured':
        print(f'  unavailable: {selection.get("reason")}')
    else:
        print(f'  PBO {selection["pbo"]:.2f} over {selection["n_splits"]} splits '
              f'of session blocks · the best in-sample signal stayed above the '
              f'out-of-sample median in '
              f'{selection["splits_where_the_winner_stayed_above_median"]}'
              f'/{selection["n_splits"]}')
        picked = sorted((selection.get('selected_signals') or {}).items(),
                        key=lambda kv: -kv[1])[:3]
        if picked:
            print('  most often selected: '
                  + ' · '.join(f'{name} ({count})' for name, count in picked))
    summary = result['refutation_summary'][args.horizon]
    print(f'\n--- {args.horizon} refutation '
          f'({PLACEBO_PERMUTATIONS} placebo relabelings per signal) ---')
    print(f'{"signal":<28}{"mean IC":>9}{"null 95%":>20}{"p":>9}'
          f'{"worst 1-name IC":>17}  verdict')
    for signal, sections in result['signals'].items():
        refutation = sections['refutation'][args.horizon]
        placebo = refutation['placebo']
        if not placebo:
            continue
        stability = refutation['leave_one_ticker_out'] or {}
        swing = stability.get('largest_swing') or {}
        null = placebo['null_ci95']
        band = f'[{null[0]:+.3f}, {null[1]:+.3f}]'
        # Built outside the f-string: nesting the same quote inside one is a
        # 3.12 grammar, and this package supports 3.11.
        worst = (f'{swing["mean_ic_without"]:+.4f} ({swing["ticker"]})'
                 if swing else '—')
        print(f'{signal:<28}{placebo["observed_mean_ic"]:>+9.4f}'
              f'{band:>20}{placebo["p_value"]:>9.4f}{worst:>17}'
              f'  {refutation["verdict"]}')
    contested = summary['interval_clears_zero_but_placebo_does_not']
    print(f'  {summary["survives_refutation"]}/{summary["signals"]} survive both · '
          f'{summary["fails_placebo"]} produce this IC as often under a relabeling · '
          f'{summary["one_name_flips_it"]} lose their sign to one name · '
          f'{summary["collecting"]} still collecting')
    if contested:
        print('  interval says it clears zero, its own placebo does not: '
              + ' · '.join(contested))

    print(f'\n--- {args.horizon} quantile structure and cost to hold '
          f'({QUANTILES} buckets) ---')
    print(f'{"signal":<28}{"q1":>9}{"q2":>9}{"q3":>9}{"spread":>9}'
          f'{"turnover":>10}{"rank AC":>9}')
    for signal, sections in result['signals'].items():
        quantiles = sections['quantiles'][args.horizon]
        holding = sections['persistence']
        if quantiles.get('status') != 'diagnostic':
            continue
        cells = [quantiles['buckets'][f'q{index + 1}']['mean_forward_return']
                 for index in range(quantiles['quantiles'])]
        text = ''.join(f'{value:>+9.4f}' if value is not None else f'{"—":>9}'
                       for value in cells)
        spread = quantiles['spread']
        turnover = holding['top_bucket_turnover']
        autocorrelation = holding['rank_autocorrelation']
        print(f'{signal:<28}{text}'
              f'{(f"{spread:+.4f}" if spread is not None else "—"):>9}'
              f'{(f"{turnover:.2f}" if turnover is not None else "—"):>10}'
              f'{(f"{autocorrelation:+.2f}" if autocorrelation is not None else "—"):>9}'
              f'{" *" if quantiles["spread_clears_zero"] else ""}')
    print('  q1 = lowest signal value. spread = q3 - q1, interval clustered by '
          'session. turnover = share of the top bucket replaced between '
          'consecutive registered sessions: an edge quoted without it is gross.')

    path_horizon = 'p' + args.horizon[1:]
    barriers = result['barriers'].get(path_horizon) or {}
    if barriers:
        print(f'\n--- {args.horizon} against an outcome the book could have held '
              f'(trailing chandelier stop; {barriers["stopped_share"]:.0%} of '
              f'windows end at the stop) ---')
        print(f'{"signal":<28}{"fixed":>9}{"path-aware":>12}{"delta":>9}  note')
        for signal, sections in result['signals'].items():
            fixed = sections[args.horizon]
            aware = sections['path_aware'][path_horizon]
            if fixed['mean_ic'] is None or aware['mean_ic'] is None:
                continue
            note = sections['path_aware'].get('circular_against_barrier')
            marks = ('*' if fixed['ic_clears_zero'] else ' ') + \
                    ('*' if aware['ic_clears_zero'] else ' ')
            print(f'{signal:<28}{fixed["mean_ic"]:>+9.4f}{aware["mean_ic"]:>+12.4f}'
                  f'{aware["mean_ic"] - fixed["mean_ic"]:>+9.4f}  {marks}'
                  f'{"  CIRCULAR: " + note if note else ""}')
        print('  the fixed column scores a position held to the horizon through '
              'any drawdown; this book exits on a chandelier breach, so where '
              'the two disagree the fixed one is describing a trade nobody made.')

    polarity = result['composite_polarity'][args.horizon]
    if polarity.get('status') == 'measured':
        print(f'\n--- composite: polarity or regime? ({polarity["n_constituents"]} '
              f'constituents, {polarity["composite_n_sessions"]} sessions) ---')
        print(f'{"factor":<26}{"weight":>8}{"declared":>10}{"mean IC":>10}'
              f'{"measured":>16}')
        for row in polarity['constituents']:
            weight = f'{row["weight"]:.2f}' if row['weight'] is not None else '—'
            mark = ' *' if row['ic_clears_zero'] else ''
            print(f'{row["factor"]:<26}{weight:>8}{"+":>10}'
                  f'{row["mean_ic"]:>+10.4f}'
                  f'{("+" if row["agrees_with_declaration"] else "-"):>16}{mark}')
        print(f'  verdict: {polarity["verdict"]} — {polarity["reading"]}')
    elif polarity.get('status') == 'no_constituents':
        print(f'\n--- composite polarity unavailable: {polarity["reason"]}')

    print('\n* = interval clears zero on a diagnostic sample. Never "validated": '
          'nothing here was pre-registered as a rule.')
    if args.horizon != 't1':
        print(f'  {args.horizon} bands are optimistic: consecutive sessions share '
              'most of their forward window, so the session bootstrap counts '
              'more independent samples than exist.')

    if not args.no_card:
        card = run_card.record(
            'signal_panel',
            params={'horizons': list(HORIZONS), 'sources': [name for name, _ in SOURCES],
                    'directional': sorted(DIRECTIONAL),
                    'floors': {'min_sessions': MIN_SESSIONS,
                               'min_observations': MIN_OBSERVATIONS},
                    'entry': 'first close strictly after the snapshot'},
            config_files=[WS / 'config' / 'factor-universe.json'],
            started_at=started_at,
            inputs=[{'symbol': name, 'source': 'registered point-in-time history',
                     'bars': len(history_store.load_series(DATA / name)),
                     'first_session': None, 'last_session': None,
                     'digest': history_store.series_digest(DATA / name)}
                    for name, _ in SOURCES if (DATA / name).exists()],
            metrics=result,
            code_files=[Path(__file__), Path(cscv.__file__)],
            notes=[
                'Measures the cross-section, not the decisions taken: a source '
                'never acted on scores nothing under decision-level attribution.',
                'IC sign is a finding; a hit rate is reported only for signals '
                'whose direction was registered in DIRECTIONAL beforehand.',
                'Intervals are bootstrapped over sessions, so the effective '
                'sample is the session count, not the row count.',
                'No status above diagnostic exists here by construction.',
            ],
        )
        print(f'\nrun card: {card.relative_to(WS)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
