"""maybe_commit() must return (False, ...) when git push fails.

Both brief_postflight and report_postflight used to return (True, 'committed
(push failed: ...)') — the caller treated commit_ok=True as "published to
origin", but push had silently failed, leaving Pages serving stale data.

These AST checks assert the invariant: any return whose first element is True
must NOT appear in a branch guarded by push failure. The test must FAIL on
unpatched code (return True on push failure) and PASS after the fix.
"""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

MODULES = [
    "clawock/harness/brief_postflight.py",
    "clawock/harness/report_postflight.py",
]


def _find_maybe_commit_returns(src_path: Path):
    """Yield every (return_node, first_element_unparsed) in maybe_commit."""
    tree = ast.parse(src_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "maybe_commit":
            for ret in ast.walk(node):
                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Tuple):
                    if ret.value.elts:
                        first = ret.value.elts[0]
                        yield ret, ast.unparse(first)


def test_maybe_commit_push_failure_returns_false():
    """No maybe_commit should return True in a push-failure branch."""
    for rel in MODULES:
        src_path = SRC / rel
        for ret, first_unparsed in _find_maybe_commit_returns(src_path):
            full = ast.unparse(ret.value)
            if "push failed" in full:
                assert first_unparsed != "True", (
                    f"{rel}: maybe_commit returns (True, ...) on push failure: "
                    f"{full[:120]}"
                )


def test_maybe_commit_idempotent_returns_true():
    """'nothing to commit' is idempotent — returning True is correct."""
    for rel in MODULES:
        src_path = SRC / rel
        for ret, first_unparsed in _find_maybe_commit_returns(src_path):
            full = ast.unparse(ret.value)
            if "nothing to commit" in full:
                assert first_unparsed == "True", (
                    f"{rel}: idempotent path should return True, got {first_unparsed}"
                )


def test_maybe_commit_pushed_returns_true():
    """Successful push — returning True is correct."""
    for rel in MODULES:
        src_path = SRC / rel
        for ret, first_unparsed in _find_maybe_commit_returns(src_path):
            full = ast.unparse(ret.value)
            if "committed + pushed" in full:
                assert first_unparsed == "True", (
                    f"{rel}: push-ok path should return True, got {first_unparsed}"
                )
