"""Research-only, sell-base/buy-back Bollinger reversion replay.

Independent implementation of the published band formula; no vendor code.
A replay is conditional timing alpha relative to retaining the same shares.
"""
from datetime import datetime
import hashlib
import json
import math
from statistics import fmean, pstdev
from zoneinfo import ZoneInfo

name = 'intraday-reversion'
inject = ('costs',)
DEFAULTS = {'window': 20, 'deviations': 2.0, 'cost_multiple': 2.0,
            'min_net_bps': 10.0, 'max_base_fraction': 0.1}


def _number(value, name, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be numeric')
    if not math.isfinite(value) or (value < 0 if zero else value <= 0):
        raise ValueError(f'{name} must be finite and {"nonnegative" if zero else "positive"}')
    return value


class Reversion:
    def __init__(self, costs, config):
        if set(config) - set(DEFAULTS):
            raise ValueError('unknown intraday-reversion config')
        self.params = {**DEFAULTS, **config}
        for key, value in self.params.items():
            _number(value, key)
        if not isinstance(self.params['window'], int) or self.params['window'] < 2:
            raise ValueError('window must be an integer >= 2')
        if self.params['max_base_fraction'] > 1 or self.params['cost_multiple'] < 1:
            raise ValueError('base fraction <= 1 and cost multiple >= 1 required')
        self.costs = costs

    def replay(self, packet):
        """Replay one complete session; never writes a ledger or grants permission."""
        if not isinstance(packet, dict):
            raise ValueError('packet must be an object')
        result = {'market': packet.get('market'), 'ticker': packet.get('ticker'),
                  'session': packet.get('session'),
                  'currency': {'hk': 'HKD', 'us': 'USD'}.get(packet.get('market')),
                  'strategy': name, 'live_permission': False, 'status': 'refused',
                  'params': dict(self.params), 'trades': [], 'net_pnl': 0.0,
                  'cost_model': self.costs.describe(),
                  'input_sha256': hashlib.sha256(json.dumps(
                      packet, sort_keys=True, allow_nan=False).encode()).hexdigest(),
                  'evidence_grade': 'conditional_replay_not_walk_forward'}
        if packet.get('research_allowed') is not True or packet.get('forbid_reduce_advice') is not False:
            return {**result, 'reason': 'missing_research_scope_or_reduce_forbidden'}
        if not isinstance(packet.get('ticker'), str) or not packet['ticker'].strip():
            raise ValueError('ticker is required')
        market = packet.get('market')
        if market not in ('hk', 'us'):
            raise ValueError('market must be hk or us')
        model = self.costs.describe()
        if model['spread_source'] != 'fixed' or model['impact_source'] != 'off':
            raise ValueError('this replay requires fixed spread and impact off')
        for field in ('spread_bps',):
            _number(model[field].get(market), field, zero=True)
        _number(model['spread_share'], 'spread_share', zero=True)
        result['cost_model'] = {**model, 'minimum_commission_applied': True}
        qty, base, lot = (packet.get(k) for k in ('shares', 'base_shares', 'lot_size'))
        for key, value in [('shares', qty), ('base_shares', base), ('lot_size', lot)]:
            _number(value, key)
            if not isinstance(value, int):
                raise ValueError(f'{key} must be an integer')
        if qty % lot or qty > base * self.params['max_base_fraction']:
            return {**result, 'reason': 'lot_or_base_fraction'}
        bars = packet.get('bars')
        if not isinstance(bars, list) or len(bars) < self.params['window'] + 3:
            return {**result, 'reason': 'insufficient_bars'}
        zone = ZoneInfo('Asia/Hong_Kong' if market == 'hk' else 'America/New_York')
        times = []
        for bar in bars:
            if not isinstance(bar, dict) or not isinstance(bar.get('end'), str):
                raise ValueError('each bar must be an object with an ISO end time')
            stamp = datetime.fromisoformat(bar['end'])
            if stamp.utcoffset() is None:
                raise ValueError('bar end needs timezone')
            stamp = stamp.astimezone(zone)
            if stamp.date().isoformat() != packet.get('session'):
                raise ValueError('mixed or wrong session')
            minutes = stamp.hour * 60 + stamp.minute
            regular = (575 <= minutes <= 720 or 785 <= minutes <= 960) if market == 'hk' else 575 <= minutes <= 960
            if not regular or stamp.second or stamp.microsecond or minutes % 5:
                raise ValueError('only regular-session completed five-minute bars')
            for key in ('open', 'high', 'low', 'close'):
                _number(bar.get(key), key)
            if not bar['low'] <= min(bar['open'], bar['close']) <= max(bar['open'], bar['close']) <= bar['high']:
                raise ValueError('invalid OHLC')
            times.append(stamp)
        expected_first = 575
        if times[0].hour * 60 + times[0].minute != expected_first or times[-1].hour != 16 or times[-1].minute != 0:
            return {**result, 'reason': 'incomplete_session_or_early_close'}
        for previous, current in zip(times, times[1:]):
            gap = (current - previous).total_seconds()
            lunch = market == 'hk' and previous.hour == 12 and previous.minute == 0 and current.hour == 13 and current.minute == 5
            if gap != 300 and not (lunch and gap == 3900):
                return {**result, 'reason': 'missing_duplicate_or_unordered_bars'}
        result.update(status='no_trade', reason='no_cost_qualified_excursion')
        window = self.params['window']
        for index in range(window, len(bars) - 2):
            history = [b['close'] for b in bars[index-window:index]]
            target, sigma = fmean(history), pstdev(history)
            if sigma <= 0 or bars[index]['close'] <= target + self.params['deviations'] * sigma:
                continue
            # Decision made at completed close; execution only at the next open.
            entry = bars[index+1]['open']
            if entry <= target:
                continue
            sell = self.costs.fill(qty * entry, market, packet['session'], direction='sell', ticker=packet.get('ticker'), shares=qty)
            buy_estimate = self.costs.fill(qty * target, market, packet['session'], direction='buy', ticker=packet.get('ticker'), shares=qty)
            charge = sell['total'] + buy_estimate['total']
            excursion = qty * (entry - target)
            net_bps = (excursion - charge) / (qty * entry) * 10000
            if excursion <= self.params['cost_multiple'] * charge or net_bps < self.params['min_net_bps']:
                continue
            stop = entry + (entry - target)
            exit_price, exit_index, reason = bars[-1]['close'], len(bars)-1, 'session_close'
            for j in range(index+1, len(bars)):
                bar = bars[j]
                # Adverse opening gaps first; stop first when OHLC cannot order touches.
                if bar['open'] >= stop:
                    exit_price, exit_index, reason = bar['open'], j, 'gap_stop'
                    break
                if bar['high'] >= stop:
                    exit_price, exit_index, reason = stop, j, 'stop'
                    break
                if bar['low'] <= target:
                    exit_price, exit_index, reason = target, j, 'target'
                    break
            buy = self.costs.fill(qty * exit_price, market, packet['session'], direction='buy', ticker=packet.get('ticker'), shares=qty)
            net = qty * (entry - exit_price) - sell['total'] - buy['total']
            result.update(status='replayed', reason='one_round_trip', net_pnl=net)
            result['trades'] = [{'shares': qty, 'signal_at': bars[index]['end'],
                                 'entry_bar_end': bars[index+1]['end'], 'sell_price': entry,
                                 'exit_bar_end': bars[exit_index]['end'], 'buy_price': exit_price,
                                 'target': target, 'stop': stop, 'exit_reason': reason,
                                 'sell_cost': sell, 'buy_cost': buy, 'net_pnl': net,
                                 'expected_net_bps_at_entry': net_bps}]
            break
        return result


def apply(ctx, config):
    ctx.provide('intraday_reversion', Reversion(ctx.get('costs'), config))
