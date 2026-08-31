"""Every test module that calls into `pytest` must import it (#1141 fallout).

`test_glossary_parity.py` used `pytest.skip(...)` on two degradation paths
without importing the module. Both paths are the *rare* branch — GitHub
unreachable, or the API answering with an error — so the missing import stayed
invisible for as long as the network behaved, and then turned a soft skip into
a hard `NameError: name 'pytest' is not defined` on master while every PR run
before it was green.

That is the shape worth gating: a name used only inside a fallback branch is
not exercised by a passing run, so no amount of green tells you it resolves.
This check is static — it reads the source rather than running it — which is
exactly why it sees branches the suite never takes.
"""
import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _imports_pytest(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == "pytest" or a.name.startswith("pytest.") for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "pytest" or (node.module or "").startswith("pytest."):
                return True
    return False


def _binds_pytest_locally(tree):
    """`pytest` could also be a parameter, assignment or fixture name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id == "pytest":
                return True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            names = [a.arg for a in args.args + args.posonlyargs + args.kwonlyargs]
            if "pytest" in names:
                return True
    return False


def _uses_pytest(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "pytest":
                return True
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id == "pytest":
                return True
    return False


def test_every_test_module_that_uses_pytest_imports_it():
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not _uses_pytest(tree):
            continue
        if _imports_pytest(tree) or _binds_pytest_locally(tree):
            continue
        offenders.append(path.relative_to(TESTS.parent).as_posix())
    assert not offenders, (
        "these test modules reference `pytest` without importing it, so any "
        "branch that reaches the name raises NameError instead of skipping or "
        "failing as written: " + ", ".join(offenders))
