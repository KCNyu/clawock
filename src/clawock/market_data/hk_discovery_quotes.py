"""Common HK quote-time semantics and independent-source reconciliation."""
from datetime import datetime, time

from clawock.safe_io import to_finite_number
from clawock.sessions import HKT, HK_HALF_DAYS, is_trading_day, latest_completed_session, previous_trading_day


def normalize(meta, *, observed, price, previous, turnover, cap, change, source, now):
    values = [to_finite_number(v) for v in (price, previous, turnover, cap, change)]
    if any(v is None for v in values) or any(values[i] <= 0 for i in (0, 1, 3)) or values[2] < 0:
        raise ValueError('invalid_quote')
    price, previous, turnover, cap, change = values
    local = now.astimezone(HKT)
    completed = latest_completed_session('HK', at=now)
    close_hour = 12 if observed.date().isoformat() in HK_HALF_DAYS else 16
    if observed > now or not is_trading_day('HK', observed.date()):
        raise ValueError('future_or_nontrading_observation')
    if observed.date() == completed and observed.hour >= close_hour:
        basis, closing_day = 'latest_completed_close', completed
    elif (observed.date() == local.date() and is_trading_day('HK', local.date())
          and time(9, 30) <= observed.time() and local.hour < 17):
        # Includes lunch and the settling interval. Never call this yesterday's close.
        basis, closing_day = 'latest_trade', previous_trading_day('HK', observed.date())
        if (now - observed).total_seconds() > 2 * 3600:
            raise ValueError('stale_intraday_quote')
    else:
        raise ValueError('missing_current_session_quote')
    return {**meta, 'price_hkd': price, 'previous_close_hkd': previous,
            'turnover_hkd': turnover, 'market_cap_hkd': cap, 'change_pct': change,
            'quote_evidence': {'source': source, 'observed_at': observed.isoformat(),
                               'session_date': observed.date().isoformat(), 'price_basis': basis,
                               'latest_close': {'session_date': closing_day.isoformat(),
                                                'field': 'last' if basis == 'latest_completed_close' else 'previous_close'},
                               'freshness': basis}}


def reconcile(primary, secondary):
    """A different session/basis is not confirmation. Divergent same-session quotes are withheld."""
    if primary is None or secondary is None:
        row = primary or secondary
        if row:
            row['quote_evidence']['cross_check'] = 'single_source'
        return row, None
    a, b = primary['quote_evidence'], secondary['quote_evidence']
    if (a['session_date'], a['price_basis']) != (b['session_date'], b['price_basis']):
        newer = max((primary, secondary), key=lambda r: r['quote_evidence']['observed_at'])
        newer['quote_evidence']['cross_check'] = 'different_price_basis'
        return newer, 'different_price_basis'
    if any(abs(primary[k] - secondary[k]) / max(primary[k], secondary[k]) > 0.01
           for k in ('price_hkd', 'previous_close_hkd')):
        return None, 'quote_divergence'
    # Intraday providers can have different delay. Disclose observation times.
    primary['quote_evidence'].update(cross_check='confirmed', sources=[a['source'], b['source']],
                                     secondary_observed_at=b['observed_at'])
    return primary, None


def parse_observed(value):
    return datetime.strptime(value, '%Y/%m/%d %H:%M:%S').replace(tzinfo=HKT)
