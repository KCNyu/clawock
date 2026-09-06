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


def _job(name):
    rest = TEXT.split(f"\n  {name}:", 1)[1]
    return rest.split("\n  analyze:", 1)[0].split("\n  portable-workflow:", 1)[0]


def test_smoke_data_fetch_does_no_work_for_a_docs_only_change():
    """A docs-only PR must not pay a pip install plus two live FX providers.

    Asserted on the steps rather than on the job's `needs:`. The gate used to be
    `if: needs.validate.outputs.code == 'true'` at job level, which bought this
    property by making the job wait for ALL of validate — 170s for a boolean a
    1s script produces (measured on run 34020103495). The lane is decided in the
    job now; what must not come back is the work happening on a docs-only PR.
    """
    job = _job("smoke-data-fetch")
    assert "python3 ops/ci/push_scope.py" in job, (
        "the job must decide its own lane rather than waiting for validate's")
    for step in ("clawock-python", "smoke_fx.py", "smoke_reddit.py"):
        head = job.split(step, 1)[0]
        assert "steps.changes.outputs.code == 'true'" in head.rsplit("- name:", 1)[-1], (
            f"{step} runs without the code-lane gate; a docs-only PR pays for it")


def test_nothing_waits_for_validate_just_to_read_its_lane():
    """The two lane-gated jobs run beside validate, not after it.

    `needs: validate` on a job that only reads `needs.validate.outputs.code` puts
    the whole test suite on its critical path for a value that is available in a
    second. Run 34020103495: validate 170s, portable-workflow 41s, wall 217s,
    with the 41s starting only when the 170s finished.
    """
    for name in ("smoke-data-fetch", "portable-workflow"):
        job = _job(name)
        assert "needs: validate" not in job, (
            f"{name} is serialised behind the whole test suite to read one boolean")
    # The one that genuinely consumes validate's artifact keeps its edge.
    assert "needs: validate" in _job("publish-coverage"), (
        "publish-coverage downloads coverage-report.json and must not outlive it")


def test_coverage_publish_chain_reads_the_lane_that_produces_the_artifact():
    """publish-coverage must not outlive the artifact it downloads.

    `examples/dsh/**` lights only the dsplugin lane (ops/ci/push_scope.py), so a
    dsh-only master push runs no pytest and produces no coverage-report.json.
    The consuming job used to start anyway and die hard in download-artifact on
    the missing file — four of the last eight red master runs were that false
    alarm (#957, runs 32760585564 / 32759484885 / 32680826301 / 32680290940).
    The upload side stays warn-only on purpose: gating a lane read on the
    starting event is the shape test_ci_trigger_paths.py bans after #750.
    """
    job = TEXT.split("\n  publish-coverage:", 1)[1].split("\n  smoke-data-fetch:", 1)[0]
    assert "needs.validate.outputs.code == 'true'" in job, (
        "publish-coverage must skip when the suite never measured anything")


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


def test_every_workflow_probing_argparse_goes_through_the_shared_script():
    """The probe list must be the registry, not two copies of it that age.

    `brief render` shipped in `harness.runner.PHASE_MODULES` and never made it
    into ci.yml's hand-written list, so a broken `render` parser was invisible
    to CI for the life of the step (#1312). Fixing that list left the second
    copy — weekly-health.yml — four phases behind instead (#1317). Both now run
    `ops/ci/argparse_probe.py`, which reads the registry, so the only thing
    these assertions have to hold is that no workflow grows a third list.
    """
    from workflow_contract_helpers import step_block

    probe = ROOT / "ops" / "ci" / "argparse_probe.py"
    assert probe.exists(), "the shared probe is gone; both workflows call it"

    for workflow, step in ((CI, "argparse-check harness CLIs"),
                           (WORKFLOWS / "weekly-health.yml",
                            "argparse contracts unchanged")):
        block = step_block(workflow, step)
        assert "ops/ci/argparse_probe.py" in block, (
            f"{workflow.name}'s `{step}` no longer runs the shared probe")
        assert "--help" not in block, (
            f"{workflow.name}'s `{step}` grew its own CLI list again; the list "
            "belongs in harness.runner.PHASE_MODULES, which the probe reads")


def test_the_shared_probe_reads_the_phase_registry():
    """The probe is only a fix while it derives its members from the registry.

    A probe that hardcodes the same seven phases is the bug with one more file
    in it, and nothing else in this suite would notice.
    """
    from clawock.harness.runner import PHASE_MODULES
    import argparse_probe as probe_module

    ran = []

    def fake_probe(command, timeout, env):
        ran.append(command)
        return True, ""

    original = probe_module.probe
    probe_module.probe = fake_probe
    try:
        assert probe_module.main([]) == 0
    finally:
        probe_module.probe = original

    assert set(ran) == {f"{w} {p}" for w, p in PHASE_MODULES}, (
        "the probe does not walk PHASE_MODULES; a new phase would land unprobed")
