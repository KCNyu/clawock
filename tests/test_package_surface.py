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

It did not catch the recurrence. `clawock.providers` and `clawock.tools` were
missing from every wheel built after they were added, and this file could not see
it: the scan globbed `src/clawock/*.py`, top level only, and the declaration check
read the package list rather than the artifact. `tests/test_wheel_contains_the_
package.py` now builds and imports the real thing; these checks stay for the
cheap, fast signal, corrected to walk the whole package.
"""
import ast
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "clawock"


def _first_party_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    stdlib = set(sys.stdlib_module_names) | {"requests", "numpy", "PIL", "yfinance"}
    return {name for name in names if name not in stdlib}


# Empty, and asserted empty rather than deleted: the one tracked escape was
# `OpenClawRuns.list_runs()` lazily importing `_watchdog_common` from
# `scripts/harness/`, which is not in the wheel — importable from an
# installation, raising the first time it was called. The cron-state chain moved
# into `clawock.providers.openclaw` (#273), so the set is empty and stays the
# thing a new escape has to break.
KNOWN_ESCAPES: dict[str, set[str]] = {}


def test_nothing_the_package_imports_lives_outside_it():
    escapes = {}
    for path in sorted(PKG.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for name in _first_party_imports(path):
            if name != "clawock":
                escapes.setdefault(
                    path.relative_to(PKG).as_posix(), set()).add(name)

    assert escapes == KNOWN_ESCAPES, (
        "the wheel contains only the clawock package, so a first-party import "
        "that resolves outside it crashes on install. Expected only the tracked "
        f"escape {KNOWN_ESCAPES}, found {escapes}")


def test_the_entry_point_is_inside_the_package():
    config = tomllib.load(open(ROOT / "pyproject.toml", "rb"))["project"]
    module = config["scripts"]["clawock"].split(":")[0]

    # Deliberately no longer compares against the declared package list. That
    # check read the declaration and passed for as long as the declaration was
    # wrong; whether the entry point is really shipped is now settled by building
    # the wheel and importing out of it.
    assert module.split(".")[0] == PKG.name, (
        f"entry point {module} is not inside the package directory {PKG.name}")
    assert (PKG / "__init__.py").exists(), "clawock must be a real package"
