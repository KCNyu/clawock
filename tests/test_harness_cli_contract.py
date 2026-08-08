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
    path = Path(__file__).resolve().parents[1] / "clawock/harness/runner.py"
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
    fake = type("Adapter", (), {
        "main": staticmethod(lambda argv: seen.update(
            workspace=os.environ.get("CLAWOCK_WORKSPACE")) or 0),
    })
    monkeypatch.setattr(runner.importlib, "import_module", lambda name: fake)
    monkeypatch.delenv("CLAWOCK_WORKSPACE", raising=False)
    assert runner.run_phase("brief", "preflight", workspace=tmp_path) == 0
    assert seen["workspace"] == str(tmp_path.resolve())
    assert "CLAWOCK_WORKSPACE" not in os.environ


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
