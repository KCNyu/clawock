#!/usr/bin/env python3
"""
compute_regime.py — the LEVERAGE DIAL (杠杆刻度盘).

Verified in backtest_hstech_regime.py on 2021→now real HSTECH data: an index-level
200DMA trend filter + 20d realized-vol band would have taken the 2021-22 crash
drawdown on a 2x-HSTECH sleeve from -95% to 0% (fully de-risked through the crash),
and de-levering on the same signal cut full-period maxDD from -95% → -44%.

The single biggest lever was LEVERAGE (2x→1x→cash), not timing. So this module
emits a leverage-cap MULTIPLIER that tightens the guardrail's leveraged-ETF leg cap
when the regime turns hostile — it does NOT generate buy/sell calls.

Distinct from brief_preflight._classify_regime (macro risk_on/off → HOLD bias).
This one is HSTECH trend+vol → hard leverage cap. The HK sleeve (07226 2x恒科,
MINIMAX, 恒科ETF cluster) is kcn's dominant exposure, so HSTECH is the right proxy.

Tiers:
  green (trend-on  & vol-ok)   → lev_cap_mult 1.0  (no extra tightening)
  amber (exactly one bad)      → lev_cap_mult 0.5  (halve the leveraged-ETF cap)
  red   (trend-off & vol-hot)  → lev_cap_mult 0.0  (force leveraged sleeve to ~0)

Writes: assets/data/lev_regime.json   (merge-not-overwrite on empty fetch)
Run:
  python3 scripts/data/compute_regime.py
  python3 scripts/data/compute_regime.py --dry-run
"""
import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

WS = Path(__file__).resolve().parent.parent.parent
OUT_FILE = WS / 'assets' / 'data' / 'lev_regime.json'
TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'

MA_WINDOW = 200      # slower MA = fewer falling-knife re-entries (verified vs 100/150)
VOL_WINDOW = 20
VOL_CAP = 0.50       # 20d annualised realised-vol ceiling for "vol-ok"

sys.path.insert(0, str(WS / 'scripts' / 'data'))
try:
    from safe_io import safe_write_json  # type: ignore
except Exception:
    def safe_write_json(path, data, indent=2):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=indent))


def fetch_hstech(start='2021-01-01', lim=2000):
    end = date.today().isoformat()
    url = f'{TENCENT}?param=hkHSTECH,day,{start},{end},{lim}'
    try:
        d = requests.get(url, timeout=20).json()
    except Exception as e:
        print(f'  warn: HSTECH fetch failed: {e}', file=sys.stderr)
        return []
    rows = (d.get('data') or {}).get('hkHSTECH', {})
    series = rows.get('day') or rows.get('qfqday') or []
    out = []
    for r in series:
        try:
            out.append((r[0], float(r[2])))
        except (IndexError, ValueError):
            continue
    return out


def compute(closes):
    n = len(closes)
    ma = sum(closes[-MA_WINDOW:]) / MA_WINDOW if n >= MA_WINDOW else None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(max(1, n - VOL_WINDOW), n)]
    vol = None
    if len(rets) >= VOL_WINDOW:
        m = sum(rets) / len(rets)
        var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
        vol = math.sqrt(var) * math.sqrt(252)
    return ma, vol


def classify(close, ma, vol):
    trend_on = ma is not None and close > ma
    vol_ok = vol is not None and vol < VOL_CAP
    if trend_on and vol_ok:
        tier, mult, label = 'green', 1.0, '趋势ON·波动正常：杠杆敞口可维持上限'
    elif (not trend_on) and (not vol_ok):
        tier, mult, label = 'red', 0.0, '趋势OFF且波动过热：杠杆敞口应清零'
    else:
        tier, mult, label = 'amber', 0.5, ('趋势OFF：杠杆敞口上限砍半'
                                           if not trend_on else '波动过热：杠杆敞口上限砍半')
    return trend_on, vol_ok, tier, mult, label


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    data = fetch_hstech()
    if not data:
        # merge-not-overwrite: never clobber a good prior file on a transient empty fetch
        if OUT_FILE.exists():
            print('  HSTECH fetch empty — RETAINED prior lev_regime.json', file=sys.stderr)
            return
        print('  HSTECH fetch empty and no prior file — skipping', file=sys.stderr)
        return

    dates = [d for d, _ in data]
    closes = [c for _, c in data]
    ma, vol = compute(closes)
    close = closes[-1]
    trend_on, vol_ok, tier, mult, label = classify(close, ma, vol)
    dist = round((close / ma - 1) * 100, 1) if ma else None

    out = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'as_of': dates[-1],
        'index': 'HSTECH',
        'source': 'tencent',
        'bars': len(closes),
        'close': round(close, 2),
        'ma_window': MA_WINDOW,
        'ma': round(ma, 2) if ma else None,
        'dist_ma_pct': dist,
        'vol_window': VOL_WINDOW,
        'vol_annualized': round(vol, 4) if vol else None,
        'vol_cap': VOL_CAP,
        'trend_on': trend_on,
        'vol_ok': vol_ok,
        'tier': tier,
        'lev_cap_mult': mult,
        'label': label,
        'rationale': (f'HSTECH {close:.0f} {"高于" if trend_on else "低于"} {MA_WINDOW}日线 '
                      f'{ma:.0f} ({dist:+.1f}%)；20日波动 {vol*100:.0f}% '
                      f'{"<" if vol_ok else "≥"} {int(VOL_CAP*100)}% 上限。'
                      f'→ 杠杆ETF腿上限 ×{mult:g}（{tier}）'),
    }

    if args.dry_run:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    safe_write_json(str(OUT_FILE), out)
    print(f'  lev_regime: {tier} (×{mult:g}) — {out["rationale"]}')


if __name__ == '__main__':
    main()
