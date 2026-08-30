"""A mean IC cannot say where the information is, or what holding it costs (#1161).

Rank IC is one number for a whole cross-section, and two questions it silently
merges decide how a signal would actually be used:

* **Which end carries it.** A signal whose top bucket outperforms while its
  bottom bucket is indistinguishable from the middle is a long-only screen; one
  whose bottom bucket carries everything is an avoid-list. The same IC is
  produced by both, and by a signal with both ends live.
* **What it costs to hold.** An edge with 90% daily turnover is paid back in
  spread every session. An edge quoted without its turnover is a gross number.

`quantile_structure` and `persistence` answer those two. These tests hold them
to the cases where the IC and the buckets disagree — which is the entire reason
for adding them.
"""
import statistics

from clawock.evaluation import signal_panel


def _rows(per_session, signal='test.signal', horizon='t5'):
    """per_session: {session: {ticker: (value, forward_return)}}"""
    out = []
    for session, names in per_session.items():
        for ticker, (value, forward) in names.items():
            out.append({'as_of': session, 'ticker': ticker, 'signal': signal,
                        'value': value, horizon: forward, 'leg': 'us'})
    return out


def _monotone_panel(sessions=12, names=12, slope=1.0, seed=5):
    import random
    rnd = random.Random(seed)
    per_session = {}
    for index in range(sessions):
        session = f'2026-06-{index + 1:02d}'
        per_session[session] = {
            f'T{name}': (float(name), slope * name + rnd.gauss(0, 0.5))
            for name in range(names)}
    return per_session


def test_a_monotone_signal_has_a_spread_that_clears_zero():
    result = signal_panel.quantile_structure(_rows(_monotone_panel()), 't5')
    assert result['status'] == 'diagnostic'
    assert result['spread'] > 0
    assert result['spread_clears_zero']
    assert result['monotone'] is True


def test_a_one_sided_signal_is_visible_as_one_sided():
    """Only the top bucket moves; the other two are the same.

    The IC and the spread both come out positive. Splitting the spread into its
    two halves is what says this is a long-only screen rather than a long-short
    signal — and that distinction is the whole difference between two ways of
    using it.
    """
    per_session = {}
    for index in range(12):
        session = f'2026-06-{index + 1:02d}'
        names = {}
        for name in range(12):
            forward = 5.0 if name >= 8 else 0.0
            names[f'T{name}'] = (float(name), forward)
        per_session[session] = names
    result = signal_panel.quantile_structure(_rows(per_session), 't5')
    assert result['top_minus_middle'] > 4.0
    assert abs(result['middle_minus_bottom']) < 0.001


def test_a_hump_is_invisible_to_both_the_ic_and_the_spread():
    """The live case this catches: `quant.dist_ma200_pct`.

    Its mean IC is -0.001 — indistinguishable from nothing — while its tertile
    means are -6.05 / -0.36 / -2.70: the middle third outperformed both ends by
    several points. Rank correlation cancels across a hump, and so does a
    top-minus-bottom spread. Only the buckets show it, which is why all three
    are published rather than one summary of them.

    Here the middle third outperforms by five points and *both* summary numbers
    say nothing is happening.
    """
    per_session = {}
    for index in range(12):
        session = f'2026-06-{index + 1:02d}'
        per_session[session] = {
            f'T{name}': (float(name), 5.0 if 4 <= name <= 7 else 0.0)
            for name in range(12)}
    rows = _rows(per_session)
    ic = signal_panel.score_signal(rows, 't5')['mean_ic']
    result = signal_panel.quantile_structure(rows, 't5')
    assert abs(ic) < 0.25                       # the ordering says nothing
    assert abs(result['spread']) < 1e-9         # and neither does top-minus-bottom
    assert result['middle_minus_bottom'] > 4.9  # while the middle carries five points
    assert result['top_minus_middle'] < -4.9
    assert result['monotone'] is False


def test_turnover_is_zero_for_a_signal_that_never_reorders():
    per_session = {f'2026-06-{index + 1:02d}':
                   {f'T{name}': (float(name), 0.0) for name in range(12)}
                   for index in range(10)}
    holding = signal_panel.persistence(_rows(per_session))
    assert holding['top_bucket_turnover'] == 0.0
    assert holding['rank_autocorrelation'] == 1.0


def test_turnover_is_high_for_a_signal_that_reshuffles_every_session():
    import random
    rnd = random.Random(3)
    per_session = {}
    for index in range(30):
        values = list(range(12))
        rnd.shuffle(values)
        per_session[f'2026-06-{index + 1:02d}'] = {
            f'T{name}': (float(values[name]), 0.0) for name in range(12)}
    holding = signal_panel.persistence(_rows(per_session))
    assert holding['top_bucket_turnover'] > 0.5
    assert abs(holding['rank_autocorrelation']) < 0.4


def test_turnover_and_the_spread_are_reported_together():
    """The pairing is the point.

    On the live panel `news.signed_score` is the only source whose t5 spread
    clears zero (+3.30) and it replaces 63% of its top bucket every session with
    a rank autocorrelation of +0.02. Either number alone tells the wrong story.
    """
    panel = signal_panel.evaluate(
        _rows(_monotone_panel(), signal='news.signed_score'))
    section = panel['signals']['news.signed_score']
    assert 'quantiles' in section and 'persistence' in section
    assert section['quantiles']['t5']['spread'] is not None
    assert section['persistence']['top_bucket_turnover'] is not None


def test_a_narrow_cross_section_is_refused_rather_than_bucketed():
    """Three names cannot be split into three buckets and mean anything."""
    per_session = {f'2026-06-{index + 1:02d}':
                   {f'T{name}': (float(name), float(name)) for name in range(3)}
                   for index in range(12)}
    result = signal_panel.quantile_structure(_rows(per_session), 't5')
    assert result['status'] == 'collecting'
    assert result['spread'] is None
    assert result['n_sessions_too_narrow'] == 12


def test_a_flat_cross_section_scores_zero_spread_rather_than_dropping_the_session():
    """Dropping flat days would restrict the measurement to lively ones.

    That is a selection: an event-count signal is flat most days, and scoring it
    only on the days it fired would quietly change the population being measured.
    """
    per_session = {f'2026-06-{index + 1:02d}':
                   {f'T{name}': (0.0, 1.0) for name in range(12)}
                   for index in range(12)}
    result = signal_panel.quantile_structure(_rows(per_session), 't5')
    assert result['status'] == 'diagnostic'
    assert result['n_sessions'] == 12
    assert abs(result['spread']) < 1e-9
