"""The off-host fallback accepts warnings only with a verified publication receipt."""
import json
import shlex
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from clawock.harness import brief_postflight


WORKFLOW = ROOT / '.github' / 'workflows' / 'brief-fallback.yml'


def _workflow_step_run(name):
    """Return the actual `run: |` shell body for a named workflow step."""
    lines = WORKFLOW.read_text().splitlines()
    step_start = next(i for i, line in enumerate(lines)
                      if line.lstrip() == f'- name: {name}')
    step_indent = len(lines[step_start]) - len(lines[step_start].lstrip())
    step_end = next((i for i in range(step_start + 1, len(lines))
                     if lines[i].startswith(' ' * step_indent + '- ')), len(lines))
    run_start = next(i for i in range(step_start + 1, step_end)
                     if lines[i].strip() == 'run: |')
    run_indent = len(lines[run_start]) - len(lines[run_start].lstrip())
    body = '\n'.join(lines[run_start + 1:step_end])
    assert all(not line.strip() or len(line) - len(line.lstrip()) > run_indent
               for line in lines[run_start + 1:step_end]), f'{name} run block ended unexpectedly'
    return textwrap.dedent(body)


def test_publish_gate_releases_only_a_non_failing_brief(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_postflight, 'WS', tmp_path)
    gate = brief_postflight.write_publish_gate('fail', '2026-07-16')
    assert gate['publish_ok'] is False
    on_disk = json.loads((tmp_path / 'logs' / 'brief_postflight_status.json').read_text())
    assert on_disk['publish_ok'] is False and on_disk['status'] == 'fail'
    for ok_status in ('pass', 'warn'):
        assert brief_postflight.write_publish_gate(ok_status, '2026-07-16')['publish_ok'] is True


def test_postflight_writes_the_gate_before_it_can_raise():
    # The gate must be emitted straight after status is categorised, not after the
    # delivery/commit work that can throw — otherwise a crash leaves no file and the
    # workflow (fail-closed) simply never publishes, which is the safe direction.
    import inspect
    src = inspect.getsource(brief_postflight.main)
    gate_at = src.find('write_publish_gate(')
    commit_at = src.find('maybe_commit(')
    assert 0 <= gate_at < commit_at, 'publish gate is written after maybe_commit (or not at all)'


def test_fallback_checks_the_verified_archive_before_regenerating():
    check_run = _workflow_step_run("Check if openclaw already ran today's brief")
    fetch_at = check_run.index('fetch_data_plane.py --expect-brief-archive')
    skip_at = check_run.index('brief-archive/memory/${TODAY}-pre-open.md')
    assert fetch_at < skip_at
    assert 'git log' not in check_run


def test_fallback_requires_both_publication_receipts(tmp_path):
    (tmp_path / 'logs').mkdir()
    day = '2026-11-28'
    gate = tmp_path / 'logs' / 'brief_postflight_status.json'
    body = _workflow_step_run('Commit + push')
    result = {'date': day, 'commit_ok': True, 'data_plane_status': 'published'}
    approved = {'today': day, 'publish_ok': True}
    cases = [
        (1, result, approved, True),
        (2, result, approved, False),
        (1, {}, None, False),
        (0, result, {**approved, 'publish_ok': False}, False),
        (0, {**result, 'commit_ok': False}, approved, False),
        (0, {**result, 'data_plane_status': 'failed'}, approved, False),
        (0, {**result, 'date': '2026-11-27'}, approved, False),
    ]
    for code, emitted, status, ok in cases:
        if status is None:
            gate.unlink(missing_ok=True)
        else:
            gate.write_text(json.dumps(status))
        command = (
            'clawock() { printf "%s\\n" ' + shlex.quote(json.dumps(emitted))
            + f'; return {code}; }}\n'
            + body
        )
        completed = subprocess.run(
            ['bash', '-e', '-o', 'pipefail', '-c', command], cwd=tmp_path,
            env={'TODAY': day, 'RUNNER_TEMP': str(tmp_path)}, capture_output=True)
        assert (completed.returncode == 0) == ok, completed.stderr
