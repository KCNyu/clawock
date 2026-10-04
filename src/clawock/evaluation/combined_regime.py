#!/usr/bin/env python3
"""
Combined-book regime evaluation — the WHOLE book (HK+US, current USD weights) with the
lev_regime dial applied, vs buy-and-hold, vs an all-1x (never-leveraged) reference.

Each holding is mapped to a factor proxy we have multi-year history for (young names
like 00100 MINIMAX-W and CRCL are proxied to HSTECH / RKLB). The portfolio is modelled
fixed-weight daily-rebalanced — which makes the daily-rebalance == the leveraged ETFs'
daily reset, so volatility decay is captured at the book level. Multi-market days are
handled on a UNION calendar (a market closed that day → 0 return for its sleeves).

Dial (matches production compute_regime):
  • HK 2x sleeve (07226): production trend/volatility dial: 2x green, 1x amber, 0x red.
  • US 2x names (any held, e.g. RKLX/SPCH): 2x when underlying > 200DMA; cut to 1x ONLY when
    trend-off AND 20d vol ≥ 70% (hot); trend-off-but-calm keeps 2x (light on low-vol).
  • 1x sleeves untouched.

Outputs: results table + memory/.tmp/combined_*.png
Run: clawock evaluate-combined-regime   (needs the charting extra: pip install 'clawock[evaluation]')
"""
from clawock.evaluation.series import mdd, rvol, sma
import json
import argparse
import math
from datetime import date
from pathlib import Path

import requests

from clawock import instruments
from clawock.decision import regime as compute_regime
from clawock.evidence import run_card
from clawock.portfolio import fx as fx_rates
from clawock.workspace import workspace_root

WS = workspace_root()
OUT = WS / 'memory' / '.tmp'
OUT.mkdir(parents=True, exist_ok=True)
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/121.0 Safari/537.36')
MA_WIN, VOL_WIN, VOL_HOT = 200, 20, 0.70

# proxy_key → fetch spec. 'hk' uses kline (index/HK), 'us' uses fqkline.
PROXIES = {
    'HSTECH': ('hk', 'hkHSTECH'),
    'GF':     ('hk', 'hk02208'),     # 金风科技
    'RKLB':   ('us', 'usRKLB.OQ'),
    'PLTR':   ('us', 'usPLTR.OQ'),
    'HOOD':   ('us', 'usHOOD.OQ'),
    'MSFT':   ('us', 'usMSFT.OQ'),
}

# holding ticker → (proxy_key, native_leverage, dial)  dial ∈ {None,'hk2x','us2x'}.
# Policy for names whose proxy is a judgement (young listings, sector stand-ins).
# Membership is NOT this table: the book is every `shares > 0` holding in
# portfolio.json, and a held name missing here is resolved from the registry
# (holding_spec) or reported as unmodelled — never dropped silently (#2051).
HOLDING_MAP = {
    '00100': ('HSTECH', 1, None),   # MINIMAX-W (young) → HSTECH 1x proxy
    '07226': ('HSTECH', 2, 'hk2x'),
    '03032': ('HSTECH', 1, None),
    '03033': ('HSTECH', 1, None),
    '02208': ('GF',     1, None),
    'RKLB':  ('RKLB',   1, None),
    'CRCL':  ('RKLB',   1, None),   # young → RKLB high-beta proxy
    'PLTU':  ('PLTR',   2, 'us2x'),
    'ROBN':  ('HOOD',   2, 'us2x'),
    'MSFU':  ('MSFT',   2, 'us2x'),
}


def fetch(kind, sym, cnt=1800):
    if kind == 'hk':
        # The window ends today, like the sibling readers (`decision/regime`,
        # `hstech_regime`). A literal end froze the HK legs — 95% of the modelled
        # book — while the union calendar kept forward-filling them (#2177).
        end = date.today().isoformat()
        url = f'https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={sym},day,2020-01-01,{end},{cnt}'
    else:
        url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{cnt},qfq'
    d = requests.get(url, headers={'User-Agent': UA}, timeout=20).json()
    node = (d.get('data') or {}).get(sym, {})
    rows = node.get('qfqday') or node.get('day') or []
    return {r[0]: float(r[2]) for r in rows if len(r) >= 3}








def underwater(nav):
    peak = -1e9; o = []
    for v in nav:
        peak = max(peak, v); o.append((v / peak - 1) * 100)
    return o


def cagr(nav, dts):
    yrs = (date.fromisoformat(dts[-1]) - date.fromisoformat(dts[0])).days / 365.25
    return (nav[-1] / nav[0]) ** (1 / yrs) - 1 if yrs > 0 else 0.0


def ann_vol(rets):
    if len(rets) < 2: return 0.0
    m = sum(rets) / len(rets)
    return math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1)) * math.sqrt(252)


def hk_effective_leverage(close, ma, vol, native=2.0):
    """Use the shipped HK dial, including its conservative missing-input tier."""
    return native * compute_regime.classify(close, ma, vol)[3]


def holding_spec(ticker):
    """(proxy_key, native_leverage, dial) for a held ticker, or None.

    HOLDING_MAP first; otherwise the registry: a name whose signal symbol is
    one of PROXIES maps onto it, with its own leverage and the market's dial.
    """
    if ticker in HOLDING_MAP:
        return HOLDING_MAP[ticker]
    meta = instruments.get(ticker)
    if not meta or meta.get('signal_symbol') not in PROXIES:
        return None
    native = meta['leverage_multiple']
    dial = None if native <= 1 else ('hk2x' if meta['region'] == 'HK' else 'us2x')
    return meta['signal_symbol'], native, dial


#: Used only when the local FX cache is missing: risk.json's
#: `meta.fx_hkd_to_usd_used` on 2026-10-01.
FX_HKD_USD_FALLBACK = 0.127449


def hkd_to_usd():
    """HKD→USD from the same cached rate the publisher reads (no network).

    This was a hand-copied literal claiming to match risk.json and had drifted
    0.6% from it (#2277).
    """
    rate = (fx_rates.read_cached_usdhkd() or {}).get('rate')
    return 1 / float(rate) if rate else FX_HKD_USD_FALLBACK


def book_weights(port):
    """Every held position at USD value, split into modelled and unmodelled.

    Returns (weights over the modelled part, modelled USD, book USD, specs,
    unmodelled [(ticker, usd)]).
    """
    fx = hkd_to_usd()
    usd, specs, unmodelled = {}, {}, []
    for leg, ccy in (('hk_stocks', fx), ('us_stocks', 1.0)):
        for h in port['portfolios'][leg]['holdings']:
            if not h.get('shares', 0) > 0:
                continue
            value = h.get('current_value', 0) * ccy
            spec = holding_spec(h.get('ticker'))
            if spec is None:
                unmodelled.append((h.get('ticker'), value))
                continue
            usd[h['ticker']] = value
            specs[h['ticker']] = spec
    modelled = sum(usd.values())
    book = modelled + sum(v for _, v in unmodelled)
    weights = {k: v / modelled for k, v in usd.items()} if modelled else {}
    return weights, modelled, book, specs, unmodelled


def weights_usd():
    w, modelled, _book, _specs, _skipped = book_weights(
        json.loads((WS / 'portfolio.json').read_text()))
    return w, modelled


def _plotting():
    """Import matplotlib at call time and return the two handles `main` draws with.

    Deferred on purpose: charting is the `evaluation` extra, so a base install of
    the wheel must be able to import this module. A module-level
    `import matplotlib` makes the whole package un-importable for everyone who
    did not ask for plots, which is the failure `test_wheel_contains_the_package`
    exists to catch.
    """
    try:
        import matplotlib
    except ImportError:
        raise SystemExit("clawock evaluate-combined-regime draws its charts with matplotlib, which is the "
                         "`evaluation` extra: pip install 'clawock[evaluation]'") from None
    matplotlib.use('Agg')
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for path in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',):
        if Path(path).exists():
            font_manager.fontManager.addfont(path)
            plt.rcParams['font.family'] = font_manager.FontProperties(
                fname=path).get_name()
    plt.rcParams['axes.unicode_minus'] = False
    return plt, mdates


def main(argv=None):
    argparse.ArgumentParser(prog='clawock evaluate-combined-regime',
                            description=__doc__).parse_args(argv)
    plt, mdates = _plotting()
    plt.rcParams.update({'figure.facecolor': '#0f172a', 'axes.facecolor': '#0f172a',
                         'axes.edgecolor': '#334155', 'text.color': '#e2e8f0',
                         'axes.labelcolor': '#94a3b8', 'xtick.color': '#94a3b8',
                         'ytick.color': '#94a3b8', 'grid.color': '#1e293b', 'font.size': 9})
    raw = {k: fetch(kind, sym) for k, (kind, sym) in PROXIES.items()}
    # union calendar from common start (bound by youngest proxy: HOOD IPO)
    start = max(min(s) for s in raw.values())
    alldates = sorted(set().union(*[set(s) for s in raw.values()]))
    dates = [d for d in alldates if d >= start]

    # forward-filled close per proxy on the union calendar
    ff = {}
    for k, s in raw.items():
        out, last = [], None
        for d in dates:
            if d in s: last = s[d]
            out.append(last)
        ff[k] = out
    n = len(dates)

    # per-proxy daily returns (a market closed that day carries its price → 0 ret)
    ret = {k: [0.0] + [ff[k][i] / ff[k][i-1] - 1 if ff[k][i-1] else 0.0 for i in range(1, n)] for k in raw}

    # The dial's inputs are computed on each proxy's NATIVE sessions and then
    # mapped onto the union calendar — not on the forward-filled series. A closed
    # market contributes a 0% return on the union calendar, and those injected
    # zero-variance days deflate 20d realised vol, which is one of the two dial
    # inputs. Production (compute_regime) reads HSTECH's own sessions, so
    # measuring vol here on the union calendar meant the backtest and the live
    # dial were reading different numbers from the same rule.
    ma, vol = {}, {}
    for k, s in raw.items():
        native_dates = sorted(s)
        native_closes = [s[d] for d in native_dates]
        native_rets = [0.0] + [native_closes[i] / native_closes[i-1] - 1
                               for i in range(1, len(native_closes))]
        native_ma = sma(native_closes, MA_WIN)
        native_vol = [rvol(native_rets, VOL_WIN, i) for i in range(len(native_closes))]
        by_date_ma = dict(zip(native_dates, native_ma))
        by_date_vol = dict(zip(native_dates, native_vol))
        # Carry the last native reading forward across a closed session: the dial
        # does not update on a day the market did not trade, and it does not go
        # blind either.
        ma[k], vol[k] = [], []
        last_ma = last_vol = None
        for d in dates:
            if d in by_date_ma:
                last_ma, last_vol = by_date_ma[d], by_date_vol[d]
            ma[k].append(last_ma)
            vol[k].append(last_vol)

    w, tot_usd, book_usd, specs, unmodelled = book_weights(
        json.loads((WS / 'portfolio.json').read_text()))
    print(f'Combined book ≈ ${book_usd:,.0f}  · 共 {len(w) + len(unmodelled)} 持仓'
          f' · 窗口 {dates[0]} → {dates[-1]} ({n} 交易日)')
    if unmodelled:
        share = sum(v for _, v in unmodelled) / book_usd * 100 if book_usd else 0
        print(f'⚠️ 未建模 {len(unmodelled)} 只（占账面 {share:.1f}%，没有长历史代理）：'
              + ', '.join(f'{t} ${v:,.0f}' for t, v in unmodelled)
              + f'；下面的权重只覆盖其余 ${tot_usd:,.0f}')
    print('权重(USD):', ', '.join(f'{t} {w[t]*100:.0f}%' for t in sorted(w, key=lambda x:-w[x])))
    print()

    def eff_lev(tk, i, mode):
        proxy, native, dial = specs[tk]
        if mode == 'all1x':
            return 1.0
        if mode == 'bh' or dial is None:
            return float(native)
        # regime mode, leveraged sleeve
        trend_on = ma[proxy][i-1] is not None and ff[proxy][i-1] > ma[proxy][i-1]
        if dial == 'hk2x':
            return hk_effective_leverage(ff[proxy][i-1], ma[proxy][i-1], vol[proxy][i-1], native)
        if dial == 'us2x':
            if trend_on:
                return 2.0
            hot = vol[proxy][i-1] is not None and vol[proxy][i-1] >= VOL_HOT
            return 1.0 if hot else 2.0   # cut only if hot; watch keeps 2x
        return float(native)

    navs, rets_book = {}, {}
    for mode in ('bh', 'regime', 'all1x'):
        nav = [1.0]; rb = []
        for i in range(1, n):
            r = sum(w[tk] * eff_lev(tk, i, mode) * ret[specs[tk][0]][i] for tk in w)
            rb.append(r); nav.append(nav[-1] * (1 + r))
        navs[mode] = nav; rets_book[mode] = rb

    crash0, crash1 = '2021-08-01', '2022-10-31'
    LBL = {'bh': '死扛(原杠杆)', 'regime': '刻度盘(降杠杆)', 'all1x': '全1x(从不加杠杆)'}
    CLR = {'bh': '#ef4444', 'regime': '#22c55e', 'all1x': '#64748b'}
    print(f'{"strategy":<22}{"totRet":>9}{"CAGR":>8}{"ann.vol":>9}{"maxDD":>9}{"21-22DD":>9}')
    print('-' * 66)
    measured = {}
    for mode in ('bh', 'regime', 'all1x'):
        nav = navs[mode]
        cdd = mdd([v for v, d in zip(nav, dates) if crash0 <= d <= crash1])
        print(f'{LBL[mode]:<22}{ (nav[-1]-1)*100:>8.0f}%{cagr(nav,dates)*100:>7.1f}%'
              f'{ann_vol(rets_book[mode])*100:>8.0f}%{mdd(nav)*100:>8.1f}%{cdd*100:>8.1f}%')
        measured[mode] = {
            'label': LBL[mode],
            'total_return': round(nav[-1] - 1, 6),
            'cagr': round(cagr(nav, dates), 6),
            'annualised_vol': round(ann_vol(rets_book[mode]), 6),
            'max_drawdown': round(mdd(nav), 6),
            'crash_2021_2022_drawdown': round(cdd, 6),
        }

    # ---- charts: equity (log) + underwater
    dts = [date.fromisoformat(d) for d in dates]
    fig, (ax, axd) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 2]})
    for mode in ('bh', 'regime', 'all1x'):
        ax.plot(dts, navs[mode], color=CLR[mode], lw=1.7, label=f'{LBL[mode]}  ({(navs[mode][-1]-1)*100:+.0f}%, maxDD {mdd(navs[mode])*100:.0f}%)')
    ax.set_yscale('log'); ax.grid(True, alpha=0.3); ax.legend(loc='upper left', framealpha=0.25, fontsize=9)
    ax.set_title(f'合并组合净值(对数) — HK+US 当前权重 ${tot_usd:,.0f} · {dates[0]}→{dates[-1]}', fontsize=12)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%y-%m'))
    for mode in ('bh', 'regime', 'all1x'):
        uw = underwater(navs[mode])
        axd.fill_between(dts, uw, 0, color=CLR[mode], alpha=0.3)
        axd.plot(dts, uw, color=CLR[mode], lw=1.1, label=f'{LBL[mode]} maxDD {min(uw):.0f}%')
    axd.grid(True, alpha=0.3); axd.legend(loc='lower left', framealpha=0.25, fontsize=8)
    axd.set_title('水下回撤 %'); axd.set_ylim(-100, 3)
    axd.xaxis.set_major_formatter(mdates.DateFormatter('%y-%m'))
    fig.tight_layout()
    p = OUT / 'combined_regime.png'; fig.savefig(p, dpi=110); plt.close(fig)
    print(f'\n chart → {p}')

    card = run_card.record(
        'combined_regime',
        params={'ma_window': MA_WIN, 'vol_window': VOL_WIN, 'vol_hot': VOL_HOT, 'hk_vol_cap': compute_regime.VOL_CAP,
                'crash_window': [crash0, crash1],
                'weights_usd': {tk: round(wt, 6) for tk, wt in sorted(w.items())},
                'holding_map': {tk: list(spec) for tk, spec in sorted(specs.items())},
                'unmodelled_usd': {tk: round(v, 2) for tk, v in sorted(unmodelled)},
                'book_usd': round(book_usd, 2),
                'fx_hkd_usd': round(hkd_to_usd(), 6)},
        inputs=[{
            'symbol': 'union-calendar book', 'source': 'tencent kline/fqkline via PROXIES',
            'bars': n, 'first_session': dates[0], 'last_session': dates[-1],
            'digest': run_card.series_digest(
                [(d, sum(ff[proxy][i] for proxy in sorted(ff)))
                 for i, d in enumerate(dates)]),
            'note': 'closes are forward-filled onto a union calendar; see #233',
        }] + [
            # Per proxy, because the union calendar's last session is set by
            # whichever leg runs longest: a leg that stopped early is only
            # visible in its own last bar (#2177).
            {'symbol': proxy, 'source': f'tencent {PROXIES[proxy][0]} {PROXIES[proxy][1]}',
             'bars': len(raw[proxy]), 'first_session': min(raw[proxy]),
             'last_session': max(raw[proxy])}
            for proxy in sorted(raw) if raw[proxy]
        ],
        metrics=measured,
        code_files=[__file__, Path(compute_regime.__file__)],
        notes=['book weights are current, applied to history — this is a '
               'fixed-weight simulation, not a replay of what was held'],
    )
    print(f' run card → {card.relative_to(WS)}')


if __name__ == '__main__':
    raise SystemExit(main())
