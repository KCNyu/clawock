"""The failure that matters is a stale citation, not a missing one.

A claim pointing at a run card that no longer contains its number reads as
maximally credible and is wrong. Three tests: the mismatch case, the
non-existent-card case, and the real repository staying green.

Run: python3 -m pytest tests/test_claim_provenance.py -q
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from clawock import claim_provenance as cp


def _workspace(tmp_path, prose, metrics, run_id="fixture-20260802-abcdef12"):
    (tmp_path / "src" / "clawock").mkdir(parents=True)
    (tmp_path / "memory" / "backtests").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "src" / "clawock" / "compute_regime.py").write_text(prose)
    (tmp_path / "memory" / "backtests" / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "metrics": metrics}))
    return tmp_path


def _check(root):
    return cp.check(root=root,
                    cards_dir=root / "memory" / "backtests",
                    allowlist=root / "config" / "claim-allowlist.json",
                    scanned=("src/clawock/compute_regime.py",))


def test_a_claim_whose_card_says_something_else_fails(tmp_path):
    root = _workspace(
        tmp_path,
        prose='"""Evidence: run card fixture-20260802-abcdef12.\nmaxDD -55.5%\n"""\n',
        metrics={"regime": {"max_drawdown": -0.916}})

    problems = _check(root)

    assert problems and "no cited run card contains" in problems[0]


def test_the_same_claim_passes_when_the_card_agrees(tmp_path):
    root = _workspace(
        tmp_path,
        prose='"""Evidence: run card fixture-20260802-abcdef12.\nmaxDD -91.6%\n"""\n',
        metrics={"regime": {"max_drawdown": -0.916}})

    assert _check(root) == []


def test_citing_a_card_that_does_not_exist_fails(tmp_path):
    root = _workspace(
        tmp_path,
        prose='"""Evidence: run card fixture-20260802-99999999.\nmaxDD -91.6%\n"""\n',
        metrics={"regime": {"max_drawdown": -0.916}})

    problems = _check(root)

    assert any("does not exist" in problem for problem in problems)


def test_the_allowlist_exempts_a_figure_quoted_in_order_to_correct_it(
        tmp_path):
    """`compute_regime` quotes the superseded -95%/-44% framing precisely to
    retire it. Corrective prose must stay legal, and the mechanism has to be
    tested rather than assumed."""
    root = _workspace(
        tmp_path,
        prose='"""Evidence: run card fixture-20260802-abcdef12.\n'
              'the old framing said maxDD -44.0%, which this replaces\n"""\n',
        metrics={"regime": {"max_drawdown": -0.916}})
    (root / "config" / "claim-allowlist.json").write_text(json.dumps({
        "src/clawock/compute_regime.py": {"values": [-0.44], "reason": "retired"}
    }))

    assert _check(root) == []


def test_the_repository_itself_is_green_and_the_scan_is_not_vacuous():
    """A scanner that finds nothing passes trivially; assert it sees the real
    claims in compute_regime.py as well as that they resolve."""
    text = (ROOT / "src" / "clawock" / "compute_regime.py").read_text()
    claims = cp.scan_text(text, source="compute_regime.py")

    assert len(claims) >= 5, "the scanner stopped seeing real claims"
    assert cp.check() == []
