"""The failure that matters is a stale citation, not a missing one.

A claim pointing at a run card that no longer contains its number reads as
maximally credible and is wrong. Three tests: the mismatch case, the
non-existent-card case, and the real repository staying green.

Run: python3 -m pytest tests/test_claim_provenance.py -q
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from clawock.evidence import claim_provenance as cp


def _workspace(tmp_path, prose, metrics, run_id="fixture-20260802-abcdef12"):
    (tmp_path / "src" / "clawock" / "decision").mkdir(parents=True)
    (tmp_path / "memory" / "backtests").mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "src" / "clawock" / "decision" / "regime.py").write_text(prose)
    (tmp_path / "memory" / "backtests" / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "metrics": metrics}))
    return tmp_path


def _check(root):
    return cp.check(root=root,
                    cards_dir=root / "memory" / "backtests",
                    allowlist=root / "config" / "claim-allowlist.json",
                    scanned=("src/clawock/decision/regime.py",))


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


def test_p_value_requires_a_p_value_metric_not_a_nearby_drawdown(tmp_path):
    prose = '"""Evidence: run card fixture-20260802-abcdef12.\np = 0.92 for drawdown\n"""\n'
    root = _workspace(tmp_path, prose,
                      {"regime": {"max_drawdown": -0.916061,
                                  "vol_cap": 0.4}})
    assert _check(root)
    card = root / "memory" / "backtests" / "fixture-20260802-abcdef12.json"
    card.write_text(json.dumps({"run_id": "fixture-20260802-abcdef12",
                                "metrics": {"permutation": {"p_value_drawdown": 0.92454}}}))
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
        "src/clawock/decision/regime.py": {"values": [-0.44], "reason": "retired"}
    }))

    assert _check(root) == []


def test_a_p_value_line_with_no_other_quantity_word_is_checked(tmp_path):
    """#2075: `p = 0.04` (space after `=`) never matched QUANTITY, so a line
    whose only claim is a p-value was never compared with its card."""
    card = {"permutation": {"p_value_drawdown": 0.92454}}
    made_up = '"""Evidence: run card fixture-20260802-abcdef12.\np = 0.04 is a failure to reject.\n"""\n'
    assert _check(_workspace(tmp_path / "a", made_up, card))
    honest = made_up.replace("0.04", "0.92")
    assert _check(_workspace(tmp_path / "b", honest, card)) == []
    # A parameter such as `vol_cap=0.50` next to a quantity word is not a p-value.
    param = '"""Evidence: run card fixture-20260802-abcdef12.\np = 0.92; vol_cap=0.50\n"""\n'
    assert _check(_workspace(tmp_path / "c", param, card)) == []


def test_a_card_that_stores_percent_units_under_pct_keys_still_backs_its_claim(tmp_path):
    # #2185: add-side cards write `max_drawdown_pct_of_book: -14.93`, which a
    # claim read as -0.1493 never matched, so docs citing them could not be gated.
    prose = '"""Evidence: run card fixture-20260802-abcdef12.\ndrawdown -14.93% of book\n"""\n'
    root = _workspace(tmp_path, prose,
                      {"left": {"out_of_sample": {"max_drawdown_pct_of_book": -14.93}}})
    assert _check(root) == []

    card = root / "memory" / "backtests" / "fixture-20260802-abcdef12.json"
    card.write_text(json.dumps({"run_id": "fixture-20260802-abcdef12", "metrics": {
        "left": {"out_of_sample": {"max_drawdown_pct_of_book": -9.2}}}}))
    assert _check(root) and "no cited run card contains" in _check(root)[0]


def test_the_harness_doc_is_a_claim_surface():
    # #2185: the left-side table cited a card that was never committed, on the
    # one surface the gate did not read.
    assert "docs/architecture/harness.md" in cp.load_surfaces(
        ROOT / "config" / "claim-provenance.json")
    # Being listed is not being read: on #2185 one number of the table's
    # drawdown row entered judgement (#2193). The row's four members and the
    # -14.93% below it must all be claims.
    claims = cp.scan_text((ROOT / "docs/architecture/harness.md").read_text(),
                          source="harness.md")
    assert len(claims) >= 5


def test_every_member_of_a_series_is_a_claim_not_only_the_one_with_the_unit(tmp_path):
    prose = ('"""Evidence: run card fixture-20260802-abcdef12.\n'
             'drawdown −1.79 / −2.47 / −5.45%\n"""\n')
    card = {"a": {"max_drawdown_pct_of_book": -1.79},
            "b": {"max_drawdown_pct_of_book": -5.45}}
    problems = _check(_workspace(tmp_path, prose, card))
    assert len(problems) == 1 and "-0.0247" in problems[0]


def test_a_percentage_matches_only_the_quantity_its_line_names(tmp_path):
    # The percent-side twin of #1960: a dense card held some number within
    # tolerance of 98% of all possible claims because every leaf was eligible.
    prose = '"""Evidence: run card fixture-20260802-abcdef12.\ndrawdown -3.30%\n"""\n'
    card = {"left": {"return_per_unit_deployed_pct": -3.3,
                     "max_drawdown_pct_of_book": -4.1}}
    assert _check(_workspace(tmp_path, prose, card))
    card["left"]["max_drawdown_pct_of_book"] = -3.3
    assert _check(_workspace(tmp_path / "b", prose, card)) == []


def test_tolerance_follows_the_precision_the_claim_is_printed_at(tmp_path):
    card = {"regime": {"max_drawdown": -0.955}}
    coarse = '"""Evidence: run card fixture-20260802-abcdef12.\nmaxDD -95%\n"""\n'
    assert _check(_workspace(tmp_path, coarse, card)) == []
    # -95.0% claims one decimal: -95.5% does not round to it.
    fine = '"""Evidence: run card fixture-20260802-abcdef12.\nmaxDD -95.0%\n"""\n'
    assert _check(_workspace(tmp_path / "b", fine, card))


def test_no_file_with_a_backtest_shaped_number_sits_outside_the_gate():
    """The surface list is hand-kept, so a file left off it was simply never read
    (#2185 the harness doc, #2556 the left-side module). Every tracked source,
    doc or skill the scanner matches is either a surface or a listed non-claim."""
    config = json.loads((ROOT / "config" / "claim-provenance.json").read_text())
    surfaces = set(cp.load_surfaces(ROOT / "config" / "claim-provenance.json"))
    reasons = {path: reason for path, reason in config["not_backtest_claims"].items()
               if not path.startswith("_")}
    assert all(isinstance(reason, str) and len(reason) > 20 for reason in reasons.values())
    assert not surfaces & set(reasons), "a surface is checked; it needs no exemption"

    matched = set()
    for pattern in ("src/**/*.py", "docs/**/*.md", "skills/**/*.md", "*.md"):
        for path in ROOT.glob(pattern):
            rel = path.relative_to(ROOT).as_posix()
            if cp.scan_text(path.read_text(encoding="utf-8"), source=rel):
                matched.add(rel)
    unowned = sorted(matched - surfaces - set(reasons))
    assert unowned == [], (
        f"{unowned} carry a backtest-shaped number: add the file to `surfaces` (and cite its "
        "run card) or to `not_backtest_claims` with the reason it is not one")
    assert sorted(set(reasons) - matched) == [], "an exemption for a file the scanner no longer matches"
