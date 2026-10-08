"""Small contract tests for the package harness boundary (#365)."""
import ast
import json
import os
import re
from pathlib import Path

import pytest

from clawock.cli import main
from clawock.harness import AgentRun, AgentRunRequest
from clawock.harness.model import Artifact, ArtifactSet
from clawock.publish import FilesystemStore


def test_cli_dispatches_a_preflight_in_process(monkeypatch):
    seen = {}
    import clawock.harness.runner as runner

    def fake(workflow, phase, argv=(), **kwargs):
        seen.update(workflow=workflow, phase=phase, argv=list(argv))
        return 0

    monkeypatch.setattr(runner, "run_phase", fake)
    assert main([
        "intraday", "preflight", "--market", "hk", "--profile", "kcnyu"
    ]) == 0
    assert seen == {"workflow": "intraday", "phase": "preflight",
                    "argv": ["--market", "hk"]}


def test_runner_contains_no_subprocess_calls():
    path = Path(__file__).resolve().parents[1] / "src/clawock/harness/runner.py"
    tree = ast.parse(path.read_text())
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and
                   ((isinstance(node, ast.Import) and any(a.name == "subprocess" for a in node.names)) or
                    (isinstance(node, ast.ImportFrom) and node.module == "subprocess"))
                   for node in ast.walk(tree))


def test_artifact_set_rejects_mixed_generations(tmp_path):
    artifact = Artifact("plan", tmp_path / "plan.json", "application/json", "old")
    value = ArtifactSet("new", (artifact,))
    try:
        value.validate()
    except ValueError as exc:
        assert "mixed artifact generations" in str(exc)
    else:
        raise AssertionError("mixed generations were accepted")


def test_profile_selects_phase_and_scopes_runtime_environment(monkeypatch, tmp_path):
    import clawock.harness.runner as runner

    seen = {}
    def phase(argv):
        seen.update(
            workspace=os.environ.get("CLAWOCK_WORKSPACE"),
            profile=os.environ.get("CLAWOCK_PROFILE"),
            argv=argv,
        )
        return 0

    class Module:
        main = staticmethod(phase)

    profile = tmp_path / "config/profiles/fixture/profile.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps({
        "schema_version": 1,
        "id": "fixture",
        "locale": "en-US",
        "timezone": "UTC",
        "markets": {"paper": {
            "timezone": "UTC", "label": "Paper", "analysis_command": "analyze-paper"
        }},
        "workflows": {"brief": {
            "enabled": True, "markets": ["paper"]
        }},
        "resources": {"schedule_contract": "config/schedule.json"},
        "delivery": {"provider": "filesystem", "targets": {}},
    }))
    monkeypatch.setattr(runner, "import_module", lambda name: Module)
    monkeypatch.delenv("CLAWOCK_WORKSPACE", raising=False)
    monkeypatch.delenv("CLAWOCK_PROFILE", raising=False)
    assert runner.run_phase(
        "brief", "preflight", workspace=tmp_path, profile="fixture"
    ) == 0
    assert seen["workspace"] == str(tmp_path.resolve())
    assert seen["profile"] == str(profile.resolve())
    assert seen["argv"] == []
    assert "CLAWOCK_WORKSPACE" not in os.environ
    assert "CLAWOCK_PROFILE" not in os.environ


def test_init_joins_an_existing_agent_workspace_without_overwriting(tmp_path):
    context = tmp_path / "CONTEXT.md"
    context.write_text("runtime-owned context\n")
    (tmp_path / "AGENTS.md").write_text("runtime-owned instructions\n")

    assert main(["init", str(tmp_path)]) == 0
    assert context.read_text() == "runtime-owned context\n"
    assert (tmp_path / "AGENTS.md").read_text() == "runtime-owned instructions\n"
    assert (tmp_path / "clawock.json").exists()
    assert (tmp_path / ".clawock/.gitignore").read_text() == "*\n!.gitignore\n"


def test_external_agent_can_repair_then_publish_one_certified_generation(tmp_path):
    (tmp_path / "CONTEXT.md").write_text("source fact\n")
    output = tmp_path / "out"
    harness = AgentRun()
    prepared = harness.prepare(AgentRunRequest(
        task="answer from context",
        workspace=tmp_path,
        context_files=("CONTEXT.md",),
        output_directory=output,
    ))

    rejected = harness.publish(prepared, {"answer.md": ""}, FilesystemStore(output))
    assert rejected.status == "rejected"
    assert rejected.validation_issues[0].code == "empty_artifact"
    assert not output.exists()

    receipt = harness.publish(
        prepared, {"answer.md": "grounded answer\n"}, FilesystemStore(output))
    assert receipt.status == "published"
    assert {item.generation_id for item in receipt.artifacts.artifacts} == {
        receipt.generation_id}
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["generation_id"] == receipt.generation_id
    assert manifest["context"]["documents"][0]["name"] == "CONTEXT.md"
    assert len(manifest["context"]["documents"][0]["sha256"]) == 64


def test_every_packaged_utility_is_actually_callable():
    """Each table entry must import and expose a `main` that takes argv.

    #429 added four `evaluate-*` commands to the name list without touching the
    dispatch chain beside it: one module had no `main` at all and three had
    `main()` with no parameters, so every invocation — `--help` included — died
    on ImportError or TypeError. Nothing noticed, because no test ever asked the
    CLI to reach them. The two are one table now; this asserts the table resolves.
    """
    import importlib
    import inspect

    from clawock.cli import HARD_EXIT_UTILITIES, PACKAGED_UTILITIES

    broken = []
    for command, target in sorted(PACKAGED_UTILITIES.items()):
        try:
            module = importlib.import_module(target)
        except Exception as exc:
            broken.append(f"{command}: {target} does not import ({exc})")
            continue
        entry = getattr(module, "main", None)
        if entry is None:
            broken.append(f"{command}: {target} has no main()")
            continue
        try:
            inspect.signature(entry).bind([])
        except TypeError:
            broken.append(f"{command}: {target}.main() does not accept argv")
        if command in HARD_EXIT_UTILITIES and not hasattr(module, "hard_exit"):
            broken.append(f"{command}: {target} has no hard_exit()")
    assert not broken, "packaged utilities the CLI cannot reach:\n" + "\n".join(broken)


def test_every_subcommand_the_parser_offers_can_actually_be_dispatched():
    """The other direction, and the one #745 broke: advertised but unreachable.

    `record` was added to the parser's own utility name list on 2026-08-16 and
    never to `PACKAGED_UTILITIES`. Every gate above iterates the *table*, so all
    of them stayed green while `clawock record` — the only write path into the
    decision-mind ledger, and the command `docs/decision-mind-ledger.md` calls
    its "唯一写入入口" — died before reaching a module, for the three months of
    its existence. `clawock --help` listed it the whole time.

    The parser is built from the table now, so the old drift cannot recur in
    that shape. This asserts the property itself rather than the shape: every
    name argparse offers is either a table entry or one of the hand-built
    commands named here, so a new subcommand registered anywhere else has to be
    added to this list deliberately.
    """
    import io
    import re
    from contextlib import redirect_stdout

    from clawock import cli

    hand_built = {
        "init", "run", "doctor", "calendar", "profile", "report", "brief",
        "intraday", "tool", "context", "workflow",
    }

    out = io.StringIO()
    with redirect_stdout(out), pytest.raises(SystemExit):
        cli.main(["--help"])
    choices = re.search(r"\{([a-z0-9,-]+)\}", out.getvalue().replace("\n", "")
                        .replace(" ", ""))
    assert choices, "clawock --help no longer prints its subcommand choices"
    offered = set(choices.group(1).split(","))

    unreachable = sorted(offered - set(cli.PACKAGED_UTILITIES) - hand_built)
    assert not unreachable, (
        f"`clawock --help` offers {unreachable}, which no registry can dispatch. "
        "Add each to PACKAGED_UTILITIES (with its UTILITY_HELP line), or to the "
        "hand-built set in this test if it really is its own parser.")

    missing = sorted(set(cli.PACKAGED_UTILITIES) - offered)
    assert not missing, f"packaged utilities the parser never registers: {missing}"

    # A help string per table entry, because the parser reads UTILITY_HELP by
    # key while it is being built: a missing one is a KeyError on every
    # invocation, and an orphan one is a name that used to exist.
    assert set(cli.UTILITY_HELP) == set(cli.PACKAGED_UTILITIES)
    assert all(cli.UTILITY_HELP.values()), "a utility ships an empty help line"


FORWARDED_FLAGS = {"--market", "--phase", "--context-id", "--text-file", "--date",
                   "--dry-run", "--judgment-packet", "--page-url"}


def _flags_the_phase_module_declares(workflow, phase):
    source = (Path(__file__).resolve().parents[1] / "src" / "clawock" / "harness"
              / f"{workflow}_{phase}.py").read_text(encoding="utf-8")
    return {arg.value for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            for arg in node.args
            if isinstance(arg, ast.Constant) and str(arg.value).startswith("--")}


def test_every_flag_a_lifecycle_help_prints_is_accepted_by_a_phase_it_names(monkeypatch, capsys):
    """#2616: `clawock brief|report|intraday --help` printed one flat flag list.

    Six of the seven lifecycle entries rejected a flag their own `--help`
    advertised, and `intraday` offered `--date`/`--dry-run`, which neither of its
    phases reads. The table is held against each phase module's own parser in
    both directions, the workflow parser may offer only what the table lists,
    and a flag given to the wrong phase is refused by name before anything runs.
    """
    from clawock import cli
    from clawock.harness import runner

    for (workflow, phase), flags in cli.PHASE_FLAGS.items():
        declared = _flags_the_phase_module_declares(workflow, phase) & FORWARDED_FLAGS
        assert set(flags) == declared, (
            f"{workflow} {phase}: PHASE_FLAGS lists {sorted(flags)}, "
            f"its parser declares {sorted(declared)}")

    ran = []
    monkeypatch.setattr(runner, "run_phase",
                        lambda *args, **kwargs: ran.append(args) or 0)
    samples = {"--market": ["--market", "hk"], "--phase": ["--phase", "open"],
               "--context-id": ["--context-id", "c1"], "--text-file": ["--text-file", "p.md"],
               "--date": ["--date", "2026-10-05"], "--dry-run": ["--dry-run"],
               "--judgment-packet": ["--judgment-packet"],
               "--page-url": ["--page-url", "https://example.com/brief"]}
    for workflow in ("brief", "report", "intraday"):
        phases = [phase for name, phase in cli.PHASE_FLAGS if name == workflow]
        offered = set()
        for flag, argv in samples.items():
            outcomes = {}
            for phase in phases:
                ran.clear()
                try:
                    code = cli.main([workflow, phase, *argv])
                except SystemExit:
                    break  # the workflow parser does not offer this flag at all
                outcomes[phase] = (code, bool(ran), capsys.readouterr().err)
            else:
                offered.add(flag)
                for phase, (code, reached, err) in outcomes.items():
                    if flag in cli.PHASE_FLAGS[workflow, phase]:
                        assert (code, reached) == (0, True), (workflow, phase, flag, err)
                    else:
                        assert (code, reached) == (2, False), (workflow, phase, flag)
                        assert flag in err and cli._flag_phases(workflow, flag) in err
            capsys.readouterr()
        accepted_somewhere = {flag for phase in phases
                              for flag in cli.PHASE_FLAGS[workflow, phase]}
        assert offered == accepted_somewhere, (
            f"`clawock {workflow} --help` offers {sorted(offered - accepted_somewhere)} "
            "that no phase of it accepts")


def test_report_modes_refuse_each_others_flags(monkeypatch, capsys, tmp_path):
    """#2627: one parser serves assembly and the phases; each mode took the
    other's flags and dropped them — a bogus `--context-id` changed nothing."""
    from clawock import cli
    from clawock.harness import runner

    ran = []
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: ran.append(a) or 0)
    ctx = tmp_path / "ctx.json"
    ctx.write_text("{}")
    for argv in (["--market", "us"], ["--phase", "open"], ["--context-id", "BOGUS"],
                 ["--text-file", "/nonexistent.md"]):
        assert cli.main(["report", "--context", str(ctx), *argv]) == 2
        err = capsys.readouterr().err
        assert argv[0] in err and cli._flag_phases("report", argv[0]) in err
    for argv in (["--context", str(ctx)], ["--prose", str(ctx)], ["--json"]):
        assert cli.main(["report", "preflight", "--market", "hk", "--phase", "open", *argv]) == 2
        assert argv[0] in capsys.readouterr().err
    assert ran == []
    assert cli.main(["report", "preflight", "--market", "hk", "--phase", "open"]) == 0
    assert len(ran) == 1


def test_every_packaged_utility_answers_help_without_running_anything():
    """`--help` is the first thing anyone types, and it must not do work.

    Two separate failures hid here. Some utilities took `argv[0]` as a path, so
    `--help` came back as a FileNotFoundError traceback. Worse, eleven scan argv
    for flags by hand and simply ignore anything they do not recognise — so
    `clawock analyze-hk --help` fetched live quotes and rewrote portfolio.json.

    Driven through `cli.main`, because that is the surface a user touches; the
    module's own `main` is not where the guarantee has to hold.
    """
    import io
    from contextlib import redirect_stdout, redirect_stderr

    from clawock import cli

    bad = []
    for command in sorted(cli.PACKAGED_UTILITIES):
        out = io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(out):
                returned = cli.main([command, "--help"])
        except SystemExit as exit_code:
            if exit_code.code not in (0, None):
                bad.append(f"{command}: --help exited {exit_code.code}")
        except Exception as exc:
            bad.append(f"{command}: --help raised {type(exc).__name__}: {exc}")
            continue
        else:
            if returned not in (0, None):
                bad.append(f"{command}: --help returned {returned}")
        if "usage" not in out.getvalue().lower():
            bad.append(f"{command}: --help printed no usage line")
            continue
        # argparse names the program after argv[0] unless told otherwise:
        # `__main__.py` under `python -m clawock`, a bare `clawock` from the
        # launcher — a usage line for an invocation that doesn't exist (#1591).
        usage = next(line for line in out.getvalue().splitlines()
                     if line.lower().startswith("usage"))
        if not usage.startswith(f"usage: clawock {command}"):
            bad.append(f"{command}: usage line names the wrong program: {usage[:60]!r}")
    assert not bad, "utilities that mishandle --help:\n" + "\n".join(bad)


def test_docstring_help_lists_every_flag_the_module_reads():
    """A hand-scanned flag has no argparse entry, so its help is the docstring.

    `--13f`, `--wechat`/`--md-table` and `--intraday` all worked and were all
    missing from `--help` (#1571): nothing ties a new `'--x' in argv` check to
    the docstring written next to it. Every flag literal the module tests
    against argv must appear in what `clawock <command> --help` prints.
    """
    import importlib
    import inspect
    import io
    from contextlib import redirect_stdout, redirect_stderr

    from clawock import cli
    from clawock.utilities import DOCSTRING_HELP_UTILITIES

    missing = {}
    for command in sorted(DOCSTRING_HELP_UTILITIES):
        source = inspect.getsource(importlib.import_module(cli.PACKAGED_UTILITIES[command]))
        flags = set(re.findall(r"""['"](--[a-z0-9][a-z0-9-]*)['"]\s+in\s+argv""", source))
        out = io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(out):
                cli.main([command, "--help"])
        except SystemExit:
            pass
        undocumented = sorted(flag for flag in flags - {"--help"} if flag not in out.getvalue())
        if undocumented:
            missing[command] = undocumented
    assert missing == {}, f"flags read from argv but absent from --help: {missing}"


def test_brief_render_forwards_custom_footer_url(monkeypatch):
    from clawock.harness import runner

    seen = []
    monkeypatch.setattr(runner, "run_phase",
                        lambda *args, **kwargs: seen.append(args) or 0)
    assert main(["brief", "render", "--page-url", "https://example.com/brief",
                 "--dry-run"]) == 0
    assert seen == [("brief", "render",
                     ["--page-url", "https://example.com/brief", "--dry-run"])]
