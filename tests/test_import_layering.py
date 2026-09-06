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
import inspect
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
KNOWN_MODULE_CYCLES: set[frozenset[str]] = set()
# Empty as of #814. Both entries that were here are gone:
#
#   tools <-> tools.context_tools          — the registry pattern. Common enough
#       to read as idiomatic, and `build_registry` deferred its import so it
#       worked, but a cycle all the same. `tools.base` now holds the three
#       definitions every tool module needs, so both sides sit above it.
#   decision.ledger <-> decision.record    — `record` appends through `ledger`,
#       and `ledger` reached back to validate one row type behind a
#       function-level import. The schema moved to `decision.mind_record`.
#
# A function-level import is not a fix for a cycle; it is a cycle that starts
# working. Both of these were that.

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
    assert not KNOWN_MODULE_CYCLES, (
        "the import graph has no cycles at all as of #814 — module or package. "
        "An entry here means one came back."
    )


def test_the_write_guard_has_no_position_in_the_collection_order(request):
    """The guard moved to `pytest_sessionfinish` (#1089).

    It used to be this test, whose own docstring claimed "this runs last by
    name". It was not last — pytest collects by path and `test_i...` is followed
    by `test_j` through `test_w`, including `test_validate_sidecars.py`.
    Measured 2026-08-26: a full suite rendered

        tests/test_validate_sidecars.py::test_real_committed_dashboard_passes  <-- NEW

    and failed for something else entirely. A writer in any module sorting after
    the guard was invisible to it, and the dashboard-shaped modules — the ones
    most likely to write — all live there.

    What is left here is the reason it moved, plus the attribution log's own
    shape. The enforcement is a session hook, which nothing can sort after.

    On parallelism, measured rather than assumed, twice — and the second
    measurement reversed the first. While the top twelve tests were
    subprocess-bound waiting on network and the live host, `-n 4` bought
    5-10% (175/182/191s against ~195s serial) and xdist stayed off. #1362 took
    that waiting out, #1365 gave the session rebuild its own output tree, and
    then `-n auto` was worth it: CI's pytest step went 197s -> 129s. It is on in
    `ci.yml` now, which is why every shared mutable output in this suite is a
    flake class rather than an inefficiency.
    """
    import conftest  # noqa: PLC0415

    assert hasattr(conftest, "pytest_sessionfinish"), (
        "the enforcement must be a session hook; a test can always be sorted "
        "after by adding a module with a later name")
    # Behaviour, not a grep over the hook's source. The substring form said
    # "`_tolerated` appears in `pytest_sessionfinish`", which stopped being true
    # the moment the verdict moved into a helper — a refactor with no behaviour
    # change turned this red, which is a test asserting the shape of the code
    # rather than what it does.
    # The allowlist is empty now, so the interesting cases are "nothing wrote"
    # and "something did". A tolerated entry is still constructed rather than
    # taken from the set, because the mechanism has to keep working the day
    # someone argues one back in.
    intruder = {"test": "tests/test_made_up.py::test_writes", "created": [],
                "removed": [], "changed": ["memory/decisions.jsonl"]}

    assert conftest._offenders([]) == set()
    assert conftest._offenders([intruder]) == {intruder["test"]}
    assert conftest._tolerated(intruder["test"]) is False

    # Excused by PATH, not by test name. `record_preservation` appends build
    # telemetry to `memory/.tmp/preserve-absent-*.jsonl` against WS_ROOT on
    # purpose, so `--out-dir` does not move it and the session rebuild trips this
    # watcher once per run. Excusing the file keeps that quiet; excusing the test
    # would have excused everything else it touches, which is the shape the old
    # `TOLERATED_WRITERS` had and the reason it could not be trusted under -n.
    telemetry = {"test": "tests/test_dashboard_payload_size.py::test_payload_stays_under_the_published_cap",
                 "created": ["memory/.tmp/preserve-absent-2026-09-06.jsonl"],
                 "removed": [], "changed": []}
    also_wrote = {**telemetry, "changed": ["memory/decisions.jsonl"]}
    assert conftest._offenders([telemetry]) == set()
    # The other excused path: `money_checker.sh` writes the integrity report into
    # the checkout because the gate's whole point is checking the repo being
    # pushed, and `restores_untracked_artifact` puts it back. Serially the pair
    # lands inside one window and records nothing; under `-n` a bystander sees
    # the middle of it, which is what CI reported on 2026-09-06.
    transient = {"test": "tests/test_readme_renders_off_github.py::test_anything",
                 "created": ["assets/data/integrity_report.json"],
                 "removed": ["assets/data/.tmp-abc123.json"], "changed": []}
    assert conftest._offenders([transient]) == set()
    assert conftest._offenders([also_wrote]) == {also_wrote["test"]}, (
        "excusing the telemetry file must not excuse the test that wrote it")
    assert "exitstatus" in inspect.signature(conftest.pytest_sessionfinish).parameters, (
        "the hook must be able to fail the run")


def test_the_verdict_is_reached_once_over_the_whole_run():
    """Under `-n` the guard used to be absent, not merely imprecise.

    `pytest_sessionfinish` returned on every worker — attribution across four
    partial logs looked meaningless — and the controller's own log is empty
    because it runs no tests. So `pytest -n` enforced nothing at all, and the
    only thing that said so was a comment (#1364).

    Workers now ship their log through `workeroutput` and the controller joins
    them, which is what makes one verdict over the whole run possible. With the
    session rebuild building into its own directory, nothing in this suite is
    supposed to write into the checkout any more, so "this run wrote" is a sound
    conclusion in either mode — only the naming needs a serial run, and the
    parallel branch says so instead of pretending.
    """
    import conftest  # noqa: PLC0415

    source = inspect.getsource(conftest.pytest_sessionfinish)
    assert "_WRITES_FROM_WORKERS" in source, (
        "the verdict must join the workers' logs before deciding anything")
    assert "workeroutput" in source, (
        "a worker must ship its log rather than judging on its own partial view")
    assert hasattr(conftest, "pytest_testnodedown"), (
        "the controller needs the join hook; without it every worker's log is "
        "dropped and -n enforces nothing")


def test_restoring_an_unchanged_artifact_does_not_touch_it(tmp_path, monkeypatch):
    """The restore must be able to be a no-op, or it is itself a writer.

    `publish_owned_artifacts_are_left_as_found` is session-scoped, and under
    `-n` a session is a worker — so a restore that rewrites unconditionally
    lands the same bytes with a new mtime while the other workers are mid-test,
    and the write guard, which watches (size, mtime_ns), records the four
    payloads as changed against whoever happened to be running. Two CI runs on
    2026-09-06 named four different innocent modules between them.
    """
    import conftest  # noqa: PLC0415

    artifact = tmp_path / "assets" / "data" / "overview.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b'{"kept": true}')
    monkeypatch.setattr(conftest, "ROOT", tmp_path)
    before = {"assets/data/overview.json": artifact.read_bytes()}
    stat_before = artifact.stat()

    assert conftest._restore_publish_owned(before) == [], (
        "an unchanged artifact was rewritten; that write is what the guard sees")
    assert artifact.stat().st_mtime_ns == stat_before.st_mtime_ns

    # And it still restores — the no-op must not have been bought by doing
    # nothing at all.
    artifact.write_bytes(b'{"clobbered": true}')
    assert conftest._restore_publish_owned(before) == ["assets/data/overview.json"]
    assert artifact.read_bytes() == b'{"kept": true}'


def test_the_tolerated_writer_list_is_empty_and_stays_empty():
    from conftest import TOLERATED_WRITERS  # noqa: PLC0415

    assert TOLERATED_WRITERS == set(), (
        f"a test was added to the write allowlist: {sorted(TOLERATED_WRITERS)}. "
        "The last entry left when the session rebuild moved to its own "
        "--out-dir (#1364), and an empty list is what lets the write guard "
        "reach a verdict under -n as well as serially — one exception and the "
        "guard is back to being unable to tell a writer from a bystander. Point "
        "the test at an isolated workspace instead."
    )


def test_no_workflow_or_script_invokes_a_module_by_a_path_that_moved():
    """`python3 -m clawock.x.y` in a workflow is an import the AST scan cannot see.

    #814 moved four modules and the graph came back clean, because a `-m`
    invocation in ci.yml is a string, not an import. CI caught
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
