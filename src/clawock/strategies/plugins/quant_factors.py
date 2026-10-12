"""The `factors` service: the quant factor row every live path reads.

This is the arithmetic behind `assets/data/quant_signals.json`, the intraday
radar, the watch list, the brief's add side and the pre-position lane: trend,
momentum, mean reversion, volatility, the chandelier exit, and the three
deterministic technical setups built from them. It is pure — bars in, one row
out — and it is mounted as a plugin so that what the live paths compute is a
row in `config/strategy-plugins.json` rather than an import.

`decision.signals` keeps the names the callers use and delegates here through
`clawock.plugin_host.live`. This is the only implementation.

Config: `sigma_target`, the portfolio volatility the vol-target weight sizes
against (0.25 annualised, kcn 2026-06-11).
"""
from __future__ import annotations

import math

from clawock.market_data.daily_prices import clean_bars

name = 'quant-factors'

SIGMA_TARGET = 0.25


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


def compute_signals(bars, sigma_target=SIGMA_TARGET):
    bars = clean_bars(bars)
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
        'prior_5d_high': round(prior_5d_high, 3) if prior_5d_high else None,
        'prior_5d_low': round(prior_5d_low, 3) if prior_5d_low else None,
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
        'vol_target_weight': round(min(1.0, sigma_target / vol20), 2) if vol20 else None,
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
    tags.append('趋势未知' if sig['trend_on'] is None else
                ('趋势ON' if sig['trend_on'] else '趋势OFF'))
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


def compute_short_history_signals(bars):
    """Reduced technical view for 20–29-bar names (early-trend lane only).

    Newly listed names cannot compute MA200, so the mature `compute_signals`
    30-bar gate answers None and the early-trend lane — built exactly for these
    short-history targets — never sees them. This view computes the fields that
    exist from 20 bars up (close, MA20, prior-20d/5d range, RSI14, zscore20,
    ATR/chandelier) and leaves the mature factors (MA50/MA200/vol20/momentum)
    None, so a short name can never masquerade as a mature factor row. It
    answers None below 20 bars, where even the short view is not computable.
    """
    bars = clean_bars(bars)
    closes = [b['close'] for b in bars]
    if len(closes) < 20:
        return None
    c = closes[-1]
    ma20 = _ma(closes, 20)
    prior_20d_high = max(b['high'] for b in bars[-21:-1]) if len(bars) >= 21 else None
    prior_20d_low = min(b['low'] for b in bars[-21:-1]) if len(bars) >= 21 else None
    prior_5d_high = max(b['high'] for b in bars[-6:-1]) if len(bars) >= 6 else None
    prior_5d_low = min(b['low'] for b in bars[-6:-1]) if len(bars) >= 6 else None
    prev_close = closes[-2] if len(closes) >= 2 else None
    z = None
    if ma20 and len(closes) >= 20:
        sd = math.sqrt(sum((x - ma20) ** 2 for x in closes[-20:]) / 20)
        z = round((c - ma20) / sd, 2) if sd else None
    atr = _atr14(bars)
    chandelier = stop_dist = None
    if atr and len(bars) >= 22:
        hi22 = max(b['high'] for b in bars[-22:])
        chandelier = hi22 - 3 * atr
        stop_dist = round((c / chandelier - 1) * 100, 1) if chandelier > 0 else None
    sig = {
        'close': c,
        'prev_close': prev_close,
        'ma20': round(ma20, 3) if ma20 else None,
        'ma50': None,
        'ma200': None,
        'prior_20d_high': round(prior_20d_high, 3) if prior_20d_high else None,
        'prior_20d_low': round(prior_20d_low, 3) if prior_20d_low else None,
        'prior_5d_high': round(prior_5d_high, 3) if prior_5d_high else None,
        'prior_5d_low': round(prior_5d_low, 3) if prior_5d_low else None,
        'dist_ma200_pct': None,
        'golden_cross': None,
        'trend_on': None,
        'mom_1m': None,
        'mom_3m': None,
        'mom_6m': None,
        'mom_12_1': None,
        'rsi14': _rsi14(closes),
        'zscore20': z,
        'vol20_annualized': None,
        'atr14_pct': round(atr / c * 100, 2) if atr else None,
        'chandelier_stop': round(chandelier, 3) if chandelier else None,
        'stop_distance_pct': stop_dist,
        'vol_target_weight': None,
        'pct_52w_range': None,
        'bars': len(closes),
    }
    sig['technical_setups'] = []
    tags = ['短历史']
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


class Factors:
    def __init__(self, sigma_target: float):
        self.sigma_target = sigma_target

    def signals(self, bars):
        """The mature factor row; None below 30 usable bars."""
        return compute_signals(bars, self.sigma_target)

    def short_history(self, bars):
        """The reduced row for 20-29-bar names; None below 20."""
        return compute_short_history_signals(bars)

    def rsi(self, closes, period=14):
        return _rsi14(closes, period)

    def atr(self, bars, period=14):
        return _atr14(bars, period)

    def describe(self) -> dict:
        return {'sigma_target': self.sigma_target}


def apply(ctx, config):
    sigma = config.get('sigma_target', SIGMA_TARGET)
    if isinstance(sigma, bool) or not isinstance(sigma, (int, float)) or not sigma > 0:
        raise ValueError(f'quant-factors sigma_target must be a positive number, got {sigma!r}')
    ctx.provide('factors', Factors(float(sigma)))
