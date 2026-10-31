"""Shared research prerequisites and active exposure exclusions for discovery."""
from clawock.safe_io import to_strict_finite_number

MISSING = ["报价时点与交易场次核验", "一手披露与商业模式", "估值与下行风险", "entry-gate 硬否决"]


def excluded_exposure(portfolio, registry):
    """Exclude actual holdings and their known underlying/1x/signal exposures."""
    blocked = set()
    if not isinstance(portfolio, dict) or not isinstance(portfolio.get("portfolios"), dict):
        raise ValueError("portfolio missing portfolios")
    for book in portfolio["portfolios"].values():
        if not isinstance(book, dict) or not isinstance(book.get("holdings"), list):
            raise ValueError("invalid region book")
        for holding in book["holdings"]:
            if not isinstance(holding, dict):
                raise ValueError("invalid holding row")
            shares = to_strict_finite_number(holding.get("shares"))
            if shares is None or shares < 0:
                raise ValueError("invalid holding shares")
            if shares == 0:
                continue
            symbol = str(holding.get("ticker") or "").strip().upper()
            if not symbol:
                raise ValueError("active holding missing ticker")
            blocked.add(symbol)
            meta = registry.get(symbol)
            if not isinstance(meta, dict):
                raise ValueError("active holding missing exposure metadata")
            for key in ("underlying", "one_x_substitute", "signal_symbol"):
                if meta.get(key):
                    blocked.add(str(meta[key]).upper())
    return blocked
