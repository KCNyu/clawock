"""The `book` lane runs the tests that read the committed book, and only those.

A push that changes nothing but runtime-written book files (`push_scope.BOOK_GLOBS`)
runs the validate job's data gates and `pytest -m book` instead of the whole
suite. That is only as strong as the marker: a test that reads the real
`portfolio.json` but is not marked would stop running on exactly the pushes
that can break it. So the marker is not left to memory. Tests that build the
real tree through `freshly_built_generation` are marked by the conftest hook;
every other test that reaches a book file from the checkout root is found here,
statically, and must carry the mark itself.

The scan follows how this suite names the checkout: a module-level alias
assigned from `__file__` (`ROOT = Path(__file__).resolve().parents[1]`) or the
expression inline, joined with `/`, `joinpath`, `glob` or `rglob`. A test that
reads the book through a library default (`workspace_root()`) is outside what
a static scan can see; the full suite still runs it on every code push, PR and
the weekly backstop.
"""
from __future__ import annotations

import ast
import fnmatch
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "ci"))
import push_scope  # noqa: E402


def _is_checkout_root(node: ast.AST) -> bool:
    text = ast.unparse(node)
    return "__file__" in text and ("parents[1]" in text or "parent.parent" in text)


def _root_aliases(tree: ast.Module) -> set[str]:
    return {
        target.id
        for node in tree.body if isinstance(node, ast.Assign) and _is_checkout_root(node.value)
        for target in node.targets if isinstance(target, ast.Name)
    }


def _path_from_root(node: ast.AST, aliases: set[str]) -> str | None:
    """The checkout-relative path an expression names, if it starts at the root."""
    if isinstance(node, ast.Name) and node.id in aliases:
        return ""
    if isinstance(node, (ast.Call, ast.Attribute, ast.Subscript)) and _is_checkout_root(node) \
            and not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                     and node.func.attr in {"joinpath", "glob", "rglob"}):
        return ""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        base = _path_from_root(node.left, aliases)
        if base is not None and isinstance(node.right, ast.Constant) \
                and isinstance(node.right.value, str):
            return f"{base}/{node.right.value}".lstrip("/")
        return None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in {"joinpath", "glob", "rglob"}:
        base = _path_from_root(node.func.value, aliases)
        parts = [arg.value for arg in node.args
                 if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
        if base is not None and parts and len(parts) == len(node.args):
            return "/".join([base, *parts]).lstrip("/")
    return None


def _marks_book(decorators) -> bool:
    return any("mark.book" in ast.unparse(d) for d in decorators)


def _book_readers(source: Path) -> dict[str, bool]:
    """{function name: carries the book mark} for every reader of a book file.

    A reader outside a test function (a helper, a fixture, module level) is
    reported as `<module>`: the module then has to be marked as a whole.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"))
    aliases = _root_aliases(tree)
    module_marked = any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
        and "mark.book" in ast.unparse(node.value)
        for node in tree.body
    )
    readers: dict[str, bool] = {}

    def visit(node, owner, inherited=False):
        if isinstance(node, ast.ClassDef):
            inherited = inherited or _marks_book(node.decorator_list)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and owner is None:
            owner = ((node.name, inherited or _marks_book(node.decorator_list))
                     if node.name.startswith("test") else ("<module>", False))
        path = _path_from_root(node, aliases)
        if path and any(fnmatch.fnmatchcase(path, glob) for glob in push_scope.BOOK_GLOBS):
            name, marked = owner or ("<module>", False)
            readers[name] = readers.get(name, False) or marked or module_marked
        for child in ast.iter_child_nodes(node):
            visit(child, owner, inherited)

    visit(tree, None)
    return readers


def _test_modules() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "tests/*.py"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / name for name in out if name != "tests/conftest.py"]


def test_every_direct_reader_of_the_committed_book_is_marked():
    unmarked, seen = {}, 0
    for source in _test_modules():
        readers = _book_readers(source)
        seen += len(readers)
        missing = sorted(name for name, marked in readers.items() if not marked)
        if missing:
            unmarked[str(source.relative_to(ROOT))] = missing
    assert seen, "the scan found no reader at all, so it is not looking"
    assert unmarked == {}, (
        "these tests read the committed book from the checkout but are not "
        "marked `book`, so a book-only push would skip them (mark the test, or "
        f"the module with `pytestmark` when a helper reads the book): {unmarked}")


@pytest.mark.parametrize("snippet,expected", [
    ("ROOT = Path(__file__).resolve().parents[1]\n"
     "def test_x():\n    (ROOT / 'portfolio.json').read_text()\n", {"test_x": False}),
    ("ROOT = Path(__file__).resolve().parents[1]\n"
     "@pytest.mark.book\ndef test_x():\n    (ROOT / 'memory' / 'decisions.jsonl').read_text()\n",
     {"test_x": True}),
    ("def test_x():\n    Path(__file__).parents[1].joinpath('memory', 'archive', 'eod-history.csv')\n",
     {"test_x": False}),
    ("ROOT = Path(__file__).resolve().parents[1]\n"
     "def _helper():\n    return sorted((ROOT / 'memory').glob('*-plan.json'))\n",
     {"<module>": False}),
    ("ROOT = Path(__file__).resolve().parents[1]\npytestmark = pytest.mark.book\n"
     "def _helper():\n    return (ROOT / 'portfolio.json')\n", {"<module>": True}),
    ("def test_x(tmp_path):\n    (tmp_path / 'portfolio.json').write_text('{}')\n", {}),
], ids=["unmarked direct read", "marked direct read", "joinpath from __file__",
        "helper globbing plans", "module-marked helper", "a temp book is not the book"])
def test_the_scan_sees_the_shapes_this_suite_uses(tmp_path, snippet, expected):
    source = tmp_path / "test_sample.py"
    source.write_text(snippet, encoding="utf-8")
    assert _book_readers(source) == expected


def test_the_fixture_built_from_the_real_tree_marks_its_users(request):
    """The conftest hook, checked on a real collected item rather than restated."""
    items = [item for item in request.session.items
             if "freshly_built_generation" in getattr(item, "fixturenames", ())]
    for item in items:
        assert item.get_closest_marker("book"), item.nodeid


def test_the_book_lane_is_the_book_files_and_nothing_else():
    for name in push_scope.BOOK_GLOBS:
        assert any(fnmatch.fnmatchcase(name, g) for g in push_scope.CODE_GLOBS), (
            f"{name} must stay in the code lane's globs: the book lane narrows "
            "what runs, it never removes a file from CI")
    assert push_scope.classify(["portfolio.json", "src/clawock/cli.py"])["book"] is False
    assert push_scope.classify(["memory/peer-map.json"])["book"] is False
