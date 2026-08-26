#!/usr/bin/env python3
"""B2 — T+0 牌面 edge 自检（给 compute_t0_setups 的评级补数据背书）。

与 quant_signal_review.py 同思路、同纪律：读 t0_setups_history.jsonl（compute_t0_setups
每次运行留痕），把每天每只的牌面评级对账 T+1 实际 forward return，输出每种牌面的命中率：

  追高低质 (🔴)   假设：买在当日高位 → 次日多半回落。direction=-1（次日跌算「警告命中」）
  偏高位   (🟡)   同向但更弱的追高警告。direction=-1
  低位/超卖 (🟡)  假设：超卖 → 次日反弹。direction=+1（次日涨算命中）

「命中」的含义：评级给出的方向警示是否被次日价格证实——不是「能赚钱」，是「这条牌面规则
有没有预测力」。这正是 kcn 要的「数据背书」：以后报🔴追高时能引用历史命中率，而不是空口。

 铁律（同 quant_signal_review）：
   • 纯本地文件运算，零网络（绝不每分钟抓价——结算用的是后续 preflight 已留痕的 close）
   • sample_sufficient 只回答样本够不够；edge_supported 只回答 Wilson CI
     是否完整高于 50%。两者同时为真才 usable，禁止再用 raw n 自动解锁
   • 结算按 (日期, 标的) 去重取当日最后一条（端午盘中多条 → 取收盘牌面）
   • 闭市留痕行不产生结算观测（#1050 剔周末，#1056 推广到交易日历整日休市）：
     留痕器任何时刻跑都会落一行，而闭市日报价源会漂移、或与下一交易日的
     盘前快照逐字重复——跨它算出的 forward return 是伪观测（实测周末行把
     chase_low_quality 的 T+1 命中率从干净段 63.0% 拖到公开值 54.0%，解锁判词被压翻转；
     节假日重复行 fwd 恒 0，对 ±方向都是必 miss）。结算按「标的所属市场的开市留痕日」
     序列走：触发日闭市的行不产生观测，开市触发的窗口顺延到该标的自己的第 N 个
     开市留痕日（周五顺延周一的同语义推广）。市场归属单一出处 instruments registry，
     日历未覆盖的年份 fail-open 不剔数据。读取侧防御、数据不改写，与 quant_signal_review
     的冻结价闸同一模式。
 输出 assets/data/t0_setup_review.json。brief preflight 每日顺跑，dashboard🎯卡展示。
"""
import json
import math
import sys
from datetime import date
from datetime import date as real_date
from pathlib import Path

from clawock import instruments
from clawock import sessions as trading_calendar


def wilson_ci(hits, n, z=1.96):
    """95% Wilson score interval for a proportion → [lo, hi], or None.
    Inlined (not imported) so an isolated cron never breaks on a path issue.
    A band that straddles 0.5 = the 'edge' is indistinguishable from a coin flip."""
    if not n:
        return None
    p = hits / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, center - half), 3), round(min(1.0, center + half), 3)]


from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
HIST = WS / 'assets' / 'data' / 't0_setups_history.jsonl'
OUT = WS / 'assets' / 'data' / 't0_setup_review.json'

MIN_N = 20   # 牌面结论可被引用的最小样本量
HORIZON = 1  # T+1:按「下一个有该标的留痕的交易日」结算(顶层兼容字段)
# #819:同一条留痕在多个周期上各结算一遍。T+1 是顶层(现有读者),
# multi_horizon 带全部周期——上一次"换个周期会不会成立"的验证是手工
# 重放的,不该再做第二遍。
HORIZONS = (1, 5, 10, 20)

# 牌面 → (匹配函数, 预期方向 +1=次日涨算命中 / -1=次日跌算命中)
GRADE_TESTS = {
    'chase_low_quality': (lambda lab: lab == '追高低质', -1),
    'elevated':          (lambda lab: lab.startswith('偏高位'), -1),
    'oversold_low':      (lambda lab: lab.startswith('低位'), +1),
}
GRADE_CN = {'chase_low_quality': '🔴 追高低质', 'elevated': '🟡 偏高位',
            'oversold_low': '🟡 低位/超卖'}


def _load_days():
    """读 jsonl → 按 (**该标的所属市场的交易日**, ticker) 去重取最后一条。

    去重的键必须是行情自己的日子，不是留痕器的墙钟日子。`as_of` 是主机
    HKT 日期，而美股一场 session 跨 HKT 午夜（21:30 开、次日 04:00 收），
    于是同一个 `as_of` 下混着两场 session 的行：HKT 白天写的是**上一场**的
    收盘，21:30 之后写的才是当天的。按 `as_of` 折叠 = 把两场行情压成一个
    观测，而原注释「取收盘牌面」对美股名从来没兑现过——那一场的后半段
    （00:00-04:00）已经落到下一个 `as_of` 里去了。

    留痕器现在直接写 `session_date`（#1077）。老行没有这个字段，读取侧
    回落到 `as_of`：与冻结价闸同一模式——防在读取侧，不改写已有数据。
    """
    if not HIST.exists():
        return []
    by_day = {}   # session date -> {ticker: {grade_label, close}}
    for line in HIST.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        fallback = rec.get('as_of')
        if not fallback:
            continue
        for t, m in (rec.get('rows') or {}).items():
            d = m.get('session_date') or fallback
            by_day.setdefault(d, {})[t] = m   # 后写覆盖 → 该 session 最后一条
    return [{'as_of': d, 'rows': by_day[d]} for d in sorted(by_day)]


def _session_open(ticker, day):
    """该标的所属市场在 day 是否有交易时段。

    周六/周日与交易日历里的整日休市（节假日）都算闭市；日期无法解析或
    日历未覆盖该年份时 fail-open 当开市——宁可少剔一行，绝不静默丢真时段。
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
    """闭市留痕日里本会触发计数的牌面行数——它们不再产生任何观测（#1050/#1056）。

    按标的各自的市场判断：US 休市日（07-03）的 HK 行是真时段，反之亦然。
    """
    n = 0
    for d in days:
        for t, m in (d.get('rows') or {}).items():
            if _session_open(t, d.get('as_of')):
                continue
            if not m.get('close'):
                continue
            lab = m.get('grade_label') or ''
            if any(cond(lab) for cond, _ in GRADE_TESTS.values()):
                n += 1
    return n


def _settle(days, horizon):
    """Run the grade-vs-forward-return accounting for one horizon.

    Settlement walks each ticker's own open-market logged-day sequence
    (#1050, extended to weekday holidays by #1056): a trigger on a closed
    day produces no observation at all, and a window crossing a closed day
    settles against that ticker's next open logged day — the same deferral
    that already carried a Friday trigger to Monday.

    Returns (stats, grades, usable_lines) — the same three things main()
    assembles, so a multi-horizon run is one loop instead of a copy.
    """
    stats = {k: {'n': 0, 'hits': 0, 'fwd_sum': 0.0} for k in GRADE_TESTS}
    universe = sorted({t for d in days for t in (d.get('rows') or {})})
    seq_max = 0
    for t in universe:
        # 该标的自己的时段序列：开市留痕日上有它一行才入列。
        seq = [row for d in days if _session_open(t, d.get('as_of'))
               for row in [(d.get('rows') or {}).get(t)] if row is not None]
        seq_max = max(seq_max, len(seq))
        for i, m in enumerate(seq):
            if i + horizon >= len(seq):
                continue  # 窗口未到期
            c0 = m.get('close')
            lab = m.get('grade_label') or ''
            c1 = (seq[i + horizon] or {}).get('close')
            if not c0 or not c1:
                continue
            fwd = c1 / c0 - 1
            for name, (cond, direction) in GRADE_TESTS.items():
                if cond(lab):
                    s = stats[name]
                    s['n'] += 1
                    s['hits'] += 1 if fwd * direction > 0 else 0
                    s['fwd_sum'] += fwd * direction  # 方向化收益(正=警示/预测被证实)
    # #819:这些窗口是重叠的(Wilson CI 假设独立),写一个非重叠上限估计,
    # 免得 n=210 被当成 210 个独立样本。交易日按标的自己的序列上限计。
    non_overlap_cap = len(universe) * (seq_max // horizon) if horizon else 0
    grades = {}
    usable = []
    for name, s in stats.items():
        wr = round(s['hits'] / s['n'], 3) if s['n'] else None
        avg = round(s['fwd_sum'] / s['n'] * 100, 2) if s['n'] else None
        ci = wilson_ci(s['hits'], s['n'])      # 95% Wilson — 让样本不确定性显形
        sample_sufficient = s['n'] >= MIN_N
        edge_supported = ci is not None and ci[0] > 0.5
        reverse_edge_supported = ci is not None and ci[1] < 0.5
        usable_now = sample_sufficient and edge_supported
        if not sample_sufficient:
            note = '样本不足，不得当结论引用方向'
        elif reverse_edge_supported:
            note = 'Wilson CI 支持相反方向；原牌面禁用，不自动反向交易'
        elif not edge_supported:
            note = 'Wilson CI 跨 50%，正向 edge 未获支持'
        else:
            note = ''
        grades[name] = {
            'label': GRADE_CN[name], 'n': s['n'], 'hit_rate': wr,
            'ci95': ci,
            # edge_significant is retained for old dashboard readers.
            'edge_significant': edge_supported,
            'sample_sufficient': sample_sufficient,
            'edge_supported': edge_supported,
            'reverse_edge_supported': reverse_edge_supported,
            'decision_direction': 'original' if usable_now else None,
            'avg_dir_fwd_pct': avg,
            'usable': usable_now,
            'note': note,
            # 重叠窗口的非重叠样本上限:CI 乐观与否,至少这里不假装独立。
            'non_overlap_cap': non_overlap_cap,
        }
        if usable_now and wr is not None:
            band = f"[{ci[0]*100:.0f}–{ci[1]*100:.0f}]" if ci else ''
            usable.append(f"{GRADE_CN[name]} 命中{wr*100:.0f}%{band}(n={s['n']})")
    return stats, grades, usable


def main(argv=None):
    del argv
    days = _load_days()
    if not days:
        out = {'as_of': date.today().isoformat(), 'days_logged': 0,
               'grades': {}, 'summary': '尚无留痕 — 累积中'}
        safe_write_json(str(OUT), out)
        print('  no t0 history yet — skip')
        return 0

    closed_rows = _closed_trigger_rows(days)
    _, grades, usable = _settle(days, HORIZON)

    summary = ('、'.join(usable) if usable
               else f'没有牌面同时通过样本与正向 edge 闸（{len(days)} 交易日留痕）——结论未解锁')

    multi = {}
    for h in HORIZONS:
        _, h_grades, h_usable = _settle(days, h)
        h_summary = ('、'.join(h_usable) if h_usable
                     else f'没有牌面同时通过样本与正向 edge 闸——结论未解锁')
        multi[f'H{h}'] = {'horizon': h, 'grades': h_grades, 'summary': h_summary}

    out = {
        'as_of': date.today().isoformat(), 'days_logged': len(days),
        'min_n': MIN_N, 'horizon': HORIZON, 'grades': grades, 'summary': summary,
        # #1050/#1056:闭市留痕行（周末+节假日，按各自市场）不结算。
        # days_logged 是原始留痕天数；closed_market_rows_excluded 是其中本会
        # 触发计数、现不再产生观测的牌面行数。
        'closed_market_rows_excluded': closed_rows,
        # #819:同一条留痕的 T+1/5/10/20 对账,horizons 键顺序即周期。
        'multi_horizon': multi,
        'overlap_note': ('留痕窗口重叠,Wilson CI 假设独立,故偏乐观;'
                         'grades 内 non_overlap_cap = 标的数 × (交易日 ÷ horizon) 的非重叠上限,'
                         'n 超过该上限时结论必须打折。'),
        'unlock_rule': 'sample_sufficient AND Wilson_ci95_lower>50pct',
        'discipline': ('自迭代：usable 需要样本量与正向 Wilson edge 同时成立；'
                       '样本够多但方向错误也只展示不下结论；'
                       '「命中」= 评级方向警示被次日价格证实（追高→跌 / 超卖→涨），不是「能赚钱」。'),
    }
    safe_write_json(str(OUT), out)
    print(f'  t0 review: {len(days)} 交易日留痕 — {summary}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
