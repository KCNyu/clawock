"""The product/instance rule has to keep describing the repository (#331).

A written boundary that nobody re-reads becomes wrong the first time a file is
added, and then it is worse than nothing: a reviewer applies a rule that no
longer matches the tree and files the new module wherever it is convenient —
which is `scripts/data/`, which is how that directory reached 87 files.

So this asserts the cheap, mechanical half: every module in `scripts/data/`
appears in the classification, and the classification names no module that does
not exist. The judgement half — whether a given call is right — stays with a
human, which is why the page marks its contested calls instead of hiding them.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "reference" / "product-vs-instance.md"


def _classified_names(text):
    """Module names the page mentions in backticks, restricted to real modules."""
    candidates = set(re.findall(r"`([a-z0-9_]+)`", text))
    return {n for n in candidates if (ROOT / "scripts" / "data" / f"{n}.py").exists()}


def test_every_data_module_is_classified():
    text = DOC.read_text()
    actual = {p.stem for p in (ROOT / "scripts" / "data").glob("*.py")}
    missing = sorted(actual - _classified_names(text))
    assert not missing, (
        f"{len(missing)} module(s) in scripts/data/ are not in "
        f"{DOC.relative_to(ROOT)}: {missing}. A new file needs a stated home, "
        "otherwise the default home is 'wherever', which is the problem #331 "
        "exists to end.")


def test_every_harness_module_is_classified():
    text = DOC.read_text()
    actual = {p.stem for p in (ROOT / "scripts" / "harness").glob("*.py")}
    named = set(re.findall(r"`([a-z0-9_]+)`", text))
    missing = sorted(actual - named)
    assert not missing, f"unclassified scripts/harness modules: {missing}"


def test_the_retired_backfill_stays_retired():
    """backfill_t0_history seeded t0 history once and had zero callers after."""
    assert not (ROOT / "scripts" / "legacy" / "backfill_t0_history.py").exists(), (
        "the one-off t0 history backfill is back; its job completed and nothing "
        "referenced it — if it is genuinely needed again, say why in "
        "docs/reference/product-vs-instance.md")
