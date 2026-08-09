#!/usr/bin/env python3
"""
US leverage evaluation — same regime backtest as HSTECH, but for kcn's US 2x
single-stock ETFs: PLTU(2x PLTR), ROBN(2x HOOD), MSFU(2x MSFT).

These ETFs are young (2023-24 launches) so we simulate the 2x daily-reset sleeve
from the UNDERLYING stock's full history (Tencent fqkline, qfq-adjusted) — which
captures volatility decay exactly. Regime dial = per-stock 200DMA trend + 20d vol.

Outputs:
  • a results table (totRet / CAGR / maxDD / worst-window / %inMkt / switches)
  • PNG charts → memory/.tmp/us_lev_*.png  (equity log + underwater drawdown + summary bars)

Run: clawock evaluate-us-leverage
"""
import math
from datetime import date
from pathlib import Path

import requests

from clawock.decision import regime as compute_regime
from clawock.evidence import run_card
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
OUT = WS / 'memory' / '.tmp'
OUT.mkdir(parents=True, exist_ok=True)
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/121.0 Safari/537.36')

# kcn's US 2x single-stock ETFs → underlying
NAMES = [('PLTU', 'PLTR', 'usPLTR.OQ'),
         ('ROBN', 'HOOD', 'usHOOD.OQ'),
         ('MSFU', 'MSFT', 'usMSFT.OQ')]
MA_WIN, VOL_WIN, VOL_CAP = 200, 20, 0.80   # single stocks run hot → 80% vol band


def _plotting():
    """Import matplotlib at call time and return the two handles `main` draws with.

    Deferred on purpose: charting is the `evaluation` extra, so a base install
    of the wheel must be able to import this module. A module-level
    `import matplotlib` makes the whole package un-importable for everyone who
    did not ask for plots, which is the failure `test_wheel_contains_the_package`
    exists to catch.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # Register Noto Sans CJK so Chinese labels render (no tofu boxes). .ttc files
    # hold several faces — resolve the real family name matplotlib indexes it under.
    for path in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                 '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc'):
        if Path(path).exists():
            try:
                font_manager.fontManager.addfont(path)
                plt.rcParams['font.family'] = font_manager.FontProperties(
                    fname=path).get_name()
                break
            except Exception:
                pass
    plt.rcParams['axes.unicode_minus'] = False
    return plt, mdates


def fetch(sym, cnt=1800):
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{cnt},qfq'
    d = requests.get(url, headers={'User-Agent': UA}, timeout=20).json()
    node = (d.get('data') or {}).get(sym, {})
    rows = node.get('qfqday') or node.get('day') or []
    out = []
    for r in rows:
        try:
            out.append((r[0], float(r[2])))
        except (IndexError, ValueError):
            continue
    return out


def sma(v, n):
    out = [None] * len(v); s = 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n: s -= v[i - n]
        if i >= n - 1: out[i] = s / n
    return out


def rvol(rets, n, i):
    if i < n: return None
    w = rets[i - n + 1:i + 1]; m = sum(w) / n
    return math.sqrt(sum((x - m) ** 2 for x in w) / (n - 1)) * math.sqrt(252)


def mdd(nav):
    peak = -1e9; m = 0.0
    for v in nav:
        peak = max(peak, v); m = min(m, v / peak - 1)
    return m


def underwater(nav):
    peak = -1e9; out = []
    for v in nav:
        peak = max(peak, v); out.append((v / peak - 1) * 100)
    return out


def cagr(nav, dates):
    yrs = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    return (nav[-1] / nav[0]) ** (1 / yrs) - 1 if yrs > 0 else 0.0


def simulate(closes):
    n = len(closes)
    rets = [0.0] + [closes[i] / closes[i - 1] - 1 for i in range(1, n)]
    ma = sma(closes, MA_WIN)
    vols = [rvol(rets, VOL_WIN, i) for i in range(n)]
    bh1, bh2, reg, rgv, r1x = [1.0], [1.0], [1.0], [1.0], [1.0]
    pos = []
    for i in range(1, n):
        r = rets[i]; lev = 1 + 2 * r
        trend = ma[i - 1] is not None and closes[i - 1] > ma[i - 1]
        vok = vols[i - 1] is not None and vols[i - 1] < VOL_CAP
        bh1.append(bh1[-1] * (1 + r))
        bh2.append(bh2[-1] * lev)
        reg.append(reg[-1] * (lev if trend else 1.0))
        rgv.append(rgv[-1] * (lev if (trend and vok) else 1.0))
        r1x.append(r1x[-1] * ((1 + r) if trend else 1.0))
        pos.append(1 if trend else 0)
    return dict(bh1=bh1, bh2=bh2, reg=reg, rgv=rgv, r1x=r1x, pos=pos, ma=ma, vols=vols)


COLORS = {'bh2': '#ef4444', 'reg': '#f59e0b', 'rgv': '#a855f7', 'r1x': '#22c55e', 'bh1': '#64748b'}
LBL = {'bh1': '标的 1x 持有', 'bh2': '2x ETF 死扛', 'reg': 'Regime 2x', 'rgv': 'Regime+Vol 2x', 'r1x': 'Regime 1x(降杠杆)'}


def main():
    plt, mdates = _plotting()
    plt.rcParams.update({'figure.facecolor': '#0f172a', 'axes.facecolor': '#0f172a',
                         'axes.edgecolor': '#334155', 'text.color': '#e2e8f0',
                         'axes.labelcolor': '#94a3b8', 'xtick.color': '#94a3b8',
                         'ytick.color': '#94a3b8', 'grid.color': '#1e293b',
                         'font.size': 9, 'axes.titlesize': 11})
    sims, allrows = {}, []
    measured, series_inputs = {}, []
    print(f'{"ETF/标的":<14}{"strategy":<20}{"totRet":>9}{"CAGR":>8}{"maxDD":>9}{"%inMkt":>8}{"sw":>5}')
    print('-' * 76)
    for etf, ul, sym in NAMES:
        data = fetch(sym)
        dates = [d for d, _ in data]; closes = [c for _, c in data]
        series_inputs.append({
            'symbol': sym, 'etf': etf, 'underlying': ul,
            'source': 'tencent fqkline (qfq-adjusted)',
            'bars': len(data), 'first_session': dates[0], 'last_session': dates[-1],
            'digest': run_card.series_digest(data),
        })
        s = simulate(closes); s['dates'] = dates; s['last_close'] = closes[-1]; sims[etf] = s
        for key in ('bh1', 'bh2', 'reg', 'rgv', 'r1x'):
            nav = s[key]
            pos = s['pos'] if key in ('reg', 'rgv', 'r1x') else None
            tot, cg, m = nav[-1] - 1, cagr(nav, dates), mdd(nav)
            inmkt = (sum(s['pos']) / len(s['pos']) * 100) if key in ('reg', 'rgv', 'r1x') else 100
            sw = sum(1 for a, b in zip(s['pos'], s['pos'][1:]) if a != b) if key in ('reg', 'rgv', 'r1x') else 0
            print(f'{(etf+"/"+ul):<14}{LBL[key]:<20}{tot*100:>8.0f}%{cg*100:>7.1f}%{m*100:>8.1f}%{inmkt:>7.0f}%{sw:>5}')
            allrows.append((etf, ul, key, tot, cg, m))
            measured[f'{etf}:{key}'] = {
                'strategy': LBL[key], 'underlying': ul,
                'total_return': round(tot, 6), 'cagr': round(cg, 6),
                'max_drawdown': round(m, 6),
                'pct_time_in_market': round(inmkt, 2), 'switches': sw,
            }
        print('-' * 76)

    # ---- Figure 1: per-name equity (log) + underwater drawdown (3 rows × 2 cols)
    fig, axes = plt.subplots(3, 2, figsize=(13, 11))
    for row, (etf, ul, sym) in enumerate(NAMES):
        s = sims[etf]; dts = [date.fromisoformat(d) for d in s['dates']]
        axe, axd = axes[row]
        for key in ('bh2', 'reg', 'r1x', 'bh1'):
            axe.plot(dts, s[key], color=COLORS[key], lw=1.4, label=LBL[key])
        axe.set_yscale('log'); axe.set_title(f'{etf} = 2x {ul} · 净值(对数)'); axe.grid(True, alpha=0.3)
        axe.legend(fontsize=7, loc='upper left', framealpha=0.2)
        axe.xaxis.set_major_formatter(mdates.DateFormatter('%y'))
        for key in ('bh2', 'reg', 'r1x'):
            uw = underwater(s[key])
            axd.fill_between(dts, uw, 0, color=COLORS[key], alpha=0.35, label=f'{LBL[key]} maxDD {min(uw):.0f}%')
            axd.plot(dts, uw, color=COLORS[key], lw=0.8)
        axd.set_title(f'{etf} · 水下回撤 %'); axd.grid(True, alpha=0.3); axd.set_ylim(-100, 2)
        axd.legend(fontsize=7, loc='lower left', framealpha=0.2)
        axd.xaxis.set_major_formatter(mdates.DateFormatter('%y'))
    fig.suptitle('美股 2x 单股杠杆 ETF：死扛 vs 200日线制度过滤 vs 降杠杆', fontsize=13, y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    p1 = OUT / 'us_lev_equity.png'; fig.savefig(p1, dpi=110); plt.close(fig)

    # ---- Figure 2: summary bars — maxDD & CAGR per name per strategy
    fig2, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6))
    keys = ['bh2', 'reg', 'rgv', 'r1x']
    etfs = [n[0] for n in NAMES]; x = range(len(etfs)); w = 0.2
    for j, key in enumerate(keys):
        ddv = [next(m for (e, u, k, t, c, m) in allrows if e == etf and k == key) * 100 for etf in etfs]
        cgv = [next(c for (e, u, k, t, c, m) in allrows if e == etf and k == key) * 100 for etf in etfs]
        off = [xi + (j - 1.5) * w for xi in x]
        a1.bar(off, ddv, w, color=COLORS[key], label=LBL[key])
        a2.bar(off, cgv, w, color=COLORS[key], label=LBL[key])
    a1.set_title('最大回撤 %（越浅越好）'); a2.set_title('年化收益 CAGR %')
    for a in (a1, a2):
        a.set_xticks(list(x)); a.set_xticklabels(etfs); a.grid(True, axis='y', alpha=0.3); a.axhline(0, color='#475569', lw=0.8)
    a1.legend(fontsize=7, framealpha=0.2)
    fig2.suptitle('美股 2x 杠杆 ETF 回测汇总（per-name 200日线制度）', fontsize=12)
    fig2.tight_layout(rect=[0, 0, 1, 0.95])
    p2 = OUT / 'us_lev_summary.png'; fig2.savefig(p2, dpi=110); plt.close(fig2)

    # current regime read per name
    print('\n--- 当前各标的制度读数 ---')
    for etf, ul, sym in NAMES:
        s = sims[etf]; c = s['last_close']; ma = s['ma'][-1]; vol = s['vols'][-1]
        trend = 'ABOVE ✅' if (ma and c > ma) else 'BELOW ⛔'
        print(f'  {etf}/{ul}: close {c:.1f} vs 200DMA {ma:.1f} → {trend} ({(c/ma-1)*100:+.0f}%) | 20d vol {vol*100:.0f}%')
    print(f'\n charts → {p1}\n          {p2}')

    card = run_card.record(
        'us_leverage_regime',
        params={'ma_window': MA_WIN, 'vol_window': VOL_WIN, 'vol_cap': VOL_CAP,
                'names': [list(n) for n in NAMES]},
        inputs=series_inputs,
        metrics=measured,
        code_files=[__file__, Path(compute_regime.__file__)],
        notes=['charts are written to memory/.tmp/ and are not evidence — '
               'they are regenerated on every run and never committed'],
    )
    print(f' run card → {card.relative_to(WS)}')


if __name__ == '__main__':
    main()
