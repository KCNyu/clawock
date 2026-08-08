#!/usr/bin/env python3
"""量化因子 edge 自检 — 自迭代闭环第二半（与 driven_by calibration 同思路）。

读 quant_signals_history.jsonl（compute_quant_signals.py 每日留痕），把每天每只标的的
因子状态和 T+1 / T+5 的实际 forward return 对账，输出每个因子的命中率表：

  trend_on=True   → 次日/5日为正的比例（趋势因子有没有跟住）
  trend_on=False  → 次日/5日为负的比例（趋势OFF是不是该轻仓）
  rsi14<=30       → 超卖后 T+5 反弹比例（均值回归 edge）
  rsi14>=70       → 超买后 T+5 回落比例
  zscore20<=-2    → 极端偏离后 T+5 回归比例
  stop_breached   → 破吊灯线后 T+5 继续跌的比例（止损线是否值得执行）

写 assets/data/quant_signal_review.json。公开 events/dates/tickers 三种样本数并使用
date×ticker 双向聚类 bootstrap CI。CI 跨 50% 不入决策；低于 50% 也只有在反向
CI 整体成立时才允许反向解读，不按 raw n 自动解锁。
纯本地文件运算，无网络请求，brief preflight 每日顺跑。
"""
import json
import random
import sys
from datetime import date
from pathlib import Path

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
WS = workspace_root(Path(__file__).resolve().parents[2])
HIST = WS / 'assets' / 'data' / 'quant_signals_history.jsonl'
OUT = WS / 'assets' / 'data' / 'quant_signal_review.json'

sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))
try:
    from clawock.safe_io import safe_write_json
except Exception:
    def safe_write_json(path, data, indent=2):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=indent))

# 因子 → (触发条件, 预期方向: +1=涨算命中 / -1=跌算命中, 结算窗口天数)
FACTOR_TESTS = {
    'trend_on_follow':    (lambda r: r.get('trend_on') is True,  +1, 1),
    'trend_off_avoid':    (lambda r: r.get('trend_on') is False, -1, 5),
    'rsi_oversold_bounce':(lambda r: (r.get('rsi14') if r.get('rsi14') is not None else 50) <= 30, +1, 5),
    'rsi_overbought_fade':(lambda r: (r.get('rsi14') if r.get('rsi14') is not None else 50) >= 70, -1, 5),
    'zscore_extreme_revert': (lambda r: (r.get('zscore20') if r.get('zscore20') is not None else 0) <= -2, +1, 5),
    'stop_breach_continue':  (lambda r: (r.get('stop_distance_pct') if r.get('stop_distance_pct') is not None else 1) < 0, -1, 5),
}


def clustered_ci(observations, samples=2000):
    """Two-way pigeonhole bootstrap over date and ticker clusters."""
    if not observations:
        return None
    dates = sorted({row['date'] for row in observations})
    tickers = sorted({row['ticker'] for row in observations})
    if len(dates) < 2 or len(tickers) < 2:
        return None
    rnd = random.Random(20260717)
    draws = []
    for _ in range(samples):
        date_counts = {d: 0 for d in dates}
        ticker_counts = {t: 0 for t in tickers}
        for _ in dates:
            date_counts[rnd.choice(dates)] += 1
        for _ in tickers:
            ticker_counts[rnd.choice(tickers)] += 1
        hits = total = 0
        for row in observations:
            weight = date_counts[row['date']] * ticker_counts[row['ticker']]
            hits += weight * int(row['hit'])
            total += weight
        if total:
            draws.append(hits / total)
    if not draws:
        return None
    draws.sort()
    return [
        round(draws[int(.025 * (len(draws) - 1))], 3),
        round(draws[int(.975 * (len(draws) - 1))], 3),
    ]


def main():
    if not HIST.exists():
        print('  no history yet — skip')
        return
    days = []
    for line in HIST.read_text().splitlines():
        if line.strip():
            try:
                days.append(json.loads(line))
            except Exception:
                continue
    days.sort(key=lambda d: d['as_of'])

    stats = {k: {'n': 0, 'hits': 0, 'observations': []} for k in FACTOR_TESTS}
    for i, day in enumerate(days):
        for sym, sig in (day.get('rows') or {}).items():
            c0 = sig.get('close')
            if not c0:
                continue
            for name, (cond, direction, horizon) in FACTOR_TESTS.items():
                if i + horizon >= len(days):
                    continue          # 窗口未到期，留给未来结算
                if not cond(sig):
                    continue
                c1 = ((days[i + horizon].get('rows') or {}).get(sym) or {}).get('close')
                if not c1:
                    continue
                fwd = c1 / c0 - 1
                stats[name]['n'] += 1
                hit = fwd * direction > 0
                stats[name]['hits'] += 1 if hit else 0
                stats[name]['observations'].append({
                    'date': day['as_of'], 'ticker': sym, 'hit': hit,
                })

    factors = {}
    usable = []
    for name, s in stats.items():
        wr = round(s['hits'] / s['n'], 3) if s['n'] else None
        observations = s['observations']
        dates = {row['date'] for row in observations}
        tickers = {row['ticker'] for row in observations}
        ci = clustered_ci(observations)
        edge_sig = ci is not None and ci[0] > 0.5
        reverse_sig = ci is not None and ci[1] < 0.5
        direction = ('original' if edge_sig else
                     'reverse' if reverse_sig else None)
        usable_now = direction is not None
        if ci is None:
            note = 'date/ticker 聚类不足，方向结论不入决策'
        elif not usable_now:
            note = '聚类 CI 跨 50%，方向结论不入决策'
        elif reverse_sig:
            note = '反向聚类 CI 完全低于 50%，仅允许反向解读'
        else:
            note = ''
        factors[name] = {'n_events': s['n'],
                         'n_dates': len(dates),
                         'n_tickers': len(tickers),
                         'hit_rate': wr,
                         'ci95': ci,
                         'ci_method': 'date_ticker_two_way_cluster_bootstrap',
                         'edge_significant': edge_sig,
                         'reverse_edge_significant': reverse_sig,
                         'decision_direction': direction,
                         'usable': usable_now,
                         'note': note}
        if usable_now and wr is not None:
            band = f"[{ci[0]*100:.0f}–{ci[1]*100:.0f}]" if ci else ''
            label = '原向' if edge_sig else '反向'
            usable.append(
                f"{name} {label} {wr*100:.0f}%{band}"
                f"(events={s['n']}, dates={len(dates)}, tickers={len(tickers)})")

    summary = ('、'.join(usable) if usable
               else f'没有因子通过聚类 CI 50% 闸（{len(days)} 天留痕）——结论未解锁')
    out = {'as_of': date.today().isoformat(), 'days_logged': len(days),
           'unlock_rule': 'cluster_ci_entirely_above_or_below_50pct',
           'factors': factors, 'summary': summary,
           'discipline': ('自迭代规则：公开 n_events/n_dates/n_tickers；date×ticker 双向聚类 '
                          'CI 跨 50% 不入决策；只有反向 CI 整体低于 50% 才允许反向解读。driven_by='
                          'technical 的整体战绩以 dashboard 的实时 decision_metrics.by_driver.technical '
                          '为准，不使用固定百分比。')}
    safe_write_json(OUT, out)
    print(f'  review: {len(days)} days, summary: {summary}')


if __name__ == '__main__':
    main()
