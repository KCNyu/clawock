"""Small contract tests for the package harness boundary (#365)."""
import ast
import os
from pathlib import Path

from clawock.cli import main
from clawock.harness.model import Artifact, ArtifactSet


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
