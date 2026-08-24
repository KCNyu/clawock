"""CodeQL's push gate lives in exactly one place and fails toward analysing.

#910 moved the gate out of the `analyze` job's steps and into its `if:`, so a
pure-data push stops three runners from starting at all instead of starting
them to discover there is nothing to do.  That is a cheap win with an expensive
failure mode: a gate whose input goes missing must not silently drop CodeQL.
The `if:` therefore has three independent escapes, and this test pins all of
them — plus the fact that nobody re-added a second gate inside the steps.
"""
import pathlib
import yaml

CI = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
WF = yaml.safe_load(CI.read_text(encoding="utf-8"))
JOBS = WF["jobs"]


def test_lint_publishes_the_classification_analyze_reads():
    outputs = JOBS["lint"].get("outputs") or {}
    assert "analysable" in outputs, (
        "lint is the workflow's scope job; it must publish `analysable`")
    assert "steps." in outputs["analysable"], (
        "the output must come from the classifier step, not a literal")
    step = next(s for s in JOBS["lint"]["steps"] if s.get("id") == "scope")
    assert "ops/ci/push_scope.py" in step["run"], (
        "the published classification must come from the shared classifier")


def test_analyze_is_gated_on_lint_and_fails_open():
    analyze = JOBS["analyze"]
    needs = analyze["needs"]
    assert needs == "lint" or "lint" in needs, "analyze must read lint's output"

    cond = " ".join(analyze["if"].split())
    # 1) a skipped/failed `needs` skips the dependent job unless always()
    assert "always()" in cond, (
        "without always() a failed lint would silently skip CodeQL")
    # 2) never gate a pull_request — those contexts are required checks
    assert "github.event_name != 'push'" in cond, (
        "PRs must always be analysed; their CodeQL contexts are required")
    # 3) classifier unavailable => analyse anyway
    assert "needs.lint.result != 'success'" in cond, (
        "a lint that did not succeed must fail toward analysing")
    # 4) the actual scope answer
    assert "needs.lint.outputs.analysable == 'true'" in cond


def test_the_gate_is_not_duplicated_inside_the_steps():
    """Two gates drift apart; that is how #750 happened. The job-level `if:` is
    the only one, so the CodeQL steps themselves must carry no condition."""
    for step in JOBS["analyze"]["steps"]:
        uses = step.get("uses", "")
        if "codeql-action" in uses:
            assert "if" not in step, (
                f"{uses} re-grew its own gate; the job-level if: owns this")
