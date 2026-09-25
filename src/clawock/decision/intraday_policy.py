"""Instance strategy metadata for intraday presentation and verified escalations.

The engine is ticker agnostic. A holding selects a strategy in portfolio.json;
config/intraday-strategy-policies.json supplies that strategy's exception rules.
These rules affect intraday copy, never the underlying portfolio risk ledger.
"""
from __future__ import annotations

import json
from datetime import datetime

from clawock import instruments


def load(workspace, market):
    policies = json.loads((workspace / 'config' / 'intraday-strategy-policies.json').read_text())
    portfolio = json.loads((workspace / 'portfolio.json').read_text())
    leg = 'hk_stocks' if market == 'hk' else 'us_stocks'
    rows = portfolio.get('portfolios', {}).get(leg, {}).get('holdings', [])
    return {row['ticker']: {
                **policies[row['strategy']], 'strategy': row['strategy'],
                'escalations': [_resolve_rule(row['ticker'], rule) for rule in
                                policies[row['strategy']].get('escalations', [])],
                'strategy_note': row.get('strategy_note'),
                'risk_escalation_triggers': row.get('risk_escalation_triggers'),
            }
            for row in rows if row.get('ticker') and row.get('shares', 0) > 0
            and row.get('strategy') in policies}


def _resolve_rule(holding, rule):
    """Bind a strategy rule to the holding that selected the strategy.

    A strategy is shared by any holding that names it, so its rules speak of
    `holding` or of the holding's registry `signal_symbol` (`underlying`), never
    of a ticker: a second holding adopting the strategy must not inherit the
    first one's thresholds. An unresolvable underlying stays `None` so the
    check reports unavailable evidence instead of vanishing.
    """
    if rule.get('subject') == 'holding':
        ticker = holding
    elif rule.get('subject') == 'underlying':
        ticker = (instruments.get(holding) or {}).get('signal_symbol')
        ticker = ticker if ticker and ticker != holding else None
    else:
        raise ValueError(f"intraday strategy rule needs subject holding|underlying: {rule}")
    return {**rule, 'ticker': ticker}


def plan_conflicts(holding_policies, plan_context):
    """Expose unresolved policy/plan disagreement; do not choose an action."""
    reducing = {'cut', 'trim_on_rebound'}
    return [{
        'ticker': row['ticker'], 'decision_id': row.get('decision_id'),
        'plan_action': row.get('action'), 'driven_by': row.get('driven_by'),
        'strategy': holding_policies[row['ticker']].get('strategy'),
        'issue': 'open reduce plan conflicts with current intraday strategy',
    } for row in ((plan_context or {}).get('open') or [])
        if row.get('ticker') in holding_policies
        and row.get('action') in reducing
        and holding_policies[row['ticker']].get('forbid_reduce_advice')]


def actionable_signals(counts, detail, holding_policies):
    rows = [row for row in detail if not holding_policies.get(
        row.get('ticker'), {}).get('suppress_cost_basis_signals')]
    levels = ('ALERT', 'WATCH', 'STOP', 'TRIM')
    return ({level.lower(): sum(str(row.get('level', '')).upper() == level
                                for row in rows) for level in levels}, rows)


def escalations(holding_policies, anomalies, coverage, prices, universe, fetch_bars,
                session_date, *, errors=None, checks=None, daily_moves=None):
    """Evaluate each configured rule and expose both crossing and source state."""
    missing = set(coverage.get('unrefreshed') or [])
    errors = errors if errors is not None else []
    checks = checks if checks is not None else []
    daily = {**(daily_moves or {}), **{
        row.get('ticker'): row.get('move_pct') for row in anomalies or []}}
    codes = {row.get('label'): row.get('code') for row in universe}
    rows = []
    for holding, policy in holding_policies.items():
        for rule in policy.get('escalations', []):
            ticker = rule['ticker']
            window = rule['window']
            check = {'holding': holding, 'ticker': ticker, 'window': window,
                     'threshold_pct': rule['below_pct'], 'observed_pct': None,
                     'status': 'unavailable', 'source': None}
            if ticker is None:
                errors.append(f"{holding}: {rule.get('subject')} not in instrument registry")
                checks.append(check)
                continue
            if (ticker in missing or not coverage.get('active')
                    or not coverage.get('refreshed')):
                errors.append(f'{ticker}: quote not freshly verified')
                checks.append(check)
                continue
            pct = None
            if window == 'session':
                pct = daily.get(ticker)
                check['source'] = 'fresh intraday quote vs verified prior close'
                if not isinstance(pct, (int, float)):
                    errors.append(f'{ticker}: daily move unavailable')
            elif window == 'five_sessions' and ticker in prices and ticker in codes:
                try:
                    bars = fetch_bars(codes[ticker], 400)
                    completed = [bar for bar in bars if bar.get('date', '') < session_date]
                    if len(completed) >= 5 and (datetime.fromisoformat(session_date).date()
                            - datetime.fromisoformat(completed[-1]['date']).date()).days <= 5:
                        pct = round((prices[ticker] / completed[-5]['close'] - 1) * 100, 1)
                        check['source'] = f"fresh quote vs {completed[-5]['date']} completed close"
                    else:
                        errors.append(f'{ticker}: five-session bars unavailable or stale')
                except Exception as exc:  # noqa: BLE001 - failed evidence must stay visible
                    errors.append(f'{ticker}: invalid five-session bars: {type(exc).__name__}')
            elif window == 'five_sessions':
                errors.append(f'{ticker}: price or universe code unavailable')
            if isinstance(pct, (int, float)):
                check['observed_pct'] = pct
                check['status'] = 'triggered' if pct < rule['below_pct'] else 'clear'
            checks.append(check)
            if isinstance(pct, (int, float)) and pct < rule['below_pct']:
                rows.append({'holding': holding, 'ticker': ticker,
                             'window': window, 'move_pct': pct,
                             'threshold_pct': rule['below_pct']})
    return rows


def strip_suppressed_signal_lines(block, holding_policies):
    """Remove only analyzer signal lines for policy covered holdings from copy."""
    suppressed = {ticker for ticker, policy in holding_policies.items()
                  if policy.get('suppress_cost_basis_signals')}
    out, skip_detail = [], False
    for line in block.splitlines():
        if any(f' {ticker} ' in f' {line} ' and
               any(word in line for word in ('STOP-LOSS', 'STOP?', 'WATCH', 'TRIM'))
               for ticker in suppressed):
            skip_detail = True
            continue
        if skip_detail and line.lstrip().startswith('·'):
            continue
        skip_detail = False
        out.append(line)
    for index in range(len(out) - 1, -1, -1):
        if out[index].strip() == '⚠️ 信号':
            following = next((line.strip() for line in out[index + 1:] if line.strip()), '')
            if not following.startswith(('▼', '△', '✋', '▲')):
                del out[index]
    return '\n'.join(out)
