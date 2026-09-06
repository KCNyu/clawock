"""Nobody may cap `safe_push.sh` below the retry ladder it is going to run.

2026-09-06. `push_with_rebase_retry` wrapped the script in `timeout=120`. The
script pushes up to `MAX_RETRIES=3` times, and **every one of those pushes
re-runs `.githooks/pre-push`**, whose cost is `ops/system_check.py` — measured
four times on the live host that day, idle: 53.9 / 56.0 / 59.7 / 61.3 s. So the
cap could not cover two attempts, and the retry machinery that exists to survive
a lost push race could never reach the end of its second one. Every `push
failed` string in the openclaw session history is that timeout; not one is a
refusal by the hook. The commits stayed on the host (10 of 14 slots on the
2026-09-04 evening reported `data_plane_status: committed_local`).

The gate is the same shape as `test_llm_workflow_deadlines`: a per-attempt
timeout smaller than the budget the attempt actually needs is not a safety
margin, it is a guarantee of failure. Two halves:

  1. the constants in `_harness_common` still describe the ladder that
     `safe_push.sh` really runs (attempts and backoff are read out of the shell
     script, so changing the script without the budget trips this);
  2. every caller that hands `safe_push.sh` to `subprocess` either passes no
     timeout at all (the shell publishers) or one big enough for the ladder.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAFE_PUSH = ROOT / 'ops' / 'publish' / 'safe_push.sh'
PRE_PUSH = ROOT / '.githooks' / 'pre-push'

import sys
sys.path.insert(0, str(ROOT / 'src'))
from clawock.harness._harness_common import (  # noqa: E402
    PREPUSH_ATTEMPT_SECONDS,
    PUSH_RETRY_BACKOFF_SECONDS,
    PUSH_TIMEOUT_SECONDS,
    SAFE_PUSH_ATTEMPTS,
)


def _shell_attempts() -> int:
    m = re.search(r'^MAX_RETRIES=(\d+)', SAFE_PUSH.read_text(), re.M)
    assert m, 'safe_push.sh no longer declares MAX_RETRIES'
    return int(m.group(1))


def _shell_backoff(attempts: int) -> int:
    """The script sleeps `i * 3` after every attempt but the last."""
    m = re.search(r'sleep \$\(\(i \* (\d+)\)\)', SAFE_PUSH.read_text())
    assert m, 'safe_push.sh no longer backs off between attempts'
    step = int(m.group(1))
    return sum(i * step for i in range(1, attempts))


def test_the_declared_ladder_is_the_one_safe_push_runs():
    attempts = _shell_attempts()
    assert SAFE_PUSH_ATTEMPTS == attempts, (
        f'safe_push.sh retries {attempts}x, the budget assumes '
        f'{SAFE_PUSH_ATTEMPTS}x')
    assert PUSH_RETRY_BACKOFF_SECONDS == _shell_backoff(attempts), (
        'the backoff ladder in safe_push.sh changed; re-derive '
        'PUSH_RETRY_BACKOFF_SECONDS from it')


def test_the_budget_covers_every_attempt_not_just_the_first():
    assert PUSH_TIMEOUT_SECONDS >= (
        SAFE_PUSH_ATTEMPTS * PREPUSH_ATTEMPT_SECONDS + PUSH_RETRY_BACKOFF_SECONDS
    ), ('the push budget cannot pay for the retries safe_push.sh will run — a '
        'lost race then strands the commit instead of rebasing past it')


def test_the_per_attempt_cost_is_still_dominated_by_the_hook_it_names():
    """PREPUSH_ATTEMPT_SECONDS is a measurement of `ops/system_check.py` running
    inside the hook. If the hook stops running it, the number is about nothing
    and has to be re-measured rather than inherited."""
    hook = PRE_PUSH.read_text()
    assert 'ops/system_check.py' in hook, (
        'the pre-push hook no longer runs system_check — re-measure '
        'PREPUSH_ATTEMPT_SECONDS instead of keeping a number that described it')


def _names_bound_to_safe_push(node) -> set[str]:
    """Locals whose value is (or contains) the path to safe_push.sh.

    `_harness_common` binds it with `script = WS / ... / 'safe_push.sh'`, the
    gold publisher iterates over argv tuples with the path inline — both have to
    be reachable from the call site, which only mentions the local.
    """
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assign) and 'safe_push' in ast.unparse(sub.value):
            for target in sub.targets:
                names.update(n.id for n in ast.walk(target)
                             if isinstance(n, ast.Name))
        elif isinstance(sub, ast.For) and 'safe_push' in ast.unparse(sub.iter):
            names.update(n.id for n in ast.walk(sub.target)
                         if isinstance(n, ast.Name))
    return names


def _subprocess_calls_on_safe_push():
    """Every subprocess call whose argv is safe_push.sh.

    Argv, not the enclosing function: `system_check.check_publish_backlog` names
    the script in its docstring and runs `git rev-list` with a 10s cap, which is
    correct and must not be read as a caller of it.
    """
    found = {}
    for path in sorted(list((ROOT / 'src').rglob('*.py'))
                       + list((ROOT / 'ops').rglob('*.py'))):
        source = path.read_text()
        if 'safe_push' not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover - not our file to fix
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.Module)):
                continue
            bound = _names_bound_to_safe_push(node)
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                fn = ast.unparse(call.func)
                if not fn.startswith(('subprocess.run', 'subprocess.Popen',
                                      'subprocess.check_call',
                                      'subprocess.check_output')):
                    continue
                argv = ' '.join(ast.unparse(a) for a in call.args)
                mentions = 'safe_push' in argv or any(
                    re.search(rf'\b{re.escape(n)}\b', argv) for n in bound)
                if not mentions:
                    continue
                kw = {k.arg: k.value for k in call.keywords}
                where = getattr(node, 'name', '<module>')
                # Walking the module and then each function reaches the same
                # call twice; the call site, not the walk, is the unit.
                found[(path, call.lineno)] = (path.relative_to(ROOT), where,
                                              call.lineno, kw.get('timeout'))
    return list(found.values())


def test_no_caller_cuts_safe_push_off_mid_ladder():
    calls = _subprocess_calls_on_safe_push()
    assert calls, 'found no subprocess caller of safe_push.sh — the scan broke'
    too_small = []
    for rel, func, lineno, timeout in calls:
        if timeout is None:
            continue  # the shell publishers cap nothing, which is allowed
        if isinstance(timeout, ast.Constant) and isinstance(timeout.value, (int, float)):
            value = timeout.value
        elif isinstance(timeout, ast.Name):
            value = {'PUSH_TIMEOUT_SECONDS': PUSH_TIMEOUT_SECONDS}.get(timeout.id)
            if value is None:
                too_small.append(f'{rel}:{lineno} ({func}) timeout={timeout.id} '
                                 f'— not a budget this gate can read')
                continue
        else:
            too_small.append(f'{rel}:{lineno} ({func}) timeout is an expression '
                             f'this gate cannot evaluate')
            continue
        if value < PUSH_TIMEOUT_SECONDS:
            too_small.append(
                f'{rel}:{lineno} ({func}) caps safe_push.sh at {value}s, below '
                f'the {PUSH_TIMEOUT_SECONDS}s its retry ladder needs')
    assert not too_small, '\n'.join(too_small)


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(pytest.main([__file__, '-q']))
