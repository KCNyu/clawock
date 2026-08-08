#!/usr/bin/env python3
"""
compute_regime.py — the LEVERAGE DIAL (杠杆刻度盘).

Verified in backtest_hstech_regime.py on 2021→now real HSTECH data: an index-level
200DMA trend filter + 20d realized-vol band would have taken the 2021-22 crash
drawdown on a 2x-HSTECH sleeve from -95% to 0% (fully de-risked through the crash),
and de-levering on the same signal cut full-period maxDD from -95% → -44%.

Evidence: run card `hstech_regime-20260802-f7d80e00` (1370 HSTECH bars,
2021-01-04 → 2026-07-31). It reproduces both figures — crash-window drawdown
-95.3% for buy-and-hold 2x against 0.0% for the regime sleeve, and full-period
maxDD -95.5% against -44.2% for the de-levered 1x variant. Re-derive with
`python3 scripts/data/run_card.py --run-id hstech_regime-20260802-f7d80e00`.

READ THIS BEFORE QUOTING THE NUMBERS ABOVE. Neither of them describes the dial
this module actually ships. Both come from rows that switch a 2x sleeve to
*cash* (or hold a 1x sleeve) on the trend signal alone. What ships is the tier
mapping below: `amber` only halves the cap, and `red` needs trend-off AND
vol-hot together. HSTECH's 20d vol sits under 50% through much of a slow
decline, so the common crash state is amber — 1x on a 2x sleeve, not cash.

`validate_regime_dial.py` models that shipped mapping and reports
(run card `regime_dial_validation-20260802-896b2145`, 1370 bars,
2021-01-04 → 2026-07-31):

  in-sample     maxDD -91.6% vs always-2x -95.5% — an improvement of +3.9pp,
                not the -95%→-44% the rows above suggest
  tiers fired   green 30.5% · amber 59.5% · red 10.0%
  permutation   p = 0.92 for drawdown, 0.97 for return. The observed
                improvement is WORSE than the median random re-timing of the
                same exposure path (+10.2pp), so on this window the dial's
                timing is not distinguishable from chance
  walk-forward  2 of 4 out-of-sample folds improved drawdown; the calibrated
                thresholds were unstable and never chose 200/0.50
  sensitivity   200/0.50 ranks 13th of 16 on the grid

The dial is deliberately still here and unchanged. One index and one crash
cannot support "this does not work" any more than they supported "this does";
p = 0.92 is a failure to reject, not a refutation, and the module's other job —
capping leveraged exposure when the regime turns hostile — is a risk-appetite
rule that does not need a timing edge to be worth keeping. What is no longer
defensible is the previous framing, in which a -95%→-44% figure from a
different strategy read as evidence for this one.

Re-derive: `python3 scripts/data/validate_regime_dial.py`.

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

# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402

# Code lives in the checkout; only DATA lives in the workspace. `workspace_root`
# is overridable, so resolving our own modules through WS would read them out of
# someone else's data directory — or silently pick up whatever happens to be
# there. Same expression WS is seeded from, kept separate on purpose (#269).
_CHECKOUT = Path(__file__).resolve().parents[2]
WS = workspace_root(Path(__file__).resolve().parent.parent.parent)
OUT_FILE = WS / 'assets' / 'data' / 'lev_regime.json'
PORTFOLIO = WS / 'portfolio.json'
TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'
TENCENT_FQ = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/121.0 Safari/537.36')

MA_WINDOW = 200      # slower MA = fewer falling-knife re-entries (verified vs 100/150)
VOL_WINDOW = 20
VOL_CAP = 0.50       # HSTECH 20d annualised realised-vol ceiling for "vol-ok"

sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))
from instrument_registry import INSTRUMENTS  # noqa: E402

# US 2x single-stock ETF → (underlying ticker, Tencent fqkline symbol). The US dial is
# PER-NAME (each ETF tracks one stock) and — verified in backtest_us_leverage.py — must
# be LIGHT on low-vol names (MSFT regime-filter whipsawed and hurt returns). So a US name
# only triggers a forced CUT when its underlying is trend-off AND vol is hot (>70%);
# trend-off-but-calm is a soft 'watch', not a cut.
US_2X_MAP = {
    symbol: (
        meta['signal_symbol'],
        INSTRUMENTS[meta['signal_symbol']]['tencent_symbol'],
    )
    for symbol, meta in INSTRUMENTS.items()
    if meta['region'] == 'US'
    and meta['leverage_multiple'] == 2
    and meta.get('signal_symbol')
}
US_VOL_HOT = 0.70    # single stocks run hot; only >70% annualised counts as "过热"
SHORT_MA_WINDOW = 5  # 新上市杠杆名不足 200DMA 时的「右侧确认」短均线（仅趋势方向、非完整 regime）
SHORT_MA_MIN = 5     # 短均线至少需要的 bar 数，再少则 unknown

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
            # 新上市标的不够 200DMA：用短均线做「右侧确认」回退（kcn 口径：逆市不上 2x，
            # 趋势确认了再上）。仅判趋势方向、不算 vol；短均线之下=左侧逆市→保守 cut。
            if len(closes) >= SHORT_MA_MIN:
                w = min(SHORT_MA_WINDOW, len(closes))
                short_ma = sum(closes[-w:]) / w
                close = closes[-1]
                trend_on = close > short_ma
                names.append({
                    'etf': etf, 'underlying': underlying,
                    'close': round(close, 2), 'ma': round(short_ma, 2), 'ma_window': w,
                    'dist_ma_pct': round((close / short_ma - 1) * 100, 1),
                    'vol_annualized': None, 'trend_on': trend_on,
                    'state': 'ok' if trend_on else 'cut',
                    'regime_basis': f'short_ma_{w}',
                    'note': (f'{underlying} 新上市仅 {len(closes)} bars，不足 200DMA → 用 {w}日均线'
                             f'做右侧确认（非完整 regime）。'
                             + ('趋势确认(>短均)→可持杠杆' if trend_on
                                else '短均线之下=左侧逆市，2x 应降杠杆/换 1x，等右侧再上')),
                })
            else:
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
            'vol_n_returns': min(VOL_WINDOW, len(closes) - 1),
            'vol_hot_cap': US_VOL_HOT, 'trend_on': trend_on, 'vol_hot': vol_hot,
            'state': state, 'regime_basis': 'ma_200_and_20d_realized_vol',
        })
    cuts = [n for n in names if n.get('state') == 'cut']
    watches = [n for n in names if n.get('state') == 'watch']
    if cuts:
        tier, label = 'red', f"{len(cuts)} 只触发降杠杆（趋势off+波动过热，或新名左侧逆市）"
    elif watches:
        tier, label = 'amber', f"{len(watches)} 只趋势off(波动未过热) → 观察，暂不强砍"
    else:
        tier, label = 'green', '美股各2x标的趋势ON' if names else '无持仓2x ETF'
    return {'names': names, 'tier': tier, 'label': label,
            'vol_hot_cap': US_VOL_HOT, 'cut_count': len(cuts), 'watch_count': len(watches)}


MOM_WINDOW = 10      # ~2 周动量：短周期市场方向（牛/熊/震荡），比 200DMA 有对比度
MOM_BAND = 3.0       # ±3% 死区 = 震荡；之上=牛(up-leg)、之下=熊(down-leg)


def build_regime_history(dates, closes, lookback=150):
    """Per-date regime for the most recent `lookback` sessions, consumed by build_dashboard
    to bucket the vs_baseline alpha by market regime — the caveat check for '−6pp 是不是纯
    涨市假象'. Emits per date:
      • regime3  — short-horizon MOM_WINDOW momentum → bull/bear/chop (牛/熊/震荡). The axis
                   with real contrast; primary key build_dashboard buckets on.
      • trend_on — canonical 200DMA dial (same def as the live leverage dial `classify`);
                   None when the series is shorter than 200 bars (e.g. US SPY proxy).
    Works on short series (US SPY ≈ 39 bars): momentum needs only MOM_WINDOW+1 bars."""
    n = len(closes)
    hist = {}
    start = max(MOM_WINDOW, n - lookback)
    for i in range(start, n):
        ma200 = sum(closes[i - MA_WINDOW + 1:i + 1]) / MA_WINDOW if i >= MA_WINDOW - 1 else None
        mom = (closes[i] / closes[i - MOM_WINDOW] - 1) * 100
        regime3 = 'bull' if mom > MOM_BAND else ('bear' if mom < -MOM_BAND else 'chop')
        hist[dates[i]] = {
            'trend_on': (closes[i] > ma200) if ma200 is not None else None,
            'dist_ma_pct': round((closes[i] / ma200 - 1) * 100, 1) if ma200 else None,
            'mom_pct': round(mom, 1),
            'regime3': regime3,
        }
    return hist


def load_spy_series():
    """US market-direction proxy for the regime split. tencent only returns 1 bar for
    ETFs/indices, so reuse the SPY daily series already maintained in benchmark.json
    (~60d). Enough for MOM_WINDOW momentum; not for 200DMA (trend_on stays None on US)."""
    try:
        bench = json.loads((WS / 'assets' / 'data' / 'benchmark.json').read_text())
        spy = (bench.get('series') or {}).get('SPY') or []
        pts = [(x['date'], float(x['close'])) for x in spy if x.get('close') is not None]
        pts.sort(key=lambda p: p[0])
        return [d for d, _ in pts], [c for _, c in pts]
    except Exception as e:
        print(f'  warn: SPY series load failed (US regime skipped): {e}', file=sys.stderr)
        return [], []


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
    # regime_history: per-market per-date regime for the alpha-by-regime dashboard bucket.
    # hk ← HSTECH (full history: 200DMA + momentum); us ← SPY proxy (momentum only).
    us_dates, us_closes = load_spy_series()
    out['regime_history'] = {
        'hk': build_regime_history(dates, closes),
        'us': build_regime_history(us_dates, us_closes) if us_closes else {},
        'meta': {'hk_index': 'HSTECH', 'us_index': 'SPY(proxy)',
                 'mom_window': MOM_WINDOW, 'mom_band_pct': MOM_BAND,
                 'note': 'regime3=近%d日动量分 牛(>+%g%%)/熊(<-%g%%)/震荡；trend_on=200日线(US 因样本<200 为 null)'
                         % (MOM_WINDOW, MOM_BAND, MOM_BAND)},
    }

    if args.dry_run:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    safe_write_json(str(OUT_FILE), out)
    us = out['us']
    print(f'  lev_regime HK: {tier} (×{mult:g}) — {out["rationale"]}')
    print(f'  lev_regime US: {us["tier"]} — {us["label"]}')
    for n in us['names']:
        if n.get('state') in ('cut', 'watch'):
            vol = n.get('vol_annualized')
            vol_text = f'{vol*100:.0f}%' if vol is not None else 'N/A'
            basis = n.get('regime_basis') or (
                f'ma_{n.get("ma_window")}' if n.get('ma_window') else 'unknown'
            )
            print(f'     {n["etf"]}=2x{n["underlying"]}: {n["state"]} '
                  f'({n.get("dist_ma_pct")}% vs {n.get("ma_window") or "?"}线, '
                  f'vol {vol_text}, basis {basis})')


if __name__ == '__main__':
    main()
