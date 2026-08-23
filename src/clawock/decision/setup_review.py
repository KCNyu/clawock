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

输出 assets/data/t0_setup_review.json。brief preflight 每日顺跑，dashboard🎯卡展示。
"""
import json
import math
import sys
from datetime import date
from pathlib import Path


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
    """读 jsonl → 按 (date, ticker) 去重取当日最后一条 → 按日期排序的列表。"""
    if not HIST.exists():
        return []
    by_day = {}   # date -> {ticker: {grade_label, close}}
    for line in HIST.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        d = rec.get('as_of')
        if not d:
            continue
        day = by_day.setdefault(d, {})
        for t, m in (rec.get('rows') or {}).items():
            day[t] = m   # 后写覆盖 → 当日最后一条
    return [{'as_of': d, 'rows': by_day[d]} for d in sorted(by_day)]


def _settle(days, horizon):
    """Run the grade-vs-forward-return accounting for one horizon.

    Returns (stats, grades, usable_lines) — the same three things main()
    assembles, so a multi-horizon run is one loop instead of a copy.
    """
    stats = {k: {'n': 0, 'hits': 0, 'fwd_sum': 0.0} for k in GRADE_TESTS}
    for i, day in enumerate(days):
        if i + horizon >= len(days):
            continue  # 窗口未到期
        nxt = days[i + horizon]['rows']
        for t, m in day['rows'].items():
            c0 = m.get('close')
            lab = m.get('grade_label') or ''
            c1 = (nxt.get(t) or {}).get('close')
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
    # 免得 n=210 被当成 210 个独立样本。
    tickers = {t for d in days for t in d['rows']}
    non_overlap_cap = len(tickers) * (len(days) // horizon) if horizon else 0
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
