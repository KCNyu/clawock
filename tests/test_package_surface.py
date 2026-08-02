"""The installable surface has to be self-contained.

The first version of this packaging shipped a wheel containing only
`clawock_cli.py`, while that module reached into `scripts/data/workspace.py`
through a sys.path hack for code the wheel did not contain. Installed outside
the source checkout it died with `ModuleNotFoundError: No module named
'workspace'`. `pip install -e .` hid it completely — an editable install leaves
the source tree on sys.path, so the check that was supposed to prove
installability proved nothing.

Structural rather than a real wheel build, so it stays cheap enough to run on
every PR while still catching that exact class.
"""
import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "clawock"


def _first_party_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    stdlib = set(sys.stdlib_module_names) | {"requests", "numpy", "PIL"}
    return {name for name in names if name not in stdlib}


def test_nothing_the_package_imports_lives_outside_it():
    escapes = {}
    for path in sorted(PKG.glob("*.py")):
        for name in _first_party_imports(path):
            if name != "clawock":
                escapes.setdefault(path.name, set()).add(name)

    assert not escapes, (
        "the installed wheel contains only the clawock package, so a first-party "
        f"import that resolves outside it crashes on install: {escapes}")


def test_the_entry_point_and_the_packaged_directory_agree():
    config = tomllib.load(open(ROOT / "pyproject.toml", "rb"))["project"]
    packages = tomllib.load(open(ROOT / "pyproject.toml", "rb"))[
        "tool"]["setuptools"]["packages"]

    module = config["scripts"]["clawock"].split(":")[0]

    assert module.split(".")[0] in packages, (
        f"entry point {module} is not inside a packaged directory {packages}")
    assert (PKG / "__init__.py").exists(), "clawock must be a real package"
