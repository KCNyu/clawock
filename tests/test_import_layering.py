"""The package import graph, held where it is.

#814 measured `src/clawock`: 137 modules, ~345 intra-package imports, and two
package-level dependency cycles tangling nine subpackages. Nothing in the suite
constrained import direction — the existing boundary tests
(`test_quant_package_boundary`, `test_harness_import_independence`,
`test_core_utilities_moved`) are about packaging and ownership, about whether
code ships from the wheel, not about which layer may import which.

This is a ratchet, not a fix. The cycles that exist are listed below and
tolerated; a cycle that is NOT listed fails. The list may only shrink — a test
asserts that too, so "just add it to the allowlist" is not a way past this.

The direction that matters: a cycle is cheap to add and expensive to remove.
`harness` imported `clawock.cli` for a constant table, which is the most
clear-cut inversion in the package, and nothing noticed for as long as it took
someone to go looking.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PKG = "clawock"

# Package-level cycles that exist today, each as a frozenset of subpackages.
# Every entry is a debt with a name. Removing one means deleting its line here;
# nothing may ever be added.
KNOWN_PACKAGE_CYCLES: set[frozenset[str]] = set()
# Empty as of #814. Both entries that used to live here are gone:
#
#   decision <-> evidence <-> market_data <-> portfolio
#   automation <-> cli <-> harness <-> publish <-> workflows
#
# Four modules turned out to be foundation-shaped — zero clawock imports, needed
# by several packages — and were simply in the wrong package: `sessions` and
# `instruments` (13 importers between them across decision and market_data),
# `runtime_model` (a dataclass `workflows` had to import the harness to name),
# and `provenance` (a manifest validator `decision.earnings` reached into
# `evidence` for). The rest was the guardrail arithmetic that `publish` climbed
# into `harness` to call, and `load_request`, which belongs beside the workflow
# contract it resolves.
#
# Adding an entry back means a package cycle was reintroduced. Do not.

# Module-level cycles. `tools` is the registry pattern and is not a defect: the
# package __init__ owns the base classes, submodules import them, and
# build_registry() imports the submodules lazily. The other two are real.
KNOWN_MODULE_CYCLES = {
    frozenset({"clawock.tools", "clawock.tools.context_tools"}),
    frozenset({"clawock.decision.ledger", "clawock.decision.record"}),

}


def _modules() -> dict[str, Path]:
    out = {}
    for path in sorted((SRC / PKG).rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        out[".".join(parts)] = path
    return out


def _graph() -> dict[str, set[str]]:
    """Intra-package imports, parsed rather than grepped.

    A grep cannot tell `from clawock.decision import ledger` (a module) from
    `from clawock.decision import ACTIVE_ACTIONS` (a name in the package
    __init__), and getting that wrong invents edges that are not there.
    """
    mods = _modules()

    def nearest(name: str) -> str | None:
        while name and name not in mods:
            if "." not in name:
                return None
            name = name.rsplit(".", 1)[0]
        return name or None

    edges: dict[str, set[str]] = defaultdict(set)
    for name, path in mods.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = nearest(alias.name)
                    if target and target != name and target.startswith(PKG):
                        edges[name].add(target)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    own = name.split(".")
                    if mods[name].name != "__init__.py":
                        own = own[:-1]
                    if node.level > 1:
                        own = own[: len(own) - (node.level - 1)]
                    base = ".".join(own + ([base] if base else []))
                if not base.startswith(PKG):
                    continue
                hit = False
                for alias in node.names:
                    target = nearest(f"{base}.{alias.name}")
                    if target and target != name:
                        edges[name].add(target)
                        hit = True
                if not hit:
                    target = nearest(base)
                    if target and target != name:
                        edges[name].add(target)
    for name in mods:
        edges.setdefault(name, set())
    return edges


def _cycles(adj: dict[str, set[str]]) -> list[frozenset[str]]:
    """Strongly connected components of size > 1, iteratively (Tarjan).

    Iterative because a recursive walk over 137 modules is a stack risk for a
    test that must never be the flaky one.
    """
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    found: list[frozenset[str]] = []
    counter = 0

    for root in sorted(adj):
        if root in index:
            continue
        work = [(root, iter(sorted(adj[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack[child] = True
                    work.append((child, iter(sorted(adj[child]))))
                    advanced = True
                    break
                if on_stack.get(child):
                    low[node] = min(low[node], index[child])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                component = []
                while True:
                    popped = stack.pop()
                    on_stack[popped] = False
                    component.append(popped)
                    if popped == node:
                        break
                if len(component) > 1:
                    found.append(frozenset(component))
    return found


@pytest.fixture(scope="module")
def graph() -> dict[str, set[str]]:
    return _graph()


def test_the_graph_is_actually_populated(graph):
    """Every assertion below passes vacuously against an empty graph, and an
    import-parser that silently matches nothing is exactly the failure mode this
    repository keeps finding in its own gates."""
    assert len(graph) > 100, "the module scan found almost nothing"
    assert sum(len(v) for v in graph.values()) > 200


def test_no_module_cycle_beyond_the_known_ones(graph):
    new = [c for c in _cycles(graph) if c not in KNOWN_MODULE_CYCLES]
    assert not new, (
        "new import cycle(s) between modules: "
        + "; ".join(" <-> ".join(sorted(c)) for c in new)
        + ". A cycle is cheap to add and expensive to remove — break it now, or "
          "argue for it in #814 before listing it here."
    )


def test_no_package_cycle_beyond_the_known_ones(graph):
    def pkg(module: str) -> str:
        parts = module.split(".")
        return parts[1] if len(parts) > 1 else "(root)"

    coarse: dict[str, set[str]] = defaultdict(set)
    for src, targets in graph.items():
        for target in targets:
            if pkg(src) != pkg(target):
                coarse[pkg(src)].add(pkg(target))
    for node in list(coarse):
        coarse.setdefault(node, set())

    new = [c for c in _cycles(coarse) if c not in KNOWN_PACKAGE_CYCLES]
    assert not new, (
        "new dependency cycle(s) between subpackages: "
        + "; ".join(" <-> ".join(sorted(c)) for c in new)
    )


def test_nothing_below_the_cli_imports_the_cli(graph):
    """`cli` is the entry point. Anything importing it is upside down.

    This had two violations: both harness preflights pulled `PACKAGED_UTILITIES`
    out of `clawock.cli`, which is a data table, not an entry point. It now
    lives in `clawock.utilities`, which imports nothing at all.
    """
    offenders = sorted(m for m, targets in graph.items()
                       if f"{PKG}.cli" in targets and m != f"{PKG}.__main__")
    assert not offenders, (
        f"these import the CLI entry point from below it: {offenders}. "
        "If it is data they need, it belongs in a module the CLI imports, not "
        "the other way round."
    )


@pytest.mark.parametrize("leaf", ["workspace", "safe_io", "json_repair", "utilities",
                                  "credentials", "sessions"])
def test_the_foundation_modules_stay_leaves(graph, leaf):
    """These are imported from everywhere — workspace by 67 modules, safe_io by
    30. A single import added here reaches the whole package, and the reason
    `clawock.utilities` exists at all is that a table with 24 consumers was
    living somewhere that could not be imported from below."""
    name = f"{PKG}.{leaf}"
    assert name in graph, f"{name} disappeared; update this list deliberately"
    assert not graph[name], (
        f"{name} must import nothing from clawock, now imports {sorted(graph[name])}"
    )


def test_the_allowlists_only_ever_shrink():
    """The counts are written down so that adding an entry is a visible edit to
    a number, not a quiet append to a set."""
    assert not KNOWN_PACKAGE_CYCLES, (
        "the package graph is a DAG as of #814; an entry here means a cycle came back"
    )
    assert len(KNOWN_MODULE_CYCLES) <= 2, (
        "a module cycle was added to the allowlist; #814 is about removing these"
    )


def test_no_new_test_writes_to_published_state(request):
    """A test that writes into the checkout changes what later tests see.

    #816: `assets/data/workflow-outcomes.json` is untracked and absent in a
    clean tree. One test created it, it persisted between runs, and it armed an
    assertion in a different module that is dormant otherwise — a failure that
    only ever appeared in full-suite order and passed on its own, twice, before
    anyone could say which test was responsible.

    This runs last by name and reads the attribution log the conftest fixture
    builds.

    On parallelism, measured rather than assumed: with the four other writers
    isolated, `-n 4` does pass — but not safely. Every xdist worker gets its own
    session, so four workers each run the dashboard rebuild against the same
    four files concurrently, and that it passed is luck rather than a property.
    Turning `-n auto` on needs that rebuild to be per-session-shared or
    group-pinned first; it is not just a flag.
    """
    from conftest import _WRITE_LOG, _tolerated  # noqa: PLC0415

    if not _WRITE_LOG:
        pytest.skip("no writes recorded — this ran outside a full-suite session")

    # Under xdist the attribution is not trustworthy and neither is the result:
    # every worker gets its own session, so N workers each run the dashboard
    # rebuild against the same four files at once, and a write by one worker
    # lands in whatever test another worker happened to be running. Measured on
    # `-n 4`: this named test_hook_entrypoints_can_import_clawock, which writes
    # nothing. The suite is not parallel-safe yet — see the module docstring —
    # and pretending to check it here would be worse than saying so.
    if getattr(request.config, "workerinput", None) is not None:
        pytest.skip("write attribution is not valid under xdist; see #816")

    offenders = sorted({e["test"] for e in _WRITE_LOG if not _tolerated(e["test"])})
    assert not offenders, (
        "these tests wrote into the checkout and are not on the tolerated list: "
        f"{offenders}. Point them at an isolated workspace "
        "(monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))) rather than "
        "adding them to TOLERATED_WRITERS — that list is meant to shrink."
    )


def test_the_tolerated_writer_list_only_shrinks():
    from conftest import TOLERATED_WRITERS  # noqa: PLC0415

    assert len(TOLERATED_WRITERS) <= 1, (
        "a test was added to the write allowlist. The one entry left is the "
        "session dashboard rebuild, which is supposed to run against the real "
        "tree; everything else now isolates its workspace (#816)."
    )


def test_no_workflow_or_script_invokes_a_module_by_a_path_that_moved():
    """`python3 -m clawock.x.y` in a workflow is an import the AST scan cannot see.

    #814 moved four modules and the graph came back clean, because a `-m`
    invocation in harness-regression.yml is a string, not an import. CI caught
    it — after the PR was opened, on a step that only runs when code changes.
    A grep is cheap and runs with everything else.
    """
    moved = {
        "clawock.portfolio.instruments": "clawock.instruments",
        "clawock.market_data.sessions": "clawock.sessions",
        "clawock.evidence.research_provenance": "clawock.provenance",
        "clawock.portfolio.shadow": "clawock.decision.shadow",
    }
    haystacks = []
    for pattern in ("*.yml", "*.yaml", "*.sh", "*.md", "*.json"):
        for base in (ROOT / ".github", ROOT / "ops", ROOT / "config", ROOT / "skills",
                     ROOT / "docs"):
            haystacks.extend(base.rglob(pattern))

    offenders = []
    for path in haystacks:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for old, new in moved.items():
            if old in text:
                offenders.append(f"{path.relative_to(ROOT)} still names {old} (now {new})")
    assert not offenders, offenders
