"""Deterministic two-currency P&L shared by brief inputs, plans and cards."""
import math


def pnl_totals(hk_leg_hkd, us_leg_usd, rate):
    values = (hk_leg_hkd, us_leg_usd, rate)
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) for v in values) or rate <= 0:
        raise ValueError('book inputs invalid: finite legs and positive USDHKD required')
    usd = hk_leg_hkd / rate + us_leg_usd
    hkd = hk_leg_hkd + us_leg_usd * rate
    if not math.isfinite(usd) or not math.isfinite(hkd):
        raise ValueError('book inputs invalid: totals overflow')
    return {'usd_total_pnl': round(usd, 2), 'hkd_total_pnl': round(hkd, 2)}


def plan_totals(plan):
    book = plan.get('book')
    if not isinstance(book, dict):
        raise ValueError('book inputs invalid: book must be an object')
    return pnl_totals(book.get('hk_leg_hkd'), book.get('us_leg_usd'),
                      plan.get('fx_rate_usdhkd'))


def validate_plan_book(plan):
    if 'book' not in plan:
        return []  # Older/minimal plans have no monetary block to consume.
    try:
        expected = plan_totals(plan)
    except ValueError as exc:
        return [str(exc)]
    errors = []
    for key, value in expected.items():
        supplied = plan['book'].get(key)
        if (isinstance(supplied, bool) or not isinstance(supplied, (int, float))
                or not math.isfinite(supplied) or abs(supplied - value) > .02):
            errors.append(f'book totals mismatch: {key} must equal {value}')
    return errors
