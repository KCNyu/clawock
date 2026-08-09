"""Small contract tests for the package harness boundary (#365)."""
import ast
import json
import os
from pathlib import Path

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
    assert main(["intraday", "preflight", "--market", "hk"]) == 0
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


def test_instance_adapter_receives_workspace_without_leaking_env(monkeypatch, tmp_path):
    import clawock.harness.runner as runner

    seen = {}
    def adapter(argv):
        seen.update(workspace=os.environ.get("CLAWOCK_WORKSPACE"), argv=argv)
        return 0

    class FakeEntryPoint:
        @staticmethod
        def load():
            return adapter

    class FakeEntryPoints:
        @staticmethod
        def select(*, group, name):
            assert group == runner.ENTRYPOINT_GROUP
            assert name == "fixture.brief.preflight"
            return (FakeEntryPoint(),)

    monkeypatch.setattr(runner, "entry_points", lambda: FakeEntryPoints())
    monkeypatch.setenv("CLAWOCK_INSTANCE", "fixture")
    monkeypatch.delenv("CLAWOCK_WORKSPACE", raising=False)
    assert runner.run_phase("brief", "preflight", workspace=tmp_path) == 0
    assert seen["workspace"] == str(tmp_path.resolve())
    assert seen["argv"] == []
    assert "CLAWOCK_WORKSPACE" not in os.environ


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
    assert not bad, "utilities that mishandle --help:\n" + "\n".join(bad)
