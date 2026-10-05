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


def gate_debt(tmp_path, *, canonical=True, kind='debt', same=True, precedent='无先例，本次为预防性。'):
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
    body += '\n证据: src/clawock/a.py:1 src/clawock/b.py:1\n' + precedent + '\n<!-- DEBT-CHECK\n'+json.dumps(BASE)+'\n-->\n'
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


def test_duplicate_subset_is_not_hidden_by_distinct_implementations(tmp_path):
    root = repository(tmp_path)
    (root / 'src/clawock/c.py').write_text('def value(x):\n    y = x - 1\n    z = y * 2\n    z += 3\n    return z\n')
    subprocess.run(['git', '-C', str(root), 'add', 'src/clawock/c.py'], check=True)
    contract = dict(BASE, symbols=BASE['symbols'] + ['src/clawock/c.py::value'])
    red, detail, _ = debt_check.evaluate(contract, root)
    assert red and 'copies=2 of 3' in detail


# ── 2026-10-05: renamed copies, unreferenced symbols, tail structure, and the narrowed refactor gate ──

def commit(root, message):
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                    'commit', '-q', '-m', message], check=True)


def test_renamed_locals_are_a_copy_but_a_different_helper_or_constant_is_not(tmp_path):
    root = repository(tmp_path)
    (root / 'src/clawock/b.py').write_text(
        'def other(value: int) -> int:\n    """Docstring and annotations are not the fact."""\n'
        '    a = value + 1\n    b = a * 2\n    b += 3\n    return b\n')
    exact = dict(BASE, symbols=['src/clawock/a.py::value', 'src/clawock/b.py::other'])
    assert not debt_check.evaluate(exact, root)[0]
    red, output, _ = debt_check.evaluate(dict(exact, normalize='alpha'), root)
    assert red and 'copies=2' in output
    for different in ('    a = abs(value) + 1\n', '    a = value + 2\n'):
        text = (root / 'src/clawock/b.py').read_text().replace('    a = value + 1\n', different)
        (root / 'src/clawock/c.py').write_text(text)
        subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
        assert not debt_check.evaluate(dict(exact, normalize='alpha', symbols=['src/clawock/a.py::value', 'src/clawock/c.py::other']), root)[0]
    with pytest.raises(ValueError, match='normalize'):
        debt_check.evaluate(dict(exact, normalize='constants'), root)


def test_unreferenced_symbol_counts_every_tracked_file_and_goes_green_when_deleted(tmp_path):
    root = repository(tmp_path)
    (root / 'src/clawock/a.py').write_text('def lonely(x):\n    return x\n\n\ndef used(x):\n    return x\n')
    (root / 'src/clawock/b.py').write_text('from .a import used\n\n\ndef only_tested(x):\n    return used(x)\n')
    (root / 'tests/test_b.py').write_text('from clawock.b import only_tested\n')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    contract = dict(BASE, check='unreferenced-symbol', symbols=['src/clawock/a.py::lonely'])
    red, output, paths = debt_check.evaluate(contract, root)
    assert red and 'claim=full' in output and paths == ['src/clawock/a.py']
    # a test, a document or a script naming it is a reference: whether to delete is then a product call
    for symbol in ('src/clawock/a.py::used', 'src/clawock/b.py::only_tested'):
        assert not debt_check.evaluate(dict(contract, symbols=[symbol]), root)[0]
    red, output, _ = debt_check.evaluate(dict(contract, symbols=['src/clawock/a.py::lonely', 'src/clawock/a.py::used']), root)
    assert red and 'claim=partial' in output          # the gate refuses a padded list
    (root / 'docs.md').write_text('call `lonely` from the shell\n')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    assert not debt_check.evaluate(contract, root)[0]
    (root / 'docs.md').write_text('nothing\n')
    (root / 'src/clawock/a.py').write_text('def used(x):\n    return x\n')
    green, output, _ = debt_check.evaluate(contract, root)
    assert not green and 'removed' in output


@pytest.mark.parametrize('source,symbol', [
    ('def __getattr__(name):\n    return name\n', 'src/clawock/a.py::__getattr__'),
    ('import functools\n\n@functools.cache\ndef hook():\n    return 1\n', 'src/clawock/a.py::hook'),
    ('def main():\n    return 1\n', 'src/clawock/a.py::main'),
    ('def exported():\n    return 1\n', 'src/clawock/__init__.py::exported'),
    # under `if __name__ == "__main__":` the definition is in the file but not at module level (#2573)
    ("if __name__ == '__main__':\n    def _bump(i):\n        return i\n    _bump(1)\n", 'src/clawock/a.py::_bump'),
    ('try:\n    import x\nexcept ImportError:\n    def shim():\n        return 1\n', 'src/clawock/a.py::shim'),
])
def test_entry_points_reached_without_a_name_are_not_dead_code(tmp_path, source, symbol):
    root = repository(tmp_path)
    (root / symbol.split('::')[0]).write_text(source)
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    with pytest.raises(ValueError):
        debt_check.evaluate(dict(BASE, check='unreferenced-symbol', symbols=[symbol]), root)


BIG = 'def big(x):\n' + ''.join(f'    if x == {i}:\n        x += 1\n' for i in range(30)) + '    return x\n'
STRUCTURE = dict(BASE, check='structure', symbol='src/clawock/big.py::big', measure='cc', after=10,
                 landing=['src/clawock/big.py::_first', 'src/clawock/big.py::_second'], callers=1,
                 benefit='31 branches become 2 pieces a test can drive alone', precedent=[])
del STRUCTURE['symbols']


def tail_repository(tmp_path):
    root = repository(tmp_path)
    (root / 'src/clawock/small.py').write_text(''.join(f'def f{i}(x):\n    return x\n\n\n' for i in range(30)))
    (root / 'src/clawock/big.py').write_text(BIG)
    (root / 'src/clawock/use.py').write_text('from .big import big\n\n\ndef run(v):\n    return big(v)\n')
    (root / 'tests/test_big.py').write_text('from clawock.big import big\nbig(1)\n')
    commit(root, 'fix: big miscounted the seventh branch (#7)')
    return root


def test_structure_is_red_only_in_the_tail_of_the_distribution_measured_now(tmp_path):
    root = tail_repository(tmp_path)
    red, output, paths = debt_check.evaluate(STRUCTURE, root)
    assert red and 'claim=full' in output and 'cc=31' in output and 'p99 at this HEAD=31' in output
    assert paths == ['src/clawock/big.py']
    # The same function, untouched, stops being evidence once the rest of the repository has grown
    # past it: the cut-off is this HEAD's p99, not a number anyone wrote down.
    (root / 'src/clawock/huge.py').write_text('def huge(x):\n' + ''.join(f'    if x == {i}:\n        x += 1\n' for i in range(70)) + '    return x\n')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    with pytest.raises(ValueError, match=r'cc=31 is below the tail \(cc p99 at this HEAD=71\)'):
        debt_check.evaluate(STRUCTURE, root)
    # with enough functions the cut-off sits below the worst ones, and a target that would
    # leave the function above it is not a repair
    (root / 'src/clawock/many.py').write_text(''.join(f'def g{i}(x):\n    return x\n\n\n' for i in range(120)))
    (root / 'src/clawock/worse.py').write_text('def worse(x):\n' + ''.join(f'    if x == {i}:\n        x += 1\n' for i in range(90)) + '    return x\n')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    huge = dict(STRUCTURE, symbol='src/clawock/huge.py::huge', callers=0)
    with pytest.raises(ValueError, match=r'after=40 leaves the function in the tail \(cc p99 at this HEAD=31\)'):
        debt_check.evaluate(dict(huge, after=40), root)
    assert debt_check.evaluate(huge, root)[0]


def test_structure_recounts_callers_and_precedents(tmp_path):
    root = tail_repository(tmp_path)
    with pytest.raises(ValueError, match=r"callers=4 claimed, measured 1: \['src/clawock/use.py:5'\]"):
        debt_check.evaluate(dict(STRUCTURE, callers=4), root)
    assert debt_check.evaluate(dict(STRUCTURE, precedent=[7]), root)[0]
    (root / 'src/clawock/later.py').write_text('def later(x):\n    return x\n')
    commit(root, 'fix: unrelated cleanup (#70), closes #8')
    assert debt_check.precedent_touches(root, 7, ['src/clawock/big.py']).endswith(' src/clawock/big.py')
    assert debt_check.precedent_touches(root, 7, ['src/clawock/later.py']) == ''     # #70 is not #7
    assert debt_check.precedent_touches(root, 8, ['src/clawock/later.py'])           # an issue named in the fix
    with pytest.raises(ValueError, match=r'precedent \[8\] never changed src/clawock/big.py'):
        debt_check.evaluate(dict(STRUCTURE, precedent=[7, 8]), root)
    for bad in (dict(measure='lines_in_module'), dict(landing=['src/clawock/big.py::_first']), dict(benefit='much cleaner code'),
                dict(precedent=None), dict(after=0)):
        with pytest.raises(ValueError):
            debt_check.evaluate(dict(STRUCTURE, **bad), root)


def test_structure_repair_must_cut_the_body_not_move_it(tmp_path):
    root = tail_repository(tmp_path)
    big = root / 'src/clawock/big.py'
    # moved verbatim under a landing name: the measure went nowhere, still red
    big.write_text(BIG.replace('def big', 'def _first') + '\n\ndef _second(x):\n    return x\n')
    red, output, _ = debt_check.evaluate(STRUCTURE, root)
    assert red and 'claim=relocated' in output
    # kept as a thin entry point over an equally complex helper: still red
    big.write_text(BIG.replace('def big', 'def _first') + '\n\ndef _second(x):\n    return x\n\n\ndef big(x):\n    return _first(x)\n')
    red, output, _ = debt_check.evaluate(STRUCTURE, root)
    assert red and 'claim=moved-not-cut' in output
    # shrunk or deleted without the declared landing: the contract no longer describes the code
    for text in ('def big(x):\n    return x\n', 'def elsewhere(x):\n    return x\n'):
        big.write_text(text)
        with pytest.raises(ValueError, match='does not exist'):
            debt_check.evaluate(STRUCTURE, root)
    half = lambda name, lo: f'def {name}(x):\n' + ''.join(f'    if x == {i}:\n        x += 1\n' for i in range(lo, lo + 8)) + '    return x\n\n\n'
    big.write_text(half('_first', 0) + half('_second', 8) + 'def big(x):\n    return _second(_first(x))\n')
    green, output, _ = debt_check.evaluate(STRUCTURE, root)
    assert not green and 'claim=repaired' in output


def test_structure_green_is_checked_like_red(tmp_path):
    """A shortened function plus two helpers that already had their own callers is not a repair (#2573, #2574)."""
    root = tail_repository(tmp_path)
    big = root / 'src/clawock/big.py'
    half = lambda name, lo: f'def {name}(x):\n' + ''.join(f'    if x == {i}:\n        x += 1\n' for i in range(lo, lo + 8)) + '    return x\n\n\n'
    cut = half('_first', 0) + half('_second', 8) + 'def big(x):\n    return _second(_first(x))\n'
    big.write_text(cut)
    for bad, message in (({'callers': 99}, 'callers=99 claimed'), ({'precedent': [999999]}, 'never changed')):
        with pytest.raises(ValueError, match=message):
            debt_check.evaluate(dict(STRUCTURE, **bad), root)
    # the same pieces, but one of them is somebody else's helper
    (root / 'src/clawock/other.py').write_text('from clawock.big import _first\n\n\ndef other(x):\n    return _first(x)\n')
    subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
    with pytest.raises(ValueError, match='used outside'):
        debt_check.evaluate(STRUCTURE, root)
    # the original still in the file under a guard is unreadable, not repaired
    (root / 'src/clawock/other.py').write_text('')
    big.write_text(half('_first', 0) + half('_second', 8) + 'if True:\n' + ''.join('    ' + line for line in BIG.splitlines(True)))
    with pytest.raises(ValueError, match='below module level'):
        debt_check.evaluate(STRUCTURE, root)


def run_gate(tmp_path, body, prepare=None, lens='debt'):
    """The real gate, dry run, over a committed worktree and a `gh` that knows issues below 9000."""
    probe = _gate(tmp_path, DRAFT.format(sev='P2'))
    assert probe.returncode == 0, probe.stderr
    wt = tmp_path / 'a/wt'
    subprocess.run(['git', 'init', '-q', str(wt)], check=True)
    commit(wt, 'fix: total() dropped every row after the first (#41)')
    if prepare:
        prepare(wt)
    fake = tmp_path / 'bin'
    fake.mkdir()
    (fake / 'gh').write_text('#!/bin/sh\ncase "$*" in *issues/9[0-9][0-9][0-9]*) exit 1;; esac\necho "a real issue title"\n')
    (fake / 'gh').chmod(0o755)
    draft = tmp_path / 'a/state/R1-x.md'
    draft.write_text(body)
    env = dict(os.environ, PATROL_STATE=str(draft.parent), PATROL_WORKTREE=str(wt), GATE_DRY_RUN='1',
               AGENT_DISPATCH_TASK_ID=f'patrol-{lens}-20261005-000000', PATH=f'{fake}:{os.environ["PATH"]}')
    env.pop('CLAWOCK_WORKSPACE', None)
    return subprocess.run([sys.executable, str(TOOL / 'gate_issue.py'), str(draft)], env=env,
                          capture_output=True, text=True, timeout=60)


SPLIT = DRAFT.format(sev='P2').replace('面板总市值少算一行：total() 只加第一条', 'total() 职责过多，建议拆分成三个函数')
LANDING = ('落点: src/clawock/money.py:1 拆成 _rows() 与 _sum()，调用点 1 处，签名不变\n'
           '收益: 30 条语句分成 2 段可单测的函数，这段代码上已有 1 个 fix 提交\n')


def with_lines(text):
    return SPLIT.replace('## 建议修法', text + '\n## 建议修法')


def test_split_shaped_draft_without_landing_benefit_or_precedent_is_still_refused(tmp_path):
    r = run_gate(tmp_path, SPLIT)
    assert r.returncode == 2 and '两条出路' in r.stderr and '没有 `先例:` 行' in r.stderr
    # 落点/收益 alone do not replace the consequence
    r = run_gate(tmp_path / 'b', with_lines(LANDING))
    assert r.returncode == 2 and '两条出路' in r.stderr


def test_precedent_must_have_changed_the_file_the_draft_is_about(tmp_path):
    def unrelated(wt):
        (wt / 'README.md').write_text('docs\n')
        commit(wt, 'docs: reword the readme (#77)')
    # #77 exists and is a real fix, but it never touched money.py: an unrelated number no longer passes
    r = run_gate(tmp_path, with_lines('先例: #77\n' + LANDING), unrelated)
    assert r.returncode == 2 and '#77 不存在，或没有改过 src/clawock/money.py' in r.stderr
    # a number that does not exist at all
    r = run_gate(tmp_path / 'b', with_lines('先例: #9123\n' + LANDING))
    assert r.returncode == 2 and '#9123' in r.stderr
    # #41 fixed this very file, but the draft still has to say where the cut lands and what it buys
    r = run_gate(tmp_path / 'c', with_lines('先例: #41\n'))
    assert r.returncode == 2 and '落点:' in r.stderr and '收益:' in r.stderr
    r = run_gate(tmp_path / 'd', with_lines('先例: #41\n落点: 拆成几个小函数\n收益: 更清晰更好维护更容易读\n'))
    assert r.returncode == 2 and '落点:' in r.stderr


def test_split_with_a_precedent_that_touched_the_file_passes(tmp_path):
    r = run_gate(tmp_path, with_lines('先例: #41\n' + LANDING))
    assert r.returncode == 0, r.stderr
    assert '先例碰过该文件：#41' in r.stderr and 'src/clawock/money.py' in r.stderr


def structure_draft(contract, note='无先例，本次为预防性。'):
    body = DRAFT.format(sev='P2').replace('面板总市值少算一行：total() 只加第一条', 'total() 的 32 行函数体拆成两段')
    body = body.replace('领域: data', '领域: debt').replace('类型: bug', '类型: debt').replace('SURFACE: 面板', 'SURFACE: 无（基础设施）')
    body += f'\n{note}\n<!-- DEBT-CHECK\n' + json.dumps(contract) + '\n-->\n'
    start = body.index('<!-- RED-CHECK'); end = body.index('-->', start) + 3
    return body[:start] + '<!-- RED-CHECK\n' + debt_check.red_command(contract, TOOL) + '\n-->' + body[end:]


GATE_STRUCTURE = dict(STRUCTURE, symbol='src/clawock/money.py::total', measure='length', callers=0,
                      landing=['src/clawock/money.py::_rows', 'src/clawock/money.py::_sum'])


def test_structure_contract_opens_the_gate_for_debt_with_no_precedent_only_when_it_says_so(tmp_path):
    r = run_gate(tmp_path, structure_draft(GATE_STRUCTURE))
    assert r.returncode == 0, r.stderr
    assert 'claim=full' in r.stderr and 'triage P3 area:debt kind:debt' in r.stderr
    r = run_gate(tmp_path / 'b', structure_draft(GATE_STRUCTURE, note='这段迟早出事。'))
    assert r.returncode == 2 and '无先例' in r.stderr
    # a precedent written in the draft is checked the same way as anywhere else
    r = run_gate(tmp_path / 'c', structure_draft(GATE_STRUCTURE, note='先例: #9123'))
    assert r.returncode == 2 and '#9123' in r.stderr
    r = run_gate(tmp_path / 'd', structure_draft(dict(GATE_STRUCTURE, precedent=[41]), note='先例: #41'))
    assert r.returncode == 0, r.stderr
    assert '先例=#41' in r.stderr


def test_gate_refuses_a_structure_claim_the_measurement_does_not_carry(tmp_path):
    # callers invented
    r = run_gate(tmp_path, structure_draft(dict(GATE_STRUCTURE, callers=3)))
    assert r.returncode == 2 and 'callers=3 claimed, measured 0' in r.stderr
    # red, but only because an equally long function already sits under a landing name
    def relocated(wt):
        money = wt / 'src/clawock/money.py'
        money.write_text(money.read_text().replace('def total', 'def _rows') + '\n\ndef _sum(x):\n    return x\n')
        commit(wt, 'refactor: rename')
    draft = structure_draft(GATE_STRUCTURE).replace('money.py:31', 'money.py:1')
    r = run_gate(tmp_path / 'b', draft, relocated)
    assert r.returncode == 2 and '不全相符' in r.stderr and 'claim=relocated' in r.stderr
    # an unreferenced-symbol list padded with a symbol that is in use
    def two(wt):
        (wt / 'src/clawock/money.py').write_text('def total(rows):\n    return used(rows)\n\n\ndef used(rows):\n    return rows\n' + '\n' * 30)
        commit(wt, 'feat: used')
    padded = dict(BASE, check='unreferenced-symbol', symbols=['src/clawock/money.py::total', 'src/clawock/money.py::used'])
    r = run_gate(tmp_path / 'c', structure_draft(padded), two)
    assert r.returncode == 2 and 'claim=partial' in r.stderr


def test_unreferenced_symbol_draft_needs_no_handwritten_grep(tmp_path):
    def orphan(wt):
        with (wt / 'src/clawock/money.py').open('a') as f:
            f.write('\n\ndef orphan_sum(rows):\n    return rows\n')
        commit(wt, 'feat: helper nobody calls')
    contract = dict(BASE, check='unreferenced-symbol', symbols=['src/clawock/money.py::orphan_sum'])
    body = structure_draft(contract).replace('total() 的 32 行函数体拆成两段', 'orphan_sum() 从未被调用，是死代码')
    r = run_gate(tmp_path, body, orphan)
    assert r.returncode == 0, r.stderr
    assert 'claim=full' in r.stderr
    # `total` is a key in the published dashboard.json: any tracked file naming it is a reference
    r = run_gate(tmp_path / 'b', structure_draft(dict(contract, symbols=['src/clawock/money.py::total'])))
    assert r.returncode == 2 and '债务已证伪' in r.stderr


def test_prompt_and_lens_allow_precedented_refactors_and_keep_the_guards():
    prompt = (TOOL / 'round-prompt.md').read_text()
    lens = next(line for line in (TOOL / 'axes.tsv').read_text().splitlines() if line.startswith('debt\t'))
    for text in (prompt, lens):
        assert 'debt_check.py --candidates' in text and '落点' in text and '收益' in text and '无先例' in text
    assert '审美重构/拆分' not in prompt and '只把代码换个文件' in prompt
    assert '禁只换文件位置' in lens and '本轮不提独立拆文件' in lens and lens.count('\t') == 2
