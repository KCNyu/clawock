"""Every third-party import is declared, and every extra we advertise exists.

Two failures with the same shape, found the same week:

* `yfinance` is the last hop of both quote chains and appears in no dependency
  table at all, so `pip install clawock` produced a package whose bottom
  fallback raises ImportError on the one day the other hops are rate-limited
  (#1325). The import is lazy and inside a `try`, so nothing is loud about it.
* `[project.optional-dependencies].compute` was an empty list that three call
  sites asked for, one of them a composite action documenting it to users as
  "the heavier dependency set" (#1321). pip installs an empty extra happily.

Both are invisible to a green test run because neither changes behaviour on a
machine that happens to have the package. What follows enumerates from the
source in each direction — imports in the tree, extras named in the repo — so
the next one fails here instead of in production.
"""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

# Import name -> distribution name, for the few that differ. Kept explicit: a
# guess ("PIL is probably a dist called PIL") is how a declaration gate passes
# while the package is still missing.
DISTRIBUTION = {
    "PIL": "pillow",
    "google": "google-auth",
    "yaml": "pyyaml",
}

# Scanned trees. `tests/` is deliberately out: conftest puts ops/ci, ops/host
# and ops/growth on sys.path, so a test importing `push_scope` looks like a
# third-party root and the gate would be noise instead of a gate.
SCANNED = ("src", "ops")


def _declared_distributions() -> set[str]:
    project = PYPROJECT["project"]
    requirements = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        requirements.extend(extra)
    # `name>=1.2`, `name[extra]>=1`, `name` -> `name`, normalised per PEP 503.
    return {re.split(r"[<>=!~\[; ]", req, maxsplit=1)[0].strip().lower().replace("_", "-")
            for req in requirements}


def _imported_roots() -> dict[str, set[str]]:
    roots: dict[str, set[str]] = {}
    for tree in SCANNED:
        base = ROOT / tree
        local = {path.stem for path in base.rglob("*.py")}
        for path in base.rglob("*.py"):
            module = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(module):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    root = name.split(".")[0]
                    if root in sys.stdlib_module_names or root == "clawock" or root in local:
                        continue
                    roots.setdefault(root, set()).add(str(path.relative_to(ROOT)))
    return roots


def test_every_third_party_import_is_declared_somewhere_in_pyproject():
    declared = _declared_distributions()
    undeclared = {
        root: sorted(files)
        for root, files in _imported_roots().items()
        if DISTRIBUTION.get(root, root).lower().replace("_", "-") not in declared
    }
    assert not undeclared, (
        "these third-party imports are in the tree but in no dependency table, "
        "so an install that follows pyproject.toml cannot run the code paths "
        f"that reach them: {undeclared}. Add them to `dependencies` if the "
        "package needs them to work, or to an extra if a caller can opt in "
        "(#1325); the reason belongs in a comment next to the line.")


def test_every_extras_selector_named_in_the_repo_resolves_to_a_real_extra():
    """`.[name]` anywhere in the repo must be an extra that exists and installs something.

    An empty extra is worse than a missing one: pip succeeds, CI stays green,
    and whoever read the line believes they installed the heavier set (#1321).
    """
    extras = PYPROJECT["project"].get("optional-dependencies", {})
    # Prose counts: the damage in #1321 was a composite action recommending an
    # extra, not only the lines that ran pip. JSON is the exception — this repo
    # keeps schemas in it, and a regex `"^\\d+\\.[0-9]{2}$"` is not a selector —
    # so only the devcontainer, which really does name extras, is read.
    tracked = [
        path for path in ROOT.rglob("*")
        if (path.suffix in {".sh", ".yml", ".yaml", ".toml", ".md", ".cfg"}
            or (path.suffix == ".json" and "devcontainer" in path.name))
        and ".git/" not in str(path) and "node_modules" not in str(path)
    ]
    offenders: dict[str, list[str]] = {}
    for path in tracked:
        text = path.read_text(encoding="utf-8", errors="ignore")
        # `?.[x]` is JavaScript optional chaining in a heredoc, not an extra.
        for match in re.finditer(r"(?<![\w?])\.\[([A-Za-z0-9_.,-]+)\]", text):
            # `.[market,test]` is one selector naming two extras (devcontainer).
            for name in match.group(1).split(","):
                name = name.strip()
                if extras.get(name):
                    continue
                reason = "is not an extra" if name not in extras else "is an empty list"
                offenders.setdefault(f"{name} ({reason})", []).append(
                    str(path.relative_to(ROOT)))
    assert not offenders, (
        f"these extras selectors install nothing they promise: {offenders}")


def test_the_market_extra_carries_the_fallback_the_quote_chains_end_on():
    """Named so the next person deleting it has to answer for the chain.

    yfinance is tier 4 for HK and provider 5 for US — the hop that exists
    precisely because the four above it are rate-limited that morning.
    """
    market = PYPROJECT["project"]["optional-dependencies"].get("market", [])
    assert any(req.startswith("yfinance") for req in market), (
        "the market extra no longer declares yfinance; both quote chains still "
        "import it lazily, so removing it deletes their last hop silently")
