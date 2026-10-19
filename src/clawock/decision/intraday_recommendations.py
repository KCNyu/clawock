"""Advisory-only conditional orders; historical research never grants execution."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from statistics import fmean, pstdev
from zoneinfo import ZoneInfo

from clawock import sessions
from clawock.costs import CostModel, trade_cost
from clawock.market_data import intraday_bars


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def build(workspace, market, research, policies, plan_context, *, now=None, fetch=None):
    """Fixed exploration rule, studied ticker only; never writes any order or book."""
    now = now or datetime.now(timezone.utc)
    result = {'schema': 'intraday-recommendations/v1', 'advisory_only': True,
              'execution_permission': False, 'rows': [], 'reasons': [],
              'generated_at': now.isoformat(), 'market': market,
              'manifest_sha256': research.get('manifest_sha256'),
              'data_sha256': research.get('data_sha256'),
              'research_base': (research.get('metrics') or {}).get('base'),
              'prospective_status': research.get('prospective_status', 'not_started')}

    def refuse(reason):
        result['rows'] = []
        result['reasons'].append(reason)
        return result

    try:
        if (market != 'us' or research.get('validation') not in
                {'insufficient_or_failed', 'retrospective_candidate'}
                or research.get('metrics_withheld_for_rights') is not False
                or not research.get('recommendation_evidence_ok')):
            return refuse('无可用的本市场真实研究证据；不外推其他标的')
        for key in ('manifest_sha256', 'data_sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}', result[key] or ''):
                return refuse('研究指纹缺失或无效')
        base = result['research_base']
        if not base or any(type(base.get(k)) not in (int, float) or not math.isfinite(base[k])
                           for k in ('net_increment', 'max_session_close_drawdown', 'costs')):
            return refuse('历史净结果缺失')
        ticker = research['ticker']
        result['ticker'] = ticker
        if research.get('recommendation_candidate') != {
                'service': 'intraday_reversion', 'params': {'window': 20, 'deviations': 2.0}}:
            return refuse('冻结研究的首个候选不匹配推荐规则')
        if ticker == 'SPCH' or policies.get(ticker, {}).get('forbid_reduce_advice'):
            return refuse('持仓策略禁止减持建议')
        book = json.loads((workspace / 'portfolio.json').read_text())
        leg = book['portfolios']['us_stocks']
        amounts = [r.get('shares') for r in leg['holdings']
                   if isinstance(r, dict) and r.get('ticker') == ticker]
        if any(type(q) not in (int, float) or not math.isfinite(q) or q < 0 for q in amounts):
            return refuse('真实持仓股数无效')
        shares = sum(amounts)
        if shares <= 0:
            return refuse(f'真实账本未持有 {ticker}；研究底仓不是持仓，不建议新开仓')
        if any(r.get('ticker') == ticker for r in plan_context.get('open', [])):
            return refuse('该标的已有未完成计划；先核对成交和剩余持仓')
        if not sessions.in_session(market, now):
            return refuse('当前非美股常规交易时段')
        local = now.astimezone(ZoneInfo('America/New_York'))
        # Regular full sessions only. Conservatively exclude July 2/3,
        # Christmas Eve and the Friday after US Thanksgiving.
        day_of_month = local.day
        early = ((local.month, day_of_month) in {(7, 2), (7, 3), (12, 24)}
                 or (local.month == 11 and local.weekday() == 4 and 23 <= day_of_month <= 29))
        if early:
            return refuse('节日前后可能为短交易场次；仅支持常规完整场次')
        if local.hour * 60 + local.minute >= 950:
            return refuse('临近收盘，不再开始回转')
        qty = min(1, math.floor(shares * 0.1))
        if qty < 1:
            return refuse('真实底仓不足以按最多十分之一、整股回转')
        day = local.date().isoformat()
        packet = (fetch or intraday_bars.fetch)(workspace, ticker, day)
        bars, times = [], []
        for bar in packet['bars']:
            stamp = datetime.fromisoformat(bar['end'])
            if stamp.utcoffset() is None:
                raise ValueError('bar timezone missing')
            stamp = stamp.astimezone(local.tzinfo)
            if stamp > local:
                continue
            if (stamp.date() != local.date() or stamp.second or stamp.microsecond
                    or stamp.minute % 5 or not 575 <= stamp.hour * 60 + stamp.minute <= 960):
                raise ValueError('wrong session or bar interval')
            values = [bar[k] for k in ('open', 'high', 'low', 'close', 'volume')]
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                raise ValueError('nonfinite OHLCV')
            if (min(values[:4]) <= 0 or bar['volume'] < 0
                    or not bar['low'] <= min(bar['open'], bar['close'])
                    <= max(bar['open'], bar['close']) <= bar['high']):
                raise ValueError('invalid OHLCV')
            times.append(stamp)
            bars.append(bar)
        if (not bars or times[0].hour * 60 + times[0].minute != 575
                or any((b-a).total_seconds() != 300 for a, b in zip(times, times[1:]))):
            return refuse('当日五分钟行情缺失、乱序或不完整')
        if not 0 <= (local-times[-1]).total_seconds() < 300:
            return refuse('最新已完成五分钟行情过期；延迟源不能支持本档建议')
        if len(bars) < 21:
            return refuse('当日已完成行情不足二十一根')
        history = [b['close'] for b in bars[-21:-1]]
        mean, sigma = fmean(history), pstdev(history)
        band, signal = mean + 2 * sigma, bars[-1]['close']
        if sigma <= 0 or signal <= band:
            return refuse('未触及前二十根均价加两倍标准差的回转条件')
        if qty > bars[-1]['volume'] * 0.01:
            return refuse('股数超过最新完成 bar 成交量的百分之一')
        entry, target = math.ceil(signal * 100) / 100, round(mean, 2)
        stop = round(entry + entry - target, 2)
        if not 0 < target < entry < stop:
            return refuse('按美分取整后无有效回转空间')
        costs = CostModel.load(workspace / 'config/cost-model.json')
        def charge(price, direction):
            return trade_cost(qty*price, 'us', day, {}, costs,
                              direction=direction, ticker=ticker, shares=qty)['total']
        fee = charge(entry, 'sell') + charge(target, 'buy')
        gross = qty * (entry-target)
        if gross <= 2 * fee or (gross-fee)/(qty*entry)*10000 < 10:
            return refuse('目标价差不足以覆盖条件成本和净空间')
        cash = leg.get('cash_usd')
        if (type(cash) not in (int, float) or not math.isfinite(cash)
                or cash < qty*(stop-entry) + charge(entry, 'sell') + charge(stop, 'buy')):
            return refuse('账本现金不足以支持失效位买回；跳空仍可能超支')
        expires = times[-1] + timedelta(minutes=5)
        live_data = {'ticker': ticker, 'session': day, 'provider': packet['provider'],
                     'url': packet['url'], 'bars': bars}
        row = {'ticker': ticker, 'action': 'sell_base_then_buy_back', 'shares': qty,
               'sell_limit': entry, 'buyback_target': target, 'buyback_stop': stop,
               'signal_at': times[-1].isoformat(), 'expires_at': expires.isoformat(),
               'band': band, 'conditional_roundtrip_cost': fee,
               'manifest_sha256': result['manifest_sha256'], 'data_sha256': result['data_sha256'],
               'live_data_sha256': digest(live_data), 'research_base': base,
               'prospective_status': result['prospective_status']}
        result['rows'] = [row]
        result['live_input'] = live_data
        result['cost_model'] = costs.as_dict()
        result['book_sha256'] = digest(book)
        return result
    except Exception:
        # Optional recommendation lane must never prevent the normal card.
        # Never expose HTTP exception text: providers may put secrets in URLs.
        return refuse('推荐输入或 Massive/Polygon 行情源不可用；不以缓存价补齐')
