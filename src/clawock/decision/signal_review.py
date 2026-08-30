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
date×ticker 双向聚类 bootstrap CI。解锁纪律与 t0_setup_review 对齐（#934）：
MIN_N=20 样本不足不得当结论引用，CI 跨 50% 不入决策；低于 50% 也只有在反向
CI 整体成立时才允许反向解读。T+5/T+20 窗口逐日重叠 → 披露 non_overlap_cap
（标的数 × 天数 ÷ horizon），n 超过它时结论打折。
纯本地文件运算，无网络请求，brief preflight 每日顺跑。

冻结价闸：2026-06/07 的留痕里 RKLB 连续 30 个交易日卡在 114.78、HOOD 卡在
112.9（写入侧当时还没有 per-row freshness 闸），forward return 对这种冻结对
恒为 0，把每个因子的命中率系统性压低——trend_on_follow 公开值 10%，其中
32/40 个观测是伪影。连续多个留痕日同一收盘价在真实市场几乎不出现（周末/
假日顺延造成的同价 ≤2–3 天），≥4 判为断源：这些 ticker-日不产生任何观测，
排除量披露在 frozen_feed_excluded，数据本身保留不作改写。

闭市日行闸（#1050 剔周末，#1056 推广到交易日历整日休市）：留痕器任何时刻跑都会落
一行，而周六/周日和节假日永远没有对应市场的交易时段——闭市日报价源会漂移，或与
下一交易日盘前快照逐字重复（实测 07-26≡07-27、08-09≡08-10 全 ticker 收盘集相同；
07-03 美股休市日 MSFT/HOOD 收盘 = 下周一遍），跨它结算的 forward return 是伪观测
（重复行 fwd 恒 0，对 ±方向都是必 miss）。结算按「标的所属市场的开市留痕日」序列走：
触发日闭市的因子行不产生观测并计入 closed_market_rows_excluded；开市触发的窗口
顺延到该标的自己的第 N 个开市留痕行（周五顺延周一的同语义推广），horizon 数的是
时段行而不是原始行。市场归属单一出处 instruments registry；日历未覆盖的年份
fail-open 不剔数据。
"""
import json
import random
from datetime import date as real_date
from datetime import date
from pathlib import Path

from clawock import seeds
from clawock import history_store
from clawock import instruments
from clawock import sessions as trading_calendar
from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
HIST = WS / 'assets' / 'data' / 'quant_signals_history.jsonl'
OUT = WS / 'assets' / 'data' / 'quant_signal_review.json'

# 因子结论可被引用的最小样本量——与 setup_review.MIN_N 同一条纪律。此前文档
# 承诺「样本<20 不解锁」但代码没有这个闸（#934），小样本假解锁全部偏向高估。
MIN_N = 20

# 同一标的连续 ≥FROZEN_RUN_MIN 个留痕日收盘价完全相同 = 行情源断流（见
# docstring 的 RKLB/HOOD 事故）。周末/假日顺延造成的合法同价最多 2–3 天。
FROZEN_RUN_MIN = 4


def _session_open(ticker, day):
    """该标的所属市场在 day 是否有交易时段。

    周六/周日与交易日历里的整日休市（节假日）都算闭市；日期无法解析或
    日历未覆盖该年份时 fail-open 当开市——宁可少剔一行，绝不静默丢真时段。

    用 real_date 而非模块级 date：测试会替换后者（_FixedDate 只造 today）。
    """
    try:
        d = real_date.fromisoformat(str(day)[:10])
    except ValueError:
        return True
    try:
        return trading_calendar.is_trading_day(
            instruments.market_for_symbol(ticker), d)
    except Exception:
        return True


def _closed_trigger_rows(days):
    """闭市留痕日里本会触发计数的因子行数——它们不再产生任何观测（#1050/#1056）。

    按标的各自的市场判断：US 休市日（07-03）的 HK 行是真时段，反之亦然。
    """
    n = 0
    for day in days:
        for sym, sig in (day.get('rows') or {}).items():
            if _session_open(sym, day.get('as_of')):
                continue
            if not sig.get('close'):
                continue
            if any(cond(sig) for cond, _, _ in FACTOR_TESTS.values()):
                n += 1
    return n


def frozen_ticker_days(days):
    """{(ticker, as_of)} 收盘价处在 ≥FROZEN_RUN_MIN 连续同价行程里的 ticker-日。

    只认「完全相等」：真实市场的平盘极少逐分不差，而断流的缓存价必然逐字节
    相同——这正是 2026-06/07 污染被事后检出的签名。
    """
    series = {}
    for day in days:
        as_of = day.get('as_of')
        if not as_of:
            continue
        for sym, sig in (day.get('rows') or {}).items():
            close = (sig or {}).get('close')
            if close is not None:
                series.setdefault(sym, []).append((as_of, close))
    frozen = set()
    for sym, points in series.items():
        run = []
        for as_of, close in points:
            if run and close != run[-1][1]:
                if len(run) >= FROZEN_RUN_MIN:
                    frozen.update((sym, d) for d, _ in run)
                run = []
            run.append((as_of, close))
        if len(run) >= FROZEN_RUN_MIN:
            frozen.update((sym, d) for d, _ in run)
    return frozen

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
    rnd = random.Random(seeds.seed('decision_cluster_bootstrap'))
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


def main(argv=None):
    del argv
    # 「文件还没有」才 skip；「文件在但今天零行」仍要出零状态卡（否则解锁
    # 视图会因为一天没留痕而整块消失）。这条分界原来就在，别被 #951 改掉。
    if not (HIST.exists() or history_store.archive_path(HIST).exists()):
        print('  no history yet — skip')
        return
    # 归档 + 热窗（#951）：命中率是逐日回放算出来的，读窗口一短，n 就变小。
    days = history_store.load_series(HIST)

    stats = {k: {'n': 0, 'hits': 0, 'observations': [], 'horizon': h}
             for k, (_, _, h) in FACTOR_TESTS.items()}
    frozen = frozen_ticker_days(days)
    frozen_excluded = 0
    # 闭市留痕行不是交易时段（#1050/#1056）：每只标的走自己的开市留痕日序列，
    # 触发日闭市的因子行由 _closed_trigger_rows 单独披露；horizon 数的是该
    # 标的自己的时段行数，跨闭市日的窗口顺延到它的下一个时段行。
    closed_excluded = _closed_trigger_rows(days)
    universe = sorted({sym for day in days for sym in ((day.get('rows')) or {})})
    seq_max = 0
    for sym in universe:
        seq = []
        for day in days:
            if not _session_open(sym, day.get('as_of')):
                continue
            sig = (day.get('rows') or {}).get(sym)
            if sig is not None:
                seq.append((day['as_of'], sig))
        seq_max = max(seq_max, len(seq))
        for i, (as_of, sig) in enumerate(seq):
            c0 = sig.get('close')
            if not c0:
                continue
            for name, (cond, direction, horizon) in FACTOR_TESTS.items():
                if i + horizon >= len(seq):
                    continue          # 窗口未到期，留给未来结算
                if not cond(sig):
                    continue
                settle_as_of, settle_sig = seq[i + horizon]
                c1 = settle_sig.get('close')
                if not c1:
                    continue
                if (sym, as_of) in frozen or (sym, settle_as_of) in frozen:
                    # 冻结价观测：fwd 恒 0 或假跳变，两个方向都是伪影。
                    frozen_excluded += 1
                    continue
                fwd = c1 / c0 - 1
                stats[name]['n'] += 1
                hit = fwd * direction > 0
                stats[name]['hits'] += 1 if hit else 0
                stats[name]['observations'].append({
                    'date': as_of, 'ticker': sym, 'hit': hit,
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
        # Unlock discipline, aligned with setup_review (#934): the sample-size
        # gate comes first — a tiny-n CI clearing 50% is noise, not edge — then
        # the cluster-CI gate decides the direction.
        sample_sufficient = s['n'] >= MIN_N
        if not sample_sufficient:
            note = f'样本 < {MIN_N}，方向结论不入决策（#934 与文档承诺对齐）'
            direction = None
        elif ci is None:
            note = 'date/ticker 聚类不足，方向结论不入决策'
        elif direction is None:
            note = '聚类 CI 跨 50%，方向结论不入决策'
        elif reverse_sig:
            note = '反向聚类 CI 完全低于 50%，仅允许反向解读'
        else:
            note = ''
        usable_now = (sample_sufficient and ci is not None
                      and direction == 'original')
        factors[name] = {'n_events': s['n'],
                         'n_dates': len(dates),
                         'n_tickers': len(tickers),
                         'hit_rate': wr,
                         'ci95': ci,
                         'ci_method': 'date_ticker_two_way_cluster_bootstrap',
                         'edge_significant': edge_sig,
                         'reverse_edge_significant': reverse_sig,
                         'sample_sufficient': sample_sufficient,
                         'min_n': MIN_N,
                         'non_overlap_cap': (len(tickers) * (seq_max // s['horizon'])
                                            if s['horizon'] else 0),
                         'decision_direction': direction if usable_now else None,
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
           'frozen_feed_excluded': frozen_excluded,
           'closed_market_rows_excluded': closed_excluded,
           'factors': factors, 'summary': summary,
           'discipline': ('自迭代规则：公开 n_events/n_dates/n_tickers；date×ticker 双向聚类 '
                          'CI 跨 50% 不入决策；只有反向 CI 整体低于 50% 才允许反向解读。driven_by='
                          'technical 的整体战绩以 dashboard 的实时 decision_metrics.by_driver.technical '
                          '为准，不使用固定百分比。')}
    safe_write_json(OUT, out)
    skipped = f'，冻结价剔除 {frozen_excluded} 个观测' if frozen_excluded else ''
    closed = f'，闭市日剔除 {closed_excluded} 个观测' if closed_excluded else ''
    print(f'  review: {len(days)} days, summary: {summary}{skipped}{closed}')


if __name__ == '__main__':
    main()
