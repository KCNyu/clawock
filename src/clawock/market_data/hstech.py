"""Tencent HSTECH daily closes shared by live decisions and evaluations."""
import requests  # noqa: F401  compatibility for callers patching the shared transport

from clawock.market_data.tencent_daily import TENCENT, fetch_hk_daily_closes  # noqa: F401


def fetch_hstech(start='2021-01-01', end=None, lim=2000):
    """Return dated closes, skipping malformed rows; transport errors propagate."""
    return fetch_hk_daily_closes('hkHSTECH', start, end, lim)
