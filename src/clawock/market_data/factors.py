#!/usr/bin/env python3
"""Point-in-time, sector-neutral cross-sectional factor research.

This layer deliberately stays separate from ``quant_signals.json``. The latter
describes held names; this file ranks a curated peer universe and validates the
fixed ranking rule walk-forward. A retrospective result can never activate the
layer. Activation uses only snapshots recorded after ``registered_at`` and is
also blocked until historical universe membership is available.

Writes:
  assets/data/cross_sectional_factor.json
  assets/data/cross_sectional_factor_history.jsonl
"""

import argparse
import json
import math
import random
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from clawock import history_store
from clawock.safe_io import safe_write_json, safe_write_text
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
CONFIG = WS / 'config' / 'factor-universe.json'
OUT = WS / 'assets' / 'data' / 'cross_sectional_factor.json'
HISTORY = WS / 'assets' / 'data' / 'cross_sectional_factor_history.jsonl'
CACHE = WS / '.cache' / 'cross_sectional_quality.json'

TENCENT_QUOTE = 'https://qt.gtimg.cn/q='
TENCENT_KLINE = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
HEADERS = {'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) '
                          'AppleWebKit/537.36 clawock-factor-research/1.0')}
TIMEOUT = 15
TRADING_DAYS = 252
HORIZONS = {'1m': 21, '3m': 63, '6m': 126}
RAW_FACTORS = (
    'residual_mom_1m', 'residual_mom_3m', 'residual_mom_6m',
    'relative_strength', 'breadth', 'liquidity', 'low_volatility',
    'drawdown_resilience', 'quality_profitability',
)
QUALITY_METHOD_VERSION = 2

def load_config(path=CONFIG):
    config = json.loads(Path(path).read_text())
    weights = config.get('factor_weights') or {}
    if set(weights) != set(RAW_FACTORS):
        raise ValueError('factor_weights must exactly match the pre-registered factors')
    if not math.isclose(sum(float(v) for v in weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError('factor_weights must sum to 1')
    keys = {(row['ticker'], row['region']) for row in config.get('symbols') or []}
    if len(keys) != len(config.get('symbols') or []):
        raise ValueError('duplicate ticker/region in factor universe')
    return config


def _quote_parts(ticker):
    response = requests.get(
        f'{TENCENT_QUOTE}us{ticker}', headers=HEADERS, timeout=TIMEOUT
    )
    response.encoding = 'gbk'
    text = response.text.strip()
    start, end = text.find('"') + 1, text.rfind('"')
    return text[start:end].split('~') if start > 0 and end > start else []


def resolve_symbol(spec):
    if spec['region'] == 'hk':
        return f"hk{spec['ticker']}"
    parts = _quote_parts(spec['ticker'])
    if len(parts) > 3 and parts[2]:
        return f'us{parts[2]}'
    return None


def parse_bars(payload, symbol):
    node = (payload.get('data') or {}).get(symbol) or {}
    rows = node.get('qfqday') or node.get('day') or []
    out = []
    for row in rows:
        try:
            open_ = float(row[1])
            close = float(row[2])
            high = float(row[3])
            low = float(row[4])
            volume = float(row[5]) if len(row) > 5 and row[5] not in ('', None) else None
            if min(open_, close, high, low) > 0:
                out.append({'date': str(row[0])[:10], 'open': open_,
                            'close': close, 'high': high, 'low': low,
                            'volume': volume})
        except (TypeError, ValueError, IndexError):
            continue
    deduped = {row['date']: row for row in out}
    return [deduped[d] for d in sorted(deduped)]


def fetch_bars(spec, count=420):
    symbol = resolve_symbol(spec)
    if not symbol:
        return {'ticker': spec['ticker'], 'bars': [], 'error': 'symbol_unresolved'}
    try:
        response = requests.get(
            TENCENT_KLINE,
            params={'param': f'{symbol},day,,,{count},qfq'},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        bars = parse_bars(response.json(), symbol)
    except Exception as exc:
        return {'ticker': spec['ticker'], 'symbol': symbol, 'bars': [],
                'error': str(exc)[:120]}
    return {'ticker': spec['ticker'], 'symbol': symbol, 'bars': bars,
            'error': None if bars else 'empty_history'}


def fetch_universe(config, workers=8):
    specs = list(config['symbols'])
    known = {(row['ticker'], row['region']) for row in specs}
    for proxy in config.get('leveraged_proxies') or []:
        key = (proxy['ticker'], proxy['region'])
        if key not in known:
            specs.append({'ticker': proxy['ticker'], 'region': proxy['region'],
                          'sector': 'leveraged_proxy'})
            known.add(key)
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_bars, spec): spec for spec in specs}
        for future in as_completed(futures):
            spec = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {'ticker': spec['ticker'], 'bars': [],
                          'error': str(exc)[:120]}
            results[spec['ticker']] = result
    return results


def _as_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _concept_entries(facts, concept, as_of):
    concept_node = ((facts.get('facts') or {}).get('us-gaap') or {}).get(concept) or {}
    units = concept_node.get('units') or {}
    entries = units.get('USD') or next(iter(units.values()), [])
    out = []
    for row in entries:
        value = _as_number(row.get('val'))
        filed = str(row.get('filed') or '')[:10]
        if (value is None or not filed or filed > as_of
                or row.get('form') not in ('10-Q', '10-K', '20-F', '40-F')):
            continue
        out.append({
            'value': value,
            'end': str(row.get('end') or '')[:10],
            'filed': filed,
            'form': row.get('form'),
            'fp': row.get('fp'),
        })
    out.sort(key=lambda row: (row['end'], row['filed']), reverse=True)
    return out


def quality_snapshot(facts, as_of):
    """Return profitability known by ``as_of``; filing date prevents look-ahead."""
    concepts = {
        'revenue': ('RevenueFromContractWithCustomerExcludingAssessedTax',
                    'Revenues', 'SalesRevenueNet'),
        'gross_profit': ('GrossProfit',),
        'operating_income': ('OperatingIncomeLoss',),
        'net_income': ('NetIncomeLoss', 'ProfitLoss'),
        'assets': ('Assets',),
    }
    values = {}
    for label, candidates in concepts.items():
        rows = []
        for concept in candidates:
            rows.extend(_concept_entries(facts, concept, as_of))
        rows.sort(key=lambda row: (row['end'], row['filed']), reverse=True)
        values[label] = rows
    revenue_rows = values['revenue']
    if not revenue_rows:
        return {'available': False, 'reason': 'no_point_in_time_revenue'}
    revenue = revenue_rows[0]

    def matching(label, denominator):
        rows = values[label]
        same_period = [row for row in rows if row['end'] == denominator['end']]
        return same_period[0] if same_period else None

    gross = matching('gross_profit', revenue)
    operating = matching('operating_income', revenue)
    net = matching('net_income', revenue)
    assets = matching('assets', revenue)
    metrics = {
        'gross_margin': (
            gross['value'] / revenue['value']
            if gross and revenue['value'] else None
        ),
        'operating_margin': (
            operating['value'] / revenue['value']
            if operating and revenue['value'] else None
        ),
        'return_on_assets': (
            net['value'] / assets['value']
            if net and assets and assets['value'] else None
        ),
    }
    available = [value for value in metrics.values() if value is not None]
    return {
        'available': bool(available),
        'known_as_of': max(
            [revenue['filed']]
            + [row['filed'] for row in (gross, operating, net, assets) if row]
        ),
        'period_end': revenue['end'],
        'form': revenue['form'],
        'metrics': {key: (round(value, 6) if value is not None else None)
                    for key, value in metrics.items()},
        'raw_score': round(statistics.mean(available), 6) if available else None,
        'source': 'SEC XBRL filed-date-filtered',
    }


def _load_quality_cache():
    try:
        payload = json.loads(CACHE.read_text())
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def fetch_quality(config, as_of, enabled=True):
    cache = _load_quality_cache()
    snapshots = {
        row['ticker']: {
            'available': False,
            'reason': 'no_point_in_time_HK_filing_adapter',
        }
        for row in config['symbols'] if row['region'] == 'hk'
    }
    us_tickers = [row['ticker'] for row in config['symbols'] if row['region'] == 'us']
    for ticker in us_tickers:
        cached = cache.get(ticker) or {}
        fetched_at = str(cached.get('fetched_at') or '')[:10]
        age = ((date.fromisoformat(as_of) - date.fromisoformat(fetched_at)).days
               if fetched_at else 999)
        if (age <= 7 and cached.get('method_version') == QUALITY_METHOD_VERSION
                and isinstance(cached.get('snapshot'), dict)):
            snapshots[ticker] = cached['snapshot']
            continue
        if not enabled:
            snapshots[ticker] = {
                'available': False, 'reason': 'fundamental_refresh_skipped'
            }
            continue
        try:
            from clawock.market_data.filings import get_company_facts
            facts = get_company_facts(ticker)
            snapshot = (
                quality_snapshot(facts, as_of) if facts
                else {'available': False, 'reason': 'SEC_facts_unavailable'}
            )
        except Exception as exc:
            snapshot = {'available': False, 'reason': str(exc)[:100]}
        snapshots[ticker] = snapshot
        cache[ticker] = {
            'fetched_at': as_of,
            'method_version': QUALITY_METHOD_VERSION,
            'snapshot': snapshot,
        }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    safe_write_json(str(CACHE), cache)
    return snapshots


def _last_index(bars, as_of):
    indexes = [index for index, row in enumerate(bars) if row['date'] <= as_of]
    return indexes[-1] if indexes else None


def _return_at(bars, index, sessions):
    if index is None or index < sessions:
        return None
    return bars[index]['close'] / bars[index - sessions]['close'] - 1


def _median(values):
    clean = [value for value in values if value is not None]
    return statistics.median(clean) if clean else None


def _volatility(bars, index, sessions=20):
    if index is None or index < sessions:
        return None
    returns = [
        bars[i]['close'] / bars[i - 1]['close'] - 1
        for i in range(index - sessions + 1, index + 1)
    ]
    return statistics.stdev(returns) * math.sqrt(TRADING_DAYS)


def _drawdown(bars, index, sessions=63):
    if index is None:
        return None
    start = max(0, index - sessions + 1)
    closes = [row['close'] for row in bars[start:index + 1]]
    peak = max(closes) if closes else None
    return bars[index]['close'] / peak - 1 if peak else None


def _liquidity(bars, index, sessions=20):
    if index is None:
        return None
    start = max(0, index - sessions + 1)
    dollars = [
        row['close'] * row['volume']
        for row in bars[start:index + 1] if row.get('volume') is not None
    ]
    return _median(dollars)


def _quantile(values, probability):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower, upper = int(math.floor(position)), int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def winsorize_rows(rows, fields=RAW_FACTORS):
    clipped = {ticker: dict(row) for ticker, row in rows.items()}
    for field in fields:
        values = [row.get(field) for row in rows.values()
                  if isinstance(row.get(field), (int, float))]
        if not values:
            continue
        low, high = _quantile(values, 0.05), _quantile(values, 0.95)
        for ticker, row in clipped.items():
            value = row.get(field)
            if isinstance(value, (int, float)):
                row[field] = min(max(value, low), high)
    return clipped


def _centered_ranks(values):
    """Average-tie percentile ranks centered on zero."""
    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: item[1])
    if len(ordered) == 1:
        return {ordered[0][0]: 0.0}
    ranks, index = {}, 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[index][1]:
            end += 1
        average_position = (index + end) / 2
        centered = average_position / (len(ordered) - 1) - 0.5
        for cursor in range(index, end + 1):
            ranks[ordered[cursor][0]] = centered
        index = end + 1
    return ranks


def _percentile_ranks(values):
    """Average-tie ranks on [0, 1], independent within each market."""
    centered = _centered_ranks(values)
    return {ticker: value + 0.5 for ticker, value in centered.items()}


def rank_snapshot(config, fetched, as_of, quality=None, region=None):
    quality = quality or {}
    specs = [row for row in config['symbols']
             if region is None or row['region'] == region]
    raw = {}
    by_sector = {}
    for spec in specs:
        result = fetched.get(spec['ticker']) or {}
        bars = result.get('bars') or []
        index = _last_index(bars, as_of)
        if index is None:
            continue
        row_date = bars[index]['date']
        if (date.fromisoformat(as_of) - date.fromisoformat(row_date)).days > 7:
            continue
        momentums = {
            label: _return_at(bars, index, sessions)
            for label, sessions in HORIZONS.items()
        }
        ma50 = (
            statistics.mean(row['close'] for row in bars[index - 49:index + 1])
            if index >= 49 else None
        )
        q = quality.get(spec['ticker']) or {}
        realized_volatility = _volatility(bars, index)
        raw[spec['ticker']] = {
            'ticker': spec['ticker'],
            'region': spec['region'],
            'sector': spec['sector'],
            'feature_as_of': row_date,
            'close': bars[index]['close'],
            'mom_1m': momentums['1m'],
            'mom_3m': momentums['3m'],
            'mom_6m': momentums['6m'],
            'above_ma50': bars[index]['close'] > ma50 if ma50 is not None else None,
            'liquidity': _liquidity(bars, index),
            'low_volatility': (
                -realized_volatility
                if realized_volatility is not None else None
            ),
            'drawdown_resilience': _drawdown(bars, index),
            'quality_profitability': (
                q.get('raw_score') if q.get('available') else None
            ),
            'quality': q,
            'bars_available': len(bars),
            'corporate_action_basis': 'qfq',
        }
        by_sector.setdefault(spec['sector'], []).append(spec['ticker'])

    for sector, tickers in by_sector.items():
        medians = {
            label: _median([raw[ticker].get(f'mom_{label}') for ticker in tickers])
            for label in HORIZONS
        }
        breadth_values = [
            raw[ticker]['above_ma50'] for ticker in tickers
            if raw[ticker]['above_ma50'] is not None
        ]
        breadth = (
            sum(bool(value) for value in breadth_values) / len(breadth_values)
            if breadth_values else None
        )
        for ticker in tickers:
            residuals = {}
            for label in HORIZONS:
                momentum = raw[ticker].get(f'mom_{label}')
                median = medians[label]
                residuals[label] = (
                    momentum - median
                    if momentum is not None and median is not None else None
                )
                raw[ticker][f'residual_mom_{label}'] = residuals[label]
            available_residuals = [
                (weight, residuals[label])
                for label, weight in (('1m', 0.2), ('3m', 0.3), ('6m', 0.5))
                if residuals[label] is not None
            ]
            raw[ticker]['relative_strength'] = (
                sum(weight * value for weight, value in available_residuals)
                / sum(weight for weight, _ in available_residuals)
                if available_residuals else None
            )
            raw[ticker]['breadth'] = breadth
            raw[ticker]['sector_median_momentum'] = medians

    clipped = winsorize_rows(raw)
    ranks = {ticker: {} for ticker in raw}
    for sector, tickers in by_sector.items():
        for factor in RAW_FACTORS:
            factor_values = {
                ticker: clipped[ticker][factor] for ticker in tickers
                if isinstance(clipped[ticker].get(factor), (int, float))
            }
            for ticker, value in _centered_ranks(factor_values).items():
                ranks[ticker][factor] = value

    weights = config['factor_weights']
    for ticker, row in raw.items():
        available = [
            (float(weights[factor]), ranks[ticker][factor])
            for factor in RAW_FACTORS if factor in ranks[ticker]
        ]
        row['sector_neutral_ranks'] = {
            factor: round(value, 4) for factor, value in ranks[ticker].items()
        }
        row['factor_coverage_pct'] = round(
            100 * sum(weight for weight, _ in available), 1
        )
        row['composite_score'] = (
            round(sum(weight * value for weight, value in available)
                  / sum(weight for weight, _ in available), 6)
            if available else None
        )
        for field in ('mom_1m', 'mom_3m', 'mom_6m', *RAW_FACTORS):
            if isinstance(row.get(field), float):
                row[field] = round(row[field], 6)

    # Portfolio construction consumes a rank, not an arbitrary score cutoff.
    # Keep US and HK separate: the two markets do not share a session, peer
    # distribution, liquidity scale, or investible universe.  A sector with
    # only two near-identical ETFs is also made explicit so it cannot create a
    # spurious extreme rank merely because one of the pair is slightly ahead.
    for region in sorted({row['region'] for row in raw.values()}):
        values = {
            ticker: row['composite_score']
            for ticker, row in raw.items()
            if row['region'] == region
            and isinstance(row.get('composite_score'), (int, float))
        }
        for ticker, percentile in _percentile_ranks(values).items():
            raw[ticker]['market_percentile'] = round(percentile, 4)
    for ticker, row in raw.items():
        row['sector_universe_size'] = len(by_sector.get(row['sector']) or [])
    return raw


def _forward_return(bars, as_of, sessions):
    index = _last_index(bars, as_of)
    if index is None or index + sessions >= len(bars):
        return None
    return bars[index + sessions]['close'] / bars[index]['close'] - 1


def clustered_mean_ci(observations, samples=1000):
    if not observations:
        return None
    dates = sorted({row['date'] for row in observations})
    tickers = sorted({row['ticker'] for row in observations})
    if len(dates) < 2 or len(tickers) < 2:
        return None
    rnd = random.Random(20260726)
    draws = []
    for _ in range(samples):
        date_counts = {value: 0 for value in dates}
        ticker_counts = {value: 0 for value in tickers}
        for _ in dates:
            date_counts[rnd.choice(dates)] += 1
        for _ in tickers:
            ticker_counts[rnd.choice(tickers)] += 1
        numerator = denominator = 0.0
        for row in observations:
            weight = date_counts[row['date']] * ticker_counts[row['ticker']]
            numerator += weight * row['value']
            denominator += weight
        if denominator:
            draws.append(numerator / denominator)
    if not draws:
        return None
    draws.sort()
    return [
        round(draws[int(0.025 * (len(draws) - 1))], 6),
        round(draws[int(0.975 * (len(draws) - 1))], 6),
    ]


def _rank_values(values):
    return _centered_ranks({str(index): value for index, value in enumerate(values)})


def spearman(left, right):
    if len(left) != len(right) or len(left) < 3:
        return None
    left_ranks = _rank_values(left)
    right_ranks = _rank_values(right)
    x = [left_ranks[str(i)] for i in range(len(left))]
    y = [right_ranks[str(i)] for i in range(len(right))]
    mx, my = statistics.mean(x), statistics.mean(y)
    covariance = sum((a - mx) * (b - my) for a, b in zip(x, y))
    variance = math.sqrt(
        sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)
    )
    return covariance / variance if variance else None


def summarize_observations(observations):
    dates = sorted({row['date'] for row in observations})
    tickers = sorted({row['ticker'] for row in observations})
    sectors = sorted({row['sector'] for row in observations})
    values = [row['value'] for row in observations]
    by_date = {}
    for row in observations:
        by_date.setdefault(row['date'], []).append(row)
    ics = []
    for rows in by_date.values():
        if len(rows) < 3:
            continue
        ic = spearman([row['score'] for row in rows],
                      [row['forward_return'] for row in rows])
        if ic is not None:
            ics.append(ic)
    return {
        'n_observations': len(observations),
        'n_dates': len(dates),
        'n_tickers': len(tickers),
        'n_sectors': len(sectors),
        'first_signal_date': dates[0] if dates else None,
        'last_signal_date': dates[-1] if dates else None,
        'mean_signed_forward_return': (
            round(statistics.mean(values), 6) if values else None
        ),
        'signed_return_ci95': clustered_mean_ci(observations),
        'mean_date_spearman_ic': (
            round(statistics.mean(ics), 6) if ics else None
        ),
        'ci_method': 'date_ticker_two_way_cluster_bootstrap',
    }


def retrospective_walk_forward(config, fetched):
    all_dates = sorted({
        row['date']
        for spec in config['symbols']
        for row in (fetched.get(spec['ticker']) or {}).get('bars') or []
    })
    signal_dates = [
        value for value in all_dates
        if datetime.strptime(value, '%Y-%m-%d').weekday() == 4
    ]
    observations = []
    for signal_date in signal_dates:
        rows = rank_snapshot(config, fetched, signal_date, quality={})
        for ticker, row in rows.items():
            score = row.get('composite_score')
            if score in (None, 0):
                continue
            bars = (fetched.get(ticker) or {}).get('bars') or []
            forward = _forward_return(
                bars, signal_date, config['forward_horizon_sessions']
            )
            if forward is None:
                continue
            observations.append({
                'date': signal_date,
                'ticker': ticker,
                'sector': row['sector'],
                'score': score,
                'forward_return': forward,
                'value': forward if score > 0 else -forward,
            })
    return {
        **summarize_observations(observations),
        'status': 'retrospective_diagnostic_only',
        'method': (
            'fixed pre-registered weights; Friday point-in-time features; '
            f'{config["forward_horizon_sessions"]}-session forward returns'
        ),
        'quality_factor_treatment': (
            'excluded: no filing snapshot is used before its recorded date'
        ),
        'survivorship_warning': config['membership_history_note'],
    }


def _load_history():
    # 归档 + 热窗：prospective_walk_forward 是从第一行开始回放的，只读工作
    # 文件会缩短评估窗口、改掉 hit rate（#951）。
    return history_store.load_series(HISTORY)


def prospective_walk_forward(config, fetched, history):
    observations = []
    registered_at = config['registered_at']
    for snapshot in history:
        signal_date = str(snapshot.get('as_of') or '')[:10]
        if signal_date < registered_at:
            continue
        for ticker, row in (snapshot.get('rows') or {}).items():
            score = row.get('composite_score')
            if score in (None, 0):
                continue
            bars = (fetched.get(ticker) or {}).get('bars') or []
            forward = _forward_return(
                bars, signal_date, config['forward_horizon_sessions']
            )
            if forward is None:
                continue
            observations.append({
                'date': signal_date,
                'ticker': ticker,
                'sector': row.get('sector'),
                'score': score,
                'forward_return': forward,
                'value': forward if score > 0 else -forward,
            })
    return {
        **summarize_observations(observations),
        'status': 'pre_registered_prospective_only',
        'registered_at': registered_at,
    }


def leveraged_decay(config, fetched, live_rows):
    out = {}
    for proxy in config.get('leveraged_proxies') or []:
        proxy_bars = (fetched.get(proxy['ticker']) or {}).get('bars') or []
        underlying_bars = (fetched.get(proxy['underlying']) or {}).get('bars') or []
        proxy_by_date = {row['date']: row['close'] for row in proxy_bars}
        underlying_by_date = {row['date']: row['close'] for row in underlying_bars}
        common = sorted(set(proxy_by_date) & set(underlying_by_date))
        horizons = {}
        for label, sessions in HORIZONS.items():
            if len(common) <= sessions:
                horizons[label] = None
                continue
            first, last = common[-1 - sessions], common[-1]
            proxy_return = proxy_by_date[last] / proxy_by_date[first] - 1
            underlying_return = (
                underlying_by_date[last] / underlying_by_date[first] - 1
            )
            ideal = proxy['leverage'] * underlying_return
            horizons[label] = {
                'proxy_return': round(proxy_return, 6),
                'underlying_return': round(underlying_return, 6),
                'ideal_leveraged_return': round(ideal, 6),
                'tracking_and_decay_gap': round(proxy_return - ideal, 6),
                'n_common_returns': sessions,
            }
        underlying_row = live_rows.get(proxy['underlying']) or {}
        out[proxy['ticker']] = {
            'underlying': proxy['underlying'],
            'leverage': proxy['leverage'],
            'underlying_sector_neutral_score': underlying_row.get('composite_score'),
            'horizons': horizons,
            'research_only_preference': (
                'prefer_1x_or_no_add'
                if (underlying_row.get('composite_score') or 0) <= 0
                else 'underlying_relative_strength_positive'
            ),
            'usable_for_decisions': False,
        }
    return out


def activation_status(config, prospective, price_coverage, quality_coverage):
    criteria = config['activation_criteria']
    checks = {
        'prospective_dates': {
            'actual': prospective['n_dates'],
            'required': criteria['min_prospective_dates'],
            'pass': prospective['n_dates'] >= criteria['min_prospective_dates'],
        },
        'prospective_tickers': {
            'actual': prospective['n_tickers'],
            'required': criteria['min_prospective_tickers'],
            'pass': prospective['n_tickers'] >= criteria['min_prospective_tickers'],
        },
        'prospective_sectors': {
            'actual': prospective['n_sectors'],
            'required': criteria['min_prospective_sectors'],
            'pass': prospective['n_sectors'] >= criteria['min_prospective_sectors'],
        },
        'price_coverage': {
            'actual': price_coverage,
            'required': criteria['min_live_price_coverage'],
            'pass': price_coverage >= criteria['min_live_price_coverage'],
        },
        'quality_coverage': {
            'actual': quality_coverage,
            'required': criteria['min_point_in_time_quality_coverage'],
            'pass': quality_coverage >= criteria['min_point_in_time_quality_coverage'],
        },
        'clustered_edge': {
            'actual': prospective.get('signed_return_ci95'),
            'required': (
                f'CI lower > {criteria["signed_return_ci95_lower_gt"]}'
            ),
            'pass': bool(
                prospective.get('signed_return_ci95')
                and prospective['signed_return_ci95'][0]
                > criteria['signed_return_ci95_lower_gt']
            ),
        },
        'membership_history': {
            'actual': config['membership_history_complete'],
            'required': criteria['membership_history_complete'],
            'pass': (
                config['membership_history_complete']
                is criteria['membership_history_complete']
            ),
        },
        'corporate_actions': {
            'actual': config['price_adjustment'],
            'required': 'adjusted',
            'pass': 'adjusted' in config['price_adjustment'],
        },
    }
    blockers = [name for name, check in checks.items() if not check['pass']]
    return {
        'active': not blockers,
        'usable_for_decisions': not blockers,
        'checks': checks,
        'blockers': blockers,
        'discipline': (
            'Retrospective results never activate this layer. Every check must '
            'pass on post-registration snapshots before a rank may enter a brief.'
        ),
    }


def _history_snapshot(as_of, rows, registered_at):
    return {
        'as_of': as_of,
        'registered_at': registered_at,
        'rows': {
            ticker: {
                'sector': row['sector'],
                'feature_as_of': row['feature_as_of'],
                'close': row['close'],
                'composite_score': row['composite_score'],
                'market_percentile': row.get('market_percentile'),
                'sector_universe_size': row.get('sector_universe_size'),
                'factor_coverage_pct': row['factor_coverage_pct'],
                # The constituents the composite is a weighted mean of (#1133).
                # `rank_snapshot` has always computed these and the snapshot
                # dropped them, which made the composite the one published
                # research surface that could not be diagnosed from its own
                # registered history: a reversed polarity in one factor and an
                # ordinary bad month for all nine look identical once only the
                # weighted mean survives.
                'sector_neutral_ranks': dict(row.get('sector_neutral_ranks') or {}),
                'ranks_provenance': row.get('ranks_provenance') or 'recorded_at_snapshot',
            }
            for ticker, row in rows.items()
        },
    }


def backfill_history_ranks(config, fetched, history, *, quality_by_date=None):
    """Reconstruct the constituent ranks for already-registered snapshots.

    The persistence fix above only helps sessions that have not happened yet,
    and #1133's question — is the composite's negative IC a polarity error or a
    bad month — is being asked about the twenty-four sessions already on the
    record. `rank_snapshot` is point-in-time by construction: it indexes each
    ticker's bars at `as_of` and computes the same sector-neutral ranks the live
    path computes, so re-running it over the registered dates reconstructs
    exactly what that session saw.

    One factor cannot be reconstructed and is left out rather than faked:
    `quality_profitability` comes from filed fundamentals, and the cache holds
    today's facts, not the facts as they stood on a Friday in July. Using them
    would be a look-ahead in the one factor whose whole point is that it is
    slow-moving. It carries 5% of the weight; every row records which factors it
    actually got, so the omission is countable rather than assumed.

    Rows are only ever *added to*: an existing `sector_neutral_ranks` recorded
    live is never overwritten by a reconstruction.
    """
    quality_by_date = quality_by_date or {}
    out = []
    for snapshot in history:
        as_of = str(snapshot.get('as_of') or '')[:10]
        rows = snapshot.get('rows') or {}
        if not as_of or not rows:
            out.append(snapshot)
            continue
        try:
            rebuilt = rank_snapshot(config, fetched, as_of,
                                    quality=quality_by_date.get(as_of))
        except (ValueError, KeyError):
            out.append(snapshot)
            continue
        updated = dict(snapshot)
        updated['rows'] = {}
        for ticker, row in rows.items():
            row = dict(row)
            if not row.get('sector_neutral_ranks'):
                ranks = (rebuilt.get(ticker) or {}).get('sector_neutral_ranks')
                if ranks:
                    row['sector_neutral_ranks'] = dict(ranks)
                    row['ranks_provenance'] = 'reconstructed_point_in_time_from_bars'
                    # What the reconstruction could and could not see, so a
                    # reader can tell a missing factor from a zero one.
                    row['ranks_factors_reconstructed'] = sorted(ranks)
            updated['rows'][ticker] = row
        out.append(updated)
    return out


def reconstruction_fidelity(history, config):
    """How closely the reconstructed ranks reproduce the recorded composite.

    A reconstruction nobody checked is a second dataset, not the same one. This
    recomputes the weighted mean from the reconstructed ranks and reports the
    Spearman correlation against the composite that was actually registered, per
    session. Anything but a near-1 correlation means the reconstruction is not
    the thing it claims to be and the constituent ICs below it are meaningless.
    """
    weights = config['factor_weights']
    out = []
    for snapshot in history:
        recorded, rebuilt = [], []
        for row in (snapshot.get('rows') or {}).values():
            ranks = row.get('sector_neutral_ranks') or {}
            score = row.get('composite_score')
            available = [(float(weights[name]), value)
                         for name, value in ranks.items() if name in weights]
            if not available or not isinstance(score, (int, float)):
                continue
            recorded.append(float(score))
            rebuilt.append(sum(weight * value for weight, value in available)
                           / sum(weight for weight, _ in available))
        if len(recorded) >= 3:
            out.append({
                'as_of': str(snapshot.get('as_of') or '')[:10],
                'n': len(recorded),
                'spearman': spearman(recorded, rebuilt),
            })
    return out


def update_history(as_of, rows, registered_at):
    existing = [
        row for row in _load_history()
        if str(row.get('as_of') or '')[:10] != as_of
    ]
    existing.append(_history_snapshot(as_of, rows, registered_at))
    return history_store.write_series(HISTORY, existing)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-fundamentals', action='store_true',
                        help='use a valid cache only; do not refresh SEC facts')
    parser.add_argument('--config', default=str(CONFIG))
    parser.add_argument(
        '--backfill-history-ranks', action='store_true',
        help=('reconstruct sector-neutral constituent ranks for registered '
              'snapshots that predate their persistence (#1133), print the '
              'fidelity check, and exit without touching the live snapshot'))
    args = parser.parse_args(argv)

    config = load_config(args.config)
    fetched = fetch_universe(config)
    if args.backfill_history_ranks:
        history = backfill_history_ranks(config, fetched, _load_history())
        # Written through the same writer the daily append uses. A second
        # serialisation would reformat every historical row and leave the file
        # in two styles the moment cron next appends to it.
        history_store.write_series(HISTORY, history)
        fidelity = reconstruction_fidelity(history, config)
        print(json.dumps({
            'snapshots': len(history),
            'reconstruction_fidelity': fidelity,
            'worst_spearman': min((row['spearman'] for row in fidelity
                                   if row['spearman'] is not None), default=None),
        }, ensure_ascii=False, indent=2))
        return 0
    successful = {
        ticker: result for ticker, result in fetched.items() if result.get('bars')
    }
    latest_dates = [
        result['bars'][-1]['date'] for result in successful.values()
    ]
    as_of = max(latest_dates) if latest_dates else date.today().isoformat()
    quality = fetch_quality(
        config, as_of, enabled=not args.no_fundamentals
    )
    live_rows = rank_snapshot(config, fetched, as_of, quality=quality)
    history = update_history(as_of, live_rows, config['registered_at'])
    retrospective = retrospective_walk_forward(config, fetched)
    prospective = prospective_walk_forward(config, fetched, history)

    price_coverage = len(live_rows) / len(config['symbols']) if config['symbols'] else 0
    quality_available = sum(
        bool((row.get('quality') or {}).get('available'))
        for row in live_rows.values()
    )
    quality_coverage = quality_available / len(live_rows) if live_rows else 0
    activation = activation_status(
        config, prospective, price_coverage, quality_coverage
    )
    for row in live_rows.values():
        row['usable_for_decisions'] = activation['usable_for_decisions']

    failures = {
        ticker: result.get('error')
        for ticker, result in fetched.items() if not result.get('bars')
    }
    out = {
        'schema_version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'as_of': as_of,
        'registered_at': config['registered_at'],
        'universe': {
            'configured_symbols': len(config['symbols']),
            'priced_symbols': len(live_rows),
            'price_coverage_pct': round(100 * price_coverage, 1),
            'sectors': sorted({row['sector'] for row in config['symbols']}),
            'failed': failures,
            'membership_history_complete': config['membership_history_complete'],
            'membership_history_note': config['membership_history_note'],
            'price_adjustment': config['price_adjustment'],
        },
        'live_rankings': dict(sorted(
            live_rows.items(),
            key=lambda item: (
                item[1]['sector'],
                -(item[1].get('composite_score') or -999),
            ),
        )),
        'leveraged_proxy_decay': leveraged_decay(config, fetched, live_rows),
        'validation': {
            'retrospective': retrospective,
            'prospective': prospective,
        },
        'activation': activation,
        'methodology': {
            'momentum': '21/63/126-session qfq return minus sector median',
            'relative_strength': '20%/30%/50% blend of residual 1m/3m/6m momentum',
            'breadth': 'sector fraction above 50-session moving average',
            'liquidity': '20-session median close times volume',
            'volatility': 'negative 20-session annualized realized volatility',
            'drawdown': 'current close versus trailing 63-session peak',
            'quality': 'SEC XBRL profitability filtered by filed date; unavailable HK data is not imputed',
            'ranking': '5/95 winsorization followed by within-sector centered percentile ranks',
            'weights': config['factor_weights'],
        },
    }
    safe_write_json(str(OUT), out)
    print(
        f'factor layer: {len(live_rows)}/{len(config["symbols"])} priced, '
        f'{quality_available}/{len(live_rows)} quality, '
        f'active={activation["active"]}, blockers={",".join(activation["blockers"])}'
    )
    print(f'wrote {OUT.relative_to(WS)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
