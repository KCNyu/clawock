"""When a signal's distribution moves, every threshold on it changes meaning.

The gap this closes
-------------------
`market_data/integrity.py` answers "is this bar believable" — one observation at
a time, against rules about what is structurally impossible. It is the right
gate and it is blind to the failure that matters for the research layer: a
signal whose individual values are all perfectly believable and whose
*distribution* has moved.

That failure is silent by construction. `peer_residuals` activates rules
pre-registered against a curated universe; `add_alpha` compares
`stop_distance_pct` to a fixed threshold; `information_overlay` upsizes above the
75th percentile of a cross-sectional rank. Every one of those is a statement
about where a value sits in a distribution, and every one of them keeps
returning a number after that distribution shifts. Nothing in the system
currently notices.

Three distances, and why all three
----------------------------------
* **PSI** — the population stability index, the industry's default. Bins the
  reference window and asks how much probability mass moved. Coarse, bounded,
  and the one with conventional read-off levels, which is its whole value.
* **Two-sample KS** — the largest gap between the two empirical CDFs. Sensitive
  to a shift in the middle of the distribution, insensitive to the tails.
* **1-Wasserstein** — the average distance mass had to travel, in the signal's
  own units. The only one of the three that answers "by how much", and the only
  one that notices a tail moving a long way.

A signal can move on one and not the others, and which one fires says what kind
of move it was — so the three are reported together rather than reduced to a
verdict.

The mistake this module exists to not make
------------------------------------------
Every one of those tests assumes independent observations. The panel has about
twenty-one names per session, and on any given day they move together: a
21-name cross-section is nowhere near 21 independent draws. Feeding pooled rows
to a textbook KS p-value would report `p < 1e-9` for a market that simply had a
directional week, every time, and the alert would be worthless within a month.

So the p-values here are **not** the textbook ones. The null is built by
permuting whole **sessions** between the two windows and recomputing the
statistic, which preserves the within-session correlation and only breaks the
association with time. That is the same shape as the circular-shift null in
`regime_validation` and the session-clustered bootstrap in `signal_panel`, for
the same reason.
"""
from __future__ import annotations

import math
import random
import statistics

#: Conventional PSI read-off. Published with the number because a bare 0.18 is
#: not interpretable and the levels are the only reason to prefer PSI over the
#: two better-behaved statistics beside it.
PSI_BANDS = ((0.10, 'stable'), (0.25, 'moderate_shift'), (float('inf'), 'major_shift'))

#: Below this, a window cannot describe a distribution and the honest output is
#: a refusal. Ten sessions of twenty-one names is 210 rows and 10 observations.
MIN_SESSIONS_PER_WINDOW = 8


def population_stability_index(reference, current, *, bins=10) -> float | None:
    """Sum over bins of `(p_cur - p_ref) * ln(p_cur / p_ref)`.

    Bin edges come from the **reference** window's quantiles, which is what
    makes it a stability index rather than a symmetric distance: the question is
    whether today's data still fits yesterday's picture of the world.
    """
    reference = sorted(float(value) for value in reference)
    current = [float(value) for value in current]
    if len(reference) < bins * 2 or not current:
        return None
    edges = [reference[int(index * len(reference) / bins)] for index in range(1, bins)]
    if len(set(edges)) < len(edges):
        # A signal that is constant across most of its range cannot be binned
        # into equal-mass buckets, and forcing it produces a PSI driven entirely
        # by tie-breaking.
        return None

    def histogram(values):
        counts = [0] * bins
        for value in values:
            index = 0
            while index < len(edges) and value > edges[index]:
                index += 1
            counts[index] += 1
        # Laplace-smoothed: an empty bin makes the log infinite, and a PSI of
        # infinity says "one bin emptied" rather than "the distribution moved".
        return [(count + 0.5) / (len(values) + 0.5 * bins) for count in counts]

    reference_share = histogram(reference)
    current_share = histogram(current)
    return sum((cur - ref) * math.log(cur / ref)
               for ref, cur in zip(reference_share, current_share))


def ks_statistic(reference, current) -> float | None:
    """Largest vertical gap between the two empirical CDFs."""
    reference = sorted(float(value) for value in reference)
    current = sorted(float(value) for value in current)
    if not reference or not current:
        return None
    merged = sorted(set(reference) | set(current))
    largest = 0.0
    i = j = 0
    for value in merged:
        while i < len(reference) and reference[i] <= value:
            i += 1
        while j < len(current) and current[j] <= value:
            j += 1
        largest = max(largest, abs(i / len(reference) - j / len(current)))
    return largest


def wasserstein_distance(reference, current) -> float | None:
    """1-Wasserstein distance, in the signal's own units.

    Computed as the mean absolute difference between the two quantile functions
    on a common grid — the one-dimensional case where the optimal transport plan
    is just "match the sorted values".
    """
    reference = sorted(float(value) for value in reference)
    current = sorted(float(value) for value in current)
    if len(reference) < 2 or len(current) < 2:
        return None
    grid = 200

    def quantile(values, probability):
        position = probability * (len(values) - 1)
        low = int(math.floor(position))
        high = min(low + 1, len(values) - 1)
        weight = position - low
        return values[low] * (1 - weight) + values[high] * weight

    return statistics.fmean(
        abs(quantile(current, (index + 0.5) / grid)
            - quantile(reference, (index + 0.5) / grid))
        for index in range(grid))


def _by_session(rows, key='value'):
    grouped = {}
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        grouped.setdefault(row['as_of'], []).append(float(value))
    return grouped


def session_permutation_p(reference_sessions, current_sessions, statistic,
                          *, permutations=500, seed=20260830):
    """Null built by swapping whole sessions between the windows.

    The textbook p-value for any of these statistics assumes independent
    observations. Twenty-one names on one session are not twenty-one
    independent draws — on a directional day they are closer to one — and the
    textbook answer would report a catastrophic drift for an ordinary week.
    Permuting sessions keeps whatever correlation a session has and breaks only
    the association with which window it fell in.
    """
    days = list(reference_sessions) + list(current_sessions)
    pool = {**reference_sessions, **current_sessions}
    if len(reference_sessions) < 2 or len(current_sessions) < 2:
        return None
    observed = statistic(
        [value for day in reference_sessions for value in pool[day]],
        [value for day in current_sessions for value in pool[day]])
    if observed is None:
        return None
    rng = random.Random(seed)
    split = len(reference_sessions)
    at_least = 0
    for _ in range(permutations):
        shuffled = days[:]
        rng.shuffle(shuffled)
        drawn = statistic(
            [value for day in shuffled[:split] for value in pool[day]],
            [value for day in shuffled[split:] for value in pool[day]])
        if drawn is not None and drawn >= observed:
            at_least += 1
    # +1 on both sides: the observed split is itself one arrangement, so a
    # p-value of exactly zero is not a claim this null can support.
    return round((at_least + 1) / (permutations + 1), 5)


def signal_drift(rows, *, recent_sessions=10, permutations=500) -> dict:
    """Reference window versus the most recent `recent_sessions`, one signal.

    The split is by session and the reference is everything before it, so the
    comparison is "does the last two weeks still look like the history" rather
    than a comparison of two arbitrary halves.
    """
    by_session = _by_session(rows)
    days = sorted(by_session)
    if len(days) < MIN_SESSIONS_PER_WINDOW + recent_sessions:
        return {'status': 'insufficient_sample', 'n_sessions': len(days),
                'required': MIN_SESSIONS_PER_WINDOW + recent_sessions}
    reference_days = days[:-recent_sessions]
    current_days = days[-recent_sessions:]
    reference = [value for day in reference_days for value in by_session[day]]
    current = [value for day in current_days for value in by_session[day]]

    psi = population_stability_index(reference, current)
    band = None
    if psi is not None:
        band = next(name for threshold, name in PSI_BANDS if psi < threshold)
    reference_windows = {day: by_session[day] for day in reference_days}
    current_windows = {day: by_session[day] for day in current_days}
    return {
        'status': 'measured',
        'reference': {'sessions': len(reference_days), 'n': len(reference),
                      'first': reference_days[0], 'last': reference_days[-1],
                      'median': round(statistics.median(reference), 6)},
        'current': {'sessions': len(current_days), 'n': len(current),
                    'first': current_days[0], 'last': current_days[-1],
                    'median': round(statistics.median(current), 6)},
        'psi': round(psi, 6) if psi is not None else None,
        'psi_band': band,
        'ks': round(ks_statistic(reference, current), 6),
        'wasserstein': round(wasserstein_distance(reference, current), 6),
        'ks_session_permutation_p': session_permutation_p(
            reference_windows, current_windows, ks_statistic,
            permutations=permutations),
        'wasserstein_session_permutation_p': session_permutation_p(
            reference_windows, current_windows, wasserstein_distance,
            permutations=permutations),
        'null': ('whole sessions permuted between the windows; the textbook '
                 'p-value would treat one directional day as twenty-one '
                 'independent observations'),
    }


def panel_drift(panel, *, recent_sessions=10, permutations=500) -> dict:
    """Every registered signal, scored for distributional drift.

    Takes the long-format panel `signal_panel.build_panel` already produces, so
    a new source becomes drift-monitored by being registered rather than by
    anyone remembering to add it here.
    """
    by_signal = {}
    for row in panel:
        by_signal.setdefault(row['signal'], []).append(row)
    out = {
        signal: signal_drift(rows, recent_sessions=recent_sessions,
                             permutations=permutations)
        for signal, rows in sorted(by_signal.items())
    }
    measured = [(name, row) for name, row in out.items()
                if row.get('status') == 'measured']

    def _flagged(row) -> bool:
        significant = (row.get('ks_session_permutation_p') or 1.0) <= 0.05
        if not significant:
            return False
        if row.get('psi') is not None:
            return row.get('psi_band') in ('moderate_shift', 'major_shift')
        # PSI is unavailable for a tie-heavy signal — the sector-neutral ranks
        # take about seven distinct values, so equal-mass reference bins
        # collide. Requiring a PSI band would have made every rank signal
        # unflaggable no matter how far it moved, which is the wrong kind of
        # quiet. The effect-size floor stands in for the band.
        return (row.get('ks') or 0.0) >= 0.10

    flagged = sorted((name for name, row in measured if _flagged(row)),
                     key=lambda name: -(out[name].get('psi')
                                        or out[name].get('ks') or 0))
    share = round(len(flagged) / len(measured), 4) if measured else None
    return {
        'schema_version': 1,
        'recent_sessions': recent_sessions,
        'signals': out,
        'n_measured': len(measured),
        'n_psi_unavailable': sum(1 for _, row in measured if row.get('psi') is None),
        # Both conditions, not either: PSI has conventional bands and no null,
        # the permutation has a null and no interpretable scale. A signal that
        # moves on one alone is worth looking at and is not worth an alert.
        'flagged': flagged,
        'flagged_share': share,
        # The number that says whether this table is usable as an alert. On
        # 2026-08-30 it was 0.59 — nineteen of thirty-two — and that is not a
        # threshold to tune down. A ten-session window against a reference of
        # two to three months that contains one regime change will flag nearly
        # everything, correctly, and a detector that fires on nearly everything
        # cannot discriminate. The fix is a reference window long enough to hold
        # more than one regime, not a stricter cut-off; tuning the cut-off until
        # fewer fire is a search over the alert rate.
        'discriminating': bool(share is not None and share <= 0.25),
        'reading': ('flagged means the session permutation could not reproduce '
                    'the move AND the size passed a band (PSI where it exists, '
                    'the KS statistic where the signal is too tie-heavy to bin). '
                    'A flagged_share above a quarter means the reference window '
                    'does not span enough regimes for this to discriminate, and '
                    'the table is a description rather than an alert'),
    }
