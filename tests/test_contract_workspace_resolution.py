"""The cron contract must resolve from the tree, not from the caller's cwd (#775).

`ops/host/sync_us_cron_dst.py` is started by cron as a bare
`python3 <abs path>`, so its process cwd is `/root`. While `load_contract()`
fell back to `Path.cwd()` that made the DST synchroniser look for
`/root/config/cron-schedules.json` and fail on every run for eight days, with
the traceback going to a log nobody reads. Every other cron line survived only
because the launcher exports `CLAWOCK_WORKSPACE`.

These tests pin the resolution order itself rather than that one script: an
explicit path wins, then the env var, then an explicit `workspace=`, and the
last fallback is the tree the module physically sits in.
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops' / 'host'))

from clawock import scheduling


@pytest.fixture
def no_workspace_env(monkeypatch):
    """Neither override set, so the tests exercise the fallback itself."""
    monkeypatch.delenv('CLAWOCK_WORKSPACE', raising=False)
    monkeypatch.delenv('CLAWOCK_PROFILE', raising=False)


def test_load_contract_ignores_the_process_cwd(tmp_path, monkeypatch, no_workspace_env):
    """Ran from a directory with no `config/`, it still finds its own contract."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / 'config' / 'cron-schedules.json').exists()

    contract = scheduling.load_contract()

    assert contract['jobs'], 'contract resolved but came back empty'
    assert contract.workspace == ROOT


def test_a_foreign_cwd_containing_a_contract_does_not_hijack_the_lookup(
        tmp_path, monkeypatch, no_workspace_env):
    """The failure mode is silent substitution, not only a missing file.

    A cwd that happens to hold a `config/cron-schedules.json` is the worse half
    of the same bug: one book's schedules would be applied to another book's
    runtime with no error at all.
    """
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'cron-schedules.json').write_text(json.dumps({
        'schema_version': 2,
        'jobs': [{'name': 'not-our-job', 'schedule': {'kind': 'cron', 'expr': '0 0 * * *'}}],
    }))
    monkeypatch.chdir(tmp_path)

    contract = scheduling.load_contract()

    assert 'not-our-job' not in [job['name'] for job in contract['jobs']]
    assert contract.workspace == ROOT


def test_explicit_workspace_still_wins_over_the_tree(tmp_path, no_workspace_env):
    with pytest.raises(FileNotFoundError) as excinfo:
        scheduling.load_contract(workspace=tmp_path)
    assert str(tmp_path) in str(excinfo.value)


def test_env_override_still_wins_over_the_tree(tmp_path, monkeypatch, no_workspace_env):
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    with pytest.raises(FileNotFoundError) as excinfo:
        scheduling.load_contract()
    assert str(tmp_path) in str(excinfo.value)


def test_missing_contract_says_which_workspace_it_chose(tmp_path, no_workspace_env):
    """The message has to separate "wait for it" from "you must change a setting"."""
    with pytest.raises(FileNotFoundError) as excinfo:
        scheduling.load_contract(workspace=tmp_path)
    message = str(excinfo.value)
    assert 'workspace resolved to' in message
    assert 'CLAWOCK_WORKSPACE' in message


def test_dst_sync_runs_from_crons_own_cwd(tmp_path, monkeypatch, no_workspace_env):
    """The regression, reproduced through the script cron actually starts."""
    import sync_us_cron_dst

    monkeypatch.chdir(tmp_path)
    contract = sync_us_cron_dst.load_contract()
    assert contract['jobs']
