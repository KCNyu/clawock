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
PORTFOLIO = WS / 'portfolio.json'
TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'
TENCENT_FQ = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/121.0 Safari/537.36')

MA_WINDOW = 200      # slower MA = fewer falling-knife re-entries (verified vs 100/150)
VOL_WINDOW = 20
VOL_CAP = 0.50       # HSTECH 20d annualised realised-vol ceiling for "vol-ok"

# US 2x single-stock ETF → (underlying ticker, Tencent fqkline symbol). The US dial is
# PER-NAME (each ETF tracks one stock) and — verified in backtest_us_leverage.py — must
# be LIGHT on low-vol names (MSFT regime-filter whipsawed and hurt returns). So a US name
# only triggers a forced CUT when its underlying is trend-off AND vol is hot (>70%);
# trend-off-but-calm is a soft 'watch', not a cut.
US_2X_MAP = {
    'PLTU': ('PLTR', 'usPLTR.OQ'),
    'ROBN': ('HOOD', 'usHOOD.OQ'),
    'MSFU': ('MSFT', 'usMSFT.OQ'),
}
US_VOL_HOT = 0.70    # single stocks run hot; only >70% annualised counts as "过热"

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


def fetch_us(sym, cnt=400):
    """Tencent fqkline (qfq-adjusted) US daily closes — enough bars for 200DMA + vol."""
    url = f'{TENCENT_FQ}?param={sym},day,,,{cnt},qfq'
    try:
        d = requests.get(url, headers={'User-Agent': UA}, timeout=20).json()
    except Exception as e:
        print(f'  warn: US {sym} fetch failed: {e}', file=sys.stderr)
        return []
    node = (d.get('data') or {}).get(sym, {})
    rows = node.get('qfqday') or node.get('day') or []
    out = []
    for r in rows:
        try:
            out.append(float(r[2]))
        except (IndexError, ValueError):
            continue
    return out


def _held_us_lev_etfs():
    """Held US 2x ETFs (shares>0) that we have an underlying mapping for."""
    try:
        port = json.loads(PORTFOLIO.read_text())
        us = port['portfolios']['us_stocks']['holdings']
    except Exception:
        return []
    return [h['ticker'] for h in us
            if h.get('shares', 0) > 0 and h.get('ticker') in US_2X_MAP]


def compute_us():
    """Per-name US leverage dial for each held 2x single-stock ETF."""
    names = []
    for etf in _held_us_lev_etfs():
        underlying, sym = US_2X_MAP[etf]
        closes = fetch_us(sym)
        if len(closes) < MA_WINDOW + 1:
            names.append({'etf': etf, 'underlying': underlying, 'state': 'unknown',
                          'note': f'insufficient history ({len(closes)} bars)'})
            continue
        ma, vol = compute(closes)
        close = closes[-1]
        trend_on = ma is not None and close > ma
        vol_hot = vol is not None and vol >= US_VOL_HOT
        if trend_on:
            state = 'ok'
        elif vol_hot:
            state = 'cut'        # trend-off AND hot → force de-lever
        else:
            state = 'watch'      # trend-off but calm → advisory only (light on low-vol)
        names.append({
            'etf': etf, 'underlying': underlying,
            'close': round(close, 2), 'ma': round(ma, 2), 'ma_window': MA_WINDOW,
            'dist_ma_pct': round((close / ma - 1) * 100, 1),
            'vol_annualized': round(vol, 4) if vol else None,
            'vol_hot_cap': US_VOL_HOT, 'trend_on': trend_on, 'vol_hot': vol_hot,
            'state': state,
        })
    cuts = [n for n in names if n.get('state') == 'cut']
    watches = [n for n in names if n.get('state') == 'watch']
    if cuts:
        tier, label = 'red', f"{len(cuts)} 只趋势off+波动过热 → 该名降杠杆"
    elif watches:
        tier, label = 'amber', f"{len(watches)} 只趋势off(波动未过热) → 观察，暂不强砍"
    else:
        tier, label = 'green', '美股各2x标的趋势ON' if names else '无持仓2x ETF'
    return {'names': names, 'tier': tier, 'label': label,
            'vol_hot_cap': US_VOL_HOT, 'cut_count': len(cuts), 'watch_count': len(watches)}


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
                      f'→ HK 杠杆ETF腿上限 ×{mult:g}（{tier}）'),
    }
    # Top-level fields above describe the HK (HSTECH) dial; mirror under 'hk' and add 'us'.
    out['hk'] = {'tier': tier, 'lev_cap_mult': mult, 'label': label,
                 'close': out['close'], 'ma': out['ma'], 'dist_ma_pct': dist,
                 'vol_annualized': out['vol_annualized'], 'trend_on': trend_on, 'vol_ok': vol_ok}
    out['us'] = compute_us()

    if args.dry_run:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    safe_write_json(str(OUT_FILE), out)
    us = out['us']
    print(f'  lev_regime HK: {tier} (×{mult:g}) — {out["rationale"]}')
    print(f'  lev_regime US: {us["tier"]} — {us["label"]}')
    for n in us['names']:
        if n.get('state') in ('cut', 'watch'):
            print(f'     {n["etf"]}=2x{n["underlying"]}: {n["state"]} '
                  f'({n.get("dist_ma_pct")}% vs 200线, vol {(n.get("vol_annualized") or 0)*100:.0f}%)')


if __name__ == '__main__':
    main()
