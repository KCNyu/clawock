#!/usr/bin/env python3
"""Is the leverage dial evidence, or one lucky crash?

The problem
-----------
`compute_regime.py` gates the largest exposure in the book, and its justification
is a single in-sample number: the 200DMA / 20d-vol thresholds were chosen on the
same 2021→now HSTECH window the improvement is reported on, and the effective
sample contains roughly *one* crash. A -95% → -44% headline from a fit over one
regime transition is exactly the kind of number that does not survive contact
with the next one.

The repo already holds itself to a higher bar elsewhere: `cross_sectional_factor`
refuses to activate a rule on retrospective evidence and validates walk-forward,
and `quant_signal_review` gates factors on a clustered bootstrap CI that must not
cross 50%. The dial is the one place where the strongest claim rested on the
weakest evidence.

What this measures
------------------
1. **Walk-forward** — thresholds are chosen on a training window and scored on
   the *next* window only, rolling forward. Per-window out-of-sample results, not
   one full-period headline.
2. **Selection (PBO)** — walk-forward reports four draws of "does the chosen
   threshold hold up"; with 16 candidates on one index that is too few to
   separate a rule from a search. Combinatorially symmetric cross-validation
   ranks the same candidates in both halves of every symmetric split, purged
   with a two-sided embargo, and reports how often the in-sample winner lands
   below the out-of-sample median (#1114).
3. **Permutation** — the null is "the dial's timing carries no information". The
   exposure path is circularly shifted against the returns, which preserves its
   length, its time-in-market and its autocorrelation while destroying the
   alignment. The p-value is where the observed improvement lands in that null.
4. **Sensitivity** — the metric surface over the (MA, vol-cap) grid, so a
   knife-edge fit is visible rather than implied.

It models the *production* dial
-------------------------------
Existing backtests model 2x→cash or 2x→1x. Neither is what ships:
`compute_regime.classify` emits a tier multiplier (green 1.0 / amber 0.5 / red
0.0) that scales the leveraged-ETF cap. This module applies that same mapping to
a 2x sleeve, so the thing being validated is the thing in production.

This never writes to the live pipeline. It prints, and it leaves a run card.

Run:
  clawock validate-regime-dial
  clawock validate-regime-dial --folds 4 --permutations 5000 --groups 8
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import date
from pathlib import Path

import requests

from clawock.decision import regime as compute_regime
from clawock.evaluation import cscv
from clawock.evidence import run_card
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'

# Production defaults, imported in spirit from compute_regime so the validated
# object is the shipped one. Kept as literals rather than an import so this
# script stays runnable when compute_regime's module-level fetch is unavailable.
PROD_MA, PROD_VOL_CAP, PROD_VOL_WINDOW = 200, 0.50, 20
BASE_LEVERAGE = 2.0
TIER_MULT = {'green': 1.0, 'amber': 0.5, 'red': 0.0}

MA_GRID = (100, 150, 200, 250)
VOL_CAP_GRID = (0.40, 0.50, 0.60, 0.70)


# ── data ────────────────────────────────────────────────────────────────────

def fetch_hstech(start='2021-01-01', end=None, lim=2000):
    end = end or date.today().isoformat()
    url = f'{TENCENT}?param=hkHSTECH,day,{start},{end},{lim}'
    payload = requests.get(url, timeout=20).json()
    rows = (payload.get('data') or {}).get('hkHSTECH', {})
    out = []
    for row in rows.get('day') or rows.get('qfqday') or []:
        try:
            out.append((row[0], float(row[2])))
        except (IndexError, ValueError, TypeError):
            continue
    return out


# ── the dial, as production defines it ──────────────────────────────────────

def trailing_mean(values, window):
    out, total = [None] * len(values), 0.0
    for i, value in enumerate(values):
        total += value
        if i >= window:
            total -= values[i - window]
        if i >= window - 1:
            out[i] = total / window
    return out


def realized_vol(returns, window, i):
    """Annualised stdev of the trailing `window` returns ending at `i`."""
    if i < window:
        return None
    sample = returns[i - window + 1:i + 1]
    mean = sum(sample) / window
    variance = sum((x - mean) ** 2 for x in sample) / (window - 1)
    return math.sqrt(variance) * math.sqrt(252)


def tier_for(trend_on, vol_ok):
    """compute_regime.classify's mapping, isolated so drift is visible."""
    if trend_on and vol_ok:
        return 'green'
    if (not trend_on) and (not vol_ok):
        return 'red'
    return 'amber'


def exposure_path(closes, *, ma_window=PROD_MA, vol_cap=PROD_VOL_CAP,
                  vol_window=PROD_VOL_WINDOW, base=BASE_LEVERAGE):
    """Daily leverage the dial would have permitted. Index i uses data up to i-1.

    Look-ahead is structurally impossible: the signal for day i is built from
    closes and vols through i-1, exactly as the live dial reads yesterday's bar.
    """
    n = len(closes)
    returns = [0.0] + [closes[i] / closes[i - 1] - 1 for i in range(1, n)]
    ma = trailing_mean(closes, ma_window)
    vols = [realized_vol(returns, vol_window, i) for i in range(n)]

    exposure, tiers = [], []
    for i in range(1, n):
        trend_on = ma[i - 1] is not None and closes[i - 1] > ma[i - 1]
        vol_ok = vols[i - 1] is not None and vols[i - 1] < vol_cap
        tier = tier_for(trend_on, vol_ok)
        tiers.append(tier)
        exposure.append(base * TIER_MULT[tier])
    return returns[1:], exposure, tiers


def nav_from(returns, exposure):
    nav = [1.0]
    for ret, lev in zip(returns, exposure):
        nav.append(nav[-1] * (1 + lev * ret))
    return nav


def max_drawdown(nav):
    peak, worst = -1e9, 0.0
    for value in nav:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    return worst


def tier_distribution(tiers):
    """How often each tier actually fires — the mechanism behind the result.

    The dial only reaches `red` when trend-off AND vol-hot coincide. HSTECH's
    20d vol sits below 50% for much of a slow decline, so `amber` (half the cap,
    i.e. 1x on a 2x sleeve) is the common crash state, not cash.
    """
    total = len(tiers)
    counts = {tier: tiers.count(tier) for tier in ('green', 'amber', 'red')}
    return {
        'sessions': total,
        'counts': counts,
        'pct': {tier: round(100 * n / total, 1) if total else None
                for tier, n in counts.items()},
    }


def summarize(returns, exposure, base=BASE_LEVERAGE):
    """Dial vs an always-on sleeve over the same returns."""
    dial = nav_from(returns, exposure)
    hold = nav_from(returns, [base] * len(returns))
    dial_dd, hold_dd = max_drawdown(dial), max_drawdown(hold)
    return {
        'n_sessions': len(returns),
        'dial_total_return': round(dial[-1] - 1, 6),
        'hold_total_return': round(hold[-1] - 1, 6),
        'dial_max_drawdown': round(dial_dd, 6),
        'hold_max_drawdown': round(hold_dd, 6),
        # Positive = the dial made the drawdown shallower.
        'drawdown_improvement': round(dial_dd - hold_dd, 6),
        'return_improvement': round(dial[-1] - hold[-1], 6),
        'pct_time_at_full_leverage': round(
            100 * sum(1 for e in exposure if e >= base) / len(exposure), 2)
        if exposure else None,
    }


# ── 1. walk-forward ─────────────────────────────────────────────────────────

def _score(returns, exposure):
    """Calibration objective: shallower drawdown first, return as tie-break.

    The dial exists to control drawdown, so it is selected on drawdown. Choosing
    on return instead would validate a different instrument than the one shipped.
    """
    stats = summarize(returns, exposure)
    return (stats['drawdown_improvement'], stats['return_improvement'])


def best_thresholds(closes, ma_grid=MA_GRID, vol_grid=VOL_CAP_GRID):
    best, best_score = None, None
    for ma_window in ma_grid:
        for vol_cap in vol_grid:
            returns, exposure, _ = exposure_path(
                closes, ma_window=ma_window, vol_cap=vol_cap)
            if not returns:
                continue
            score = _score(returns, exposure)
            if best_score is None or score > best_score:
                best, best_score = (ma_window, vol_cap), score
    return best


def walk_forward(dates, closes, *, folds=4, ma_grid=MA_GRID, vol_grid=VOL_CAP_GRID):
    """Calibrate on a leading window, score on the next one, roll forward.

    Warmup matters: a fold shorter than the longest MA in the grid cannot form a
    signal, so the split is over the usable tail and each training window keeps
    every bar before it.
    """
    longest = max(ma_grid)
    usable_start = longest + max(VOL_CAP_GRID and [PROD_VOL_WINDOW] or [0])
    if len(closes) <= usable_start + folds * 2:
        return {'folds': [], 'reason': (
            f'{len(closes)} bars cannot support {folds} folds after a '
            f'{usable_start}-bar warmup')}

    span = len(closes) - usable_start
    edges = [usable_start + round(span * k / (folds + 1)) for k in range(folds + 2)]

    results = []
    for k in range(1, folds + 1):
        train_end, test_end = edges[k], edges[k + 1]
        chosen = best_thresholds(closes[:train_end], ma_grid, vol_grid)
        if chosen is None:
            continue
        ma_window, vol_cap = chosen

        # Score on the test slice only, but build the signal from the full
        # history up to each point — otherwise the first 200 test bars have no
        # MA and the fold would measure warmup, not the rule.
        returns, exposure, _ = exposure_path(
            closes[:test_end], ma_window=ma_window, vol_cap=vol_cap)
        offset = train_end - 1
        oos = summarize(returns[offset:], exposure[offset:])

        prod_returns, prod_exposure, _ = exposure_path(closes[:test_end])
        prod = summarize(prod_returns[offset:], prod_exposure[offset:])

        results.append({
            'fold': k,
            'train': [dates[0], dates[train_end - 1]],
            'test': [dates[train_end], dates[test_end - 1]],
            'chosen_ma': ma_window,
            'chosen_vol_cap': vol_cap,
            'chosen_matches_production': bool(
                ma_window == PROD_MA and abs(vol_cap - PROD_VOL_CAP) < 1e-9),
            'out_of_sample': oos,
            'production_thresholds_out_of_sample': prod,
        })

    improvements = [r['out_of_sample']['drawdown_improvement'] for r in results]
    prod_improvements = [
        r['production_thresholds_out_of_sample']['drawdown_improvement']
        for r in results]
    return {
        'folds': results,
        'n_folds': len(results),
        'folds_with_shallower_drawdown': sum(1 for x in improvements if x > 0),
        'mean_drawdown_improvement': (
            round(sum(improvements) / len(improvements), 6) if improvements else None),
        'production_mean_drawdown_improvement': (
            round(sum(prod_improvements) / len(prod_improvements), 6)
            if prod_improvements else None),
        'threshold_stability': (
            'stable' if len({(r['chosen_ma'], r['chosen_vol_cap']) for r in results}) == 1
            else 'unstable'),
    }


# ── 1b. selection: probability of backtest overfitting ──────────────────────

#: Fraction of the sample embargoed on each side of a test block. One percent is
#: López de Prado's default and is what the label horizon needs here (the dial's
#: label is one session). It is deliberately *not* the 200-bar MA window: a
#: trailing mean is available in real time, so sharing it across a boundary is
#: not look-ahead, and embargoing it would delete most of every training half —
#: a purge that leaves nothing to select on measures nothing.
EMBARGO_FRACTION = 0.01


def _config_columns(closes, ma_grid, vol_grid):
    """Per-bar (dial return, always-on return) for every threshold pair.

    Computed once over the whole sample and sliced afterwards, which is sound
    precisely because `exposure_path` is trailing-only: bar i's exposure is
    built from closes through i-1 whichever window it is later scored in.
    """
    configs, columns = [], []
    for ma_window in ma_grid:
        for vol_cap in vol_grid:
            returns, exposure, _ = exposure_path(
                closes, ma_window=ma_window, vol_cap=vol_cap)
            if not returns:
                continue
            configs.append({'ma': ma_window, 'vol_cap': vol_cap})
            columns.append([(exposure[i] * returns[i], BASE_LEVERAGE * returns[i])
                            for i in range(len(returns))])
    return configs, columns


def _drawdown_improvement(pairs):
    """The selection objective, over an arbitrary subset of bars.

    Same quantity `_score` ranks on, so CSCV measures the search that
    `best_thresholds` actually performs rather than a proxy for it.
    """
    if not pairs:
        return None
    dial = hold = 1.0
    dial_peak = hold_peak = 1.0
    dial_dd = hold_dd = 0.0
    for dial_ret, hold_ret in pairs:
        dial *= 1 + dial_ret
        hold *= 1 + hold_ret
        dial_peak, hold_peak = max(dial_peak, dial), max(hold_peak, hold)
        dial_dd = min(dial_dd, dial / dial_peak - 1)
        hold_dd = min(hold_dd, hold / hold_peak - 1)
    return dial_dd - hold_dd


def overfitting_probability(closes, *, ma_grid=MA_GRID, vol_grid=VOL_CAP_GRID,
                            groups=8, embargo=None):
    """How often the best in-sample threshold pair is below median out of sample.

    Walk-forward answers this once per fold and reports the answer as a table;
    with 16 candidates on one index and roughly one crash in the sample, four
    draws cannot separate a rule from a search. CSCV takes every symmetric
    half-split of the sample instead, so the same 16 candidates are ranked
    against each other in both halves ~70 times.
    """
    configs, columns = _config_columns(closes, ma_grid, vol_grid)
    if not configs:
        return {'status': 'insufficient_sample',
                'reason': 'no threshold pair produced a usable exposure path',
                'pbo': None}
    warmup = max(ma_grid) + PROD_VOL_WINDOW
    length = min(len(column) for column in columns)
    if length <= warmup:
        return {'status': 'insufficient_sample',
                'reason': (f'{length} scored bars do not clear a {warmup}-bar '
                           'warmup'), 'pbo': None}
    matrix = [[column[i] for column in columns] for i in range(warmup, length)]
    if embargo is None:
        embargo = max(1, round(EMBARGO_FRACTION * len(matrix)))
    result = cscv.probability_of_backtest_overfitting(
        matrix, _drawdown_improvement, n_groups=groups, embargo=embargo)
    result['configs'] = configs
    result['objective'] = 'drawdown improvement vs an always-on 2x sleeve'
    # Read the number with this in hand: the shipped objective rewards being out
    # of the market, and de-risking reduces drawdown whether or not the timing
    # carries information. So a low PBO here says the *ranking* of thresholds is
    # stable across halves — not that the dial pays. The permutation test below
    # is what answers the second question, and the two are reported together for
    # that reason.
    result['caveat'] = (
        'the objective is the shipped one (drawdown improvement), which any '
        'de-risking rule improves; PBO measures rank stability of the search, '
        'the permutation test measures whether the timing carries information')
    result['warmup_bars_dropped'] = warmup
    if result.get('status') == 'measured':
        result['selected_thresholds'] = [
            configs[index] for index in result['selected_configs']]
        production = next(
            (index for index, config in enumerate(configs)
             if config['ma'] == PROD_MA
             and abs(config['vol_cap'] - PROD_VOL_CAP) < 1e-9), None)
        # How often the search would have landed on the thresholds that ship.
        # A dial the search never picks is not disqualified — it was
        # pre-registered, not fitted — but the gap belongs in the report rather
        # than in the reader's head.
        result['production_selected_share'] = round(
            (result['selection_counts'].get(str(production), 0)
             / result['n_splits']) if production is not None else 0.0, 4)
    return result


# ── 2. permutation ──────────────────────────────────────────────────────────

def permutation_test(returns, exposure, *, permutations=2000, seed=20260802):
    """Circular-shift null: same exposure path, wrong place in time.

    Shuffling the exposure vector outright would destroy its autocorrelation and
    make almost any real signal look significant. A circular shift keeps the
    path's shape, its time-in-market and its clustering, and only breaks the
    alignment with returns — which is precisely the thing being claimed.
    """
    if len(returns) < 30 or len(returns) != len(exposure):
        return {'p_value_drawdown': None, 'p_value_return': None,
                'reason': 'need at least 30 aligned sessions'}

    observed = summarize(returns, exposure)
    rng = random.Random(seed)
    n = len(exposure)
    dd_at_least, ret_at_least = 0, 0
    null_dd = []
    switch_counts = set()
    for _ in range(permutations):
        shift = rng.randrange(1, n)
        shifted = exposure[shift:] + exposure[:shift]
        switch_counts.add(circular_switches(shifted))
        stats = summarize(returns, shifted)
        null_dd.append(stats['drawdown_improvement'])
        if stats['drawdown_improvement'] >= observed['drawdown_improvement']:
            dd_at_least += 1
        if stats['return_improvement'] >= observed['return_improvement']:
            ret_at_least += 1

    null_dd.sort()
    # +1 in numerator and denominator: the observed path is itself one draw from
    # the null, so a p-value of exactly 0 is not a claim the data can support.
    return {
        'permutations': permutations,
        'observed_drawdown_improvement': observed['drawdown_improvement'],
        'observed_return_improvement': observed['return_improvement'],
        'p_value_drawdown': round((dd_at_least + 1) / (permutations + 1), 5),
        'p_value_return': round((ret_at_least + 1) / (permutations + 1), 5),
        'null_drawdown_improvement_median': round(null_dd[len(null_dd) // 2], 6),
        'null_drawdown_improvement_p95': round(null_dd[int(0.95 * len(null_dd))], 6),
        'null': 'circular shift of the exposure path against returns',
        # Published as proof the null is the hard one. A circular shift cannot
        # change how many times the exposure path switches level (counted
        # around the wrap), so every draw shares the observed count. A plain
        # shuffle would shatter it — and would make almost any real signal look
        # significant by comparison.
        'observed_switches': circular_switches(exposure),
        'null_switch_counts': sorted(switch_counts),
    }


def circular_switches(path):
    """How many times the path changes level, counted around the wrap."""
    if not path:
        return 0
    return sum(1 for a, b in zip(path, path[1:] + path[:1]) if a != b)


# ── 3. sensitivity ──────────────────────────────────────────────────────────

def sensitivity_surface(closes, ma_grid=MA_GRID, vol_grid=VOL_CAP_GRID):
    surface = []
    for ma_window in ma_grid:
        for vol_cap in vol_grid:
            returns, exposure, _ = exposure_path(
                closes, ma_window=ma_window, vol_cap=vol_cap)
            if not returns:
                continue
            stats = summarize(returns, exposure)
            surface.append({
                'ma': ma_window, 'vol_cap': vol_cap,
                'drawdown_improvement': stats['drawdown_improvement'],
                'return_improvement': stats['return_improvement'],
                'dial_max_drawdown': stats['dial_max_drawdown'],
            })
    surface.sort(key=lambda row: -row['drawdown_improvement'])
    best = surface[0] if surface else None
    production = next(
        (row for row in surface
         if row['ma'] == PROD_MA and abs(row['vol_cap'] - PROD_VOL_CAP) < 1e-9),
        None)
    return {
        'grid': surface,
        'best': best,
        'production': production,
        'production_rank': (surface.index(production) + 1) if production else None,
        'neighbourhood_spread': (
            round(max(r['drawdown_improvement'] for r in surface)
                  - min(r['drawdown_improvement'] for r in surface), 6)
            if surface else None),
    }


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    # One parser, parsing the argv it was handed. There used to be two: an empty
    # one that consumed `argv` so `--help` would answer through the CLI, and a
    # second that re-read `sys.argv` for the real flags. The first rejected every
    # flag the second defined, so `clawock validate-regime-dial --folds 4` — the
    # invocation this module's own docstring documents — exited 2 without ever
    # running. A `--help` gate is satisfied by any parser; it does not need a
    # parser that answers nothing else.
    ap = argparse.ArgumentParser(prog='clawock validate-regime-dial',
                                 description=__doc__)
    ap.add_argument('--folds', type=int, default=4)
    ap.add_argument('--permutations', type=int, default=2000)
    ap.add_argument('--groups', type=int, default=8,
                    help='CSCV groups; every symmetric half-split is scored')
    ap.add_argument('--no-card', action='store_true',
                    help='skip writing a run card (for ad-hoc exploration)')
    args = ap.parse_args(argv)

    data = fetch_hstech()
    if len(data) < 400:
        print(f'HSTECH fetch returned {len(data)} bars — not enough to validate',
              file=sys.stderr)
        return 1
    dates = [d for d, _ in data]
    closes = [c for _, c in data]
    print(f'HSTECH {len(closes)} bars  {dates[0]} → {dates[-1]}\n')

    full_returns, full_exposure, full_tiers = exposure_path(closes)
    in_sample = summarize(full_returns, full_exposure)
    tiers = tier_distribution(full_tiers)
    print('--- in-sample, production thresholds (this is the weak claim) ---')
    print(f'  dial maxDD {in_sample["dial_max_drawdown"]*100:.1f}%  vs '
          f'always-2x {in_sample["hold_max_drawdown"]*100:.1f}%  '
          f'(improvement {in_sample["drawdown_improvement"]*100:+.1f}pp)')
    print(f'  dial totRet {in_sample["dial_total_return"]*100:.0f}%  vs '
          f'always-2x {in_sample["hold_total_return"]*100:.0f}%')
    print(f'  tiers: green {tiers["pct"]["green"]}% (2x) · '
          f'amber {tiers["pct"]["amber"]}% (1x) · red {tiers["pct"]["red"]}% (cash)')

    wf = walk_forward(dates, closes, folds=args.folds)
    print('\n--- walk-forward (thresholds chosen on the past, scored on the next window) ---')
    if not wf.get('folds'):
        print(f'  unavailable: {wf.get("reason")}')
    else:
        print(f'{"fold":<6}{"test window":<26}{"chosen":<14}{"OOS ΔmaxDD":>12}'
              f'{"prod ΔmaxDD":>13}')
        for fold in wf['folds']:
            chosen = f'{fold["chosen_ma"]}/{fold["chosen_vol_cap"]:.2f}'
            print(f'{fold["fold"]:<6}{fold["test"][0]}→{fold["test"][1]:<14}'
                  f'{chosen:<14}'
                  f'{fold["out_of_sample"]["drawdown_improvement"]*100:>11.1f}pp'
                  f'{fold["production_thresholds_out_of_sample"]["drawdown_improvement"]*100:>12.1f}pp')
        print(f'  {wf["folds_with_shallower_drawdown"]}/{wf["n_folds"]} folds '
              f'improved drawdown out of sample · thresholds {wf["threshold_stability"]}')

    pbo = overfitting_probability(closes, groups=args.groups)
    print('\n--- selection (how much of the fit is the search itself?) ---')
    if pbo.get('status') != 'measured':
        print(f'  unavailable: {pbo.get("reason")}')
    else:
        print(f'  PBO {pbo["pbo"]:.2f} over {pbo["n_splits"]} symmetric splits of '
              f'{pbo["n_configs"]} threshold pairs · '
              f'embargo {pbo["embargo"]} bars '
              f'(~{pbo["purged_per_split"]:.0f} training bars purged per split)')
        print(f'  the in-sample winner stayed above the out-of-sample median in '
              f'{pbo["splits_where_the_winner_stayed_above_median"]}/'
              f'{pbo["n_splits"]} splits · '
              f'mean OOS degradation {pbo["mean_out_of_sample_degradation"]*100:+.1f}pp')
        ranked = sorted(pbo['selection_counts'].items(),
                        key=lambda kv: -kv[1])[:3]
        top = ' · '.join(
            f'{pbo["configs"][int(index)]["ma"]}/'
            f'{pbo["configs"][int(index)]["vol_cap"]:.2f} '
            f'({count}/{pbo["n_splits"]})' for index, count in ranked)
        print(f'  {len(pbo["selection_counts"])} distinct pairs won at least one '
              f'split; most often {top}')
        print(f'  production {PROD_MA}/{PROD_VOL_CAP:.2f} won '
              f'{pbo["production_selected_share"]*100:.0f}% of splits · '
              f'{pbo["caveat"]}')

    perm = permutation_test(full_returns, full_exposure,
                            permutations=args.permutations)
    print('\n--- permutation test (null: the timing carries no information) ---')
    if perm.get('reason'):
        print(f'  unavailable: {perm["reason"]}')
    else:
        print(f'  observed ΔmaxDD {perm["observed_drawdown_improvement"]*100:+.1f}pp · '
              f'null median {perm["null_drawdown_improvement_median"]*100:+.1f}pp · '
              f'null p95 {perm["null_drawdown_improvement_p95"]*100:+.1f}pp')
        print(f'  p(drawdown) = {perm["p_value_drawdown"]:.4f}   '
              f'p(return) = {perm["p_value_return"]:.4f}')

    surface = sensitivity_surface(closes)
    print('\n--- threshold sensitivity (is 200/0.50 a peak or a plateau?) ---')
    if surface['production']:
        print(f'  production 200/0.50 ranks {surface["production_rank"]}'
              f'/{len(surface["grid"])} on drawdown improvement; '
              f'grid spread {surface["neighbourhood_spread"]*100:.1f}pp')
        print(f'  best on this window: {surface["best"]["ma"]}/'
              f'{surface["best"]["vol_cap"]:.2f} '
              f'({surface["best"]["drawdown_improvement"]*100:+.1f}pp)')

    if not args.no_card:
        card = run_card.record(
            'regime_dial_validation',
            params={'folds': args.folds, 'permutations': args.permutations,
                    'cscv_groups': args.groups,
                    'ma_grid': list(MA_GRID), 'vol_cap_grid': list(VOL_CAP_GRID),
                    'production': {'ma': PROD_MA, 'vol_cap': PROD_VOL_CAP,
                                   'vol_window': PROD_VOL_WINDOW},
                    'base_leverage': BASE_LEVERAGE, 'tier_mult': TIER_MULT},
            inputs=[{'symbol': 'hkHSTECH', 'source': 'tencent kline (day, unadjusted)',
                     'bars': len(closes), 'first_session': dates[0],
                     'last_session': dates[-1],
                     'digest': run_card.series_digest(data)}],
            metrics={'in_sample': in_sample, 'tier_distribution': tiers,
                     'walk_forward': wf, 'overfitting': pbo, 'permutation': perm,
                     'sensitivity': surface},
            code_files=[__file__, Path(compute_regime.__file__),
                        Path(cscv.__file__)],
            notes=['models the production tier mapping (green/amber/red -> '
                   '1.0/0.5/0.0) applied to a 2x sleeve, not 2x->cash',
                   'PBO is combinatorially symmetric cross-validation over the '
                   'same 16 threshold pairs walk-forward selects from, purged '
                   'with a two-sided embargo; it measures the search, not the '
                   'skill of the shipped pre-registered dial'],
        )
        print(f'\nrun card: {card.relative_to(WS)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
