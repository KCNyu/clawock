#!/usr/bin/env python3
"""B3 — T+0 setup 评级（牌面质量，不是买卖信号）。

背景：kcn 最近频繁做 T，但 calibration 已证明主动做 T 胜率≈0。本模块不去找日内 alpha
（大概率没有），而是把「这单的 setup 质量」量化出来，让 kcn 点买入前先看到牌面——
尤其是「追高」检测（在当日高位、且今天已大幅波动时买入 = 低质）。

铁律：零额外请求。所有指标从 portfolio.json 已抓字段 + quant_signals.json 已算 ATR 推导：
  gap_pct          (day_open − prev_close)/prev_close      隔夜跳空
  range_pos        (cur − day_low)/(day_high − day_low)    现价在当日区间位置 0=低 100=高
  day_range_pct    (day_high − day_low)/prev_close          当日振幅
  range_used_atr   day_range_pct / atr14_pct                今日是否已跑过一个典型日(>1=耗尽)
  today_change_pct                                          今日涨跌
  rsi14/zscore20   ← quant_signals.json                     均值回归上下文
  decay_note       2x 每日杠杆 → 多日持有衰减提示

VWAP/ORB 需要分钟数据，默认**不抓**（kcn 担心限速）。仅当 T0_INTRADAY=1 且市场开盘时，
每只最多一次 minute/query，抓不到就降级 vwap=None（由 A2 健康卡显示）。

输出 assets/data/t0_setups.json。消费方：dashboard「🎯 T+0 牌面」卡。
"""
import json
import os
import sys
from datetime import datetime
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
PORTFOLIO = WS / 'portfolio.json'
QUANT = WS / 'assets' / 'data' / 'quant_signals.json'
OUT = WS / 'assets' / 'data' / 't0_setups.json'
HIST = WS / 'assets' / 'data' / 't0_setups_history.jsonl'
HIST_MAX_LINES = 4000   # 盘中每 30min 一行，封顶约 1 年留痕

sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))
from clawock.instrument_registry import INSTRUMENTS  # noqa: E402

try:
    from safe_io import safe_write_json
except Exception:
    def safe_write_json(path, data, indent=2):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=indent))
try:
    import trading_calendar as tc
except Exception:
    tc = None

# 2x/3x 每日杠杆 ETF → (标的, 倍数)，由 canonical registry 生成。
LEVERAGED = {
    symbol: (meta.get('underlying') or meta.get('signal_symbol'), meta['leverage_multiple'])
    for symbol, meta in INSTRUMENTS.items()
    if meta['leverage_multiple'] > 1
}
TENCENT_MIN = 'https://web.ifzq.gtimg.cn/appstock/app/minute/query'


def _num(x):
    try:
        v = float(x)
        return v
    except (TypeError, ValueError):
        return None


def _market_of(region):
    return {'us_stocks': 'us', 'hk_stocks': 'hk'}.get(region)


def _tencent_code(ticker, market):
    if market == 'hk':
        return 'hk' + ticker
    # us：现货 .OQ/.N，缺省试 .OQ；杠杆 ETF 也用代码本身
    return 'us' + ticker


def fetch_vwap_orb(code):
    """best-effort：当日分钟 tick → VWAP + 前 30 分钟开盘区间。失败返回 None。"""
    try:
        import requests
        r = requests.get(TENCENT_MIN, params={'code': code}, timeout=6)
        node = r.json()['data'][code]['data']
        ticks = node['data'] if isinstance(node, dict) else node
        pv = 0.0
        vol = 0.0
        or_hi = or_lo = None
        for i, row in enumerate(ticks):
            parts = row.split()
            if len(parts) < 3:
                continue
            hhmm, price, cumvol = parts[0], _num(parts[1]), _num(parts[2])
            if price is None:
                continue
            # cumvol 是累计量；用增量近似 VWAP 分子
            inc = (cumvol or 0) - vol
            if inc > 0:
                pv += price * inc
                vol = cumvol
            if i < 30:  # 前 30 分钟开盘区间
                or_hi = price if or_hi is None else max(or_hi, price)
                or_lo = price if or_lo is None else min(or_lo, price)
        vwap = round(pv / vol, 4) if vol else None
        return {'vwap': vwap, 'or_high': or_hi, 'or_low': or_lo}
    except Exception:
        return None


def holding_metrics(h, q=None):
    """从单只持仓字段（+ 可选 quant 行）算 T+0 牌面指标。供 compute() 与 backfill 复用。"""
    q = q or {}
    cur = _num(h.get('current_price'))
    lo = _num(h.get('day_low'))
    hi = _num(h.get('day_high'))
    op = _num(h.get('day_open'))
    pc = _num(h.get('prev_close'))
    atr = _num(q.get('atr14_pct'))
    gap = round((op - pc) / pc * 100, 2) if op and pc else None
    rng = (hi - lo) if (hi and lo) else None
    range_pos = round((cur - lo) / rng * 100, 1) if (rng and rng > 0 and cur is not None) else None
    day_range_pct = round(rng / pc * 100, 2) if (rng and pc) else None
    range_used_atr = round(day_range_pct / atr, 2) if (day_range_pct and atr) else None
    return {
        'name': h.get('name'), 'current': cur,
        'today_change_pct': _num(h.get('today_change_pct')),
        'gap_pct': gap, 'range_pos': range_pos, 'day_range_pct': day_range_pct,
        'range_used_atr': range_used_atr,
        'rsi14': _num(q.get('rsi14')), 'zscore20': _num(q.get('zscore20')),
        'atr14_pct': atr,
    }


def grade(m):
    """规则化牌面评级（诚实：纪律因子，不是 alpha）。返回 (emoji, label, reason)。"""
    rp = m.get('range_pos')
    ru = m.get('range_used_atr')
    rsi = m.get('rsi14')
    z = m.get('zscore20')
    chg = m.get('today_change_pct')

    # 追高检测（ATR 缺失也能判——区间位本身就是牌面）：
    #   ① 极端高位（≥85%）：买在当日最高一截，无条件 🔴
    #   ② 高位（≥75%）+ 今日振幅已耗尽（≥0.8×ATR）：追在尾部，🔴
    if rp is not None and rp >= 85:
        ext = f'、今日振幅已达典型日 {ru:.1f}×' if ru is not None else ''
        return ('🔴', '追高低质',
                f'现价在当日区间 {rp:.0f}% 顶部{ext}，几乎买在最高点')
    if rp is not None and ru is not None and rp >= 75 and ru >= 0.8:
        return ('🔴', '追高低质',
                f'现价在当日区间 {rp:.0f}% 高位、今日振幅已达典型日的 {ru:.1f}×，追在尾部')
    if rp is not None and rp >= 70:
        return ('🟡', '偏高位（追高风险）',
                f'现价在当日区间 {rp:.0f}% 偏高位，追买性价比差，等回踩')
    # 超卖/低位反弹候选（接刀风险，仅作观察）
    if (rsi is not None and rsi <= 30) or (z is not None and z <= -2) or (rp is not None and rp <= 20):
        bits = []
        if rsi is not None and rsi <= 30:
            bits.append(f'RSI{rsi:.0f} 超卖')
        if z is not None and z <= -2:
            bits.append(f'z={z:.1f} 极端偏离')
        if rp is not None and rp <= 20:
            bits.append(f'区间 {rp:.0f}% 低位')
        return ('🟡', '低位/超卖（观察）',
                '、'.join(bits) + '；均值回归候选，但有接刀风险')
    # 趋势日中段
    if rp is not None and 20 < rp < 70:
        return ('🟡', '中性', f'区间 {rp:.0f}% 中段，无明显边缘')
    return ('⚪', '无设置', '当日数据不足以判牌面')


def compute(intraday=False):
    pf = json.loads(PORTFOLIO.read_text())
    quant = {}
    if QUANT.exists():
        try:
            quant = (json.loads(QUANT.read_text()).get('rows') or {})
        except Exception:
            pass

    rows = {}
    market_closed = {}
    for region, port in pf.get('portfolios', {}).items():
        market = _market_of(region)
        if market and tc is not None:
            try:
                market_closed[market] = tc.closed_reason(market) is not None
            except Exception:
                market_closed[market] = None
        do_intraday = intraday and not market_closed.get(market, True)
        for h in port.get('holdings', []):
            if (_num(h.get('shares')) or 0) <= 0:
                continue
            t = h.get('ticker')
            cur = _num(h.get('current_price'))
            qrow = quant.get(t, {})
            if qrow.get('status') not in (None, 'fresh'):
                qrow = {}
            m = {'market': market}
            m.update(holding_metrics(h, qrow))
            if t in LEVERAGED:
                u, x = LEVERAGED[t]
                m['leveraged'] = f'{x}x {u}'
                m['decay_note'] = f'{x}x 每日杠杆，多日持有有衰减；做 T 当日无碍，别拿来等多日故事'
            if do_intraday:
                vo = fetch_vwap_orb(_tencent_code(t, market))
                if vo:
                    m.update(vo)
                    if vo.get('vwap') and cur is not None:
                        m['vs_vwap_pct'] = round((cur / vo['vwap'] - 1) * 100, 2)

            emoji, label, reason = grade(m)
            m['grade'] = emoji
            m['grade_label'] = label
            m['grade_reason'] = reason
            rows[t] = m

    return {
        'as_of': datetime.now().astimezone().isoformat(timespec='seconds'),
        'market_closed': market_closed,
        'intraday_enriched': intraday,
        'note': '牌面质量评级，非买卖信号。追高检测 = 当日高位+振幅耗尽时买入为低质。',
        'rows': rows,
    }


def persist_history(data):
    """每次运行追加一行留痕，供 t0_setup_review.py 对账（零网络）。
    只记结算需要的精简字段：grade_label + range_pos + close（= 记录时现价）。"""
    from datetime import date as _date
    rows = {t: {'grade_label': m.get('grade_label'), 'range_pos': m.get('range_pos'),
                'close': m.get('current'), 'market': m.get('market')}
            for t, m in data.get('rows', {}).items() if m.get('current') is not None}
    if not rows:
        return
    line = json.dumps({'as_of': _date.today().isoformat(),
                       'ts': data.get('as_of'), 'rows': rows}, ensure_ascii=False)
    try:
        existing = HIST.read_text().splitlines() if HIST.exists() else []
    except Exception:
        existing = []
    existing.append(line)
    if len(existing) > HIST_MAX_LINES:
        existing = existing[-HIST_MAX_LINES:]
    HIST.parent.mkdir(parents=True, exist_ok=True)
    HIST.write_text('\n'.join(existing) + '\n')


def main(argv):
    intraday = os.environ.get('T0_INTRADAY') == '1' or '--intraday' in argv
    data = compute(intraday=intraday)
    safe_write_json(str(OUT), data)
    persist_history(data)
    for t, m in data['rows'].items():
        extra = f"  vsVWAP {m['vs_vwap_pct']:+.1f}%" if m.get('vs_vwap_pct') is not None else ''
        print(f"{m['grade']} {t:7s} {m['grade_label']:14s} "
              f"区间位 {m.get('range_pos')}  振幅/ATR {m.get('range_used_atr')}{extra}")
        print(f"        └ {m['grade_reason']}")
    print(f"\n写入 {OUT}（intraday_enriched={intraday}）")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
