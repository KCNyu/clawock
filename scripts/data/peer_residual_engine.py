#!/usr/bin/env python3
"""Curated-peer residual alpha and leadership/diffusion research engine.

HK peers come only from ``memory/peer-map.json``. This script never invokes the
automatic peer suggester. Leveraged peers are folded to their 1x underlying so
an ETF and its underlying cannot count twice in the same basket.

Writes:
  assets/data/peer_residual.json
  assets/data/peer_residual_history.jsonl
"""

import argparse
import copy
import json
import math
import statistics
import sys
from datetime import date, datetime, timezone
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
RULE_CONFIG = WS / 'config' / 'peer-residual-rules.json'
FACTOR_CONFIG = WS / 'config' / 'factor-universe.json'
PEER_MAP = WS / 'memory' / 'peer-map.json'
OUT = WS / 'assets' / 'data' / 'peer_residual.json'
HISTORY = WS / 'assets' / 'data' / 'peer_residual_history.jsonl'
HORIZONS = (1, 5, 20)

sys.path.insert(0, str(_CHECKOUT / 'scripts' / 'data'))
from cross_sectional_factor import (  # noqa: E402
    _last_index,
    _liquidity,
    _return_at,
    clustered_mean_ci,
    fetch_universe,
)
from safe_io import safe_write_json, safe_write_text  # noqa: E402


def load_rule_config(path=RULE_CONFIG):
    config = json.loads(Path(path).read_text())
    if config.get('automatic_hk_peer_discovery') is not False:
        raise ValueError('automatic_hk_peer_discovery must remain false')
    if set(config.get('rules') or {}) != {
        'leader_continuation', 'laggard_avoidance', 'mean_reversion'
    }:
        raise ValueError('rule set changed without updating the registered contract')
    return config


def build_taxonomy(factor_config, peer_map):
    proxy_rows = factor_config.get('leveraged_proxies') or []
    proxy_map = {row['ticker']: row for row in proxy_rows}
    base_specs = {
        row['ticker']: dict(row) for row in factor_config.get('symbols') or []
    }
    holdings = peer_map.get('holdings') or {}
    taxonomy = {}
    universe_specs = dict(base_specs)
    for target, info in holdings.items():
        proxy = proxy_map.get(target)
        signal_ticker = proxy['underlying'] if proxy else target
        signal_region = (
            proxy['region'] if proxy
            else ('hk' if target.isdigit() else 'us')
        )
        original_peers = info.get('listed_peers') or []
        underlying_peers = (
            (holdings.get(signal_ticker) or {}).get('listed_peers') or []
        )
        source_peers = (
            underlying_peers
            if len(underlying_peers) > len(original_peers)
            else original_peers
        )
        peers, seen = [], set()
        for peer in source_peers:
            ticker = peer.get('ticker')
            region = peer.get('region')
            if ticker in proxy_map:
                region = proxy_map[ticker]['region']
                ticker = proxy_map[ticker]['underlying']
            if not ticker or ticker == signal_ticker or ticker in seen:
                continue
            seen.add(ticker)
            peers.append({
                'ticker': ticker,
                'region': region,
                'configured_name': peer.get('name'),
                'relationship': peer.get('rel'),
            })
            universe_specs.setdefault(ticker, {
                'ticker': ticker,
                'region': region,
                'sector': f'peer_of_{target}',
            })
        universe_specs.setdefault(signal_ticker, {
            'ticker': signal_ticker,
            'region': signal_region,
            'sector': info.get('theme') or f'target_{target}',
        })
        taxonomy[target] = {
            'target': target,
            'signal_ticker': signal_ticker,
            'signal_region': signal_region,
            'leveraged_target': bool(proxy),
            'peers': peers,
            'peer_source': 'curated_listed_peers',
            'automatic_discovery': False,
        }
    fetch_config = copy.deepcopy(factor_config)
    fetch_config['symbols'] = list(universe_specs.values())
    fetch_config['leveraged_proxies'] = []
    return taxonomy, fetch_config


def capped_weights(raw, cap):
    """Normalize positive weights while enforcing a deterministic max weight."""
    positive = {
        key: float(value) for key, value in raw.items() if float(value) > 0
    }
    if not positive or sum(positive.values()) <= 0:
        return {}
    weights = {key: value / sum(positive.values())
               for key, value in positive.items()}
    if cap <= 0 or cap * len(weights) < 1:
        return {key: 1 / len(weights) for key in weights}
    free = set(weights)
    fixed = {}
    while free:
        remaining = 1 - sum(fixed.values())
        raw_total = sum(positive[key] for key in free)
        proposed = {
            key: remaining * positive[key] / raw_total for key in free
        }
        over = [key for key, value in proposed.items() if value > cap]
        if not over:
            fixed.update(proposed)
            break
        for key in over:
            fixed[key] = cap
            free.remove(key)
    return fixed


def _bars(fetched, ticker):
    return (fetched.get(ticker) or {}).get('bars') or []


def _period_return(bars, start_date, end_date):
    start = _last_index(bars, start_date)
    end = _last_index(bars, end_date)
    if start is None or end is None or end <= start:
        return None
    return bars[end]['close'] / bars[start]['close'] - 1


def _peer_values(taxonomy_row, fetched, as_of, horizon):
    values = {}
    liquidities = {}
    for peer in taxonomy_row['peers']:
        bars = _bars(fetched, peer['ticker'])
        index = _last_index(bars, as_of)
        value = _return_at(bars, index, horizon)
        if value is None:
            continue
        values[peer['ticker']] = value
        liquidity = _liquidity(bars, index)
        if liquidity is not None and liquidity > 0:
            liquidities[peer['ticker']] = liquidity
    return values, liquidities


def _basket(values, liquidities, cap):
    if not values:
        return None, None, {}
    equal = statistics.mean(values.values())
    weights = capped_weights(
        {ticker: liquidities[ticker] for ticker in values
         if ticker in liquidities}, cap
    )
    if not weights:
        weights = {ticker: 1 / len(values) for ticker in values}
    liquidity_weighted = sum(
        weight * values[ticker] for ticker, weight in weights.items()
    )
    return equal, liquidity_weighted, weights


def _regime(basket_return, breadth):
    if basket_return is None or breadth is None:
        return 'unavailable'
    if basket_return > 0 and breadth >= 0.6:
        return 'broad_up'
    if basket_return < 0 and breadth <= 0.4:
        return 'broad_down'
    return 'mixed'


def metrics_at(taxonomy_row, fetched, as_of, weight_cap=0.4):
    target_bars = _bars(fetched, taxonomy_row['signal_ticker'])
    target_index = _last_index(target_bars, as_of)
    if target_index is None:
        return None
    feature_date = target_bars[target_index]['date']
    metrics = {
        'target': taxonomy_row['target'],
        'signal_ticker': taxonomy_row['signal_ticker'],
        'feature_as_of': feature_date,
        'peer_source': taxonomy_row['peer_source'],
        'automatic_discovery': taxonomy_row['automatic_discovery'],
        'configured_peer_count': len(taxonomy_row['peers']),
    }
    available_counts = []
    for horizon in HORIZONS:
        target_return = _return_at(target_bars, target_index, horizon)
        peer_returns, liquidities = _peer_values(
            taxonomy_row, fetched, feature_date, horizon
        )
        equal, liquidity, weights = _basket(
            peer_returns, liquidities, weight_cap
        )
        available_counts.append(len(peer_returns))
        dispersion = (
            statistics.stdev(peer_returns.values())
            if len(peer_returns) >= 2 else None
        )
        breadth = (
            sum(value > 0 for value in peer_returns.values()) / len(peer_returns)
            if peer_returns else None
        )
        residual_equal = (
            target_return - equal
            if target_return is not None and equal is not None else None
        )
        residual_liquidity = (
            target_return - liquidity
            if target_return is not None and liquidity is not None else None
        )
        residual_blend = (
            statistics.mean([residual_equal, residual_liquidity])
            if residual_equal is not None and residual_liquidity is not None
            else residual_equal
        )
        suffix = f'{horizon}d'
        metrics.update({
            f'target_return_{suffix}': target_return,
            f'peer_equal_return_{suffix}': equal,
            f'peer_liquidity_return_{suffix}': liquidity,
            f'residual_equal_{suffix}': residual_equal,
            f'residual_liquidity_{suffix}': residual_liquidity,
            f'residual_blend_{suffix}': residual_blend,
            f'peer_breadth_{suffix}': breadth,
            f'peer_dispersion_{suffix}': dispersion,
            f'peer_count_{suffix}': len(peer_returns),
        })
        if horizon == 20:
            metrics['liquidity_weights_20d'] = weights

    residual_signs = [
        metrics.get(f'residual_blend_{horizon}d') for horizon in HORIZONS
    ]
    metrics['leadership_persistence'] = sum(
        value > 0 for value in residual_signs if value is not None
    )
    metrics['laggard_persistence'] = sum(
        value < 0 for value in residual_signs if value is not None
    )
    metrics['sector_regime'] = _regime(
        metrics.get('peer_liquidity_return_20d'),
        metrics.get('peer_breadth_20d'),
    )
    previous_date = (
        target_bars[target_index - 5]['date'] if target_index >= 5 else None
    )
    if previous_date:
        previous_returns, previous_liquidity = _peer_values(
            taxonomy_row, fetched, previous_date, 5
        )
        previous_equal, previous_weighted, _ = _basket(
            previous_returns, previous_liquidity, weight_cap
        )
        del previous_equal
        previous_breadth = (
            sum(value > 0 for value in previous_returns.values())
            / len(previous_returns) if previous_returns else None
        )
        previous_regime = _regime(previous_weighted, previous_breadth)
    else:
        previous_regime = 'unavailable'
    current_short_regime = _regime(
        metrics.get('peer_liquidity_return_5d'),
        metrics.get('peer_breadth_5d'),
    )
    metrics['sector_regime_5d'] = current_short_regime
    metrics['previous_sector_regime_5d'] = previous_regime
    metrics['sector_regime_shift'] = (
        f'{previous_regime}->{current_short_regime}'
        if previous_regime != current_short_regime else 'unchanged'
    )
    metrics['available_peer_count'] = min(available_counts) if available_counts else 0
    for key, value in list(metrics.items()):
        if isinstance(value, float):
            metrics[key] = round(value, 6)
        elif isinstance(value, dict):
            metrics[key] = {
                name: round(number, 6) for name, number in value.items()
            }
    return metrics


def triggered_rules(metrics, minimum_peers=3):
    if not metrics or metrics.get('available_peer_count', 0) < minimum_peers:
        return []
    residual_1 = metrics.get('residual_blend_1d')
    residual_5 = metrics.get('residual_blend_5d')
    residual_20 = metrics.get('residual_blend_20d')
    dispersion_1 = metrics.get('peer_dispersion_1d')
    basket_20 = metrics.get('peer_liquidity_return_20d')
    breadth_20 = metrics.get('peer_breadth_20d')
    out = []
    if (residual_5 is not None and residual_20 is not None
            and residual_5 > 0 and residual_20 > 0
            and breadth_20 is not None and breadth_20 >= 0.5
            and metrics.get('leadership_persistence', 0) >= 2):
        out.append('leader_continuation')
    if (residual_5 is not None and residual_20 is not None
            and basket_20 is not None and residual_5 < 0
            and residual_20 < 0 and basket_20 > 0
            and metrics.get('laggard_persistence', 0) >= 2):
        out.append('laggard_avoidance')
    if (residual_1 is not None and dispersion_1 not in (None, 0)
            and residual_1 < -1.5 * dispersion_1
            and metrics.get('peer_breadth_1d') is not None
            and metrics['peer_breadth_1d'] >= 0.4):
        out.append('mean_reversion')
    return out


def forward_residual(taxonomy_row, fetched, signal_date, sessions, cap):
    target_bars = _bars(fetched, taxonomy_row['signal_ticker'])
    signal_index = _last_index(target_bars, signal_date)
    if signal_index is None or signal_index + sessions >= len(target_bars):
        return None
    start = target_bars[signal_index]['date']
    end = target_bars[signal_index + sessions]['date']
    target_return = _period_return(target_bars, start, end)
    peer_returns, liquidities = {}, {}
    for peer in taxonomy_row['peers']:
        peer_bars = _bars(fetched, peer['ticker'])
        value = _period_return(peer_bars, start, end)
        if value is None:
            continue
        peer_returns[peer['ticker']] = value
        liquidity = _liquidity(peer_bars, _last_index(peer_bars, start))
        if liquidity is not None and liquidity > 0:
            liquidities[peer['ticker']] = liquidity
    equal, weighted, _ = _basket(peer_returns, liquidities, cap)
    if target_return is None or equal is None or weighted is None:
        return None
    return target_return - statistics.mean([equal, weighted])


def _observation(rule, rule_config, target, signal_date, metrics,
                 taxonomy_row, fetched):
    forward = forward_residual(
        taxonomy_row,
        fetched,
        signal_date,
        rule_config['forward_horizon_sessions'],
        rule_config['basket_weight_cap'],
    )
    if forward is None:
        return None
    direction = rule_config['rules'][rule]['expected_direction']
    signed = direction * forward
    return {
        'date': signal_date,
        'ticker': target,
        'value': signed,
        'hit': signed > 0,
        'forward_residual': forward,
        'rule': rule,
        'peer_count': metrics.get('available_peer_count'),
    }


def summarize_rule(observations):
    dates = {row['date'] for row in observations}
    tickers = {row['ticker'] for row in observations}
    hit_observations = [
        {**row, 'value': 1.0 if row['hit'] else 0.0} for row in observations
    ]
    values = [row['value'] for row in observations]
    return {
        'n_events': len(observations),
        'n_dates': len(dates),
        'n_tickers': len(tickers),
        'mean_signed_forward_residual': (
            round(statistics.mean(values), 6) if values else None
        ),
        'signed_residual_ci95': clustered_mean_ci(observations),
        'hit_rate': (
            round(sum(row['hit'] for row in observations) / len(observations), 4)
            if observations else None
        ),
        'hit_rate_ci95': clustered_mean_ci(hit_observations),
        'ci_method': 'date_ticker_two_way_cluster_bootstrap',
    }


def _canonical_taxonomy_items(taxonomy):
    """One calibration row per economic exposure, preferring the 1x ticker."""
    selected = {}
    for target, row in taxonomy.items():
        signal = row['signal_ticker']
        current = selected.get(signal)
        if current is None or target == signal:
            selected[signal] = (target, row)
    return list(selected.values())


def retrospective_calibration(rule_config, taxonomy, fetched):
    observations = {rule: [] for rule in rule_config['rules']}
    for target, taxonomy_row in _canonical_taxonomy_items(taxonomy):
        target_bars = _bars(fetched, taxonomy_row['signal_ticker'])
        signal_dates = [
            row['date'] for row in target_bars
            if datetime.strptime(row['date'], '%Y-%m-%d').weekday() == 4
        ]
        for signal_date in signal_dates:
            metrics = metrics_at(
                taxonomy_row, fetched, signal_date,
                rule_config['basket_weight_cap'],
            )
            for rule in triggered_rules(
                metrics, rule_config['activation_criteria']['min_peer_count']
            ):
                observation = _observation(
                    rule, rule_config, target, signal_date, metrics,
                    taxonomy_row, fetched,
                )
                if observation:
                    observations[rule].append(observation)
    return {
        rule: {
            **summarize_rule(rows),
            'status': 'retrospective_diagnostic_only',
        }
        for rule, rows in observations.items()
    }


def _load_history():
    if not HISTORY.exists():
        return []
    rows = []
    for line in HISTORY.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def update_history(as_of, live_rows, registered_at):
    existing = [
        row for row in _load_history()
        if str(row.get('as_of') or '')[:10] != as_of
    ]
    existing.append({
        'as_of': as_of,
        'registered_at': registered_at,
        'rows': {
            target: {
                'signal_ticker': row['signal_ticker'],
                'feature_as_of': row['feature_as_of'],
                'triggered_rules': row['triggered_rules'],
                'available_peer_count': row['available_peer_count'],
            }
            for target, row in live_rows.items()
        },
    })
    existing.sort(key=lambda row: row['as_of'])
    safe_write_text(
        str(HISTORY),
        '\n'.join(json.dumps(row, ensure_ascii=False, separators=(',', ':'))
                  for row in existing) + '\n',
    )
    return existing


def prospective_calibration(rule_config, taxonomy, fetched, history):
    observations = {rule: [] for rule in rule_config['rules']}
    canonical_targets = {
        target for target, _ in _canonical_taxonomy_items(taxonomy)
    }
    for snapshot in history:
        signal_date = str(snapshot.get('as_of') or '')[:10]
        if signal_date < rule_config['registered_at']:
            continue
        for target, row in (snapshot.get('rows') or {}).items():
            if target not in canonical_targets:
                continue
            taxonomy_row = taxonomy.get(target)
            if not taxonomy_row:
                continue
            for rule in row.get('triggered_rules') or []:
                observation = _observation(
                    rule, rule_config, target, signal_date, row,
                    taxonomy_row, fetched,
                )
                if observation:
                    observations[rule].append(observation)
    return {
        rule: {
            **summarize_rule(rows),
            'status': 'pre_registered_prospective_only',
            'registered_at': rule_config['registered_at'],
        }
        for rule, rows in observations.items()
    }


def activate_rules(rule_config, prospective):
    criteria = rule_config['activation_criteria']
    out = {}
    for rule, summary in prospective.items():
        signed_ci = summary.get('signed_residual_ci95')
        hit_ci = summary.get('hit_rate_ci95')
        checks = {
            'dates': summary['n_dates'] >= criteria['min_prospective_dates'],
            'tickers': summary['n_tickers'] >= criteria['min_prospective_tickers'],
            'signed_residual_ci': bool(
                signed_ci
                and signed_ci[0] > criteria['min_signed_residual_ci95_lower']
            ),
            'hit_rate_ci': bool(
                hit_ci and hit_ci[0] > criteria['min_hit_rate_ci95_lower']
            ),
            'curated_taxonomy': True,
            'hk_automatic_discovery_disabled': (
                rule_config['automatic_hk_peer_discovery'] is False
            ),
        }
        blockers = [name for name, passed in checks.items() if not passed]
        out[rule] = {
            'active': not blockers,
            'usable_for_decisions': not blockers,
            'checks': checks,
            'blockers': blockers,
        }
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rules', default=str(RULE_CONFIG))
    args = parser.parse_args(argv)
    rule_config = load_rule_config(args.rules)
    factor_config = json.loads(FACTOR_CONFIG.read_text())
    peer_map = json.loads(PEER_MAP.read_text())
    taxonomy, fetch_config = build_taxonomy(factor_config, peer_map)
    fetched = fetch_universe(fetch_config)
    latest_dates = [
        result['bars'][-1]['date']
        for result in fetched.values() if result.get('bars')
    ]
    as_of = max(latest_dates) if latest_dates else date.today().isoformat()
    live_rows = {}
    for target, taxonomy_row in taxonomy.items():
        metrics = metrics_at(
            taxonomy_row, fetched, as_of, rule_config['basket_weight_cap']
        )
        if not metrics:
            continue
        metrics['triggered_rules'] = triggered_rules(
            metrics, rule_config['activation_criteria']['min_peer_count']
        )
        live_rows[target] = metrics
    history = update_history(as_of, live_rows, rule_config['registered_at'])
    retrospective = retrospective_calibration(rule_config, taxonomy, fetched)
    prospective = prospective_calibration(
        rule_config, taxonomy, fetched, history
    )
    activation = activate_rules(rule_config, prospective)
    for row in live_rows.values():
        row['usable_rules'] = [
            rule for rule in row['triggered_rules']
            if (activation.get(rule) or {}).get('active')
        ]
        row['usable_for_decisions'] = bool(row['usable_rules'])

    failed = {
        ticker: result.get('error')
        for ticker, result in fetched.items() if not result.get('bars')
    }
    out = {
        'schema_version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'as_of': as_of,
        'registered_at': rule_config['registered_at'],
        'taxonomy': {
            'source': rule_config['peer_source'],
            'automatic_hk_peer_discovery': False,
            'targets': len(taxonomy),
            'priced_symbols': sum(bool(row.get('bars')) for row in fetched.values()),
            'failed_symbols': failed,
            'leveraged_products_folded_to_1x': [
                target for target, row in taxonomy.items()
                if row['leveraged_target']
            ],
            'principal_risk': (
                'curated taxonomy drift; ETF/underlying duplicates are folded '
                'before basket construction'
            ),
        },
        'live': live_rows,
        'calibration': {
            'retrospective': retrospective,
            'prospective': prospective,
        },
        'rule_activation': activation,
        'methodology': {
            'baskets': (
                'equal weight and capped 20-session median-dollar-volume weight'
            ),
            'residuals': (
                'ticker return minus mean(equal-weight, liquidity-weight) peer return'
            ),
            'horizons': [1, 5, 20],
            'leadership_persistence': (
                'count of positive residuals across 1/5/20 sessions'
            ),
            'sector_regime': (
                'peer liquidity basket sign plus peer breadth; 5d shift is published'
            ),
            'rules': rule_config['rules'],
            'activation_discipline': (
                'only post-registration date×ticker clustered evidence can unlock '
                'leader continuation, laggard avoidance, or mean reversion'
            ),
        },
    }
    safe_write_json(str(OUT), out)
    active = [rule for rule, state in activation.items() if state['active']]
    print(
        f'peer residual: {len(live_rows)}/{len(taxonomy)} targets, '
        f'active_rules={",".join(active) or "none"}, '
        f'HK_auto={rule_config["automatic_hk_peer_discovery"]}'
    )
    print(f'wrote {OUT.relative_to(WS)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
