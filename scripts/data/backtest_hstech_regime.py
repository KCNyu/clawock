#!/usr/bin/env python3
"""
backtest_hstech_regime.py — verify the "regime de-risking" thesis on real data.

Pulls 2021→now daily HSTECH (Hang Seng Tech) closes from Tencent kline and
backtests whether a simple INDEX-level regime filter (200DMA trend + realized-vol
band) would have cut drawdown on a 2x-leveraged-HSTECH sleeve — which is exactly
kcn's dominant exposure (07226 + MINIMAX + 恒科ETF cluster).

This is RESEARCH/VERIFICATION (step B). It writes nothing into the live pipeline;
it prints a table so we can decide whether to wire the regime score into the
risk guardrail (step A).

Run:
  python3 scripts/data/backtest_hstech_regime.py
  python3 scripts/data/backtest_hstech_regime.py --ma 150 --vol-cap 0.45
"""
import argparse
import math
import os
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_card  # noqa: E402  every backtest leaves evidence behind

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402

WS = workspace_root(Path(__file__).resolve().parents[2])
TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'


def fetch_hstech(start='2021-01-01', end=None, lim=2000):
    end = end or date.today().isoformat()
    url = f'{TENCENT}?param=hkHSTECH,day,{start},{end},{lim}'
    d = requests.get(url, timeout=20).json()
    rows = (d.get('data') or {}).get('hkHSTECH', {})
    series = rows.get('day') or rows.get('qfqday') or []
    out = []
    for r in series:
        try:
            out.append((r[0], float(r[2])))  # (date, close)
        except (IndexError, ValueError):
            continue
    return out


def sma(vals, n):
    """Trailing simple moving average; None until n samples exist."""
    out = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def realized_vol(rets, n, i):
    """Annualised stdev of the trailing n daily returns ending at i."""
    if i < n:
        return None
    window = rets[i - n + 1:i + 1]
    m = sum(window) / n
    var = sum((x - m) ** 2 for x in window) / (n - 1)
    return math.sqrt(var) * math.sqrt(252)


def max_drawdown(nav, dates=None):
    peak = -1e9
    peak_i = 0
    mdd = 0.0
    trough_i = 0
    for i, v in enumerate(nav):
        if v > peak:
            peak = v
            peak_i = i
        dd = v / peak - 1
        if dd < mdd:
            mdd = dd
            trough_i = i
            mdd_peak_i = peak_i
    if dates is None:
        return mdd
    return mdd, dates[mdd_peak_i], dates[trough_i]


def cagr(nav, dates):
    yrs = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    return (nav[-1] / nav[0]) ** (1 / yrs) - 1 if yrs > 0 else 0.0


def window_dd(nav, dates, d0, d1):
    """Max drawdown restricted to [d0, d1]."""
    seg = [v for v, dt in zip(nav, dates) if d0 <= dt <= d1]
    return max_drawdown(seg) if seg else 0.0


def run(ma=200, vol_cap=0.50, vol_n=20):
    data = fetch_hstech()
    dates = [d for d, _ in data]
    closes = [c for _, c in data]
    n = len(closes)
    print(f'HSTECH daily: {n} bars  {dates[0]} → {dates[-1]}\n')

    rets = [0.0] + [closes[i] / closes[i - 1] - 1 for i in range(1, n)]
    ma_line = sma(closes, ma)
    vols = [realized_vol(rets, vol_n, i) for i in range(n)]

    # NAV series for each strategy, all starting at 1.0
    bh1 = [1.0]   # buy & hold index (1x)
    bh2 = [1.0]   # buy & hold 2x daily-reset ETF (captures decay naturally)
    reg = [1.0]   # 2x ETF, held only when regime risk-ON, else cash
    rgv = [1.0]   # 2x ETF, held only when trend-ON AND vol below cap
    r1x = [1.0]   # 1x index, held only when trend-ON, else cash (de-levered dial)
    pos_reg, pos_rgv = [], []   # exposure each day (for time-in-market / whipsaw)

    for i in range(1, n):
        r = rets[i]
        lev = 1 + 2 * r  # 2x daily reset
        # Signal uses YESTERDAY's close/ma/vol → no look-ahead.
        trend_on = ma_line[i - 1] is not None and closes[i - 1] > ma_line[i - 1]
        vol_ok = vols[i - 1] is not None and vols[i - 1] < vol_cap
        bh1.append(bh1[-1] * (1 + r))
        bh2.append(bh2[-1] * lev)
        reg.append(reg[-1] * (lev if trend_on else 1.0))
        rgv.append(rgv[-1] * (lev if (trend_on and vol_ok) else 1.0))
        r1x.append(r1x[-1] * ((1 + r) if trend_on else 1.0))
        pos_reg.append(1 if trend_on else 0)
        pos_rgv.append(1 if (trend_on and vol_ok) else 0)

    def switches(pos):
        return sum(1 for a, b in zip(pos, pos[1:]) if a != b)

    crash0, crash1 = '2021-02-01', '2022-10-31'
    rows = [
        ('Buy&Hold 1x (index)', bh1, None),
        ('Buy&Hold 2x ETF', bh2, None),
        (f'Regime 2x ({ma}DMA)', reg, pos_reg),
        (f'Regime+Vol 2x ({ma}DMA,<{int(vol_cap*100)}%)', rgv, pos_rgv),
        (f'Regime 1x ({ma}DMA, de-levered)', r1x, pos_reg),
    ]
    print(f'{"strategy":<36}{"totRet":>8}{"CAGR":>7}{"maxDD":>8}{"21-22DD":>9}{"%inMkt":>7}{"sw":>4}  maxDD window')
    print('-' * 96)
    measured = {}
    for name, nav, pos in rows:
        tot = nav[-1] / nav[0] - 1
        cg = cagr(nav, dates)
        mdd, dp, dt = max_drawdown(nav, dates)
        cdd = window_dd(nav, dates, crash0, crash1)
        inmkt = (sum(pos) / len(pos) * 100) if pos else 100.0
        sw = switches(pos) if pos else 0
        print(f'{name:<36}{tot*100:>7.0f}%{cg*100:>6.1f}%{mdd*100:>7.1f}%{cdd*100:>8.1f}%{inmkt:>6.0f}%{sw:>4}  {dp}→{dt}')
        measured[name] = {
            'total_return': round(tot, 6), 'cagr': round(cg, 6),
            'max_drawdown': round(mdd, 6), 'max_dd_window': f'{dp}→{dt}',
            'crash_2021_2022_drawdown': round(cdd, 6),
            'pct_time_in_market': round(inmkt, 2), 'switches': sw,
        }

    # What does the rule say RIGHT NOW?
    print('\n--- current regime read (as of last bar) ---')
    print(f'  HSTECH close      : {closes[-1]:.0f}')
    print(f'  {ma}DMA             : {ma_line[-1]:.0f}' if ma_line[-1] else f'  {ma}DMA: n/a')
    if ma_line[-1]:
        print(f'  close vs {ma}DMA    : {"ABOVE ✅ trend-on" if closes[-1] > ma_line[-1] else "BELOW ⛔ trend-off"} ({(closes[-1]/ma_line[-1]-1)*100:+.1f}%)')
    print(f'  20d realized vol  : {vols[-1]*100:.0f}% annualised' if vols[-1] else '  vol: n/a')
    if vols[-1] is not None:
        print(f'  vol vs {int(vol_cap*100)}% cap     : {"OK ✅" if vols[-1] < vol_cap else "HOT ⛔ decay tax high"}')

    card = run_card.record(
        'hstech_regime',
        params={'ma': ma, 'vol_cap': vol_cap, 'vol_n': vol_n,
                'crash_window': [crash0, crash1]},
        inputs=[{
            'symbol': 'hkHSTECH', 'source': 'tencent kline (day, unadjusted)',
            'bars': n, 'first_session': dates[0], 'last_session': dates[-1],
            'digest': run_card.series_digest(data),
        }],
        metrics=measured,
        code_files=[__file__, Path(__file__).with_name('compute_regime.py')],
        notes=['thresholds are calibrated on this same window; see #233'],
    )
    print(f'\nrun card: {card.relative_to(WS)}')
    return measured


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--ma', type=int, default=200)
    ap.add_argument('--vol-cap', type=float, default=0.50)
    ap.add_argument('--vol-n', type=int, default=20)
    args = ap.parse_args()
    run(ma=args.ma, vol_cap=args.vol_cap, vol_n=args.vol_n)
