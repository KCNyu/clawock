"""A key with nothing in it still costs bytes, and the cap has none to spare.

Measured 2026-09-08 on the live payload: `decision_traces` was 36,720 bytes —
the single biggest block at 18% — and **13% of it (4,888 bytes) was keys whose
value was `null` / `''` / `[]`**: `thesis`, `invalidation`, `bull`, `bear`,
`emotion`, `emotionNote`, `realizedPnl` on most rows. Against 9,450 bytes of
headroom under the 200KB cap, half the remaining room was being spent saying
nothing.

This is the lossless trim, chosen over the lossy one on purpose: dropping the
row limit from 40 would have saved more and cost information kcn may want.

Controlled A/B on the same minute's data: only this block moved, −5,522 bytes.
(Measured naively across two builds it looked like −27,408 — the payload itself
swings up to 13,474 bytes run to run, #1399. The A/B is the number.)
"""
import re
from pathlib import Path

from clawock.publish import dashboard


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "site" / "assets" / "js" / "dashboard.render.js"


def _empties(value, path="$"):
    """Every path in `value` whose leaf carries no information."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if item is None or item == "" or item == [] or item == {}:
                found.append(f"{path}.{key}")
            else:
                found += _empties(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found += _empties(item, f"{path}[{index}]")
    return found


def test_an_empty_decoration_is_dropped_at_every_depth():
    row = {"ticker": "SPCH",
           "decision": {"rationale": "x", "bull": None, "invalidation": [],
                        "bear": "", "emotionNote": None},
           "t1": {"verdict": "涨"}}

    cleaned = dashboard._drop_decorative_empties(row)

    assert set(cleaned["decision"]) == {"rationale"}
    assert cleaned["t1"]["verdict"] == "涨"


def test_a_null_that_is_an_answer_is_kept():
    """THE line this change must not cross. `t1: null` says a fill has no T+1
    verdict — checked, none. `decision: null` says the fill had no paired
    decision at all, which is the most interesting row on the card.
    `sizeShares: null` says the plan's share count would not parse.

    Dropping those would make "we looked and there is none" identical to
    "nobody looked" — the exact defect this codebase spent 2026-09-07 removing
    from six other places (#1393/#1394/#1396/#1397/#1400/#1401). The first
    version of this change was a blanket strip and did cross the line; three
    existing `test_decision_traces` assertions caught it."""
    row = {"t1": None, "decision": None, "realizedPnl": None,
           "inner": {"sizeShares": None, "bull": None}}

    cleaned = dashboard._drop_decorative_empties(row)

    assert cleaned["t1"] is None
    assert cleaned["decision"] is None
    assert cleaned["realizedPnl"] is None
    assert cleaned["inner"]["sizeShares"] is None
    assert "bull" not in cleaned["inner"]


def test_zero_and_false_are_kept_even_on_a_droppable_key():
    """They are answers, not absences — and `0 == False` in Python, so a naive
    `if not value` emptiness test eats both. `note: 0` is contrived; the rule
    being exact is not."""
    cleaned = dashboard._drop_decorative_empties(
        {"shares": 0, "win": False, "note": 0, "bull": None})

    assert cleaned == {"shares": 0, "win": False, "note": 0}


def test_the_built_block_carries_no_empty_decoration(tmp_path):
    """The gate that keeps the win: a new empty decoration would re-spend it."""
    traces = dashboard.build_decision_traces(limit=40)

    leftover = [p for p in _empties(traces)
                if p.rsplit(".", 1)[-1] in dashboard.DECORATIVE_TRACE_KEYS]

    assert leftover == [], leftover[:8]


def test_traces_readers_do_not_depend_on_the_key_existing():
    """WHY the drop is safe, pinned so a future renderer edit cannot quietly
    break it.

    `undefined` behaves exactly as `null` under truthiness and under `??`, which
    is how every trace field is read today (`d.rationale || d.bull || ""`,
    `d.emotionNote ? … : ""`, `row.invalidation_price ?? "—"`). What would break
    is a strict `=== null` or an `in` test — neither exists, and this says so.
    """
    source = RENDERER.read_text()

    strict = re.findall(r"\w+\.(?:thesis|bull|bear|emotion|emotionNote|"
                        r"invalidation|realizedPnl)\s*[=!]==\s*null", source)
    membership = re.findall(r"['\"](?:thesis|bull|bear|emotion|emotionNote|"
                            r"invalidation|realizedPnl)['\"]\s+in\s+\w+", source)

    assert strict == [], strict
    assert membership == [], membership


def test_the_strip_is_scoped_to_this_block():
    """A blanket strip over the payload would be wrong: in a chart series `null`
    means "gap in the data", and removing it shifts every point after it. Only
    the trace builder calls this."""
    source = (ROOT / "src" / "clawock" / "publish" / "dashboard.py").read_text()
    # def + two recursive calls + exactly one caller. A second caller means some
    # other block is being stripped, and that block's readers were never checked.
    callers = [line for line in source.splitlines()
               if "_drop_decorative_empties(" in line
               and not line.strip().startswith("def ")
               and "item = _drop_decorative_empties(item)" not in line
               and "return [_drop_decorative_empties(item) for item in value]" not in line]

    assert callers == ["    return [_drop_decorative_empties(trace) for trace in traces[:limit]]"], callers


def test_the_droppable_set_is_named_not_inferred():
    """An allowlist, so adding a field is a decision someone makes on purpose
    rather than a byte saving that happens to them."""
    assert "t1" not in dashboard.DECORATIVE_TRACE_KEYS
    assert "decision" not in dashboard.DECORATIVE_TRACE_KEYS
    assert "sizeShares" not in dashboard.DECORATIVE_TRACE_KEYS
    assert "realizedPnl" not in dashboard.DECORATIVE_TRACE_KEYS
