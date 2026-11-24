"""Same-instrument price evidence for Mode 7's next-trigger line."""

import re
from decimal import Decimal, InvalidOperation

from clawock.harness._harness_common import parse_holdings_rows
from clawock.instruments import INSTRUMENTS, watch_level_owner

SUBJECT_ALIASES = {
    '恒科': 'HSTECH', '恒生科技': 'HSTECH', '恒指': 'HSI', '恒生指数': 'HSI',
    '标普': 'SPX', '纳指': 'NDX', '纳斯达克': 'NDX', 'NASDAQ': 'NDX',
}
# Watch-level keys are free text. Accept explicitly price-shaped names only.
WATCH_PRICE = re.compile(
    r'_(?:breakdown|reclaim(?:_ma\d+)?|ma\d+|(?:(?:own|prior|\d+d)_)*(?:low|high)'
    r'|stop|support|resistance|trigger|price|(?:[a-z]+_)+(?:trigger|price))$'
    r'|^[^_]+_close$')
TECHNICAL_LEVELS = ('close', 'prior_20d_high', 'prior_5d_low')


def subject_code(subject):
    text = str(subject or '').upper()
    return SUBJECT_ALIASES.get(text, text)


def price_number(value):
    try:
        return Decimal(str(value).replace(',', ''))
    except InvalidOperation:
        return None


def trigger_prices(ctx):
    """Group explicit prices by their owner and keep the field that supplied each one."""
    prices = {}
    seen = set()
    unrefreshed = set((ctx.get('quote_coverage') or {}).get('unrefreshed') or [])

    def add(subject, value, source, *, current=False):
        subject = subject_code(subject)
        number = price_number(value)
        if not subject or number is None or not number.is_finite() or number <= 0:
            return
        key = (subject, number, current)
        if key in seen:
            return
        seen.add(key)
        prices.setdefault(subject, []).append({
            'price': str(value), 'source': source, **({'current': True} if current else {}),
        })

    holdings = ctx.get('full_holdings')
    if holdings is not None:
        for row in holdings:
            ticker = row.get('ticker')
            if row.get('quote_fresh') is not False and ticker not in unrefreshed:
                field = 'price' if 'price' in row else 'current_price'
                add(ticker, row.get(field), f'full_holdings.{field}', current=True)
    else:
        # Compatibility with stored contexts that predate the structured sweep.
        for field in ('analyzer_block', 'raw_wechat_block'):
            for row in parse_holdings_rows(ctx.get(field)):
                ticker = row.get('ticker')
                if ticker not in unrefreshed:
                    add(ticker, row['price'], f'{field}.price', current=True)

    plan = ctx.get('plan_context') or {}
    for row in plan.get('open') or []:
        add(row.get('ticker'), row.get('condition_price'), 'plan_context.open.condition_price')
    for row in ctx.get('plan_triggers') or []:
        add(row.get('ticker'), row.get('condition_price'), 'plan_triggers.condition_price')

    for key, value in (ctx.get('watch_levels') or {}).items():
        lowered = key.lower()
        if not WATCH_PRICE.search(lowered) or '_proxy_' in lowered or '_underlying_' in lowered:
            continue
        prefix = key.split('_', 1)[0]
        subject = watch_level_owner(key)
        code = subject_code(prefix)
        if subject is None and (code in prices or code in INSTRUMENTS
                                or code in {'HSI', 'HSTECH', 'SPX', 'NDX', 'VIX'}):
            subject = code
        add(subject, value, f'watch_levels.{key}')

    radar = ctx.get('opportunity_radar') or {}
    for ticker, row in (radar.get('levels') or {}).items():
        for field in TECHNICAL_LEVELS:
            add(ticker, row.get(field), f'opportunity_radar.levels.{field}')
    for row in radar.get('rows') or []:
        for field in TECHNICAL_LEVELS:
            add(row.get('label'), row.get(field), f'opportunity_radar.rows.{field}')

    for row in (ctx.get('add_side_reads') or {}).get('rows') or []:
        ticker = row.get('ticker')
        evidence = row.get('evidence') or {}
        proxy = evidence.get('proxy_label')
        for field in TECHNICAL_LEVELS:
            if proxy:
                add(proxy, evidence.get(f'proxy_{field}'),
                    f'add_side_reads.evidence.proxy_{field}')
            else:
                add(ticker, evidence.get(field), f'add_side_reads.evidence.{field}')
        if not proxy:
            add(ticker, row.get('invalidation'), 'add_side_reads.invalidation')

    for row in (ctx.get('provisional_setups') or {}).get('rows') or []:
        for field in ('entry_price', 'invalidation_price'):
            add(row.get('label'), row.get(field), f'provisional_setups.rows.{field}')
    return prices
