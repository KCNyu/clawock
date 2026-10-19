"""Bounded, retrospective intraday walk-forward. Never a live registration.

Input data must carry an affirmative research-use grant. API access alone is
not that grant. Synthetic fixtures exercise code but cannot clear evidence.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import random
from pathlib import Path

from clawock.code_identity import file_digest, git_commit

from clawock.sessions import is_trading_day
from clawock.seeds import seed
from clawock.strategy_lab.plugins.registered_costs import Costs

SERVICES = ('intraday_reversion', 'intraday_vwap', 'intraday_breakout')
FOCI = ('validation', 'costs', 'path')
FIELDS = {'schema_version', 'author_model', 'frozen_at', 'knowledge_scope', 'universe',
          'market', 'start', 'end', 'train_sessions', 'test_sessions', 'minimum_oos',
          'shares', 'base_shares', 'lot_size', 'cash_reserve', 'monthly_opening_used_hkd',
          'usd_hkd', 'fx_basis', 'max_participation', 'candidates', 'mechanism',
          'counterexamples', 'requirements', 'selection', 'presentation_focus', 'live_permission'}


def code_provenance():
    root = Path(__file__).resolve().parents[3]
    paths = ['src/clawock/strategy_lab/intraday_study.py', 'src/clawock/costs.py'] + [
        f'src/clawock/strategies/plugins/{name}.py' for name in SERVICES]
    return {'commit': git_commit(root), 'files': {path: file_digest(root/path) for path in paths}}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def manifest(raw):
    if not isinstance(raw, dict) or set(raw) != FIELDS:
        raise ValueError('manifest fields do not match the frozen contract')
    if raw['schema_version'] != 1 or raw['live_permission'] is not False:
        raise ValueError('research manifest v1 requires live_permission=false')
    for k in ('author_model', 'knowledge_scope', 'fx_basis', 'mechanism', 'selection'):
        if not isinstance(raw[k], str) or not raw[k].strip():
            raise ValueError(f'missing manifest {k}')
    if datetime.fromisoformat(raw['frozen_at']).utcoffset() is None:
        raise ValueError('freeze needs timezone')
    for key in ('counterexamples', 'requirements'):
        if not isinstance(raw[key], list) or not raw[key] or not all(isinstance(x, str) and x for x in raw[key]):
            raise ValueError(f'missing {key}')
    if raw['market'] not in ('hk', 'us') or len(raw['universe']) != 1:
        raise ValueError('one market and one frozen ticker per study; no mixed-currency aggregation')
    if not isinstance(raw['universe'][0], str) or not raw['universe'][0]:
        raise ValueError('ticker required')
    if raw['presentation_focus'] not in FOCI:
        raise ValueError('unknown presentation emphasis')
    for k in ('train_sessions', 'test_sessions', 'minimum_oos', 'shares', 'base_shares', 'lot_size'):
        if type(raw[k]) is not int or raw[k] <= 0:
            raise ValueError(f'{k} must be a positive integer')
    if raw['train_sessions'] < 60 or raw['test_sessions'] < 20 or raw['minimum_oos'] < 60:
        raise ValueError('cannot weaken the registered sample gates')
    for k in ('cash_reserve', 'monthly_opening_used_hkd', 'usd_hkd', 'max_participation'):
        if type(raw[k]) not in (int, float) or not math.isfinite(raw[k]) or raw[k] < 0:
            raise ValueError(f'invalid {k}')
    if not 0 < raw['max_participation'] <= .01 or raw['usd_hkd'] <= 0:
        raise ValueError('participation <=1% and positive FX required')
    if raw['shares'] % raw['lot_size'] or raw['shares'] > raw['base_shares'] * .1:
        raise ValueError('lot and base sleeve constraints')
    start, end = date.fromisoformat(raw['start']), date.fromisoformat(raw['end'])
    if start > end or (end-start).days > 366:
        raise ValueError('study is bounded to one year')
    candidates = raw['candidates']
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 12:
        raise ValueError('bounded grid needs 1..12 candidates')
    if candidates[0] != {'service': 'intraday_reversion', 'params': {'window': 20, 'deviations': 2.0}}:
        raise ValueError('first arm must be the frozen default band benchmark')
    for c in candidates:
        if set(c) != {'service', 'params'} or c['service'] not in SERVICES:
            raise ValueError('unknown research service')
        if set(c['params']) != {'window', 'deviations'}:
            raise ValueError('only window and deviations can be searched')
        w, d = c['params']['window'], c['params']['deviations']
        if type(w) is not int or not 12 <= w <= 30 or type(d) not in (float, int) or not 1.5 <= d <= 2.5:
            raise ValueError('grid outside bounded search space')
    return deepcopy(raw)


def validate_source(source):
    if source.get('research_use') is not True or not source.get('license_evidence'):
        raise ValueError('research-use entitlement not established')
    for key in ('provider', 'url', 'retrieved_at', 'raw_sha256', 'price_basis'):
        if not isinstance(source.get(key), str) or not source[key]:
            raise ValueError(f'missing source {key}')
    if source['price_basis'] not in ('unadjusted', 'split_adjusted') or source.get('interval_minutes') != 5:
        raise ValueError('known five-minute price basis required')
    if type(source.get('synthetic')) is not bool or type(source.get('derived_public_use')) is not bool:
        raise ValueError('explicit synthetic and derived-public-use flags required')
    if datetime.fromisoformat(source['retrieved_at']).utcoffset() is None:
        raise ValueError('retrieved_at needs timezone')


def packets(data, plan):
    """Validate provenance and retain absent trading days as explicit refusals."""
    source = data['source']
    validate_source(source)
    if source['price_basis'] != 'unadjusted':
        raise ValueError('unadjusted five-minute bars required')
    if not isinstance(data['sessions'], list) or len(data['sessions']) > 366:
        raise ValueError('bounded sessions list required')
    by_date = {}
    for packet in data['sessions']:
        if packet['session'] in by_date:
            raise ValueError('duplicate session')
        if packet['market'] != plan['market'] or packet['ticker'] != plan['universe'][0]:
            raise ValueError('mixed universe')
        if not plan['start'] <= packet['session'] <= plan['end']:
            raise ValueError('session outside frozen range')
        if not is_trading_day(plan['market'], date.fromisoformat(packet['session'])):
            raise ValueError('non-trading day')
        # Preserve a supplied prohibition; never infer real policy authorization.
        by_date[packet['session']] = {**packet, **{k: plan[k] for k in ('shares', 'base_shares', 'lot_size')}}
    days = []
    current = date.fromisoformat(plan['start'])
    while current <= date.fromisoformat(plan['end']):
        if is_trading_day(plan['market'], current):
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days, by_date


class StressCosts:
    """Keep tax/rounding owner; only add explicit execution stress assumptions."""
    def __init__(self, base, spread_multiple=1, extra_bps=0):
        self.base, self.spread_multiple, self.extra_bps = base, spread_multiple, extra_bps

    def describe(self):
        return {**self.base.describe(), 'study_spread_multiple': self.spread_multiple,
                'study_extra_bps_per_leg': self.extra_bps}

    def fill(self, notional, leg, session, **kwargs):
        receipt = deepcopy(self.base.fill(notional, leg, session, **kwargs))
        model = self.base.describe()
        extra = notional * (model['spread_bps'][leg] * model['spread_share'] *
                            (self.spread_multiple-1) + self.extra_bps) / 10000
        receipt['study_execution_stress'] = extra
        receipt['total'] += extra
        receipt['bps'] = receipt['total'] / notional * 10000
        return receipt


def path_metrics(rows, plan, capital):
    """A gap invalidates full-path metrics; do not silently drop failed sessions."""
    used = defaultdict(lambda: plan['monthly_opening_used_hkd'])
    net, peak, dd, turnover, fees, trades = 0., 0., 0., 0., 0., 0
    reasons = Counter()
    curve = []
    for day, result in rows:
        if result['status'] in ('refused', 'unresolved'):
            reasons[result['reason']] += 1
        for t in result['trades']:
            amount = t['shares'] * (t['sell_price'] + t['buy_price'])
            used[day[:7]] += amount * (plan['usd_hkd'] if plan['market'] == 'us' else 1)
            if used[day[:7]] > 500000:
                reasons['commission_allowance_exhausted_unknown_tariff'] += 1
            turnover += amount
            fees += t['sell_cost']['total'] + t['buy_cost']['total']
            trades += 1
        net += result.get('net_pnl') or 0
        peak = max(peak, net)
        dd = max(dd, peak-net)
        curve.append({'session': day, 'net_increment': result.get('net_pnl') if not reasons else None,
                      'cumulative_net': net if not reasons else None,
                      'unpriced_or_missing': bool(reasons)})
    complete = not reasons and bool(rows) and capital is not None
    return {'complete': complete, 'sessions': len(rows), 'trades': trades,
            'reasons': dict(reasons), 'net_increment': net if complete else None,
            'net_return_on_initial_base_plus_reserve': net/capital if complete else None,
            'max_session_close_drawdown': dd if complete else None,
            'turnover_notional': turnover, 'turnover_over_initial_capital': turnover/capital if capital else None,
            'costs': fees, 'monthly_turnover_hkd_including_opening_usage': dict(used),
            'curve': curve, 'metric_basis': 'timing increment versus retaining base; not total account return; close-to-close drawdown only'}


def simultaneous_lower(paths, count=400):
    """Day blocks and Bonferroni lower tail across ALL declared comparison arms."""
    if not paths or any(not p['complete'] for p in paths.values()):
        return None
    rng = random.Random(seed('intraday_walkforward_bootstrap'))
    tail = .05/len(paths)
    output = {}
    for name, path in paths.items():
        values = [r['net_increment'] for r in path['curve']]
        n = len(values)
        samples = []
        for _ in range(count):
            draw = []
            while len(draw) < n:
                start = rng.randrange(n)
                draw.extend(values[(start+j) % n] for j in range(5))
            samples.append(sum(draw[:n]))
        samples.sort()
        output[name] = samples[max(0, int(count*tail)-1)]
    return output


def run(kernel, raw_plan, data, selections=None):
    plan = manifest(raw_plan)
    source = data.get('source', {})
    validate_source(source)
    if (source.get('research_use') is True and source.get('license_evidence')
            and source.get('price_basis') == 'split_adjusted'):
        # Do not reinterpret adjusted quotes as execution prices just to get a result.
        observed = sorted({p['session'] for p in data['sessions']})
        return {'schema': 'intraday-research/v1', 'code': code_provenance(), 'generated_at': datetime.now(timezone.utc).isoformat(),
                'live_permission': False, 'market': plan['market'], 'ticker': plan['universe'][0],
                'as_of': observed[-1] if observed else None, 'source': source,
                'data_sha256': digest(data), 'manifest': plan, 'manifest_sha256': digest(plan),
                'cost_model': kernel.get('costs').describe(), 'metrics': {}, 'requests': [],
                'validation': 'synthetic_test_only' if source['synthetic'] else 'insufficient_or_failed', 'prospective_status': 'not_started',
                'oos_sessions': 0, 'observed_sessions': len(observed),
                'observed_range': [observed[0], observed[-1]] if observed else [],
                'blockers': ['split-adjusted samples are not verified unadjusted execution prices'] +
                            (['fewer than training plus minimum OOS sessions'] if len(observed) < plan['train_sessions'] + plan['minimum_oos'] else [])}
    days, by_date = packets(data, plan)
    results, requests, folds = {}, [], []
    costs = kernel.get('costs')
    # All stress arms use the SAME training-selected schedule, never retuned on OOS.
    for scenario, delay, spread, extra in [('base', 0, 1, 0), ('spread_x2', 0, 2, 0),
                                         ('delay_one_bar', 1, 1, 0), ('unknown_fee_2bps', 0, 1, 2), ('regular_taf', 0, 1, 0)]:
        scenario_costs = costs
        if scenario == 'regular_taf':
            fees = deepcopy(costs.model.regulatory_fees)
            taf = fees.get('us', {}).get('taf', {})
            taf.update(taf.get('regular_2026', {}))
            scenario_costs = Costs(replace(costs.model, regulatory_fees=fees))
        grid = []
        for candidate in plan['candidates']:
            service = kernel.get(candidate['service']).configured(candidate['params'])
            service.costs = StressCosts(scenario_costs, spread, extra)
            outputs = {}
            for day in days:
                packet = by_date.get(day)
                if packet is None:
                    outputs[day] = {'status': 'refused', 'reason': 'missing_session', 'trades': [], 'net_pnl': None}
                    continue
                packet = {**packet, 'execution': {'delay_bars': delay,
                          'participation': plan['max_participation'], 'cash_reserve': plan['cash_reserve']}}
                outputs[day] = service.replay(packet)
            grid.append(outputs)
        results[scenario] = grid
    hold = {'status': 'no_trade', 'trades': [], 'net_pnl': 0., 'reason': 'retain_base'}
    arms = defaultdict(list)
    oos_start = plan['train_sessions']
    capital = None
    first = by_date.get(days[oos_start]) if len(days) > oos_start else None
    if first and first.get('bars'):
        capital = first['bars'][0]['open']*plan['base_shares'] + plan['cash_reserve']
    choices = selections or {}
    llm_errors = []
    for offset in range(oos_start, len(days), plan['test_sessions']):
        train = days[offset-plan['train_sessions']:offset]
        test = days[offset:offset+plan['test_sessions']]
        scores = []
        for candidate in results['base']:
            path = path_metrics([(d, candidate[d]) for d in train], plan, 1.)
            scores.append(path['net_increment'] if path['complete'] else None)
        best = max([(-1, 0.)] + [(i, v) for i, v in enumerate(scores) if v is not None], key=lambda x: x[1])[0]
        request = {'schema_version': 1, 'manifest_sha256': digest(plan), 'train_first': train[0],
                   'train_last': train[-1], 'test_first': test[0], 'training_net': scores,
                   'training_input_sha256': digest([by_date.get(d) for d in train]),
                   'cost_model_sha256': digest(costs.describe()),
                   'choices': [-1] + list(range(len(scores))), 'rule_choice': best,
                   'prompt': 'Choose a research arm (-1 hold), mechanism, counterexample and focus. Cite this receipt hash. No test outcomes supplied; not a live action.'}
        request['sha256'] = digest(request)
        requests.append(request)
        choice = choices.get(test[0])
        llm = None
        if choice:
            expected = {'request_sha256', 'candidate', 'author_model', 'mechanism', 'counterexample', 'focus'}
            if (set(choice) == expected and choice['request_sha256'] == request['sha256']
                    and type(choice['candidate']) is int and choice['candidate'] in request['choices']
                    and choice['focus'] in FOCI
                    and all(isinstance(choice[k], str) and choice[k].strip() for k in ('author_model', 'mechanism', 'counterexample'))):
                llm = choice['candidate']
            else:
                llm_errors.append({'test_first': test[0], 'reason': 'invalid_response', 'response': choice})
        else:
            llm_errors.append({'test_first': test[0], 'reason': 'missing_response'})
        folds.append({'train': [train[0], train[-1]], 'test': [test[0], test[-1]], 'selected': best,
                      'training_net': scores, 'llm_choice': llm})
        for day in test:
            arms['hold'].append((day, hold))
            arms['fixed_band'].append((day, results['base'][0][day]))
            # Simple regime benchmark: previous completed session down -> continuation.
            previous = by_date.get(days[days.index(day)-1])
            down = previous and previous.get('bars') and previous['bars'][-1]['close'] < previous['bars'][0]['open']
            regime_idx = next((i for i, c in enumerate(plan['candidates']) if c['service'] == 'intraday_breakout'), 0) if down else 0
            arms['simple_regime'].append((day, results['base'][regime_idx][day]))
            for scenario, grid in results.items():
                arms[scenario].append((day, hold if best == -1 else grid[best][day]))
            if llm is not None:
                arms['llm'].append((day, hold if llm == -1 else results['base'][llm][day]))
    metrics = {name: path_metrics(rows, plan, capital) for name, rows in arms.items()}
    if llm_errors:
        metrics.pop('llm', None)  # partial response coverage is never full performance
    bounds = simultaneous_lower({k: v for k, v in metrics.items() if k != 'hold'})
    oos = max(0, len(days)-oos_start)
    qualified = (not any(d not in by_date for d in days) and oos >= plan['minimum_oos'] and bool(bounds) and bounds.get('base', 0) > 0
                 and all(metrics[s]['complete'] and metrics[s]['net_increment'] > 0
                         for s in ('spread_x2', 'delay_one_bar', 'unknown_fee_2bps', 'regular_taf')))
    return {'schema': 'intraday-research/v1', 'code': code_provenance(), 'generated_at': datetime.now(timezone.utc).isoformat(),
            'live_permission': False, 'market': plan['market'], 'ticker': plan['universe'][0],
            'as_of': plan['end'], 'source': data['source'], 'data_sha256': digest(data),
            'manifest': plan, 'manifest_sha256': digest(plan), 'cost_model': costs.describe(),
            'folds': folds, 'requests': requests, 'llm_responses': choices, 'llm_errors': llm_errors,
            'metrics': metrics, 'simultaneous_net_lower': bounds,
            'bootstrap': {'seed': seed('intraday_walkforward_bootstrap'), 'replicates': 400, 'block_sessions': 5, 'adjustment': 'Bonferroni over reported non-hold arms'},
            'oos_sessions': oos, 'missing_sessions': [d for d in days if d not in by_date],
            'validation': 'synthetic_test_only' if data['source'].get('synthetic') is not False else
                          'retrospective_candidate' if qualified else 'insufficient_or_failed',
            'prospective_status': 'not_started',
            'limitations': ['retrospective selection, not historical LLM prediction',
                            'current tariff counterfactual, not historical invoice',
                            'monthly opening allowance usage and FX assumed; no account invoice',
                            'OHLC execution conditional; no order book/queue or intrabar drawdown',
                            'no prospective or live authorization'],
            'last_replay': results['base'][0].get(days[-1]) if days else None}
