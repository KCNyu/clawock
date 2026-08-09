"""Resolve market books without assuming workspace-specific bucket names."""

from __future__ import annotations

from collections.abc import Mapping

from clawock.instrument_registry import INSTRUMENTS


def region_book(portfolio: dict, region: str) -> tuple[str, dict]:
    """Return the one portfolio bucket that represents ``region``.

    Active registered holdings are authoritative. Currency is only a fallback
    for an empty book, so an unrelated workspace can call the market commands
    with names such as ``america`` or ``hong_kong`` without configuration that
    merely repeats its instrument registry.
    """
    wanted = str(region).upper()
    books = portfolio.get("portfolios") or {}
    if not isinstance(books, Mapping):
        raise ValueError("portfolio.json has no portfolios object")

    active_matches: list[tuple[str, dict]] = []
    empty_matches: list[tuple[str, dict]] = []
    currency = {"US": "USD", "HK": "HKD"}.get(wanted)
    for name, book in books.items():
        if not isinstance(book, dict):
            continue
        active = [
            holding for holding in (book.get("holdings") or [])
            if isinstance(holding, dict) and (holding.get("shares") or 0) > 0
        ]
        regions = {
            (INSTRUMENTS.get(str(holding.get("ticker") or "")) or {}).get("region")
            for holding in active
        }
        regions.discard(None)
        if active and regions == {wanted}:
            active_matches.append((str(name), book))
        elif not active and currency and book.get("currency") == currency:
            empty_matches.append((str(name), book))

    matches = active_matches or empty_matches
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"no {wanted} market book found from registered holdings")
    names = ", ".join(name for name, _ in matches)
    raise ValueError(f"multiple {wanted} market books are ambiguous: {names}")
