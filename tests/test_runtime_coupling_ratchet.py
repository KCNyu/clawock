"""How many places know which agent runtime we are on.

The goal is a standard, migratable harness — not something parasitic on one
runtime. That is either a fact or a wish, and the difference is countable: if
every module knows it is on OpenClaw, "it happens to run on OpenClaw" is
marketing; if only the adapter knows, it is architecture.

This is a ratchet, not a rewrite. Rewriting all the sites at once would touch
the watchdogs and system_check — the parts that tell us the live system is
healthy — which is a bad trade on a money system. So: record the count, fail if
it rises, lower it as consumers move behind `clawock.providers`.

Counting rule, and it matters
-----------------------------
A *label* naming `openclaw` as one source among several is the pattern we want,
not debt: `cron_timeline.py` already takes `--source gha|openclaw|crontab` and
treats all three as peers. A text matcher would punish that file and reward
deleting the wrong thing.

The first version of this file said exactly that and then classified by
substring anyway (`value.startswith("openclaw ")`), so it counted `raise
RuntimeError("openclaw cron list failed: …")` and `r.add('openclaw config', …)`
as coupling while missing both `["openclaw", "cron", …]` argv vectors — the
only paths in the repository that *write* OpenClaw's schedule. Walking the AST
does not help when the predicate on the node is a substring test. So the
classifier now asks what the site *does*:

1. an argv vector whose `argv[0]` is `openclaw`, or a shell string handed to
   `subprocess`/`os.system` whose first word is;
2. a use of `OPENCLAW_BIN` — it exists to be executed;
3. a filesystem path naming openclaw: its home, its state DB, its config, its
   install directory. Reading another runtime's private files is coupling
   whether or not we spawn it.

Prose is none of those. An error message, a result label, a docstring and a
`--source` choice all stay uncounted, which is what keeps the ratchet from
rewarding the deletion of an explanation.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Where knowing about OpenClaw is correct: that is what an adapter is for.
ADAPTER = ROOT / "clawock" / "providers"

RUNTIME = "openclaw"

# Lower this as consumers move behind clawock.providers. It must never rise.
# The per-file split is in the failure message; keeping a copy here only
# creates a second thing to forget to update.
#
# This baseline is not comparable to the 8 the substring classifier reported:
# that number counted six error strings and missed both cron writes. Nothing
# regressed between the two — the earlier count was measuring the wrong thing,
# so 14 was the first number here worth quoting. 14 → 13 when the cron-state
# chain moved into the adapter (#273).
BASELINE = 13

_SPAWNERS = {"run", "call", "check_call", "check_output", "Popen", "system", "getoutput"}


def _is_spawn(call: ast.Call) -> bool:
    """Whether this call hands its first argument to the OS to execute."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr in _SPAWNERS
    return isinstance(func, ast.Name) and func.id in _SPAWNERS


def _names_bound_to_the_binary(tree: ast.AST) -> set[str]:
    """Local names for the provider's binary path, including `as` aliases.

    Importing the constant is not itself a use — `_watchdog_common` re-exports
    it for `system_check`, which is the migration order we chose. Executing it
    is. Following the alias keeps `import OPENCLAW_BIN as BIN` from being a way
    to go green without moving anything.
    """
    bound = {"OPENCLAW_BIN"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "OPENCLAW_BIN" and alias.asname:
                    bound.add(alias.asname)
    return bound


def _is_runtime_path(value: str) -> bool:
    """A filesystem path that names openclaw: its home, state, config, install."""
    if RUNTIME not in value or " " in value.strip():
        return False
    if "/" in value:
        # `/root/.openclaw` is a dotted home directory, `node_modules/openclaw`
        # an install, `state/openclaw.sqlite` a private database. All three name
        # it as a path segment; a sentence mentioning it does not.
        return any(part.lstrip(".") == RUNTIME or part.lstrip(".").startswith(f"{RUNTIME}.")
                   for part in value.split("/"))
    # A bare filename still points at its private storage: `openclaw.sqlite`.
    # A bare `openclaw` is a label — the `--source` choice, a channel name —
    # and counting it is the mistake this classifier exists to stop making.
    return value.startswith(f"{RUNTIME}.")


def _docstring_ids(tree: ast.AST) -> set[int]:
    """A docstring that *describes* an OpenClaw call is documentation, not a
    call — counting it punishes writing the comment, and the cheapest way to go
    green is deleting the explanation."""
    ids = set()
    for holder in ast.walk(tree):
        if isinstance(holder, (ast.Module, ast.ClassDef, ast.FunctionDef,
                               ast.AsyncFunctionDef)):
            body = getattr(holder, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def _enumeration_ids(tree: ast.AST) -> set[int]:
    """Lists that enumerate peer names rather than build a command.

    `choices=['openclaw', 'gha', 'crontab']` is the multi-source design we want
    and must never be counted; it is a list of literal strings whose head
    happens to be the runtime.
    """
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in ("choices", "source", "sources"):
                    ids.add(id(keyword.value))
    return ids


def _is_argv_vector(node: ast.AST, enumerations: set[int]) -> bool:
    """A list display that is a command line for the runtime.

    Recognised by shape rather than by finding the spawn call, because the call
    is often out of sight: `sync_cron_payloads` passes it to an injected
    `runner` for testability, and `build_edit_command` returns it to a caller.
    Requiring the two to sit together is the same same-physical-line assumption
    that hid both cron writes from the previous classifier.

    A tuple is not a command line — `('openclaw', name, expr, tz, …)` in
    `cron_timeline` is a display row — and neither is a list of peer names.
    """
    if not isinstance(node, ast.List) or not node.elts or id(node) in enumerations:
        return False
    head = node.elts[0]
    if not (isinstance(head, ast.Constant) and head.value == RUNTIME):
        return False
    # An enumeration is all literal peers; a command line carries arguments —
    # a flag, or a value computed at runtime.
    return any(not isinstance(arg, ast.Constant)
               or (isinstance(arg.value, str) and arg.value.startswith("-"))
               for arg in node.elts[1:])


def _sites_in(tree: ast.AST) -> list[int]:
    """Line numbers in one parsed module that invoke OpenClaw or read its state."""
    docstrings = _docstring_ids(tree)
    binary_names = _names_bound_to_the_binary(tree)
    enumerations = _enumeration_ids(tree)
    found: list[int] = []
    for node in ast.walk(tree):
        # 2. The binary exists to be executed.
        if isinstance(node, ast.Name) and node.id in binary_names:
            found.append(node.lineno)
            continue
        # 1a. An argv vector, wherever it is built.
        if _is_argv_vector(node, enumerations):
            found.append(node.lineno)
            continue
        # 1b. A shell string, which only counts where it is spawned.
        if isinstance(node, ast.Call) and _is_spawn(node) and node.args:
            first = node.args[0]
            if (isinstance(first, ast.Constant) and isinstance(first.value, str)
                    and first.value.split()[:1] == [RUNTIME]):
                found.append(node.lineno)
                continue
        # 3. Another runtime's private files.
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings and _is_runtime_path(node.value)):
            found.append(node.lineno)
    return sorted(set(found))


def coupling_sites() -> dict[str, list[int]]:
    """Files outside the adapter that invoke OpenClaw or read its state."""
    sites: dict[str, list[int]] = {}
    for path in sorted(ROOT.glob("scripts/**/*.py")) + sorted(ROOT.glob("clawock/**/*.py")):
        if ADAPTER in path.parents:
            continue
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError):
            continue
        found = _sites_in(tree)
        if found:
            sites[path.relative_to(ROOT).as_posix()] = found
    return sites


def test_the_runtime_coupling_count_never_rises():
    sites = coupling_sites()
    total = sum(len(lines) for lines in sites.values())

    detail = "\n".join(f"  {name}: {len(lines)} — lines {lines}"
                       for name, lines in sorted(sites.items()))
    assert total <= BASELINE, (
        f"runtime coupling rose to {total} (baseline {BASELINE}). New code must "
        f"go through clawock.providers, not call OpenClaw directly:\n{detail}")

    # A drop is the point of the exercise; make the reminder to lower the
    # baseline impossible to miss, so the ratchet cannot silently go slack.
    assert total >= BASELINE, (
        f"runtime coupling fell to {total} — lower BASELINE to {total} in this "
        "file so the gain is locked in")


def test_prose_is_not_coupling_and_a_command_is():
    """The failure that made the first classifier worse than useless: deleting
    an error message lowered the count and changed nothing. Both directions are
    pinned here so neither drifts back."""
    prose = ast.parse(
        'raise RuntimeError(f"openclaw cron list failed: {detail}")\n'
        'r.add("openclaw config", OK, "valid")\n'
        'parser.add_argument("--source", choices=["openclaw", "gha", "crontab"])\n'
        'help_text = "run openclaw doctor --fix"\n'
    )
    command = ast.parse(
        'cmd = ["openclaw", "cron", "edit", change["id"]]\n'
        'subprocess.run(cmd, capture_output=True)\n'
    )
    shell = ast.parse('os.system("openclaw doctor")\n')
    # Sites are counted per line, so these are written the way they appear in
    # `_watchdog_common`: the home on one line, the private database on another.
    state = ast.parse(
        "OC = Path('/root/.openclaw')\n"
        "STATE_DB = OC / 'state' / 'openclaw.sqlite'\n"
    )
    aliased = ast.parse(
        'from clawock.providers.openclaw import OPENCLAW_BIN as BIN\n'
        'os.path.exists(BIN)\n'
    )

    assert _sites_in(prose) == [], "an error message is not a call to the runtime"
    assert len(_sites_in(command)) == 1, "the argv vector is the coupling, counted once"
    assert len(_sites_in(shell)) == 1, "a spawned shell string is a call"
    assert len(_sites_in(state)) == 2, "openclaw's home and its state DB are both reads"
    assert len(_sites_in(aliased)) == 1, "renaming the binary constant is not migrating it"


def test_a_multi_source_label_is_not_counted_as_coupling():
    """`--source gha|openclaw|crontab` is the design we want. If the counter
    punished it, the cheapest way to go green would be to delete the wrong
    thing."""
    sites = coupling_sites()

    assert "scripts/data/cron_timeline.py" not in sites, (
        "cron_timeline treats openclaw as one source among three — counting it "
        "would reward removing multi-source support")


def test_the_cron_writes_are_counted():
    """The substring classifier missed these while reporting a falling number.
    They are the only paths in the repository that write OpenClaw's schedule; a
    metric that cannot see them cannot claim convergence."""
    sites = coupling_sites()

    assert len(sites.get("scripts/data/sync_cron_payloads.py", [])) >= 2, (
        "the `cron list` read and the `cron edit` write must both be counted")
    assert sites.get("scripts/data/sync_us_cron_dst.py"), (
        "the DST cron rewrite spawns `openclaw cron edit` and must be counted")


def test_the_adapter_is_exempt_because_that_is_what_an_adapter_is_for():
    sites = coupling_sites()

    assert not [name for name in sites if name.startswith("clawock/providers/")]
    # And the adapter must actually exist, or the exemption is hiding nothing.
    assert (ADAPTER / "delivery.py").exists()
