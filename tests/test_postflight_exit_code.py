from __future__ import annotations

import ast
from pathlib import Path

from clawock.harness.validation import postflight_exit_code


ROOT = Path(__file__).resolve().parents[1]
POSTFLIGHTS = ROOT / "src" / "clawock" / "harness"


def test_shipped_warn_is_not_a_failed_turn():
    # An exec's non-zero exit files the whole cron turn as `error`; 2026-09-11's
    # brief was delivered, committed and published, then filed as
    # `ERR: Exec failed: clawock brief postflight` because warn exited 1.
    assert postflight_exit_code("pass") == 0
    assert postflight_exit_code("warn") == 0
    assert postflight_exit_code("fail") == 2


def test_every_postflight_exits_through_the_shared_rule():
    # The brief postflight exited on raw `status` while the other two used
    # `product`, so an advisory-only brief exited 1 where a report exited 0.
    found = []
    for path in sorted(POSTFLIGHTS.glob("*_postflight.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        main = next(
            (node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name == "main"),
            None,
        )
        assert main is not None, f"{path.name} has no main()"
        found.append(path.name)
        tail = main.body[-1]
        assert isinstance(tail, ast.Return), path.name
        call = tail.value
        assert isinstance(call, ast.Call), path.name
        assert isinstance(call.func, ast.Name), path.name
        assert call.func.id == "postflight_exit_code", path.name
        assert len(call.args) == 1, path.name
        assert isinstance(call.args[0], ast.Name), path.name
        assert call.args[0].id == "product", path.name

    assert set(found) >= {
        "brief_postflight.py",
        "intraday_postflight.py",
        "report_postflight.py",
    }, "the discovery gate itself stopped seeing the shipped postflights"
