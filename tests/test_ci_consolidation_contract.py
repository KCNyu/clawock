"""The consolidated CI workflow must keep every required check context.

The branch ruleset pins six check contexts by exact name: ``lint``,
``validate``, ``Analyze (actions)``, ``Analyze (javascript-typescript)``,
``Analyze (python)`` and ``CodeQL``. A context comes from the job name, not
from the file, so #884 merged three workflow files into ``ci.yml`` without
touching the ruleset — but that also means nothing structural stops a future
edit from quietly dropping one context and leaving every PR stuck on a
required check that never reports again. These assertions are that stop.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
TEXT = CI.read_text(encoding="utf-8")

REQUIRED_LANGUAGES = ("actions", "javascript-typescript", "python")


def test_the_three_old_files_are_gone():
    for name in ("actionlint.yml", "codeql.yml", "harness-regression.yml"):
        assert not (WORKFLOWS / name).exists(), (
            f"{name} is back; its lanes live in ci.yml since #884")


def test_both_gate_contexts_are_still_top_level_jobs():
    assert re.search(r"^  lint:$", TEXT, re.MULTILINE), "required context `lint`"
    assert re.search(r"^  validate:$", TEXT, re.MULTILINE), "required context `validate`"


def test_the_analyze_matrix_covers_every_required_language():
    block = TEXT.split("\n  analyze:", 1)[1].split("\n    steps:", 1)[0]
    for language in REQUIRED_LANGUAGES:
        assert f"language: {language}" in block, f"missing Analyze ({language})"
    assert "name: Analyze (${{ matrix.language }})" in block, (
        "the job display name is what the ruleset's `Analyze (...)` contexts "
        "are read from")


def test_the_codeql_action_is_actually_wired():
    assert "github/codeql-action/init@" in TEXT
    assert "github/codeql-action/analyze@" in TEXT


def test_the_weekly_full_matrix_backstop_survived_the_merge():
    """Saturday 03:41 UTC ran CodeQL when it lived alone; in ci.yml the same
    slot runs the whole gate, which is the point: a scheduled event has no
    diffable range, so every lane answers 'everything changed'."""
    assert "cron: '41 3 * * 6'" in TEXT


def test_prs_are_never_cancelled_and_master_never_is():
    assert (
        "group: ${{ github.workflow }}-${{ github.ref }}" in TEXT
        and "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in TEXT
    ), ("superseded PR runs are worthless and get cancelled; master runs are "
        "part of the ledger and never are")


def test_smoke_data_fetch_only_boots_for_code_changes():
    """A docs-only PR used to pay a full pip install plus two live FX providers."""
    job = TEXT.split("\n  smoke-data-fetch:", 1)[1].split("\n  analyze:", 1)[0]
    assert "needs: validate" in job
    assert "if: needs.validate.outputs.code == 'true'" in job


def test_validate_publishes_its_detector_answer_as_a_job_output():
    job = TEXT.split("\n  validate:", 1)[1].split("\n  publish-coverage:", 1)[0]
    assert "code: ${{ steps.changes.outputs.code }}" in job


def test_plugin_sources_trigger_ci_on_master_pushes():
    """examples/dsh/** was watched by the detector but missing from the push
    trigger, so a plugin-only master push started nothing at all."""
    from workflow_contract_helpers import push_paths

    assert "examples/dsh/**" in push_paths(CI)


def test_no_inline_lane_classification_left_in_the_workflow():
    """The adversarial pass on #884: three inline copies of diff-classification
    bash were how #750-style drift happened. All gates must read
    ops/ci/push_scope.py, and the smoke probe must be a script, not a
    python -c one-liner."""
    from workflow_contract_helpers import step_block

    # Two invocations, not three: #910 deleted CodeQL's own copy and made the
    # `analyze` job read `lint`'s published classification instead of starting
    # three runners to recompute it. What must stay true is the property this
    # test was written for — every gate reads the one classifier, and none of
    # them grows its own diff-parsing bash.
    assert TEXT.count("ops/ci/push_scope.py") >= 2, (
        "the lint/scope job and the detector both route through one classifier")
    assert "ops/ci/smoke_fx.py" in TEXT, (
        "smoke-data-fetch must run the script, not an inline python -c")

    for step in ("Classify this event",
                 "Detect code changes",
                 "FX fallback chain"):
        block = step_block(CI, step)
        assert "python3 -c" not in block and 'case "$f"' not in block, (
            f"{step} grew inline logic; it belongs in ops/ci/push_scope.py "
            "where tests can drive it")
