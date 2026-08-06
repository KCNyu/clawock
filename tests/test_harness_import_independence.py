"""A module that imports `clawock` must put the checkout on the path itself.

`clawock` is not installed on the live host. Modules under `scripts/` reach it
only because something inserted the repository root into `sys.path` first. Two of
the three live importers did that explicitly; `_watchdog_common` inherited it as a
side effect of importing the `scripts/data/workspace.py` shim, which inserts the
root for its own 53 consumers.

That is a live hazard and a migration blocker at the same time. `_watchdog_common`
is imported by 15 modules including all three watchdogs, driven by 28 crontab
entries; if the shim's insert goes away — which is exactly what retiring the shim
means — every watchdog fails at *import* time. The backstop that exists to notice
a missing report goes missing first, and the crontab entry logs a traceback into
watchdog.cron.log.

Why this is a source-shape test and not an "import it in a subprocess" test: CI
installs the package (`pip install -e '.[test]'`), so the repository root is on
`sys.path` there no matter what any module does. A runtime import test would pass
in CI while the live host — the only environment without the install — is the one
at risk. It would look like coverage and protect nothing. The defect is visible in
the source, so the test reads the source.

Mutation check: deleting either insert turns this red, and so does resolving the
insert from `WS` (the workspace, which CLAWOCK_WORKSPACE may point elsewhere)
instead of from the checkout.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Expressions that denote the checkout root itself. `parents[2]` from a file two
# directories down is the root; the shim names it. `_CHECKOUT` is the name #269
# gave it across the 27 modules that stopped resolving code through the
# workspace, and it is bound to that same expression everywhere it appears.
# `WS` is deliberately absent: it is the workspace, and a foreign workspace holds
# market data, not our package. Naming a form here does not weaken the check —
# the `"/" in arg` guard below still rejects `_CHECKOUT / 'scripts' / 'data'`,
# which is a directory below the root and does not make `clawock` importable.
CHECKOUT_ROOT_FORMS = ("parents[2]", "_REPO_ROOT", "_CHECKOUT")


def _inserts_checkout_root(node: ast.Call, source: str) -> bool:
    """Whether this call is `sys.path.insert(..., <checkout root>)`."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "insert"):
        return False
    if not (isinstance(func.value, ast.Attribute) and func.value.attr == "path"):
        return False
    if len(node.args) < 2:
        return False
    arg = ast.get_source_segment(source, node.args[1]) or ""
    # A path *below* the root (…/'scripts'/'data') does not make clawock
    # importable, so a join disqualifies the call however it is spelled.
    if "/" in arg:
        return False
    return any(form in arg for form in CHECKOUT_ROOT_FORMS)


def test_clawock_importers_do_not_inherit_their_sys_path():
    offenders = []
    for path in sorted(ROOT.glob("scripts/**/*.py")):
        source = path.read_text()
        if "clawock" not in source:
            continue
        tree = ast.parse(source)
        import_line = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("clawock"):
                import_line = node.lineno if import_line is None else min(import_line, node.lineno)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("clawock"):
                        import_line = node.lineno if import_line is None else min(import_line, node.lineno)
        if import_line is None:
            continue
        inserts = [
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _inserts_checkout_root(node, source)
        ]
        if not any(lineno < import_line for lineno in inserts):
            offenders.append(f"{path.relative_to(ROOT)}:{import_line}")

    assert not offenders, (
        "these modules import clawock without putting the checkout root on "
        f"sys.path first, so the import resolves only by side effect: {offenders}"
    )
