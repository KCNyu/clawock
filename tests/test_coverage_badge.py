"""Contracts for the published coverage badge and the floors behind it.

Two halves have to stay honest here: the generator must refuse to publish a
number it did not really measure, and the workflow must run the floor gate on
every PR rather than only on the master push that writes the badge.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from workflow_contract_helpers import (
    assert_validator_step, step_block, step_run, steps, strip_hash_comments)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))

import coverage_badge  # noqa: E402
import validate_sidecars  # noqa: E402

WORKFLOW = ROOT / '.github' / 'workflows' / 'harness-regression.yml'
BADGE_PATH = 'assets/data/coverage.json'


def _file_entry(statements, covered):
    return {'summary': {'num_statements': statements, 'covered_lines': covered}}


def _report(*, core_pct=90.0, filler_statements=14000, filler_pct=50.0):
    """A synthetic coverage.py report: every core module plus one filler file.

    Core modules each get the same size, so the group percentage is exactly
    `core_pct` and a test can move one knob at a time.
    """
    per_core = 200
    files = {
        module: _file_entry(per_core, round(per_core * core_pct / 100))
        for module in coverage_badge.CORE_MODULES
    }
    files['src/clawock/fetch_us_stocks.py'] = _file_entry(
        filler_statements, round(filler_statements * filler_pct / 100))
    statements = sum(f['summary']['num_statements'] for f in files.values())
    covered = sum(f['summary']['covered_lines'] for f in files.values())
    return {
        'files': files,
        'totals': {'num_statements': statements, 'covered_lines': covered},
    }


def _write_report(tmp_path, report):
    path = tmp_path / 'coverage-report.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    return path


def _run(tmp_path, report, *extra):
    out = tmp_path / 'coverage.json'
    argv = ['--report', str(_write_report(tmp_path, report)), '--out', str(out), *extra]
    return coverage_badge.main(argv), out


# --- the number on the badge -------------------------------------------------

def test_badge_reports_the_measured_total(tmp_path):
    code, out = _run(tmp_path, _report(core_pct=90.0, filler_pct=50.0))
    assert code == 0
    payload = json.loads(out.read_text())
    report = _report(core_pct=90.0, filler_pct=50.0)
    expected = round(
        100 * report['totals']['covered_lines'] / report['totals']['num_statements'])
    assert payload['message'] == f'{expected}%'
    assert payload['label'] == coverage_badge.BADGE_LABEL


def test_generated_badge_passes_the_publish_validator(tmp_path):
    """Generator and validator must not drift: what one writes, the other accepts."""
    _, out = _run(tmp_path, _report())
    validate_sidecars.validate_coverage_badge(out)


def test_badge_payload_is_strict_shields_schema(tmp_path):
    _, out = _run(tmp_path, _report())
    assert set(json.loads(out.read_text())) == {
        'schemaVersion', 'label', 'message', 'color'}


# --- the floors --------------------------------------------------------------

def test_total_below_floor_fails_and_writes_nothing(tmp_path):
    # Core stays healthy; only the aggregate falls through the floor.
    code, out = _run(tmp_path, _report(core_pct=90.0, filler_pct=20.0))
    assert code == 1
    assert not out.exists(), 'a failing run must not publish a badge'


def test_core_below_floor_fails_even_when_the_total_passes(tmp_path):
    # The whole point of the second floor: a well-covered fetch layer must not be
    # able to hide a regression in the modules that settle money.
    report = _report(core_pct=40.0, filler_pct=60.0)
    covered, statements, total_pct = coverage_badge.total_summary(report)
    assert total_pct >= coverage_badge.DEFAULT_MIN_TOTAL, 'fixture no longer isolates core'
    code, out = _run(tmp_path, report)
    assert code == 1
    assert not out.exists()


def test_check_only_enforces_floors_without_writing(tmp_path):
    code, out = _run(tmp_path, _report(), '--check-only')
    assert code == 0
    assert not out.exists()


def test_floors_are_not_silently_lowered():
    # A PR that fails the gate must fix the tests, not the floor. Pin the values so
    # lowering one is a visible, reviewed edit to this file.
    assert coverage_badge.DEFAULT_MIN_TOTAL == 52.0
    assert coverage_badge.DEFAULT_MIN_CORE == 75.0


# --- reports that must not be trusted ----------------------------------------

def test_missing_core_module_is_an_error_not_a_skip(tmp_path):
    report = _report()
    dropped = coverage_badge.CORE_MODULES[0]
    del report['files'][dropped]
    with pytest.raises(SystemExit) as excinfo:
        _run(tmp_path, report)
    assert dropped in str(excinfo.value)


def test_undersized_report_is_rejected(tmp_path):
    # A mis-scoped --cov measures a handful of statements and can score 100%.
    report = _report(filler_statements=50, filler_pct=100.0)
    with pytest.raises(SystemExit) as excinfo:
        _run(tmp_path, report)
    assert 'did not cover scripts/' in str(excinfo.value)


@pytest.mark.parametrize('content', ['', 'not json', '{}', '{"files": {}, "totals": {}}'])
def test_unusable_report_is_rejected(tmp_path, content):
    path = tmp_path / 'coverage-report.json'
    path.write_text(content, encoding='utf-8')
    with pytest.raises(SystemExit):
        coverage_badge.main(['--report', str(path), '--out', str(tmp_path / 'b.json')])


def test_absent_report_is_rejected(tmp_path):
    with pytest.raises(SystemExit):
        coverage_badge.main(['--report', str(tmp_path / 'nope.json'), '--check-only'])


def test_core_modules_all_exist_on_disk():
    missing = [m for m in coverage_badge.CORE_MODULES if not (ROOT / m).is_file()]
    assert not missing, f'CORE_MODULES lists files that no longer exist: {missing}'


# --- the validator that guards the published file ----------------------------

@pytest.mark.parametrize('payload', [
    {'schemaVersion': 1, 'label': 'COVERAGE', 'message': '54%', 'color': '738391',
     'extra': 'x'},
    {'schemaVersion': 2, 'label': 'COVERAGE', 'message': '54%', 'color': '738391'},
    {'schemaVersion': 1, 'label': 'COVERAGE', 'message': 'unknown', 'color': '738391'},
    {'schemaVersion': 1, 'label': 'COVERAGE', 'message': '0%', 'color': '738391'},
    {'schemaVersion': 1, 'label': 'COVERAGE', 'message': '100%', 'color': '738391'},
    {'schemaVersion': 1, 'label': '', 'message': '54%', 'color': '738391'},
])
def test_validator_rejects_unrenderable_badges(tmp_path, payload):
    path = tmp_path / 'coverage.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(AssertionError):
        validate_sidecars.validate_coverage_badge(path)


def test_validator_rejects_missing_and_empty_file(tmp_path):
    with pytest.raises(AssertionError):
        validate_sidecars.validate_coverage_badge(tmp_path / 'absent.json')
    empty = tmp_path / 'coverage.json'
    empty.write_text('   ', encoding='utf-8')
    with pytest.raises(AssertionError):
        validate_sidecars.validate_coverage_badge(empty)


# --- workflow contract -------------------------------------------------------

def _names():
    return [name for _, name in steps(WORKFLOW)]


def test_pr_run_measures_coverage_and_gates_on_it():
    names = _names()
    assert names.index('Unit tests — money-integrity derivations') < names.index('Coverage floors')

    test_run = step_run(WORKFLOW, 'Unit tests — money-integrity derivations')
    assert '--cov=scripts' in test_run
    assert '--cov-report=json:coverage-report.json' in test_run

    floors = step_block(WORKFLOW, 'Coverage floors')
    assert 'continue-on-error' not in floors
    assert step_run(WORKFLOW, 'Coverage floors') == (
        'python3 scripts/data/coverage_badge.py --report coverage-report.json --check-only')


def test_the_coverage_plugin_is_installed_where_it_is_used():
    # Without pytest-cov the --cov flags are an unknown-argument error, not a
    # silent skip. The install line no longer names packages — dependencies moved
    # to pyproject.toml so they stop drifting across nine workflow files — so the
    # guarantee is checked at the new source of truth instead.
    import tomllib

    installs = [line for line in strip_hash_comments(WORKFLOW.read_text()).splitlines()
                if 'pip install' in line and '[test]' in line]
    assert len(installs) == 1, 'the suite must install the test extra exactly once'

    extras = tomllib.load(open(ROOT / 'pyproject.toml', 'rb'))[
        'project']['optional-dependencies']
    assert any(dep.startswith('pytest-cov') for dep in extras['test'])


def _publish_job():
    text = WORKFLOW.read_text()
    return text.split('  publish-coverage:', 1)[1].split('\n  smoke-data-fetch:', 1)[0]


def test_publish_job_is_master_push_only_and_needs_validate():
    job = _publish_job()
    assert 'needs: validate' in job
    assert ("if: github.event_name == 'push' && github.ref == 'refs/heads/master'") in job
    assert 'group: data-write' in job, 'publish must serialize with the other writers'


def test_the_suite_is_measured_once_and_the_result_reused():
    # The badge must be the number `validate` gated on. Re-running pytest in the
    # publish job would both double the CI cost and let the published percentage
    # drift from the one that passed the floor.
    job = strip_hash_comments(_publish_job())  # comments may name pytest; steps may not
    assert 'pytest' not in job, 'publish-coverage must not re-run the suite'
    assert 'pip install' not in job
    assert 'actions/download-artifact' in job

    upload = step_block(WORKFLOW, 'Upload coverage report')
    assert 'name: coverage-report' in upload
    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/master'" in upload
    assert 'name: coverage-report' in job, 'publish downloads a differently named artifact'


def test_publish_job_validates_then_commits_one_exact_path():
    names = _names()
    assert (names.index('Coverage floors') < names.index('Upload coverage report')
            < names.index('Coverage floors and badge payload')
            < names.index('Validate coverage badge')
            < names.index('Commit'))

    badge_step = step_block(WORKFLOW, 'Coverage floors and badge payload')
    assert 'continue-on-error' not in badge_step
    assert f'--out {BADGE_PATH}' in step_run(WORKFLOW, 'Coverage floors and badge payload')

    assert_validator_step(WORKFLOW, 'Validate coverage badge', 'coverage')

    commit_run = step_run(WORKFLOW, 'Commit')
    publish = [line.strip() for line in commit_run.splitlines()
               if line.strip().startswith('bash scripts/data/gha_commit_push.sh')]
    assert len(publish) == 1
    assert publish[0].endswith(f' {BADGE_PATH}')
    assert 'assets/' not in publish[0].removesuffix(BADGE_PATH), 'commit more than the badge'


def test_publishing_the_badge_cannot_retrigger_the_workflow():
    # The push trigger lists paths one by one; if the badge were ever added there,
    # every publish would start another run that publishes again.
    trigger = WORKFLOW.read_text().split('on:', 1)[1].split('permissions:', 1)[0]
    assert BADGE_PATH not in trigger


def test_readmes_render_the_badge_from_the_published_file():
    # Both languages, and via the endpoint URL — never a hard-coded percentage,
    # which would be stale the next time the suite changes.
    for name in ('README.md', 'README.zh.md'):
        text = (ROOT / name).read_text(encoding='utf-8')
        assert 'img.shields.io/endpoint' in text, f'{name} has no endpoint badge'
        assert 'coverage.json' in text, f'{name} does not point at the badge payload'
