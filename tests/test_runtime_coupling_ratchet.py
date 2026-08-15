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

Python is not the whole repository
----------------------------------
The count below walks `*.py`. Shell is code too, and `ops/` ships entry points
that name this host on purpose. A number that reads as "the repository" while
measuring only half of it is the same failure as the scan roots that pointed at
a deleted directory (#452/#453) — so the shell half is enumerated too, at the
bottom of this file, against a per-file allowlist with a reason each. The two
checks answer different questions: Python must reach the runtime through the
adapter (target zero), while a host-owned shell script naming the host is
correct and only has to stay on the list that says why.
"""
import ast
import re
import subprocess
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
# paths. Zero means no *Python* module outside the provider knows a host-specific
# layout. It does not mean nothing in the repository names the host: six shell
# entry points do, deliberately, and they are pinned by HOST_OWNED_SHELL below.
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


# Where code lives. `scripts/**` was half of this list and #429 deleted it, so
# that half walked zero files; `ops/` — where host wiring moved — was never
# added, which is how `ops/pages/freshness.py` could default a CLI flag to
# `/root/.openclaw/workspace` while the ratchet reported zero.
CODE_ROOTS = ("src/clawock", "ops")


def _modules():
    for root in CODE_ROOTS:
        for path in sorted((ROOT / root).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def coupling_sites() -> dict[str, list[int]]:
    """Files outside the adapter that invoke OpenClaw or read its state."""
    sites: dict[str, list[int]] = {}
    for path in _modules():
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
    # Anti-vacuity: a count of zero is the goal here, so an empty scan and a
    # decoupled tree produce the same number. That is how half of this scan
    # could point at a deleted directory unnoticed.
    modules = list(_modules())
    assert len(modules) > 50, f"only {len(modules)} modules scanned — did a root move?"
    assert any(path.name == "system_check.py" for path in modules), (
        "system_check is the file this ratchet migrated last; if it is outside "
        "the scan, the scan is not looking where the coupling was")

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

    assert "ops/host/cron_timeline.py" not in sites, (
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

    for writer in ("ops/host/sync_cron_payloads.py",
                   "ops/host/sync_us_cron_dst.py"):
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


# ---------------------------------------------------------------------------
# The shell half (#478)
# ---------------------------------------------------------------------------
#
# `docs/reference/product-profile-operations.md` says `ops/host/` owns "this host's
# cron, scheduler inspection, session maintenance and launcher wiring" and
# `ops/publish/` is the only publisher implementation. Naming this host is what
# those files are for, so raising the Python baseline for them would punish
# files that are already where they belong.
#
# What is not fine is the claim being wider than the scan. So: enumerate every
# shell entry point that names the runtime and require the set to equal this
# allowlist, with a reason per file. Same shape as DELIBERATE_EXCLUSIONS, and
# for the same purpose — a documented floor that cannot quietly become false.
# A new publisher script hardcoding the live path is then a red, and the day one
# of these is parameterised its entry has to go, so the list cannot outlive its
# reason.
HOST_OWNED_SHELL = {
    "ops/publish/publish_dashboard.sh": (
        1, "the host publisher: WS is this machine's live checkout, which is "
           "what ops/publish/ is defined to own"),
    "ops/publish/publish_identity.sh": (
        1, "refuses the runtime's commit identity outside the live checkout — "
           "the path is the safety check, not a dependency"),
    "ops/host/commit_dreaming.sh": (
        1, "backstop commit for a cron owned by OpenClaw core; it has no "
           "meaning off this host"),
    "ops/host/gold_dca_refresh.sh": (
        1, "host cron wrapper around the installed CLI, run from the live "
           "checkout"),
    "ops/host/reapply_openclaw_patches.sh": (
        2, "patches the runtime's own pnpm install after an upgrade: the "
           "install directory and the patch root are the subject of the script"),
}

def _shell_files():
    """Every tracked shell file in the repository, found rather than listed.

    A hand-listed set of roots is the same defect one level up: the Python scan
    listed `scripts/**` and walked zero files after #429 deleted it, while
    `ops/` — where the code went — was never added. A new `skills/x/live.sh` or
    `.github/scripts/deploy.sh` would be invisible to a root list while every
    anti-vacuity assertion below stayed green. `git ls-files` is also the right
    boundary for a different reason: an untracked script on this host is not
    something the repository claims anything about.

    Recognised by suffix or by shebang, because `.githooks/pre-commit` has no
    suffix and is exactly where this family of defect has shipped before (#445).
    """
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, text=True, check=True)
    for name in sorted(filter(None, listing.stdout.split("\0"))):
        path = ROOT / name
        if not path.is_file():
            continue
        if path.suffix == ".sh":
            yield path
            continue
        try:
            first = path.open(encoding="utf-8", errors="ignore").readline()
        except OSError:
            continue
        if first.startswith("#!") and "sh" in first:
            yield path


def _strip_comment(line: str) -> str:
    """Drop a shell comment, quote-aware.

    Prose about the runtime is not a call to it — the Python classifier's whole
    lesson — and `safe_push.sh` explains the host's rebuild race in a comment
    while touching none of its paths. A naive `split('#')` would also cut
    `${x#prefix}` and a `#` inside a quoted string, so track the quotes.
    """
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


_SHELL_TOKEN = re.compile(r"[^\s\"'=:;()<>&|`,\[\]{}]+")

# `OC=.openclaw` then `WS=/root/$OC/workspace` is the cheapest way past a
# token-by-token path matcher, and it is one line of ordinary shell. Requiring
# whitespace before the name keeps `--source=openclaw` — the multi-source label
# the Python classifier deliberately does not count — out of it.
_RUNTIME_ASSIGNMENT = re.compile(
    rf"""(?:^|\s)[A-Za-z_][A-Za-z0-9_]*=["']?\.?{RUNTIME}(?:["']?(?:\s|$|/))""")


def runtime_paths_in_shell(text: str) -> list[int]:
    """Line numbers where a shell script spells out one of the runtime's paths.

    Reuses `_is_runtime_path`, so both halves of this file agree on what counts
    as naming the host: a path segment that *is* the runtime's directory or its
    private file, never a bare mention. `[openclaw-patches]` is a log prefix and
    `openclaw core` in a sentence is prose; `/root/.openclaw/workspace` and
    `node_modules/openclaw` are layout.

    The limit, stated rather than left for someone to find: this reads literal
    text. A path assembled from a variable the script never spells out — one
    exported by a caller, or read from a config file — is not caught, and the
    honest reason to accept that is the same one the Python side accepts for a
    flagless argv vector: the alternative punishes the parameterised form, which
    is the form we want. What it does catch is the one-line version, where the
    runtime's own directory name is assigned to a variable.
    """
    found = []
    for number, raw in enumerate(text.splitlines(), start=1):
        code = _strip_comment(raw)
        if (any(_is_runtime_path(token) for token in _SHELL_TOKEN.findall(code))
                or _RUNTIME_ASSIGNMENT.search(code)):
            found.append(number)
    return found


def host_naming_shell() -> dict[str, list[int]]:
    sites = {}
    for path in _shell_files():
        found = runtime_paths_in_shell(path.read_text(encoding="utf-8", errors="ignore"))
        if found:
            sites[path.relative_to(ROOT).as_posix()] = found
    return sites


def test_only_the_documented_shell_entry_points_name_this_host():
    # Anti-vacuity, the same failure mode as above: an empty walk and a clean
    # repository both produce "nothing outside the allowlist".
    files = list(_shell_files())
    assert len(files) > 10, f"only {len(files)} shell files walked — did the walk break?"
    walked = {path.relative_to(ROOT).as_posix() for path in files}
    for expected in (".githooks/pre-commit", "ops/publish/safe_push.sh",
                     "examples/minimal-run/run.sh"):
        assert expected in walked, (
            f"{expected} is outside the shell walk; the walk is not looking "
            "where host paths could be written")
    # And the walk must not be scoped to the directories that happen to have a
    # script today: the roots it would have listed are not the whole repository.
    assert any(not name.startswith(("ops/", ".githooks/"))
               for name in walked), (
        "every shell file found is under an ops-shaped path; if the discovery "
        "silently narrowed, a new script elsewhere would never be seen")

    sites = host_naming_shell()
    detail = "\n".join(f"  {name}: lines {lines}" for name, lines in sorted(sites.items()))

    unlisted = sorted(set(sites) - set(HOST_OWNED_SHELL))
    assert not unlisted, (
        "these shell scripts name this host's runtime layout and are not on the "
        f"allowlist:\n{detail}\n\nIf the script legitimately owns a host side "
        "effect, add it to HOST_OWNED_SHELL with the reason. Otherwise take the "
        "path from the environment or the adapter.")

    for name, (count, reason) in HOST_OWNED_SHELL.items():
        actual = sites.get(name, [])
        assert len(actual) == count, (
            f"{name} is documented as naming the host {count} time(s) — "
            f"{reason} — but now names it {len(actual)} time(s) (lines {actual}). "
            "If it was parameterised, delete the entry; the list must not "
            "outlive the reason it exists.")


def test_a_shell_comment_is_not_coupling_and_an_assignment_is():
    """Both directions, so neither drifts — the Python classifier shipped
    backwards on exactly this and made deleting an explanation the cheapest way
    to go green."""
    prose = (
        "# 背景: dreaming 是 openclaw core 内置 cron\n"
        "# dirty with OTHER in-flight files (host openclaw rebuilding dashboard.json)\n"
        'echo "[openclaw-patches] marker ok: $label"\n'
        'echo "run openclaw doctor --fix" >&2\n'
    )
    layout = (
        'WS="/root/.openclaw/workspace"\n'
        "KEYFILE=/root/.openclaw/nostr-rick.key\n"
        'OCLAW_REAL="$(realpath /root/.local/share/pnpm/global/5/node_modules/openclaw)"\n'
        "DB=/root/.openclaw/state/openclaw.sqlite  # the runtime's private state\n"
    )

    assert runtime_paths_in_shell(prose) == [], (
        "a comment and a log prefix are not the host's layout")
    assert runtime_paths_in_shell(layout) == [1, 2, 3, 4], (
        "an assigned runtime path is the coupling, one per line")
    assert runtime_paths_in_shell('printf "%s\\n" "${name#openclaw-}"\n') == [], (
        "a parameter expansion is not a path, and the comment stripper must not "
        "cut it either")
    # The one-line way around a token matcher, and the label that must not be
    # mistaken for it.
    assert runtime_paths_in_shell("OC=.openclaw\nWS=/root/$OC/workspace\n") == [1], (
        "assigning the runtime's own directory name is naming the host; the "
        "composed line after it is not separately visible, which is the "
        "documented limit")
    assert runtime_paths_in_shell("exec cron_timeline --source=openclaw --json\n") == [], (
        "--source openclaw|gha|crontab is the multi-source design, not coupling")
