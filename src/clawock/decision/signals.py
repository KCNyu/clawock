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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from clawock.market_data import sessions as trading_calendar
from clawock.portfolio.instruments import require as require_instrument
from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
PORTFOLIO = WS / 'portfolio.json'
OUT = WS / 'assets' / 'data' / 'quant_signals.json'
HIST = WS / 'assets' / 'data' / 'quant_signals_history.jsonl'

TENCENT = 'https://web.ifzq.gtimg.cn/appstock/app/kline/kline'
TENCENT_FQ = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/121.0 Safari/537.36')

SIGMA_TARGET = 0.25   # vol-target sizing 的组合级目标波动（25% 年化）
MAX_STALE_DAYS = 7
RETIRED_RETENTION_DAYS = 7

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
    prior_20d_high = max(b['high'] for b in bars[-21:-1]) if len(bars) >= 21 else None
    prior_20d_low = min(b['low'] for b in bars[-21:-1]) if len(bars) >= 21 else None
    prior_5d_high = max(b['high'] for b in bars[-6:-1]) if len(bars) >= 6 else None
    prior_5d_low = min(b['low'] for b in bars[-6:-1]) if len(bars) >= 6 else None
    prev_close = closes[-2] if len(closes) >= 2 else None
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
        'prev_close': prev_close,
        'ma20': round(ma20, 3) if ma20 else None,
        'ma50': round(ma50, 3) if ma50 else None,
        'ma200': round(ma200, 3) if ma200 else None,
        'prior_20d_high': round(prior_20d_high, 3) if prior_20d_high else None,
        'prior_20d_low': round(prior_20d_low, 3) if prior_20d_low else None,
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
    # Deterministic setup candidates.  These are entry *conditions*, not alpha
    # claims: the prospective decision ledger still measures whether they work.
    # Publishing them is necessary for exploration — a gate that permits no
    # technical add can never collect evidence about technical adds.
    stop_intact = stop_dist is not None and stop_dist >= 0
    setups = []
    # Trend pullback: require an actual recent touch of MA20 and a close back
    # above it. Merely being somewhere between MA50 and MA20 is not a reclaim.
    touched_ma20 = ma20 is not None and bars[-1]['low'] <= ma20
    if (
        trend_on and ma20 and ma50 and atr and stop_intact
        and touched_ma20 and c >= ma20 and c <= ma20 + atr * 0.75
        and c > bars[-1]['open'] and c > prev_close
    ):
        setups.append({
            'setup_id': 'trend_pullback',
            'label': '趋势回踩',
            'entry_type': 'price_above',
            'entry_price': round(c, 3),
            'invalidation_price': round(max(chandelier or 0, ma50 - atr), 3),
            'max_tranches': 2,
            'tranche_pct_of_position': 0.10,
            'detail': '多头排列中当日触及并收复 MA20，阳线且高于前收；只分两批加',
        })
    if (
        trend_on and prior_20d_high and c > prior_20d_high and stop_intact
        and (_ret(closes, 21) or 0) > 0
    ):
        setups.append({
            'setup_id': 'confirmed_breakout',
            'label': '20日突破确认',
            'entry_type': 'price_above',
            'entry_price': round(prior_20d_high, 3),
            'invalidation_price': round(max(ma20 or 0, chandelier or 0), 3),
            'max_tranches': 2,
            'tranche_pct_of_position': 0.10,
            'detail': '趋势 ON 且收盘突破此前 20 日高，回落跌回 MA20/吊灯线则失效',
        })
    rsi = sig.get('rsi14')
    # Mean-reversion add is a two-step pattern: the previous close was weak, and
    # today's bar reclaims the previous day's high. A loss or one green close by
    # itself is deliberately insufficient.
    prev_rsi = _rsi14(closes[:-1])
    prev_ma20 = _ma(closes[:-1], 20)
    prev_z = None
    if prev_ma20 and len(closes) >= 21:
        prev_window = closes[-21:-1]
        prev_sd = math.sqrt(sum((x - prev_ma20) ** 2 for x in prev_window) / 20)
        prev_z = (prev_close - prev_ma20) / prev_sd if prev_sd else None
    if (
        prev_rsi is not None and prev_rsi <= 35
        and prev_z is not None and prev_z <= -1
        and c > bars[-2]['high'] and c > bars[-1]['open']
        and prior_5d_low and c > prior_5d_low
    ):
        setups.append({
            'setup_id': 'oversold_reclaim',
            'label': '超卖收复',
            'entry_type': 'price_above',
            'entry_price': round(c, 3),
            'invalidation_price': round(prior_5d_low, 3),
            'max_tranches': 1,
            'tranche_pct_of_position': 0.05,
            'detail': '前一日 RSI≤35 且 z≤-1，今日收复前高；只加一小批，跌破此前5日低点失效',
        })
    sig['technical_setups'] = setups
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


def _universe_details():
    """活跃持仓 → 去重后的 signal rows，保留每行覆盖的真实持仓。

    杠杆产品使用 registry 的 signal_symbol 折到标的/1x proxy；venue 后缀
    同样从 registry 读取，绝不再默认猜成 Nasdaq。
    """
    port = json.loads(PORTFOLIO.read_text())
    by_code = {}
    for book in (port.get('portfolios') or {}).values():
        if not isinstance(book, dict):
            continue
        for h in book.get('holdings', []):
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
            row = by_code.setdefault(code, {
                'label': label,
                'code': code,
                'note': note,
                'region': signal_meta['region'],
                'source_holdings': [],
            })
            row['source_holdings'].append(t)
            if note and not row['note']:
                row['note'] = note
    return list(by_code.values())


def _universe():
    """Compatibility view used by registry tests and small callers."""
    return [
        (row['label'], row['code'], row['note'])
        for row in _universe_details()
    ]


def _latest_completed_session(region, at=None):
    return trading_calendar.latest_completed_session(region, at)


def _as_date(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _missing_row(detail, reason, last_good_as_of=None):
    row = {
        'code': detail['code'],
        'source_holdings': sorted(detail['source_holdings']),
        'status': 'missing',
        'row_as_of': None,
        'last_good_as_of': last_good_as_of,
        'stale_reason': reason,
        'max_age_days': MAX_STALE_DAYS,
    }
    if detail.get('note'):
        row['note'] = detail['note']
    return row


def _carry_setup_campaigns(sig, previous, row_as_of):
    """Keep a campaign id while a setup remains continuously present."""
    prior = {
        row.get('setup_id'): row.get('campaign_id')
        for row in (previous or {}).get('technical_setups') or []
        if row.get('setup_id') and row.get('campaign_id')
    }
    for setup in sig.get('technical_setups') or []:
        setup_id = setup.get('setup_id')
        setup['campaign_id'] = (
            prior.get(setup_id) or f'{setup_id}:{row_as_of.isoformat()}'
        )


def refresh_rows(previous, universe, *, run_date=None, previous_as_of=None,
                 expected_sessions=None, fetcher=fetch_bars):
    """Refresh current rows, make failures visible, and age out retired rows."""
    run_date = run_date or date.today()
    expected_sessions = expected_sessions or {
        region: _latest_completed_session(region)
        for region in ('US', 'HK')
    }
    rows = {}
    current_labels = {detail['label'] for detail in universe}

    for detail in universe:
        label = detail['label']
        old = dict(previous.get(label) or {})
        old_as_of = old.get('row_as_of')
        # Legacy rows predate per-row freshness and may inherit the old top-level
        # date once. A visible missing marker is not a last-known-good row.
        if not old_as_of and old and not old.get('status'):
            old_as_of = previous_as_of
        last_good_as_of = old_as_of or old.get('last_good_as_of')
        bars = fetcher(detail['code'])
        expected = expected_sessions.get(detail['region'])
        # Some providers publish a moving daily candle before the exchange has
        # closed. It is not a completed session and must not create a setup.
        if expected:
            bars = [
                bar for bar in bars
                if (_as_date(bar.get('date')) is not None
                    and _as_date(bar.get('date')) <= expected)
            ]
        sig = compute_signals(bars) if bars else None
        if sig is not None:
            row_as_of = _as_date(bars[-1].get('date'))
            age_days = (run_date - row_as_of).days if row_as_of else None
            if row_as_of is None:
                rows[label] = _missing_row(
                    detail, 'latest bar has no valid date', last_good_as_of)
                continue
            if age_days > MAX_STALE_DAYS:
                rows[label] = _missing_row(
                    detail,
                    f'latest bar {row_as_of} exceeds {MAX_STALE_DAYS}-day max age',
                    row_as_of.isoformat(),
                )
                continue
            _carry_setup_campaigns(sig, old, row_as_of)
            sig.update({
                'code': detail['code'],
                'source_holdings': sorted(detail['source_holdings']),
                'status': 'fresh' if not expected or row_as_of >= expected else 'stale',
                'row_as_of': row_as_of.isoformat(),
                'max_age_days': MAX_STALE_DAYS,
            })
            if expected and row_as_of < expected:
                sig['stale_reason'] = (
                    f'latest bar {row_as_of} before expected session {expected}'
                )
            if detail.get('note'):
                sig['note'] = detail['note']
            rows[label] = sig
            continue

        old_date = _as_date(old_as_of)
        age_days = (run_date - old_date).days if old_date else None
        if old and age_days is not None and age_days <= MAX_STALE_DAYS:
            old.update({
                'code': detail['code'],
                'source_holdings': sorted(detail['source_holdings']),
                'status': 'stale',
                'row_as_of': old_date.isoformat(),
                'stale_reason': 'fetch failed or returned insufficient bars',
                'max_age_days': MAX_STALE_DAYS,
            })
            if detail.get('note'):
                old['note'] = detail['note']
            rows[label] = old
        else:
                rows[label] = _missing_row(
                detail, 'fetch failed and no usable last-known-good row',
                last_good_as_of)

    for label, old_value in previous.items():
        if label in current_labels:
            continue
        old = dict(old_value or {})
        retired_since = _as_date(old.get('retired_since')) or run_date
        if (run_date - retired_since).days >= RETIRED_RETENTION_DAYS:
            continue
        old.update({
            'status': 'retired',
            'retired_since': retired_since.isoformat(),
            'retention_days': RETIRED_RETENTION_DAYS,
            'stale_reason': 'not in current signal universe',
        })
        old.setdefault('row_as_of', previous_as_of)
        rows[label] = old
    return rows


def main(argv=None):
    del argv
    prev = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text())
        except Exception:
            prev = {}
    universe = _universe_details()
    rows = refresh_rows(
        prev.get('rows') or {},
        universe,
        previous_as_of=prev.get('as_of'),
    )
    for detail in universe:
        label = detail['label']
        sig = rows[label]
        if sig['status'] == 'fresh':
            print(f"  {label:8s} {sig['tag']}  RSI {sig['rsi14']}  z {sig['zscore20']}  "
                  f"距200线 {sig['dist_ma200_pct']}%  吊灯距 {sig['stop_distance_pct']}%")
        else:
            print(f"  warn: {label} {sig['status']} — {sig.get('stale_reason')}",
                  file=sys.stderr)

    out = {
        'as_of': date.today().isoformat(),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sigma_target': SIGMA_TARGET,
        'max_stale_days': MAX_STALE_DAYS,
        'retired_retention_days': RETIRED_RETENTION_DAYS,
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
                                     for k, v in rows.items()
                                     if v.get('status') == 'fresh'}}, ensure_ascii=False)
    lines = []
    if HIST.exists():
        lines = [l for l in HIST.read_text().splitlines()
                 if l.strip() and json.loads(l).get('as_of') != out['as_of']]
    lines.append(hist_line)
    HIST.write_text('\n'.join(lines) + '\n')
    print(f'  history: {len(lines)} days in {HIST.name}')


if __name__ == '__main__':
    main()
