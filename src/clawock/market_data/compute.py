"""A restricted calculator over the stored daily bars, with a receipt per result.

The context the model reads used to arrive pre-judged: MA200, ATR, range
position and the rest were computed with fixed windows and delivered together
with what they were supposed to mean (「追高低质」). A model that wanted a
different window, a different comparison set or a feature no config names had
two options — do the arithmetic in its head, which the numeric gate rejects, or
go without (#2843).

This module is the third option. The model writes the expression; the code
executes it on `memory/bars` and returns the number with the inputs it was
computed from. What the model chooses — which series, which window, which
relation — is its hypothesis. What this module guarantees is narrower and
checkable: the inputs exist, nothing after `as_of` was read, and the same
expression on the same bars gives the same value (`verify`).

The language is a whitelist over Python's expression grammar, parsed with `ast`
and never evaluated by the interpreter: calls to the functions below, string
tickers, numbers and arithmetic. No names, attributes, subscripts or
comprehensions — it cannot reach the host.

    ret(close("RKLB"), 20)                      20-session return, percent
    zscore(close("RKLX") / close("RKLB"), 20)   a relation no config defines
    last(close("00100")) / sma(close("00100"), 50) - 1

Resource limits (`MAX_*`) are a service contract, not an alpha rule.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import re
from pathlib import Path

TOOL_VERSION = 1
MAX_EXPRESSION_CHARS = 400
MAX_NODES = 80
MAX_WINDOW = 400
TRADING_DAYS = 252
FIELDS = ("open", "high", "low", "close")
UNITS = ("plain", "price", "percent", "pp", "multiple", "sigma")
#: The key a result is stored under, so the numeric gate reads its unit off the
#: key the way it does for every other context number (`validation._UNIT_KEY_HINTS`).
VALUE_KEYS = {"plain": "value", "price": "value", "percent": "value_pct",
              "pp": "value_pp", "multiple": "value_multiple", "sigma": "value_sigma"}


_TICKER = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,11}")


class ComputeError(ValueError):
    """The expression was refused or could not be computed. Shown verbatim."""


class Series:
    """Dated values, oldest first. Arithmetic aligns on the dates both sides have."""

    __slots__ = ("dates", "values")

    def __init__(self, dates, values):
        self.dates = list(dates)
        self.values = list(values)

    def __len__(self):
        return len(self.values)


def _align(left: Series, right: Series):
    other = dict(zip(right.dates, right.values))
    dates = [day for day in left.dates if day in other]
    mine = dict(zip(left.dates, left.values))
    return dates, [mine[day] for day in dates], [other[day] for day in dates]


def _arith(op, left, right):
    def apply(a, b):
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            raise ComputeError("division by zero")
        return a / b

    if isinstance(left, Series) and isinstance(right, Series):
        dates, a, b = _align(left, right)
        if not dates:
            raise ComputeError("the two series share no session")
        return Series(dates, [apply(x, y) for x, y in zip(a, b)])
    if isinstance(left, Series):
        return Series(left.dates, [apply(x, right) for x in left.values])
    if isinstance(right, Series):
        return Series(right.dates, [apply(left, y) for y in right.values])
    return apply(left, right)


def _window(n) -> int:
    if isinstance(n, bool) or not isinstance(n, (int, float)) or int(n) != n:
        raise ComputeError("a window must be a whole number of sessions")
    n = int(n)
    if not 1 <= n <= MAX_WINDOW:
        raise ComputeError(f"a window must be within 1..{MAX_WINDOW} sessions")
    return n


def _tail(series, n, *, extra=0, what="window"):
    if not isinstance(series, Series):
        raise ComputeError(f"{what} needs a series, e.g. close(\"TICKER\")")
    need = _window(n) + extra
    if len(series) < need:
        raise ComputeError(
            f"insufficient history: {what} needs {need} sessions, {len(series)} available")
    return series.values[-need:]


def _returns(values):
    return [(b / a - 1) for a, b in zip(values, values[1:]) if a]


def _mean(values):
    return sum(values) / len(values)


def _std(values):
    if len(values) < 2:
        raise ComputeError("a standard deviation needs at least 2 observations")
    mean = _mean(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _combined_unit(op, left, right, left_literal, right_literal) -> str:
    """The unit an arithmetic step can still vouch for.

    Two returns subtracted are points, two prices added are a price, and a
    literal factor scales a quantity without renaming it. Anything else — a
    ratio of prices, a product of two measures — is a plain number whose
    meaning is the author's (`unit=` names it).
    """
    if op in "+-" and left == right:
        return "pp" if left == "percent" else left
    if op in "*/" and right_literal:
        return left
    if op == "*" and left_literal:
        return right
    return "plain"


def _scalar(value, what):
    if isinstance(value, Series):
        raise ComputeError(f"{what} needs a number; reduce the series first (last, sma, …)")
    return float(value)


class _Evaluator:
    """Walks one parsed expression against bars loaded through `load`."""

    def __init__(self, load, as_of):
        self._load = load
        self.as_of = as_of
        self.inputs: dict[str, dict] = {}
        self.unit = "plain"

    # ── inputs ──────────────────────────────────────────────────────────────

    def _bars(self, ticker):
        if not isinstance(ticker, str) or not ticker.strip():
            raise ComputeError("a ticker is a quoted string, e.g. close(\"00100\")")
        ticker = ticker.strip().upper()
        if not _TICKER.fullmatch(ticker):
            raise ComputeError(f"not a ticker: {ticker!r}")
        if ticker not in self.inputs:
            doc = self._load(ticker) or {}
            rows = {day: bar for day, bar in sorted((doc.get("bars") or {}).items())
                    if isinstance(bar, dict) and (self.as_of is None or day <= self.as_of)}
            if not rows:
                raise ComputeError(
                    f"no stored daily bars for {ticker}"
                    + (f" at or before {self.as_of}" if self.as_of else ""))
            self.inputs[ticker] = {"doc": doc, "rows": rows, "fields": set()}
        return self.inputs[ticker]

    def field(self, name, ticker):
        entry = self._bars(ticker)
        entry["fields"].add(name)
        pairs = [(day, bar.get(name)) for day, bar in entry["rows"].items()]
        pairs = [(day, float(value)) for day, value in pairs
                 if isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) and value > 0]
        if not pairs:
            raise ComputeError(f"{ticker} has no usable {name} values")
        return Series(*zip(*pairs))

    # ── functions ───────────────────────────────────────────────────────────

    def call(self, name, args):
        if name in FIELDS:
            self._arity(name, args, 1)
            self.unit = "price"
            return self.field(name, args[0])
        handler = getattr(self, f"fn_{name}", None)
        if handler is None:
            raise ComputeError(
                f"unknown function {name!r}; available: {', '.join(function_names())}")
        try:
            inspect.signature(handler).bind(*args)
        except TypeError as exc:
            raise ComputeError(f"{name}: invalid arguments ({exc})") from exc
        if name in {"min", "max"} and not args:
            raise ComputeError(f"{name} needs at least one argument")
        return handler(*args)

    @staticmethod
    def _arity(name, args, *counts):
        if len(args) not in counts:
            raise ComputeError(f"{name} takes {' or '.join(map(str, counts))} argument(s)")

    def fn_last(self, series):
        return _tail(series, 1, what="last")[-1]

    def fn_lag(self, series, k):
        return _tail(series, 1, extra=_window(k), what="lag")[0]

    def fn_sma(self, series, n):
        return _mean(_tail(series, n, what="sma"))

    def fn_ema(self, series, n):
        n = _window(n)
        values = _tail(series, n, what="ema")
        values = series.values[-min(len(series), n * 4):]
        alpha, out = 2 / (n + 1), _mean(values[:n])
        for value in values[n:]:
            out = alpha * value + (1 - alpha) * out
        return out

    def fn_highest(self, series, n):
        return max(_tail(series, n, what="highest"))

    def fn_lowest(self, series, n):
        return min(_tail(series, n, what="lowest"))

    def fn_ret(self, series, n):
        values = _tail(series, n, extra=1, what="ret")
        self.unit = "percent"
        return (values[-1] / values[0] - 1) * 100

    def fn_vol(self, series, n):
        values = _tail(series, n, extra=1, what="vol")
        self.unit = "percent"
        return _std(_returns(values)) * math.sqrt(TRADING_DAYS) * 100

    def fn_zscore(self, series, n):
        values = _tail(series, n, what="zscore")
        spread = _std(values)
        if spread == 0:
            raise ComputeError("zscore is undefined on a flat window")
        self.unit = "sigma"
        return (values[-1] - _mean(values)) / spread

    def fn_drawdown(self, series, n):
        values = _tail(series, n, what="drawdown")
        self.unit = "percent"
        return (values[-1] / max(values) - 1) * 100

    def fn_rsi(self, series, n):
        values = _tail(series, n, extra=1, what="rsi")
        moves = [b - a for a, b in zip(values, values[1:])]
        gain = sum(m for m in moves if m > 0) / len(moves)
        loss = -sum(m for m in moves if m < 0) / len(moves)
        self.unit = "plain"
        return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)

    def _true_ranges(self, ticker, n):
        high, low, close = (self.field(name, ticker) for name in ("high", "low", "close"))
        rows = self._bars(ticker)["rows"]
        days = [day for day in close.dates if day in set(high.dates) & set(low.dates)]
        need = _window(n) + 1
        if len(days) < need:
            raise ComputeError(
                f"insufficient history: atr needs {need} sessions, {len(days)} available")
        days = days[-need:]
        out = []
        for prev, day in zip(days, days[1:]):
            bar, before = rows[day], float(rows[prev]["close"])
            out.append(max(bar["high"] - bar["low"], abs(bar["high"] - before),
                           abs(bar["low"] - before)))
        return out, float(rows[days[-1]]["close"])

    def fn_atr(self, ticker, n):
        ranges, _ = self._true_ranges(ticker, n)
        self.unit = "price"
        return _mean(ranges)

    def fn_atr_pct(self, ticker, n):
        ranges, close = self._true_ranges(ticker, n)
        self.unit = "percent"
        return _mean(ranges) / close * 100

    def fn_range_pos(self, ticker, n):
        high = max(_tail(self.field("high", ticker), n, what="range_pos"))
        low = min(_tail(self.field("low", ticker), n, what="range_pos"))
        close = self.field("close", ticker).values[-1]
        if high == low:
            raise ComputeError("range_pos is undefined on a flat window")
        self.unit = "percent"
        return (close - low) / (high - low) * 100

    def _paired_returns(self, left, right, n, what):
        if not (isinstance(left, Series) and isinstance(right, Series)):
            raise ComputeError(f"{what} needs two series")
        dates, a, b = _align(left, right)
        need = _window(n) + 1
        if len(dates) < need:
            raise ComputeError(
                f"insufficient history: {what} needs {need} shared sessions, "
                f"{len(dates)} available")
        return _returns(a[-need:]), _returns(b[-need:])

    def fn_beta(self, series, benchmark, n):
        mine, base = self._paired_returns(series, benchmark, n, "beta")
        mean_a, mean_b = _mean(mine), _mean(base)
        variance = sum((b - mean_b) ** 2 for b in base)
        if variance == 0:
            raise ComputeError("beta is undefined against a flat benchmark")
        self.unit = "plain"
        return sum((a - mean_a) * (b - mean_b) for a, b in zip(mine, base)) / variance

    def fn_corr(self, series, other, n):
        mine, base = self._paired_returns(series, other, n, "corr")
        spread = _std(mine) * _std(base)
        if spread == 0:
            raise ComputeError("corr is undefined on a flat series")
        mean_a, mean_b = _mean(mine), _mean(base)
        self.unit = "plain"
        return (sum((a - mean_a) * (b - mean_b) for a, b in zip(mine, base))
                / (len(mine) - 1) / spread)

    def fn_abs(self, value):
        return abs(_scalar(value, "abs"))

    def fn_min(self, *values):
        return min(_scalar(v, "min") for v in values)

    def fn_max(self, *values):
        return max(_scalar(v, "max") for v in values)

    # ── the walk ────────────────────────────────────────────────────────────

    def visit(self, node):
        if isinstance(node, ast.Expression):
            return self.visit(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float, str)):
                raise ComputeError("only numbers and quoted tickers are literals")
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = self.visit(node.operand)
            return _arith("*", value, -1.0) if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            ops = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
            op = ops.get(type(node.op))
            if op is None:
                raise ComputeError("only + - * / are supported")
            self.unit = "plain"
            left = self.visit(node.left)
            left_unit, self.unit = self.unit, "plain"
            right = self.visit(node.right)
            right_unit = self.unit
            if isinstance(left, str) or isinstance(right, str):
                raise ComputeError("a ticker cannot be used as a number")
            self.unit = _combined_unit(op, left_unit, right_unit,
                                       isinstance(node.left, ast.Constant),
                                       isinstance(node.right, ast.Constant))
            return _arith(op, left, right)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                raise ComputeError("only plain function calls with positional arguments")
            return self.call(node.func.id, [self.visit(arg) for arg in node.args])
        raise ComputeError(f"unsupported syntax: {type(node).__name__}")


def function_names() -> list[str]:
    return sorted([*FIELDS, *(name[3:] for name in dir(_Evaluator) if name.startswith("fn_"))])


def _default_loader(ticker):
    from clawock.market_data import bars  # noqa: PLC0415 — keeps the pure path import-light

    return bars.load_bars(ticker)


def workspace_loader(workspace):
    """Bind calculation/replay to the tool's workspace, not an import-time root."""
    root = Path(workspace) / "memory" / "bars"

    def load(ticker):
        if not _TICKER.fullmatch(str(ticker)):
            raise ComputeError("invalid ticker")
        path = root / f"{ticker}.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise ComputeError(f"cannot read daily bars for {ticker}") from exc
        if not isinstance(doc, dict):
            raise ComputeError(f"invalid daily bars for {ticker}")
        return doc

    return load


def _input_rows(evaluator) -> list[dict]:
    rows = []
    for ticker, entry in sorted(evaluator.inputs.items()):
        fields = sorted(entry["fields"])
        used = {day: {name: bar.get(name) for name in fields}
                for day, bar in entry["rows"].items()}
        doc = entry["doc"]
        rows.append({
            "ticker": ticker,
            "fields": fields,
            "first_session": min(used),
            "last_session": max(used),
            "sessions": len(used),
            "source": doc.get("source"),
            "adjustment": doc.get("adjustment"),
            "sha256": hashlib.sha256(json.dumps(
                used, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        })
    return rows


def evaluate(expression: str, *, as_of: str | None = None, unit: str | None = None,
             load=None) -> dict:
    """Compute `expression` and return its receipt.

    `as_of` (YYYY-MM-DD) cuts every series at that session, so a value can be
    computed as it stood on an earlier day; nothing later is read. `unit`
    overrides the inferred one when the expression's arithmetic produces a
    quantity only its author can name (a difference of two returns is `pp`).
    """
    if not isinstance(expression, str) or not expression.strip():
        raise ComputeError("an expression is required")
    expression = " ".join(expression.split())
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise ComputeError(f"expression exceeds {MAX_EXPRESSION_CHARS} characters")
    if unit is not None and unit not in UNITS:
        raise ComputeError(f"unit must be one of {', '.join(UNITS)}")
    if as_of is not None:
        try:
            if len(as_of) != 10:
                raise ValueError(as_of)
            __import__("datetime").date.fromisoformat(as_of)
        except (TypeError, ValueError) as exc:
            raise ComputeError("as_of must be YYYY-MM-DD") from exc
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ComputeError(f"not a valid expression: {exc.msg}") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ComputeError(f"expression exceeds {MAX_NODES} syntax nodes")
    evaluator = _Evaluator(load or _default_loader, as_of)
    value = evaluator.visit(tree)
    if isinstance(value, str):
        raise ComputeError("the expression is only a ticker; wrap it in a function")
    if isinstance(value, Series):
        raise ComputeError("the expression is a series; reduce it (last, sma, ret, …)")
    if not math.isfinite(value):
        raise ComputeError("the result is not a finite number")
    inputs = _input_rows(evaluator)
    resolved_unit = unit or evaluator.unit
    body = {
        "kind": "compute",
        "tool_version": TOOL_VERSION,
        "expression": expression,
        # The session the value is as of: the caller's cut, else the latest bar read.
        "as_of": as_of or max((row["last_session"] for row in inputs), default=None),
        "requested_as_of": as_of,
        "unit": resolved_unit,
        VALUE_KEYS[resolved_unit]: round(value, 6),
        "inputs": inputs,
    }
    digest = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {"receipt_id": f"cr-{digest[:16]}", **body}


def receipt_value(receipt: dict):
    """The number a receipt carries, whichever unit key it is stored under."""
    return next((receipt[key] for key in dict.fromkeys(VALUE_KEYS.values())
                 if isinstance(receipt.get(key), (int, float))
                 and not isinstance(receipt.get(key), bool)), None)


def verify(receipt: dict, *, load=None) -> list[str]:
    """Why this receipt does not replay on the bars as stored now, or [].

    A receipt replays when the same expression, cut at the same session, reads
    the same inputs and gives the same value. Bars are append-only, so a
    mismatch means the stored history was repaired after the fact or the
    receipt was not produced by `evaluate`.
    """
    if not isinstance(receipt, dict) or receipt.get("kind") != "compute":
        return ["not a compute receipt"]
    try:
        again = evaluate(receipt.get("expression"), as_of=receipt.get("as_of"),
                         unit=receipt.get("unit"), load=load)
    except ComputeError as exc:
        return [f"does not recompute: {exc}"]
    issues = []
    if receipt_value(again) != receipt_value(receipt):
        issues.append(f"value {receipt_value(receipt)} recomputes as {receipt_value(again)}")
    before = {row.get("ticker"): row.get("sha256") for row in receipt.get("inputs") or []}
    after = {row["ticker"]: row["sha256"] for row in again["inputs"]}
    if before != after:
        issues.append("input bars differ from the ones the receipt was computed on")
    expected = {**again, "requested_as_of": receipt.get("requested_as_of")}
    expected.pop("receipt_id")
    digest = hashlib.sha256(json.dumps(
        expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    if not issues and receipt.get("receipt_id") != f"cr-{digest[:16]}":
        issues.append("receipt_id does not match its content")
    return issues


# ── the receipt store ────────────────────────────────────────────────────────

def receipts_dir(workspace) -> Path:
    return Path(workspace) / "memory" / ".tmp" / "compute-receipts"


def save_receipt(workspace, receipt: dict) -> Path:
    """Keep a receipt where postflight can find it by id. Content-addressed, so
    writing the same computation twice is one file."""
    directory = receipts_dir(workspace)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{receipt['receipt_id']}.json"
    if path.exists():
        # Asked again: the file's time is when it was last computed, which is
        # what `receipts_since` selects on.
        path.touch()
    else:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        tmp.replace(path)
    return path


def receipts_since(workspace, since) -> list[dict]:
    """Receipts computed at or after `since` (an ISO timestamp; naive is local).

    This is how a run finds the numbers its own model computed: a postflight
    passes the context's `generated_at`, and every receipt written during that
    turn becomes a source the prose may quote. Unparseable `since` selects the
    last 24 hours, which errs toward recognising a real receipt.
    """
    import time  # noqa: PLC0415
    from datetime import datetime  # noqa: PLC0415

    try:
        floor = datetime.fromisoformat(str(since).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        floor = time.time() - 24 * 3600
    out = []
    directory = receipts_dir(workspace)
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("cr-*.json")):
        try:
            # One second of slack: file times are coarser than the timestamp.
            if path.stat().st_mtime + 1 < floor:
                continue
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(receipt, dict) and receipt.get("kind") == "compute":
            out.append(receipt)
    return out


def load_receipt(workspace, receipt_id: str) -> dict | None:
    if not isinstance(receipt_id, str) or not receipt_id.startswith("cr-") \
            or not receipt_id[3:].isalnum():
        return None
    try:
        return json.loads((receipts_dir(workspace) / f"{receipt_id}.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
