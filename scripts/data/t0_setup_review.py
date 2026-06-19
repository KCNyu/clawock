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
  • 样本 n<MIN_N 的牌面标「样本不足」，不得当结论引用方向
  • 结算按 (日期, 标的) 去重取当日最后一条（端午盘中多条 → 取收盘牌面）

输出 assets/data/t0_setup_review.json。brief preflight 每日顺跑，dashboard🎯卡展示。
"""
import json
import sys
from datetime import date
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
HIST = WS / 'assets' / 'data' / 't0_setups_history.jsonl'
OUT = WS / 'assets' / 'data' / 't0_setup_review.json'

MIN_N = 20   # 牌面结论可被引用的最小样本量
HORIZON = 1  # T+1：按「下一个有该标的留痕的交易日」结算

sys.path.insert(0, str(WS / 'scripts' / 'data'))
try:
    from safe_io import safe_write_json
except Exception:
    def safe_write_json(path, data, indent=2):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=indent))

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


def main():
    days = _load_days()
    if not days:
        out = {'as_of': date.today().isoformat(), 'days_logged': 0,
               'grades': {}, 'summary': '尚无留痕 — 累积中'}
        safe_write_json(str(OUT), out)
        print('  no t0 history yet — skip')
        return 0

    stats = {k: {'n': 0, 'hits': 0, 'fwd_sum': 0.0} for k in GRADE_TESTS}
    for i, day in enumerate(days):
        if i + HORIZON >= len(days):
            continue  # 窗口未到期
        nxt = days[i + HORIZON]['rows']
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
                    s['fwd_sum'] += fwd * direction  # 方向化收益（正=警示/预测被证实）

    grades = {}
    usable = []
    for name, s in stats.items():
        wr = round(s['hits'] / s['n'], 3) if s['n'] else None
        avg = round(s['fwd_sum'] / s['n'] * 100, 2) if s['n'] else None
        grades[name] = {
            'label': GRADE_CN[name], 'n': s['n'], 'hit_rate': wr,
            'avg_dir_fwd_pct': avg, 'usable': s['n'] >= MIN_N,
            'note': '样本不足，不得当结论引用方向' if s['n'] < MIN_N else '',
        }
        if s['n'] >= MIN_N and wr is not None:
            usable.append(f"{GRADE_CN[name]} 命中{wr*100:.0f}%(n={s['n']})")

    summary = ('、'.join(usable) if usable
               else f'各牌面样本 <{MIN_N}，累积中（{len(days)} 交易日留痕）——结论未解锁')
    out = {
        'as_of': date.today().isoformat(), 'days_logged': len(days),
        'min_n': MIN_N, 'horizon': HORIZON, 'grades': grades, 'summary': summary,
        'discipline': ('自迭代：命中率是牌面话语权的唯一来源。usable=false 只展示不下结论；'
                       '「命中」= 评级方向警示被次日价格证实（追高→跌 / 超卖→涨），不是「能赚钱」。'),
    }
    safe_write_json(str(OUT), out)
    print(f'  t0 review: {len(days)} 交易日留痕 — {summary}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
