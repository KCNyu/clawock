"""Series maths shared by the regime evaluations.

`combined_regime` and `us_leverage` each carried byte-identical copies of these
three. They are small enough that copying felt cheaper than sharing, which is
how a rolling-window off-by-one gets fixed in one file and not the other — and
both of these evaluations feed the leverage dial, so a divergence between them
would be invisible and load-bearing at the same time.

Deliberately left behind: `underwater`, whose two copies are NOT identical, and
`fetch`, which is a network seam rather than maths. Merging things that only
look alike is how a shared helper acquires a caller it was never right for.

Imports nothing from clawock.
"""
from __future__ import annotations

import math


def sma(v, n):
    """Simple moving average, `None` until the window is full."""
    out = [None] * len(v)
    s = 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n:
            s -= v[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rvol(rets, n, i):
    """Annualised realised vol over the `n` returns ending at `i`."""
    if i < n:
        return None
    w = rets[i - n + 1:i + 1]
    m = sum(w) / n
    return math.sqrt(sum((x - m) ** 2 for x in w) / (n - 1)) * math.sqrt(252)


def mdd(nav):
    """Maximum drawdown of a NAV series, as a negative fraction."""
    peak = -1e9
    m = 0.0
    for v in nav:
        peak = max(peak, v)
        m = min(m, v / peak - 1)
    return m
