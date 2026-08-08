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
ADAPTER = ROOT / "src" / "clawock" / "providers"

RUNTIME = "openclaw"

# Lower this as consumers move behind clawock.providers. It must never rise.
# The per-file split is in the failure message; keeping a copy here only
# creates a second thing to forget to update.
#
# This baseline is not comparable to the 8 the substring classifier reported:
# that number counted six error strings and missed both cron writes. Nothing
# regressed between the two — the earlier count was measuring the wrong thing,
# so 14 was the first number here worth quoting. 14 → 13 when the cron-state
# chain moved into the adapter (#273); 13 → 10 when the two money CLIs and the
# legacy backfill stopped naming the runtime's workspace absolutely (#290);
# 10 → 9 when the watchdogs' session directory came from the adapter's
# OPENCLAW_HOME instead of a hard-coded path (#330 step 1); 9 → 6 when the two
# schedule writers took their command line from the adapter's scheduling
# capability instead of spelling out argv (#330 step 2); 6 → 1 when system_check
# took the runtime's layout and an is_installed() capability from the adapter
# (#330 step 3, last on purpose — it is what proves the earlier steps held).
#
# 6 → 1 when system_check moved behind the adapter; 1 → 0 when the remaining
# operator-owned session collector started asking the same adapter for runtime
# paths. Zero means no code outside the provider knows a host-specific layout.
BASELINE = 0

DELIBERATE_EXCLUSIONS = {}
HONEST_FLOOR = sum(DELIBERATE_EXCLUSIONS.values())

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
        # 1b. Anything handed to the OS to execute, where the spawn call itself
        #     removes the ambiguity the shape rule above has to guess at: a
        #     shell string, or a vector of any shape. Nobody passes `choices=`
        #     to subprocess.run, so a flagless `["openclaw", "doctor"]` and a
        #     tuple are commands here even though they are not recognisable as
        #     one when built somewhere else. Reported at the argument's own line
        #     so a multi-line call is the same single site rule 1a would find.
        if isinstance(node, ast.Call) and _is_spawn(node) and node.args:
            first = node.args[0]
            if (isinstance(first, ast.Constant) and isinstance(first.value, str)
                    and first.value.split()[:1] == [RUNTIME]):
                found.append(node.lineno)
                continue
            if (isinstance(first, (ast.List, ast.Tuple)) and first.elts
                    and isinstance(first.elts[0], ast.Constant)
                    and first.elts[0].value == RUNTIME):
                found.append(first.lineno)
                continue
        # 3. Another runtime's private files.
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings and _is_runtime_path(node.value)):
            found.append(node.lineno)
    return sorted(set(found))


def coupling_sites() -> dict[str, list[int]]:
    """Files outside the adapter that invoke OpenClaw or read its state."""
    sites: dict[str, list[int]] = {}
    for path in sorted(ROOT.glob("scripts/**/*.py")) + sorted(
        ROOT.glob("src/clawock/**/*.py")
    ):
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

    # Keep the documented floor honest. Without this the exclusion note is prose
    # that can quietly become false — either because the site was fixed and the
    # note still claims it is deliberate, or because it moved and the note points
    # at nothing. Both turn "the honest target is 1, not 0" into a lie.
    for name, count in DELIBERATE_EXCLUSIONS.items():
        assert len(sites.get(name, [])) == count, (
            f"{name} is documented as a deliberate exclusion of {count} site(s), "
            f"but now has {len(sites.get(name, []))}. Update DELIBERATE_EXCLUSIONS "
            "and the note above it — the floor is part of the claim.")


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


def test_a_spawned_command_counts_even_without_a_flag():
    """The hole left by the shape rule: away from its spawn call, a vector is
    told apart from a list of peer names by carrying a flag or a computed
    argument, so `["openclaw", "doctor"]` — the next line someone adds — landed
    green. At the spawn call there is nothing to guess: nobody hands `choices=`
    to `subprocess.run`, so any vector shape counts there, tuples included.

    A vector built away from its spawn with neither a flag nor a computed
    argument is still uncounted, and that is the deliberate trade — the
    alternative punishes `--source openclaw|gha|crontab`, which is the design.
    """
    assert len(_sites_in(ast.parse('subprocess.run(["openclaw", "doctor"])'))) == 1
    assert len(_sites_in(ast.parse('subprocess.run(("openclaw", "doctor"))'))) == 1, (
        "a tuple is a display row in cron_timeline, but not when it is being executed")
    # A multi-line call must be one site, not two: the vector is reported at its
    # own line, which is where the shape rule would have found it.
    multiline = ast.parse('subprocess.run(\n    [\n        "openclaw", "cron", "edit", cid,\n    ],\n)')
    assert len(_sites_in(multiline)) == 1
    assert _sites_in(ast.parse('subprocess.run(["gha", "openclaw"])')) == [], (
        "the runtime has to be argv[0]; naming it as an argument is not calling it")


def test_a_multi_source_label_is_not_counted_as_coupling():
    """`--source gha|openclaw|crontab` is the design we want. If the counter
    punished it, the cheapest way to go green would be to delete the wrong
    thing."""
    sites = coupling_sites()

    assert "scripts/data/cron_timeline.py" not in sites, (
        "cron_timeline treats openclaw as one source among three — counting it "
        "would reward removing multi-source support")


def test_the_cron_writes_moved_rather_than_vanished():
    """The schedule writers are the reason this metric exists.

    The substring classifier missed them while reporting a falling number, so
    the original form of this test pinned them as counted in
    `sync_cron_payloads` and `sync_us_cron_dst`. They have since moved behind
    the adapter (#330 step 2), which is the outcome the ratchet is for — but a
    count can fall for two very different reasons, and "the capability moved"
    must not be confused with "the sites were deleted and the writes now happen
    somewhere unaccounted for".

    So: the writers no longer spell out a command line, AND the adapter really
    does supply one. The classifier's ability to *see* a `cron edit` vector is
    pinned separately, on synthetic source, by
    `test_prose_is_not_coupling_and_a_command_is`.
    """
    sites = coupling_sites()

    for writer in ("scripts/data/sync_cron_payloads.py",
                   "scripts/data/sync_us_cron_dst.py"):
        assert writer not in sites, (
            f"{writer} names the runtime again — the schedule writers are "
            "supposed to reach it through clawock.providers")

    import importlib
    adapter = importlib.import_module("clawock.providers.openclaw")
    argv = adapter.build_cron_edit_argv(
        "job-id", {"schedule": {"expr": "0 8 * * 1-5", "tz": "Asia/Shanghai"}})
    assert argv[0] == adapter.OPENCLAW_BIN
    assert argv[1:4] == ["cron", "edit", "job-id"]
    assert "--exact" in argv, (
        "a schedule edit must pin the slot exactly; a scheduler stagger is how "
        "a market open drifts off its bar")


def test_the_adapter_is_exempt_because_that_is_what_an_adapter_is_for():
    sites = coupling_sites()

    assert not [name for name in sites if name.startswith("src/clawock/providers/")]
    # And the adapter must actually exist, or the exemption is hiding nothing.
    assert (ADAPTER / "delivery.py").exists()
