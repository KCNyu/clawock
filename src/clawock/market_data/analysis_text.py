"""Numeric text shared by the HK and US analysis reports."""
from clawock.safe_io import to_finite_number


def price_text(value, spec='.2f'):
    number = to_finite_number(value)
    return format(number, spec) if number is not None else '—'
