"""Debt exceptions need fixed structural evidence; old refactor/noise gates still apply."""
import json
import os
import subprocess
import sys

import pytest

from test_patrol_triage import _gate, DRAFT, TOOL
sys.path.insert(0, str(TOOL))
import debt_check
import triage

BASE = dict(check='duplicate-python', fact='same code identity for two provenance consumers',
            repair='one neutral code identity owner, callers delegate',
            guard='pin owner count and failure/wire formats in a regression test',
            symbols=['src/clawock/a.py::value', 'src/clawock/b.py::value'])


def repository(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'src/clawock').mkdir(parents=True)
    function = 'def value(x):\n    y = x + 1\n    z = y * 2\n    z += 3\n    return z\n'
    for name in ('a', 'b'):
        (tmp_path / f'src/clawock/{name}.py').write_text(function)
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests/test_packaging_extras_contract.py').write_text("DISTRIBUTION = {'PIL': 'pillow', 'google': 'google-auth', 'yaml': 'pyyaml'}\n")
    (tmp_path / 'pyproject.toml').write_text('[project]\ndependencies = []\n')
    subprocess.run(['git', '-C', str(tmp_path), 'add', '.'], check=True)
    return tmp_path


def test_duplicate_red_then_owner_delegation_green(tmp_path):
    root = repository(tmp_path)
    red, output, paths = debt_check.evaluate(BASE, root)
    assert red and 'copies=2' in output and len(paths) == 2
    (root / paths[1]).write_text('def value(x):\n    """Compatibility wrapper with no independent implementation."""\n    from .a import value as owner\n    result = owner(x)\n    return result\n')
    green, output, _ = debt_check.evaluate(BASE, root)
    assert not green and 'copies=1' in output
    (root / paths[1]).write_text('def value(x):\n    return x\n')
    assert not debt_check.evaluate(BASE, root)[0]


def test_cycle_includes_relative_child_but_excludes_deferred_import(tmp_path):
    root = repository(tmp_path)
    a, b = [root / f'src/clawock/{n}.py' for n in ('a', 'b')]
    a.write_text('from . import b\n'); b.write_text('from . import a\n')
    contract = dict(BASE, check='import-cycle', modules=['src/clawock/a.py', 'src/clawock/b.py'])
    assert debt_check.evaluate(contract, root)[0]
    b.write_text('def value():\n    from . import a\n')
    assert not debt_check.evaluate(contract, root)[0]


def test_dependency_extra_is_a_declaration_and_stdlib_is_not_debt(tmp_path):
    root = repository(tmp_path)
    (root / 'src/clawock/a.py').write_text('def value():\n    import yfinance\n')
    contract = dict(BASE, check='undeclared-import', source='src/clawock/a.py', **{'import': 'yfinance'})
    assert debt_check.evaluate(contract, root)[0]
    (root / 'pyproject.toml').write_text('[project]\ndependencies=[]\n[project.optional-dependencies]\nmarket=["yfinance>=0.2"]\n')
    assert not debt_check.evaluate(contract, root)[0]
    (root / 'src/clawock/a.py').write_text('import b\n')
    with pytest.raises(ValueError, match='repository-local'):
        debt_check.evaluate(dict(contract, **{'import': 'b'}), root)
    with pytest.raises(ValueError, match='external'):
        debt_check.evaluate(dict(contract, **{'import': 'json'}), root)


@pytest.mark.parametrize('override', [dict(check='size'), dict(fact='vague'), dict(symbols=['src/clawock/a.py::missing', 'src/clawock/b.py::value']), dict(symbols=['../a.py::value', 'src/clawock/b.py::value'])])
def test_invalid_is_never_a_violation(tmp_path, override):
    with pytest.raises(ValueError):
        debt_check.evaluate(dict(BASE, **override), repository(tmp_path))


def gate_debt(tmp_path, *, canonical=True, kind='debt', same=True):
    # _gate constructs its fixture first; then prepare tracked structural sources.
    probe = _gate(tmp_path, DRAFT.format(sev='P0'))
    assert probe.returncode == 0, probe.stderr
    wt = tmp_path / 'a/wt'
    (wt / 'src/clawock/a.py').write_text('def value(x):\n    y = x + 1\n    z = y * 2\n    z += 3\n    return z\n')
    (wt / 'src/clawock/b.py').write_text((wt / 'src/clawock/a.py').read_text().replace('z += 3', 'z += 4') if not same else (wt / 'src/clawock/a.py').read_text())
    subprocess.run(['git', 'init', '-q', str(wt)], check=True)
    subprocess.run(['git', '-C', str(wt), 'add', '.'], check=True)
    body = DRAFT.format(sev='P0').replace('面板总市值少算一行：total() 只加第一条', '重构代码身份：同一事实两处实现')
    body = body.replace('领域: data', '领域: debt').replace('类型: bug', '类型: '+kind).replace('SURFACE: 面板', 'SURFACE: 无（基础设施）')
    body += '\n证据: src/clawock/a.py:1 src/clawock/b.py:1\n<!-- DEBT-CHECK\n'+json.dumps(BASE)+'\n-->\n'
    start = body.index('<!-- RED-CHECK'); end = body.index('-->', start)+3
    red = debt_check.red_command(BASE, TOOL) if canonical else 'python3 -c "assert False"'
    body = body[:start]+'<!-- RED-CHECK\n'+red+'\n-->'+body[end:]
    draft = tmp_path / 'a/state/R1-x.md'
    draft.write_text(body)
    env = dict(os.environ, PATROL_STATE=str(draft.parent), PATROL_WORKTREE=str(wt), GATE_DRY_RUN='1',
               AGENT_DISPATCH_TASK_ID='patrol-debt-20261003-000000')
    env.pop('CLAWOCK_WORKSPACE', None)
    return subprocess.run([sys.executable, str(TOOL / 'gate_issue.py'), str(draft)], env=env,
                          capture_output=True, text=True, timeout=20)


def test_real_debt_passes_without_precedent_but_is_p3(tmp_path):
    r = gate_debt(tmp_path)
    assert r.returncode == 0, r.stderr
    assert 'DEBT RED' in (tmp_path / 'a/state/filed/R1-x.md.body').read_text()
    assert 'triage P3 area:debt kind:debt lens:debt' in r.stderr


def test_arbitrary_red_cannot_unlock_refactor_exception(tmp_path):
    r = gate_debt(tmp_path, canonical=False)
    assert r.returncode == 2 and '固定命令' in r.stderr


def test_green_debt_is_refuted(tmp_path):
    r = gate_debt(tmp_path, same=False)
    assert r.returncode == 2 and '债务已证伪' in r.stderr


def test_debt_block_cannot_exempt_bug_shape(tmp_path):
    r = gate_debt(tmp_path, kind='bug')
    assert r.returncode == 2 and '同时声明' in r.stderr


def test_axis_lens_labels_rotation_and_caps():
    assert 'debt' in triage.lenses_from_axes(TOOL / 'axes.tsv')
    assert triage.lens_of('patrol-debt-20261003-000000') == 'debt'
    assert 'lens:debt' in triage.label_taxonomy(triage.lenses_from_axes(TOOL / 'axes.tsv'))
    rotation = [w for line in (TOOL / 'rotation').read_text().splitlines() if not line.startswith('#') for w in line.split()]
    assert len(rotation) == 22 and rotation.count('recent') == 5 and rotation.count('money') == 2
    assert rotation.count('debt') == 1 and set(rotation) <= set(triage.lenses_from_axes(TOOL / 'axes.tsv'))
