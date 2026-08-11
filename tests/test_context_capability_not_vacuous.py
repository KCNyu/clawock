"""The context-capability gate must not pass by looking at nothing.

#380 exists so that losing agent context becomes a visible audit failure rather
than a silent capability loss. `check_context_capability` reads the realized
`systemPromptReport` of the newest session per profile — which works only for as
long as the runtime keeps writing those reports.

It used to answer "no prompt report recorded yet" with OK. That sentence covers
two very different worlds: a machine that has never run anything, and a machine
whose runtime stopped recording the very thing this gate reads. In the second
one every later run is unverified behind a green check — the failure family of
#452, #453 and #460, applied to the gate that guards agent capability itself.
"""
import json

import pytest


class _Report:
    def __init__(self):
        self.rows = []

    def add(self, name, level, detail=''):
        self.rows.append((name, level, detail))

    @property
    def last(self):
        return self.rows[-1]


def _run(tmp_path, monkeypatch, sessions):
    import ops.system_check as sc

    store = tmp_path / 'sessions.json'
    store.write_text(json.dumps(sessions))

    class _Paths:
        sessions_dir = tmp_path

    monkeypatch.setattr(sc, '_OPENCLAW_PATHS', _Paths)
    report = _Report()
    sc.check_context_capability(report)
    return sc, report


def _session(with_report=True, stamp=1786370000000, profile='cron'):
    entry = {'updatedAt': stamp}
    if with_report:
        entry['systemPromptReport'] = {'files': [], 'skills': 0, 'tools': 0}
    return entry


def test_sessions_without_any_prompt_report_are_a_warning(tmp_path, monkeypatch):
    """The regression this test exists for: the runtime stops recording, and the
    gate keeps saying OK forever."""
    sc, report = _run(tmp_path, monkeypatch, {
        'agent:main:cron:abc': _session(with_report=False),
        'agent:main:main': _session(with_report=False),
    })
    name, level, detail = report.last
    assert level == sc.WARNING, report.rows
    assert 'stopped recording' in detail


def test_a_machine_with_no_sessions_is_not_a_warning(tmp_path, monkeypatch):
    """A fresh or foreign workspace has nothing to say, and warning there would
    train everyone to ignore this code."""
    sc, report = _run(tmp_path, monkeypatch, {})
    _name, level, _detail = report.last
    assert level == sc.OK


def test_one_profile_going_silent_is_still_caught(tmp_path, monkeypatch):
    """Cron keeps reporting, interactive stops. A per-profile check is the point:
    the healthy half must not cover for the silent half."""
    sc, report = _run(tmp_path, monkeypatch, {
        'agent:main:cron:abc': _session(with_report=True),
        'agent:main:main': _session(with_report=False),
    })
    name, level, detail = report.last
    assert level == sc.WARNING, report.rows
    assert 'interactive' in detail
    assert 'isolated-cron' not in detail


def test_a_missing_store_still_skips_quietly(tmp_path, monkeypatch):
    """Foreign machines have no OpenClaw at all; that is not a finding."""
    import ops.system_check as sc

    class _Paths:
        sessions_dir = tmp_path / 'nope'

    monkeypatch.setattr(sc, '_OPENCLAW_PATHS', _Paths)
    report = _Report()
    sc.check_context_capability(report)
    _name, level, _detail = report.last
    assert level == sc.OK


def test_healthy_reports_still_pass(tmp_path, monkeypatch):
    """And the gate must not start firing on the live shape it sees every day."""
    import ops.system_check as sc

    monkeypatch.setattr(
        'clawock.context.assembly.verify_prompt_report',
        lambda report, profile: {'checks': {'files': True},
                                 'observed': {'files': ['a'], 'skills': 29, 'tools': 34}})
    sc_mod, report = _run(tmp_path, monkeypatch, {
        'agent:main:cron:abc': _session(with_report=True),
        'agent:main:main': _session(with_report=True),
    })
    _name, level, _detail = report.last
    assert level == sc_mod.OK, report.rows


def test_the_live_machine_is_actually_being_checked():
    """The claim that matters is about this box, not about fixtures: both
    profiles must currently carry a prompt report. If this fails, the gate above
    is warning and someone needs to find out why the runtime stopped."""
    from pathlib import Path

    store = Path('/root/.openclaw/agents/main/sessions/sessions.json')
    try:
        sessions = json.loads(store.read_text())
    except OSError:
        # Not a soft skip for convenience: a CI runner has no OpenClaw at all,
        # and `Path.exists()` is not the guard it looks like here — the runner
        # can see the directory and be refused the file, which is how this same
        # path once turned a green local suite into a red `validate` for the
        # watchdog tests. The assertion below is about THIS box, so anywhere it
        # cannot read the store there is nothing to assert.
        pytest.skip('no readable runtime session store on this machine')
    profiles = {}
    for key, entry in sessions.items():
        if not isinstance(entry, dict):
            continue
        profile = 'isolated-cron' if ':cron:' in key else 'interactive'
        profiles.setdefault(profile, False)
        if isinstance(entry.get('systemPromptReport'), dict):
            profiles[profile] = True
    assert profiles, 'no sessions at all — this assertion must not pass vacuously'
    assert all(profiles.values()), f'a profile stopped recording reports: {profiles}'


def test_an_enabled_job_with_no_report_is_named(monkeypatch):
    """#473: nine healthy cron reports averaged away a tenth enabled job that
    produced none, so the gate read OK while a live job was unverifiable."""
    import ops.system_check as sc

    monkeypatch.setattr(
        'clawock.providers.openclaw.cron_cli_json',
        lambda argv: {'jobs': [{'id': 'a', 'name': 'Healthy', 'enabled': True},
                               {'id': 'b', 'name': 'Dreaming', 'enabled': True}]})
    missing = sc._cron_jobs_without_prompt_report({
        'agent:main:cron:a:run:1': {'systemPromptReport': {}},
    })
    assert missing == ['Dreaming']


def test_a_provider_failed_run_is_not_mislabeled_as_capability_loss(monkeypatch):
    """#490: a response-header timeout replaces the job session with an entry
    that has no report. The scheduler already says the run failed; blaming
    context assembly as well makes the capability warning cry wolf."""
    import ops.system_check as sc

    monkeypatch.setattr(
        'clawock.providers.openclaw.cron_cli_json',
        lambda argv: {'jobs': [{
            'id': 'a', 'name': 'Provider timeout', 'enabled': True,
            'state': {'lastStatus': 'error'},
        }]})
    assert sc._cron_jobs_without_prompt_report({
        'agent:main:cron:a': {'updatedAt': 20},
    }) == []


def test_a_successful_job_without_a_report_is_still_named(monkeypatch):
    """A successful run had a chance to assemble context. No report after that
    remains the capability gap this gate exists to expose."""
    import ops.system_check as sc

    monkeypatch.setattr(
        'clawock.providers.openclaw.cron_cli_json',
        lambda argv: {'jobs': [{
            'id': 'a', 'name': 'Dreaming', 'enabled': True,
            'state': {'lastStatus': 'ok'},
        }]})
    assert sc._cron_jobs_without_prompt_report({
        'agent:main:cron:a': {'updatedAt': 20},
    }) == ['Dreaming']


def test_a_running_job_waits_for_its_report(monkeypatch):
    """The runtime replaces the per-job session at run start and attaches the
    report later. That bounded in-flight window is not evidence of loss."""
    import ops.system_check as sc

    monkeypatch.setattr(
        'clawock.providers.openclaw.cron_cli_json',
        lambda argv: {'jobs': [{
            'id': 'a', 'name': 'In flight', 'enabled': True,
            'state': {'runningAtMs': 1786429918631, 'lastStatus': 'error'},
        }]})
    assert sc._cron_jobs_without_prompt_report({
        'agent:main:cron:a': {'updatedAt': 20},
    }) == []


def test_a_disabled_job_is_not_demanded(monkeypatch):
    """Only what is scheduled has to be observable."""
    import ops.system_check as sc

    monkeypatch.setattr(
        'clawock.providers.openclaw.cron_cli_json',
        lambda argv: {'jobs': [{'id': 'b', 'name': 'Off', 'enabled': False}]})
    assert sc._cron_jobs_without_prompt_report({}) == []


def test_every_job_covered_reports_nothing(monkeypatch):
    import ops.system_check as sc

    monkeypatch.setattr(
        'clawock.providers.openclaw.cron_cli_json',
        lambda argv: {'jobs': [{'id': 'a', 'name': 'Healthy', 'enabled': True}]})
    assert sc._cron_jobs_without_prompt_report({
        'agent:main:cron:a:run:1': {'systemPromptReport': {}}}) == []


def test_an_unreadable_schedule_does_not_invent_findings(monkeypatch):
    """A schedule that cannot be read is not evidence either way, and this check
    must not turn that into noise on a foreign host."""
    import ops.system_check as sc

    def boom(argv):
        raise RuntimeError('no runtime here')

    monkeypatch.setattr('clawock.providers.openclaw.cron_cli_json', boom)
    assert sc._cron_jobs_without_prompt_report({}) == []
