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
2. **Permutation** — the null is "the dial's timing carries no information". The
   exposure path is circularly shifted against the returns, which preserves its
   length, its time-in-market and its autocorrelation while destroying the
   alignment. The p-value is where the observed improvement lands in that null.
3. **Sensitivity** — the metric surface over the (MA, vol-cap) grid, so a
   knife-edge fit is visible rather than implied.

It models the *production* dial
-------------------------------
Existing backtests model 2x→cash or 2x→1x. Neither is what ships:
`compute_regime.classify` emits a tier multiplier (green 1.0 / amber 0.5 / red
0.0) that scales the leveraged-ETF cap. This module applies that same mapping to
a 2x sleeve, so the thing being validated is the thing in production.

This never writes to the live pipeline. It prints, and it leaves a run card.

Run:
  python3 scripts/data/validate_regime_dial.py
  python3 scripts/data/validate_regime_dial.py --folds 4 --permutations 5000
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock import compute_regime, run_card  # noqa: E402
from clawock.workspace import workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
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

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--folds', type=int, default=4)
    ap.add_argument('--permutations', type=int, default=2000)
    ap.add_argument('--no-card', action='store_true',
                    help='skip writing a run card (for ad-hoc exploration)')
    args = ap.parse_args()

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
                    'ma_grid': list(MA_GRID), 'vol_cap_grid': list(VOL_CAP_GRID),
                    'production': {'ma': PROD_MA, 'vol_cap': PROD_VOL_CAP,
                                   'vol_window': PROD_VOL_WINDOW},
                    'base_leverage': BASE_LEVERAGE, 'tier_mult': TIER_MULT},
            inputs=[{'symbol': 'hkHSTECH', 'source': 'tencent kline (day, unadjusted)',
                     'bars': len(closes), 'first_session': dates[0],
                     'last_session': dates[-1],
                     'digest': run_card.series_digest(data)}],
            metrics={'in_sample': in_sample, 'tier_distribution': tiers,
                     'walk_forward': wf, 'permutation': perm,
                     'sensitivity': surface},
            code_files=[__file__, Path(compute_regime.__file__)],
            notes=['models the production tier mapping (green/amber/red -> '
                   '1.0/0.5/0.0) applied to a 2x sleeve, not 2x->cash'],
        )
        print(f'\nrun card: {card.relative_to(WS)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
