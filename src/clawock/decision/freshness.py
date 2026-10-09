"""Session checks for persisted quant rows consumed outside their producer."""
from datetime import date


def quant_row_for_session(payload, symbol, expected):
    """Return (usable row, source date); legacy rows require a dated artifact."""
    rows = payload.get('rows') if isinstance(payload, dict) else None
    row = rows.get(symbol) if isinstance(rows, dict) else None
    if not isinstance(row, dict):
        return {}, None
    as_of = row.get('row_as_of')
    if not as_of and row.get('status') is None:
        as_of = payload.get('as_of')
    try:
        day = date.fromisoformat(as_of)
    except (TypeError, ValueError):
        return {}, as_of
    if expected is None or day != expected or row.get('status') not in (None, 'fresh'):
        return {}, as_of
    return row, as_of
