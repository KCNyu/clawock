"""Reusable dependency-free utilities belong to the installable product."""

from pathlib import Path

from clawock import json_repair, safe_io
from clawock.market_data import integrity as bar_checks


ROOT = Path(__file__).resolve().parents[1]


def test_utility_implementations_are_in_the_product_package():
    modules = (bar_checks, json_repair, safe_io)
    assert {
        Path(module.__file__).relative_to(ROOT).as_posix() for module in modules
    } == {
        "src/clawock/market_data/integrity.py",
        "src/clawock/json_repair.py",
        "src/clawock/safe_io.py",
    }
    assert not any(
        (ROOT / "scripts" / "data" / f"{name}.py").exists()
        for name in ("bar_checks", "json_repair", "safe_io")
    )
