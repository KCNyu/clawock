"""Explain carried book values without changing valuation or asserting freshness."""
from clawock.safe_io import carried_value, to_number, to_finite_number

LABELS = {"quote": "报价估值", "cost": "成本结转", "unavailable": "无法估值"}


def basis(holding):
    value = to_number(holding.get("current_value"))
    shares = to_finite_number(holding.get("shares"))
    cost = to_finite_number(holding.get("cost_basis"))
    kind = ("unavailable" if value is not None and to_finite_number(value) is None
            else "quote" if value is not None else "cost"
            if shares is not None and cost is not None else "unavailable")
    return {"kind": kind, "label": LABELS[kind],
            "source": holding.get("data_source") if kind == "quote" else None,
            "session": holding.get("day_session_date") if kind == "quote" else None}


def summary(holdings):
    """Rows are raw active book holdings, all from the caller's generation."""
    rows = []
    total = carried = 0
    finite_total = True
    for holding in holdings:
        if not isinstance(holding, dict) or (to_number(holding.get("shares")) or 0) <= 0:
            continue
        mark = basis(holding)
        value = to_finite_number(carried_value(holding))
        if value is None:
            finite_total = False
            value = 0
        total += value
        if mark["kind"] == "cost":
            carried += value
        rows.append({"ticker": holding.get("ticker"), **mark})
    return {"rows": rows, "cost_carried_pct": round(carried / total * 100, 2) if finite_total and total > 0 else None,
            "cost_count": sum(r["kind"] == "cost" for r in rows),
            "unavailable_count": sum(r["kind"] == "unavailable" for r in rows),
            "note": "报价估值不代表新鲜度已核验；来源和场次沿用同代账本。"}
