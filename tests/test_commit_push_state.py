"""maybe_commit must never report a push that did not reach origin as a success.

Both postflights used to return `(True, 'committed (push failed: ...)')`: the
caller read commit_ok=True as "published to origin", so a lost push left Pages
serving yesterday's data with a green exit code (#1450, #1451; fixed in #1457).

The first version of this gate asserted that no `return` whose message contains
the literal `push failed` yields True. That gate passes on the bug: restore the
old `return True, ...` and reword the message (`'committed (推送失败: ...)'`) and
all of it goes green, because nothing required it to find anything — the failure
mode the repo has hit before ("a count of 0 has two causes, and the gate only
credits the flattering one"). So the checks below:

  * find the push-failure branch STRUCTURALLY — the `push_with_rebase_retry()`
    call, the flag it binds, the `if <flag>:` that guards the success returns —
    and fail loudly when that shape is not found, instead of passing quietly;
  * feed every message maybe_commit can actually return through the module's own
    data-plane classifier and assert a return that did not reach origin never
    lands in a published state, whatever the wording is;
  * enumerate the harnesses that own a `maybe_commit`, so a new one cannot slip
    past the gate by not being on the list.
"""
import ast
import importlib
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"

#: module path -> the classifier that turns its maybe_commit outcome into a
#: data-plane state. `test_no_unlisted_maybe_commit` keeps this list complete.
MODULES = {
    "clawock/harness/brief_postflight.py": "classify_commit_outcome",
    "clawock/harness/report_postflight.py": "classify_data_plane",
}

#: Everything the panel and the ledger know how to read. `None` is
#: brief_postflight's "settles nothing, ask the dashboard build status file".
KNOWN_STATES = {
    None, "published", "current", "skipped",
    "committed_local", "failed", "publish_failed", "rebuild_failed",
    "unavailable",
}

#: The two states that claim origin has the data.
PUBLISHED_STATES = {"published", "current"}


def _maybe_commit(rel):
    tree = ast.parse((SRC / rel).read_text())
    fns = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "maybe_commit"]
    assert len(fns) == 1, f"{rel}: expected exactly one maybe_commit, found {len(fns)}"
    return fns[0]


def _returns_below(nodes):
    out = []
    for node in nodes:
        out.extend(n for n in ast.walk(node) if isinstance(n, ast.Return))
    return out


def _push_failure_returns(fn, rel):
    """Every `return` reachable once push_with_rebase_retry() reported failure."""
    for i, stmt in enumerate(fn.body):
        if not (isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Call)
                and getattr(stmt.value.func, "id", None) == "push_with_rebase_retry"):
            continue
        target = stmt.targets[0]
        assert isinstance(target, ast.Tuple) and isinstance(target.elts[0], ast.Name), (
            f"{rel}: push_with_rebase_retry()'s result is not unpacked into "
            f"(ok, output) — this gate can no longer tell which branch is the "
            f"failure one; teach it the new shape."
        )
        flag = target.elts[0].id
        rest = fn.body[i + 1:]
        guard = rest[0] if rest else None
        assert (isinstance(guard, ast.If)
                and isinstance(guard.test, ast.Name)
                and guard.test.id == flag), (
            f"{rel}: the statement after push_with_rebase_retry() is not "
            f"`if {flag}:` — this gate can no longer tell which branch is the "
            f"failure one; teach it the new shape."
        )
        return _returns_below(list(guard.orelse) + list(rest[1:]))
    return None


def _message_text(node):
    """A representative string for a return's message, literal or f-string."""
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "<runtime>"
                       for v in node.values)
    return ast.unparse(node)


@pytest.mark.parametrize("rel", sorted(MODULES))
def test_push_failure_never_returns_true(rel):
    """The branch taken when the push failed must not report success."""
    returns = _push_failure_returns(_maybe_commit(rel), rel)
    assert returns, (
        f"{rel}: no push_with_rebase_retry() call found in maybe_commit. Either "
        f"the push moved elsewhere or the function was renamed — until this gate "
        f"is pointed at the new push path it proves nothing, so it fails instead "
        f"of passing on zero findings."
    )
    for ret in returns:
        assert isinstance(ret.value, ast.Tuple), (
            f"{rel}: maybe_commit's push-failure branch returns "
            f"{ast.unparse(ret.value)}, not a (ok, message) tuple"
        )
        first = ret.value.elts[0]
        assert not (isinstance(first, ast.Constant) and first.value is True), (
            f"{rel}: maybe_commit reports success on a failed push: "
            f"{ast.unparse(ret.value)[:120]}"
        )


@pytest.mark.parametrize("rel", sorted(MODULES))
def test_every_outcome_is_classified_and_unreached_origin_is_never_published(rel):
    """Each message maybe_commit can return maps to a state, and only a landed
    push maps to a published one.

    This is the wording-proof half: renaming `push failed` cannot make the
    failure look published, because the assertion is about what the module's own
    classifier does with the message the module itself returns.
    """
    module = importlib.import_module(
        rel.removesuffix(".py").replace("/", ".")
    )
    classify = getattr(module, MODULES[rel])
    fn = _maybe_commit(rel)
    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
    assert len(returns) >= 4, (
        f"{rel}: maybe_commit has {len(returns)} returns; the outcomes this gate "
        f"is meant to enumerate are gone or moved"
    )
    seen_unlanded = 0
    for ret in returns:
        assert isinstance(ret.value, ast.Tuple), (
            f"{rel}: maybe_commit returns {ast.unparse(ret.value)}, not a tuple"
        )
        first, message = ret.value.elts[0], _message_text(ret.value.elts[1])
        ok = first.value if isinstance(first, ast.Constant) else None
        state = classify(ok, message)
        assert state in KNOWN_STATES, (
            f"{rel}: {classify.__name__}({ok!r}, {message!r}) -> {state!r}, "
            f"which no reader maps. Add it to the panel's vocabulary or return "
            f"an existing state."
        )
        if ok is True:
            continue
        seen_unlanded += 1
        assert state not in PUBLISHED_STATES, (
            f"{rel}: {message!r} does not reach origin but classifies as "
            f"{state!r} — the exact claim #1450/#1451 were about"
        )
    assert seen_unlanded, (
        f"{rel}: maybe_commit has no non-success return left to check"
    )


def test_no_unlisted_maybe_commit():
    """A new harness with its own maybe_commit joins the gate, not bypasses it."""
    found = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "def maybe_commit(" in path.read_text()
    }
    assert found == set(MODULES), (
        f"maybe_commit exists in {sorted(found - set(MODULES))} but is not covered "
        f"by this gate (or {sorted(set(MODULES) - found)} no longer defines one)"
    )
