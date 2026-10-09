"""Usable daily prices for live signals and return calculations."""
from clawock.safe_io import to_finite_number


def positive_price(value):
    """A bad tick is neither a price nor a -100% return."""
    value = to_finite_number(value)
    return value if value is not None and value > 0 else None


def clean_bars(bars):
    """Skip unusable OHLC rows, retaining provider dates and extra fields."""
    out = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        prices = {key: positive_price(bar.get(key))
                  for key in ('open', 'close', 'high', 'low')}
        if any(value is None for value in prices.values()):
            continue
        out.append({**bar, **prices})
    return out
