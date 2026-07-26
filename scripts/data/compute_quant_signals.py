#!/usr/bin/env python3
"""市面标准量化因子层 — 纯算术，零 LLM 观点（kcn 2026-06-11：「纯靠 LLM 推理不行，补量化」）。

对每只活跃持仓（杠杆 ETF 按标的算，07226→HSTECH 指数）每日计算经典因子：

  趋势   ma50 / ma200 / dist_ma200_pct      经典双均线；trend_on = close>MA200 且 MA50>MA200
         golden_cross                        MA50 vs MA200（金叉/死叉）
  动量   mom_1m / mom_3m / mom_6m            21/63/126 交易日收益
         mom_12_1                            Jegadeesh-Titman 12-1 动量（252d 收益剔除最近 21d）
  均值回归 rsi14                              Wilder RSI(14)：>70 超买 / <30 超卖
         zscore20                            (close−MA20)/σ20 布林 z 分数：|z|>2 = 极端
  波动   vol20_annualized                    20d 已实现波动年化（σ_daily×√252）
         atr14_pct                           Wilder ATR(14)/close — 真实波幅
  离场   chandelier_stop                     吊灯止损 = 22d 最高价 − 3×ATR(14)（趋势跟踪标准离场）
         stop_distance_pct                   现价距吊灯线（负=已跌破，趋势单应离场）
  仓位   vol_target_weight                   波动目标仓位 = min(1, σ_target/σ_realized)，σ_target=25%
  位置   pct_52w_range                       现价在 52 周高低区间的位置（0=最低 100=最高）

写 assets/data/quant_signals.json（铁律：merge-not-overwrite——单只抓空保留旧值）。
消费方：brief context['quant_signals'] + dashboard「📊 量化因子」卡。
LLM 引用纪律：技术面判断只准引用本表数字，不得自创（SKILL 已写）。

诚实口径：这些是风控/纪律因子不是 alpha——动量/趋势有大量文献支撑但都会被洗(whipsaw)；
它们的作用是把「该不该持有/该多大仓位/何处离场」从感觉变成数字，效果靠 calibration 回头验。
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

import requests

WS = Path(__file__).resolve().parents[2]
PORTFOLIO = WS / 'portfolio.json'
OUT = WS / 'assets' / 'data' / 'quant_signals.json'
HIST = WS / 'assets' / 'data' / 'quant_signals_history.jsonl'

TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'
TENCENT_FQ = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/121.0 Safari/537.36')

SIGMA_TARGET = 0.25   # vol-target sizing 的组合级目标波动（25% 年化）

sys.path.insert(0, str(WS / 'scripts' / 'data'))
from instrument_registry import require as require_instrument  # noqa: E402

try:
    from safe_io import safe_write_json  # type: ignore
except Exception:
    def safe_write_json(path, data, indent=2):
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=indent))


def _parse_bars(rows):
    """Tencent kline 行 = [date, open, close, high, low, ...] → list of dict（含 OHLC）。"""
    out = []
    for r in rows:
        try:
            out.append({'date': r[0], 'open': float(r[1]), 'close': float(r[2]),
                        'high': float(r[3]), 'low': float(r[4])})
        except (IndexError, ValueError):
            continue
    return out


def fetch_bars(code, cnt=400):
    """日 K（qfq 优先）。HK 走 kline 带日期窗，US 走 fqkline。"""
    today = date.today().isoformat()
    if code.startswith('hk'):
        url = f'{TENCENT}?param={code},day,2024-01-01,{today},{cnt}'
    else:
        url = f'{TENCENT_FQ}?param={code},day,,,{cnt},qfq'
    try:
        d = requests.get(url, headers={'User-Agent': UA}, timeout=20).json()
    except Exception as e:
        print(f'  warn: {code} fetch failed: {e}', file=sys.stderr)
        return []
    node = (d.get('data') or {}).get(code, {})
    rows = node.get('qfqday') or node.get('day') or []
    return _parse_bars(rows)


def _ma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def _ret(closes, n):
    """n 个交易日收益率（%）。"""
    return (closes[-1] / closes[-1 - n] - 1) * 100 if len(closes) > n else None


def _rsi14(closes, n=14):
    """Wilder RSI：先 n 日均值种子，再按 (prev*(n−1)+cur)/n 平滑。"""
    if len(closes) < n + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        avg_g = (avg_g * (n - 1) + g) / n
        avg_l = (avg_l * (n - 1) + l) / n
    if avg_l == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_g / avg_l), 1)


def _atr14(bars, n=14):
    """Wilder ATR：TR=max(H−L, |H−prevC|, |L−prevC|)，同样的 Wilder 平滑。"""
    if len(bars) < n + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]['high'], bars[i]['low'], bars[i - 1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def compute_signals(bars):
    closes = [b['close'] for b in bars]
    if len(closes) < 30:
        return None
    c = closes[-1]
    ma20, ma50, ma200 = _ma(closes, 20), _ma(closes, 50), _ma(closes, 200)
    # 均值回归：20d 布林 z 分数
    z = None
    if ma20 and len(closes) >= 20:
        sd = math.sqrt(sum((x - ma20) ** 2 for x in closes[-20:]) / 20)
        z = round((c - ma20) / sd, 2) if sd else None
    # 波动：20d 已实现年化
    vol20 = None
    if len(closes) >= 21:
        rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - 20, len(closes))]
        mu = sum(rets) / len(rets)
        vol20 = math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)) * math.sqrt(252)
    atr = _atr14(bars)
    # 吊灯止损：22d 最高价 − 3×ATR（趋势跟踪标准离场线）
    chandelier = stop_dist = None
    if atr and len(bars) >= 22:
        hi22 = max(b['high'] for b in bars[-22:])
        chandelier = hi22 - 3 * atr
        stop_dist = round((c / chandelier - 1) * 100, 1) if chandelier > 0 else None
    # 12-1 动量：252d 收益剔除最近 21d（动量经典构造，避开短期反转）
    mom_12_1 = None
    if len(closes) > 252:
        mom_12_1 = round((closes[-22] / closes[-253] - 1) * 100, 1)
    lo52 = min(closes[-252:]) if len(closes) >= 252 else min(closes)
    hi52 = max(closes[-252:]) if len(closes) >= 252 else max(closes)
    trend_on = bool(ma200 and ma50 and c > ma200 and ma50 > ma200)
    sig = {
        'close': c,
        'ma50': round(ma50, 3) if ma50 else None,
        'ma200': round(ma200, 3) if ma200 else None,
        'dist_ma200_pct': round((c / ma200 - 1) * 100, 1) if ma200 else None,
        'golden_cross': (ma50 > ma200) if (ma50 and ma200) else None,
        'trend_on': trend_on if ma200 else None,
        'mom_1m': _ret(closes, 21) and round(_ret(closes, 21), 1),
        'mom_3m': _ret(closes, 63) and round(_ret(closes, 63), 1),
        'mom_6m': _ret(closes, 126) and round(_ret(closes, 126), 1),
        'mom_12_1': mom_12_1,
        'rsi14': _rsi14(closes),
        'zscore20': z,
        'vol20_annualized': round(vol20, 4) if vol20 else None,
        'atr14_pct': round(atr / c * 100, 2) if atr else None,
        'chandelier_stop': round(chandelier, 3) if chandelier else None,
        'stop_distance_pct': stop_dist,
        'vol_target_weight': round(min(1.0, SIGMA_TARGET / vol20), 2) if vol20 else None,
        'pct_52w_range': round((c - lo52) / (hi52 - lo52) * 100, 1) if hi52 > lo52 else None,
        'bars': len(closes),
    }
    # 一行人话标签（仍是规则拼的，不是 LLM）
    tags = []
    tags.append('趋势ON' if trend_on else '趋势OFF')
    if sig['rsi14'] is not None:
        if sig['rsi14'] >= 70:
            tags.append(f"RSI超买{sig['rsi14']}")
        elif sig['rsi14'] <= 30:
            tags.append(f"RSI超卖{sig['rsi14']}")
    if z is not None and abs(z) >= 2:
        tags.append(f'z{z:+.1f}σ极端')
    if stop_dist is not None and stop_dist < 0:
        tags.append('已破吊灯止损')
    sig['tag'] = ' · '.join(tags)
    return sig


def _universe():
    """活跃持仓 → [(展示名, canonical Tencent 代码, 备注)]。

    杠杆产品使用 registry 的 signal_symbol 折到标的/1x proxy；venue 后缀
    同样从 registry 读取，绝不再默认猜成 Nasdaq。
    """
    port = json.loads(PORTFOLIO.read_text())
    uni, seen = [], set()
    for region in ('hk_stocks', 'us_stocks'):
        for h in port['portfolios'][region]['holdings']:
            if h.get('shares', 0) <= 0:
                continue
            t = h.get('ticker')
            meta = require_instrument(t)
            signal_symbol = meta.get('signal_symbol') or t
            signal_meta = require_instrument(signal_symbol)
            label = signal_symbol
            code = signal_meta.get('tencent_symbol')
            note = f'{t} 的标的/1x proxy' if signal_symbol != t else ''
            if not code:
                raise ValueError(f'{signal_symbol} has no canonical Tencent symbol')
            if code in seen:
                continue
            seen.add(code)
            uni.append((label, code, note))
    return uni


def main():
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
        except Exception:
            prev = {}
    rows = dict((prev.get('rows') or {}))  # merge-not-overwrite：抓空的票保留旧值

    for label, code, note in _universe():
        bars = fetch_bars(code)
        sig = compute_signals(bars) if bars else None
        if sig is None:
            print(f'  warn: {label} ({code}) no data — retained prior', file=sys.stderr)
            continue
        sig['code'] = code
        if note:
            sig['note'] = note
        rows[label] = sig
        print(f"  {label:8s} {sig['tag']}  RSI {sig['rsi14']}  z {sig['zscore20']}  "
              f"距200线 {sig['dist_ma200_pct']}%  吊灯距 {sig['stop_distance_pct']}%")

    out = {
        'as_of': date.today().isoformat(),
        'sigma_target': SIGMA_TARGET,
        'rows': rows,
        'formulas': {
            'trend': 'trend_on = close>MA200 且 MA50>MA200（双均线）；golden_cross = MA50>MA200',
            'momentum': 'mom_Nm = N 月收益；mom_12_1 = 252d 收益剔除最近 21d（Jegadeesh-Titman）',
            'mean_reversion': 'rsi14 = Wilder RSI(14)，>70 超买/<30 超卖；zscore20 = (close−MA20)/σ20，|z|>2 极端',
            'vol': 'vol20 = 20d 日收益 σ×√252；atr14_pct = Wilder ATR(14)/close',
            'exit': 'chandelier_stop = 22d 最高价 − 3×ATR(14)；stop_distance_pct<0 = 已破线（趋势单标准离场）',
            'sizing': f'vol_target_weight = min(1, {SIGMA_TARGET}/vol20) — 波动越高仓位上限越小',
        },
        'reading_discipline': ('因子是纪律不是预言：趋势/动量管「该不该持有」，RSI/z 管「别在极端点动手」，'
                               '吊灯线管「趋势单何处离场」，vol-target 管「该拿多大」。'
                               'LLM 技术面判断只准引用本表，效果由 calibration 事后验证。'),
    }
    safe_write_json(OUT, out)
    print(f'  wrote {OUT.relative_to(WS)} ({len(rows)} symbols)')

    # 自迭代闭环第一半：每日信号留痕（JSONL，一天一行）。quant_signal_review.py 用
    # 它对账 forward return → 因子 edge 表。同日重跑替换当天行（盘中多次刷新取最后）。
    hist_line = json.dumps({'as_of': out['as_of'],
                            'rows': {k: {f: v.get(f) for f in
                                         ('close', 'trend_on', 'golden_cross', 'rsi14', 'zscore20',
                                          'stop_distance_pct', 'mom_1m', 'dist_ma200_pct')}
                                     for k, v in rows.items()}}, ensure_ascii=False)
    lines = []
    if HIST.exists():
        lines = [l for l in HIST.read_text().splitlines()
                 if l.strip() and json.loads(l).get('as_of') != out['as_of']]
    lines.append(hist_line)
    HIST.write_text('\n'.join(lines) + '\n')
    print(f'  history: {len(lines)} days in {HIST.name}')


if __name__ == '__main__':
    main()
