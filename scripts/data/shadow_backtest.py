#!/usr/bin/env python3
"""影子回测 — 「如果每条 AI 建议都被严格执行,会怎样」的诚实反事实。

kcn 的实操永远是他自己:LLM 只产出建议,执不执行是他的权利。这个模块回答的
是那个一直没被量化的问题——「要是我*全听* AI,累计比不听好还是差?」

诚实性来自复用系统已经在记的同一套数字,绝不另造乐观成交假设:
  memory/calibration.csv 的 pnl_5d / pnl_30d 已是「benefit%」(brief_preflight
  _resolve_pending_outcomes 算的)——即「听这条信号 vs 不听」的方向化好处:
    hold / add → benefit = 标的收益 ret
    cut / trim → benefit = -ret        (标的跌了 = 减仓有好处 = benefit 正)
  进场价用 calibration 已记录的 sim_entry_price(≈ plan 当日收盘),结算价取后续
  交易日快照。本模块只是把这些逐笔 benefit 累计成曲线,不引入新假设。

口径(产出里同样标注,避免自欺):
  • horizon: T+1 = pnl_5d(主, brief 预测次日);T+5 = pnl_30d(次, 论点持久度)
  • 算术累计百分点(pp),等权每条信号,不含 size / 手续费 / 滑点
  • 「全部信号」那条含 hold_and_watch——hold 的 benefit≈标的涨跌=beta,不是 AI 的
    alpha;「仅主动信号」(cut/trim/add/t_only)那条才是顾问真实价值的代理
  • benefit>0 累计上行 = 听 AI 有用;下行 = 不如不动

纯本地文件运算,无网络。build_dashboard 直接 import compute() embed,GHA 重建也能
算(calibration.csv 已 committed)。也可独立跑写 assets/data/shadow_backtest.json。
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
CALIB = WS / 'memory' / 'calibration.csv'
OUT = WS / 'assets' / 'data' / 'shadow_backtest.json'

# 主动出手(把钱真正挪动)的 bucket;hold_and_watch/watch 是 no-op,不算「听 AI 操作」
ACTIVE = {'cut', 'trim_on_rebound', 'add_only_on_trigger', 'add_on_breakout', 't_only'}
SELL = {'cut', 'trim_on_rebound'}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _agg(benefits):
    """累计 / 平均 / 命中率(benefit>0 比例)/ 样本数。"""
    n = len(benefits)
    if not n:
        return {'cum': 0.0, 'avg': None, 'win_rate': None, 'n': 0}
    return {
        'cum': round(sum(benefits), 2),
        'avg': round(sum(benefits) / n, 3),
        'win_rate': round(sum(1 for b in benefits if b > 0) / n, 3),
        'n': n,
    }


def _horizon(rows, col):
    """对单一 horizon(pnl_5d 或 pnl_30d)算全部聚合 + 按 plan_date 的累计曲线。"""
    settled = [r for r in rows
               if (r.get(col) or '').strip() != '' and _f(r.get(col)) is not None]
    settled.sort(key=lambda r: r.get('plan_date', ''))

    all_ben = [_f(r[col]) for r in settled]
    active_rows = [r for r in settled if (r.get('bucket') or '') in ACTIVE]
    active_ben = [_f(r[col]) for r in active_rows]

    by_bucket = defaultdict(list)
    for r in settled:
        by_bucket[r.get('bucket') or '(空)'].append(_f(r[col]))
    by_driver = defaultdict(list)
    for r in active_rows:  # driver 只对主动信号有意义
        by_driver[r.get('driven_by') or '(空)'].append(_f(r[col]))

    # 累计曲线:每个 plan_date 一个点(当日及之前所有信号的累计 benefit)
    curve = []
    cum_all = cum_act = 0.0
    by_date_all = defaultdict(float)
    by_date_act = defaultdict(float)
    for r in settled:
        d = r.get('plan_date', '')
        by_date_all[d] += _f(r[col])
        if (r.get('bucket') or '') in ACTIVE:
            by_date_act[d] += _f(r[col])
    for d in sorted(by_date_all):
        cum_all += by_date_all[d]
        cum_act += by_date_act.get(d, 0.0)
        curve.append({'date': d, 'cum_all': round(cum_all, 2),
                      'cum_active': round(cum_act, 2)})

    return {
        'all_signals': _agg(all_ben),
        'active_signals': _agg(active_ben),
        'by_bucket': {k: _agg(v) for k, v in
                      sorted(by_bucket.items(), key=lambda x: -sum(x[1]))},
        'by_driver': {k: _agg(v) for k, v in
                      sorted(by_driver.items(), key=lambda x: -sum(x[1]))},
        'curve': curve,
    }


def _verdict(t1):
    """一句诚实结论,基于 T+1 主动信号累计。"""
    act = t1['active_signals']
    alls = t1['all_signals']
    if act['n'] < 20:
        return f"样本不足(主动信号 n={act['n']}<20),累计 benefit 仅供参考"
    cut = t1['by_bucket'].get('cut') or {}
    parts = []
    if act['cum'] < 0:
        parts.append(f"全听 AI 的主动建议(n={act['n']})累计 {act['cum']:+.0f}pp，"
                     f"跑输「不动」——主动出手是负贡献")
    else:
        parts.append(f"AI 主动建议(n={act['n']})累计 {act['cum']:+.0f}pp")
    parts.append(f"「全部信号」{alls['cum']:+.0f}pp 几乎全来自 hold(=持有=beta，非 AI alpha)")
    if cut.get('n'):
        parts.append(f"cut 累计 {cut['cum']:+.0f}pp(均 {cut['avg']:+.1f}pp/次，n={cut['n']})最拖累")
    return '；'.join(parts)


def compute(calib_path=CALIB):
    try:
        rows = list(csv.DictReader(open(calib_path, encoding='utf-8')))
    except Exception as e:
        return {'error': f'calibration.csv read fail: {e}'}
    t1 = _horizon(rows, 'pnl_5d')
    t5 = _horizon(rows, 'pnl_30d')
    return {
        'method': ('复用 calibration benefit%(方向化:hold/add=ret, cut/trim=-ret)，'
                   '算术累计 pp，等权，不含 size/手续费/滑点。全部信号含 hold(=beta)，'
                   '主动信号(cut/trim/add/t_only)才是 AI 顾问 alpha 代理。'),
        'horizons': {'t1_next_session': t1, 't5_fifth_session': t5},
        'verdict': _verdict(t1),
    }


def main():
    data = compute()
    sys.path.insert(0, str(WS / 'scripts' / 'data'))
    try:
        from safe_io import safe_write_json
        safe_write_json(str(OUT), data)
    except Exception:
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    v = data.get('verdict', '')
    print(f'✓ wrote {OUT.name}')
    print(f'  verdict: {v}')
    t1 = data.get('horizons', {}).get('t1_next_session', {})
    print(f"  T+1 全部 {t1.get('all_signals',{}).get('cum')}pp | "
          f"主动 {t1.get('active_signals',{}).get('cum')}pp")
    return 0


if __name__ == '__main__':
    sys.exit(main())
