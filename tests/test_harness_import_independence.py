"""A script run by path must put the checkout on `sys.path` itself.

The original subject was `scripts/`, where nothing was installed and the live
watchdogs reached `clawock` only through a shim's side effect. #429 deleted that
directory and this scan went with it — it kept globbing `scripts/**/*.py` and
walking zero files, which passes exactly like a clean tree.

The rule did not disappear with the directory; its population moved. `clawock` is
installed now (#364), but into a venv, and every `ops/` entry point documents
itself as `python3 ops/<...>.py` — system python, which has no such install. On
2026-08-10 `ops/host/backfill_snapshot_realized.py` was the one module that had
lost its two bootstrap lines in the move, so the command printed in its own
docstring raised ModuleNotFoundError. That is the third time this same file has
had this defect (it was also broken by the move into `scripts/legacy`, fixed in
#290), which is why the check is a discovery over the directory rather than a
list of known entry points.

Why a source-shape test and not "import it in a subprocess": CI installs the
package, so the import succeeds there no matter what the module does. A runtime
test would pass in CI while the environment actually at risk — an operator's
plain `python3` — is the one it cannot see. The defect is visible in the source,
so the test reads the source.

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
# Substrings on purpose: `ROOT` also covers `_REPO_ROOT`, `CHECKOUT` also
# covers `_CHECKOUT`. Matching the exact private spellings is how a rename
# turns a live guard into a silent pass.
CHECKOUT_ROOT_FORMS = ("parents[2]", "ROOT", "CHECKOUT")

# Scripts an operator runs by path. Package modules are imported through an
# installed distribution and must NOT bootstrap themselves — requiring it there
# would be the opposite rule.
ENTRY_POINTS = ROOT / "ops"


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
    scripts = [p for p in sorted(ENTRY_POINTS.rglob("*.py"))
               if "__pycache__" not in p.parts]
    # Anti-vacuity: an empty scan is how this stopped working in the first place.
    assert len(scripts) > 10, f"only {len(scripts)} entry points found — did ops/ move?"

    offenders = []
    for path in scripts:
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


def test_installed_instance_adapter_never_imports_product_from_the_checkout():
    """The adapter may still reach workspace-owned data modules during the next
    migration slice; product code must already come from its declared wheel
    dependency, never from a repository-relative `src/` insertion.
    """
    root = ROOT / "instances" / "kcnyu" / "src" / "clawock_kcnyu"
    offenders = []
    for path in sorted(root.rglob("*.py")):
        source = path.read_text()
        if "Path(__file__)" in source and (
            ' / "src"' in source or " / 'src'" in source
        ):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"adapter reaches product source by checkout path: {offenders}"
