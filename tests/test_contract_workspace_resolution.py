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
import subprocess
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


# ── the same defect, 75 more times (#1248) ──────────────────────────────────
#
# #775 fixed `_contract_path`. What it did not do is ask how many other places
# had written the same line: 75 modules resolved their workspace as
# `workspace_root(Path.cwd())`, which is `Path.cwd()` whenever CLAWOCK_WORKSPACE
# is unset — the exact fallback that sent the DST synchroniser looking for
# `/root/config/cron-schedules.json` for eight days. `workspace_root`'s own
# docstring says callers pass their own `parents[2]` "so the fallback stays
# exactly what it was"; none of the 75 did.
#
# Nothing had broken yet only because every current caller happens to chdir
# first: the installed launcher exports CLAWOCK_WORKSPACE, the harness passes
# `cwd=ws` to its subprocess, the ops scripts `cd "$WS"`, and pytest runs from
# the repository root. That is a property of the callers, not of the code, and
# #775 is what it looks like when one caller stops holding it.

_PROBE_MODULES = (
    ('clawock.market_data.us_quotes', 'WS_ROOT'),
    ('clawock.portfolio.cash', 'WS'),
    ('clawock.harness._harness_common', 'WS'),
    ('clawock.publish.dashboard', 'WS_ROOT'),
)


def _probe_module_workspace(cwd, env):
    """Import each module in a fresh interpreter and print what it resolved.

    A subprocess because these are module-level constants: once this suite has
    imported them from the repository root, re-importing gives the cached value
    and the test would pass against the bug.
    """
    program = (
        f'import sys; sys.path.insert(0, {str(ROOT / "src")!r})\n'
        'import importlib\n'
        f'for name, attr in {_PROBE_MODULES!r}:\n'
        '    print(name, getattr(importlib.import_module(name), attr))\n'
    )
    done = subprocess.run([sys.executable, '-c', program], capture_output=True,
                          text=True, timeout=120, cwd=str(cwd), env=env)
    assert done.returncode == 0, done.stderr
    return dict(line.split(' ', 1) for line in done.stdout.strip().splitlines())


def test_module_workspaces_ignore_the_process_cwd(tmp_path):
    """Run from a directory that is not a workspace, they still find their own."""
    env = {k: v for k, v in os.environ.items() if k != 'CLAWOCK_WORKSPACE'}
    resolved = _probe_module_workspace(tmp_path, env)

    assert resolved, 'the probe recorded nothing, so it proves nothing'
    for name, _ in _PROBE_MODULES:
        assert resolved[name] == str(ROOT), (
            f'{name} resolved its workspace to the caller\'s cwd instead of the '
            f'tree it sits in — the #775 defect, which reads and writes another '
            f'directory\'s ledger with no error')


def test_a_foreign_cwd_that_looks_like_a_workspace_does_not_hijack_a_module():
    """The silent half: a cwd holding a portfolio.json is the worse case.

    A missing file raises. A different book's `portfolio.json` does not — it is
    read, published and written back to, and nothing anywhere says which desk
    the numbers came from.
    """
    import tempfile

    env = {k: v for k, v in os.environ.items() if k != 'CLAWOCK_WORKSPACE'}
    with tempfile.TemporaryDirectory() as foreign:
        book = Path(foreign)
        (book / 'memory').mkdir()
        (book / 'assets' / 'data').mkdir(parents=True)
        (book / 'portfolio.json').write_text('{"portfolios": {}}', encoding='utf-8')
        resolved = _probe_module_workspace(book, env)

    for name, _ in _PROBE_MODULES:
        assert resolved[name] == str(ROOT), f'{name} was hijacked by a foreign book'


def test_the_env_override_still_wins_for_modules(tmp_path):
    """Anchoring on the tree must not cost the foreign-workspace feature."""
    env = dict(os.environ, CLAWOCK_WORKSPACE=str(tmp_path))
    resolved = _probe_module_workspace(ROOT, env)
    for name, _ in _PROBE_MODULES:
        assert resolved[name] == str(tmp_path), f'{name} ignored CLAWOCK_WORKSPACE'


def test_no_module_reintroduces_the_cwd_default():
    """A static gate, because the runtime one cannot see the other 71 modules.

    The probe above imports four modules; the defect was in 75. Scanning the
    source is what covers the rest, and it is also what catches the next module
    written by copying a neighbour — which is how this spread from one line to
    seventy-five in the first place.
    """
    offenders = []
    for base in ('src', 'ops'):
        for path in (ROOT / base).rglob('*.py'):
            text = path.read_text(encoding='utf-8')
            for number, line in enumerate(text.splitlines(), 1):
                if 'workspace_root(Path.cwd())' in line:
                    offenders.append(f'{path.relative_to(ROOT)}:{number}')
    assert not offenders, (
        'workspace_root(Path.cwd()) resolves to the caller\'s cwd whenever '
        'CLAWOCK_WORKSPACE is unset, which is the #775 defect. Call '
        'workspace_root() with no argument: its own fallback is the tree the '
        f'package sits in. Found: {offenders}')
