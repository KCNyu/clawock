"""Observations and computations the model asks for, each with its provenance.

The packet hands the model measurements already folded into verdicts — a
composite score, a setup grade, a candidate state. These two tools reach under
those: `observations` returns the dated, sourced rows a verdict was built from,
and `compute` runs an expression the model wrote on the stored daily bars and
returns the number with a receipt (#2843).

Neither authorises anything. A computed feature is the model's hypothesis about
what matters; the receipt proves only that the inputs existed, nothing later
than `as_of` was read, and the arithmetic replays.
"""
from __future__ import annotations

import json
from pathlib import Path

from clawock.decision import packet as brief_decision_packet
from clawock.market_data import compute as calculator
from clawock.tools.base import BaseTool, ToolError

OBSERVATION_KINDS = ("bars", "factors", "events")
DEFAULT_BARS = 20
MAX_BARS = 120
#: Keys of a factor row that are a policy's opinion about the measurements next
#: to them. Named so a reader of the raw row can tell which is which.
FACTOR_OPINION_KEYS = ("composite_score", "market_percentile", "sector_neutral_ranks",
                       "usable_for_decisions")
EVENT_OPINION_KEYS = ("source_reliability", "impact_direction", "novelty_score",
                      "novelty_reason", "actionable_escalation", "confirmation")


def _json(workspace, relative):
    try:
        return json.loads((Path(workspace) / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Compute(BaseTool):
    name = "compute"
    description = (
        "Compute a feature you define on the stored daily bars and get the number "
        "with a receipt: the inputs it read, the session it is as of, and an id to "
        "cite. Write the expression with: "
        + ", ".join(calculator.function_names())
        + ". Tickers are quoted strings; series combine with + - * /. "
        'Example: zscore(close("RKLX") / close("RKLB"), 20).'
    )
    parameters = {
        "type": "object",
        "properties": {
            "expression": {"type": "string",
                           "description": "The expression; must reduce to one number."},
            "as_of": {"type": "string",
                      "description": "YYYY-MM-DD: cut every series at this session."},
            "unit": {"type": "string", "enum": list(calculator.UNITS),
                     "description": "Name the result's unit when arithmetic makes it "
                                    "ambiguous (a ratio of prices is `plain`)."},
        },
        "required": ["expression"],
    }
    # Writes its receipt, so a caller batching read-only tools must not assume it.
    is_readonly = False

    @classmethod
    def check_available(cls, workspace) -> bool:
        return (Path(workspace) / "memory" / "bars").is_dir()

    def execute(self, workspace, *, expression: str, as_of: str | None = None,
                unit: str | None = None) -> str:
        try:
            receipt = calculator.evaluate(
                expression, as_of=as_of or None, unit=unit or None,
                load=calculator.workspace_loader(workspace))
        except calculator.ComputeError as exc:
            raise ToolError(str(exc)) from exc
        calculator.save_receipt(workspace, receipt)
        return json.dumps(receipt, ensure_ascii=False, indent=2)


class Observations(BaseTool):
    name = "observations"
    description = (
        "The dated, sourced rows behind the packet's verdicts for one ticker. "
        "`bars`: stored daily OHLC (any registry ticker, held or not). `factors`: "
        "every measured factor value, not only the composite. `events`: every "
        "recorded event, escalated or not. Each payload separates what was "
        "measured from the policy opinion attached to it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Ticker, e.g. 00100 or RKLB."},
            "kind": {"type": "string", "enum": list(OBSERVATION_KINDS)},
            "n": {"type": "string",
                  "description": f"bars only: sessions to return (default {DEFAULT_BARS}, "
                                 f"max {MAX_BARS})."},
            "as_of": {"type": "string",
                      "description": "bars only: YYYY-MM-DD, nothing after this session."},
        },
        "required": ["ticker", "kind"],
    }

    @classmethod
    def check_available(cls, workspace) -> bool:
        root = Path(workspace)
        return (root / "memory" / "bars").is_dir() or (root / "assets" / "data").is_dir()

    def execute(self, workspace, *, ticker: str, kind: str, n: str | None = None,
                as_of: str | None = None) -> str:
        ticker = str(ticker or "").strip().upper()
        if kind not in OBSERVATION_KINDS:
            raise ToolError(f"unknown kind {kind!r}; expected one of "
                            f"{', '.join(OBSERVATION_KINDS)}")
        payload = getattr(self, f"_{kind}")(workspace, ticker, n=n, as_of=as_of)
        return brief_decision_packet.bounded_payload(payload)

    @staticmethod
    def _bars(workspace, ticker, *, n, as_of):
        try:
            count = int(n) if n not in (None, "") else DEFAULT_BARS
        except ValueError as exc:
            raise ToolError("n must be a whole number") from exc
        if not 1 <= count <= MAX_BARS:
            raise ToolError(f"n must be within 1..{MAX_BARS}")
        doc = _json(workspace, f"memory/bars/{ticker}.json") if calculator._TICKER.fullmatch(
            ticker) else None
        rows = sorted((day, bar) for day, bar in ((doc or {}).get("bars") or {}).items()
                      if isinstance(bar, dict) and (not as_of or day <= as_of))
        if not rows:
            raise ToolError(f"no stored daily bars for {ticker}"
                            + (f" at or before {as_of}" if as_of else ""))
        rows = rows[-count:]
        return {
            "ticker": ticker,
            "kind": "bars",
            "source": doc.get("source"),
            "adjustment": doc.get("adjustment"),
            "unit": "price, listing currency",
            "observed_through": rows[-1][0],
            "sessions": len(rows),
            "missing": "volume is not stored; history starts where the store does",
            "rows": [{"session": day,
                      **{key: bar.get(key) for key in ("open", "high", "low", "close")},
                      **({"flags": bar["flags"]} if bar.get("flags") else {}),
                      "fetched_at": bar.get("fetched_at")}
                     for day, bar in rows],
        }

    @staticmethod
    def _factors(workspace, ticker, **_):
        doc = _json(workspace, "assets/data/cross_sectional_factor.json") or {}
        row = (doc.get("live_rankings") or {}).get(ticker)
        if not isinstance(row, dict):
            raise ToolError(f"no factor row for {ticker}; the factor universe has "
                            f"{len(doc.get('live_rankings') or {})} names")
        activation = doc.get("activation") or {}
        return {
            "ticker": ticker,
            "kind": "factors",
            "as_of": row.get("feature_as_of") or doc.get("as_of"),
            "price_adjustment": (doc.get("universe") or {}).get("price_adjustment"),
            "measurements": {key: value for key, value in row.items()
                             if key not in FACTOR_OPINION_KEYS},
            "policy_opinion": {
                **{key: row.get(key) for key in FACTOR_OPINION_KEYS if key in row},
                "weights": (doc.get("methodology") or {}).get("weights"),
                "validated": bool(activation.get("usable_for_decisions")),
                "validation_blockers": activation.get("blockers") or [],
                "note": ("the composite and ranks are one registered way to weigh "
                         "the measurements; an unvalidated composite says nothing "
                         "about whether a single measurement is true"),
            },
            "methodology": {key: value for key, value in (doc.get("methodology") or {}).items()
                            if key != "weights"},
        }

    @staticmethod
    def _events(workspace, ticker, **_):
        doc = _json(workspace, "assets/data/news_evidence_graph.json") or {}
        rows = [event for event in doc.get("events") or []
                if isinstance(event, dict)
                and ticker in (str(event.get("ticker")), str(event.get("reported_ticker")))]
        return {
            "ticker": ticker,
            "kind": "events",
            "as_of": doc.get("as_of"),
            "source_status": doc.get("source_status"),
            "events": [{
                "observed": {key: value for key, value in event.items()
                             if key not in EVENT_OPINION_KEYS},
                "policy_opinion": {key: event.get(key) for key in EVENT_OPINION_KEYS
                                   if key in event},
            } for event in rows],
            "missing": None if rows else "no event recorded for this ticker; "
                                         "that is not the same as no news",
        }


TOOLS = (Compute, Observations)
