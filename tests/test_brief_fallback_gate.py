"""The off-host brief fallback must fail closed.

brief-fallback.yml runs on a fresh GH-Action checkout and commits with its own
broad `git add … && commit && push`, which cannot see brief_postflight.maybe_commit's
`status == 'fail'` refusal. A failing/unvalidated brief was therefore published
anyway, right after postflight reported it FAILED. The fix is a cross-process
publish gate the workflow consults; these tests pin both halves.

Run: python3 -m pytest tests/test_brief_fallback_gate.py -q
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'harness'))
import brief_postflight


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
    yml = (ROOT / '.github' / 'workflows' / 'brief-fallback.yml').read_text()
    # The committer must gate on the publish decision, fail-closed.
    assert 'brief_postflight_status.json' in yml, 'commit step no longer reads the publish gate'
    assert 'publish_ok' in yml, 'commit step no longer checks publish_ok'
    # The postflight step must not swallow its own failure into a silent publish...
    invocations = [l for l in yml.splitlines()
                   if 'brief_postflight.py' in l and not l.strip().startswith('#')]
    assert invocations, 'postflight invocation not found'
    assert all('|| true' not in l for l in invocations), 'postflight failure is being swallowed again'
    # ...but a publishable warn (exit 1) must NOT fail the job; only fail (>=2)/crash does.
    assert '-lt 2' in yml, 'postflight step no longer tolerates a publishable warn (exit 1)'
