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

写 assets/data/quant_signal_review.json。样本 n<MIN_N 的因子标「样本不足」，brief 不得引用
其方向结论——这就是自迭代：哪个因子可信由数据决定并随样本自动更新，不靠手调。
纯本地文件运算，无网络请求，brief preflight 每日顺跑。
"""
import json
import sys
from datetime import date
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
HIST = WS / 'assets' / 'data' / 'quant_signals_history.jsonl'
OUT = WS / 'assets' / 'data' / 'quant_signal_review.json'

MIN_N = 20   # 因子结论可被 brief 引用的最小样本量

sys.path.insert(0, str(WS / 'scripts' / 'data'))
try:
    from safe_io import safe_write_json  # type: ignore
except Exception:
    def safe_write_json(path, data, indent=2):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=indent))

# 因子 → (触发条件, 预期方向: +1=涨算命中 / -1=跌算命中, 结算窗口天数)
FACTOR_TESTS = {
    'trend_on_follow':    (lambda r: r.get('trend_on') is True,  +1, 1),
    'trend_off_avoid':    (lambda r: r.get('trend_on') is False, -1, 5),
    'rsi_oversold_bounce':(lambda r: (r.get('rsi14') or 50) <= 30, +1, 5),
    'rsi_overbought_fade':(lambda r: (r.get('rsi14') or 50) >= 70, -1, 5),
    'zscore_extreme_revert': (lambda r: (r.get('zscore20') if r.get('zscore20') is not None else 0) <= -2, +1, 5),
    'stop_breach_continue':  (lambda r: (r.get('stop_distance_pct') if r.get('stop_distance_pct') is not None else 1) < 0, -1, 5),
}


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

    stats = {k: {'n': 0, 'hits': 0} for k in FACTOR_TESTS}
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
                stats[name]['hits'] += 1 if fwd * direction > 0 else 0

    factors = {}
    usable = []
    for name, s in stats.items():
        wr = round(s['hits'] / s['n'], 3) if s['n'] else None
        factors[name] = {'n': s['n'], 'hit_rate': wr,
                         'usable': s['n'] >= MIN_N,
                         'note': '样本不足，brief 不得引用方向结论' if s['n'] < MIN_N else ''}
        if s['n'] >= MIN_N and wr is not None:
            usable.append(f"{name} {wr*100:.0f}%(n={s['n']})")

    summary = ('、'.join(usable) if usable
               else f'全部因子样本 <{MIN_N}，累积中（{len(days)} 天留痕）——结论未解锁')
    out = {'as_of': date.today().isoformat(), 'days_logged': len(days),
           'min_n': MIN_N, 'factors': factors, 'summary': summary,
           'discipline': ('自迭代规则：hit_rate 是因子话语权的唯一来源。usable=false 的因子只展示'
                          '不入决策；usable 后 <50% 的因子方向结论按反向警示处理（同 driven_by '
                          'technical 39% 降权为过滤器的先例）。')}
    safe_write_json(OUT, out)
    print(f'  review: {len(days)} days, summary: {summary}')


if __name__ == '__main__':
    main()
