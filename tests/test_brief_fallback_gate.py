"""The off-host brief fallback must fail closed.

brief-fallback.yml runs on a fresh GH-Action checkout and commits with its own
broad `git add … && commit && push`, which cannot see brief_postflight.maybe_commit's
`status == 'fail'` refusal. A failing/unvalidated brief was therefore published
anyway, right after postflight reported it FAILED. The fix is a cross-process
publish gate the workflow consults; these tests pin both halves.

Run: python3 -m pytest tests/test_brief_fallback_gate.py -q
"""
import json
import re
import sys
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


def test_fallback_workflow_consults_the_gate_and_does_not_swallow_failure():
    commit_run = _workflow_step_run('Commit + push')
    # The committer must gate on the publish decision, fail-closed.
    assert 'brief_postflight_status.json' in commit_run, 'commit step no longer reads the publish gate'
    assert 'publish_ok' in commit_run, 'commit step no longer checks publish_ok'
    # Exit 1 is deliberate: exit 0 would publish nothing but leave a crash-before-gate
    # indistinguishable from a legitimate warning in the Actions result.
    missing_gate_guard = re.search(
        r'if\s+\[\s*!\s+-f\s+["\']?logs/brief_postflight_status\.json["\']?\s*\]\s*;\s*then'
        r'(?P<body>.*?)\bfi\b', commit_run, re.DOTALL)
    assert missing_gate_guard, 'commit step does not guard a missing postflight gate file'
    assert re.search(r'\bexit\s+1\b', missing_gate_guard.group('body')), (
        'missing postflight gate file does not fail the job')
    # The postflight step must not swallow its own failure into a silent publish...
    postflight_run = _workflow_step_run('Postflight validation')
    invocations = [l for l in postflight_run.splitlines()
                   if 'clawock brief postflight' in l and not l.strip().startswith('#')]
    assert invocations, 'postflight invocation not found'
    assert all('|| true' not in l for l in invocations), 'postflight failure is being swallowed again'
    # ...but a publishable warn (exit 1) must NOT fail the job; only fail (>=2)/crash does.
    assert '-lt 2' in postflight_run, 'postflight step no longer tolerates a publishable warn (exit 1)'


def test_fallback_pushes_any_commit_ahead_of_origin_not_only_a_dirty_index():
    """2026-07 audit finding #4: postflight's maybe_commit already commits on the
    ephemeral runner and its push can fail while reporting success; gating the
    workflow push on a dirty index then discards that commit (green, unpublished).
    The commit step must push whenever HEAD is ahead of origin/master."""
    commit_run = _workflow_step_run('Commit + push')
    assert 'rev-list FETCH_HEAD..HEAD' in commit_run, (
        'commit step does not push a commit that is ahead of the remote (maybe_commit '
        'push-failure would be discarded)')
    assert 'safe_push.sh' in commit_run, 'commit step no longer pushes via safe_push'
