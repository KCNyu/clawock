"""Every registered phase must be a phase the request vocabulary accepts.

`brief render` shipped registered in `harness.runner.PHASE_MODULES` and rejected
by `RunRequest`, whose `PHASES` tuple still listed only preflight/postflight —
so `clawock brief render` answered "unknown phase: render" while the module it
names sat right there in the registry. The unit tests all called the renderer
directly, which is exactly the seam they could not see.
"""
import pytest

from clawock.harness.runner import PHASE_MODULES
from clawock.runtime_model import PHASES, WORKFLOWS, RunRequest


@pytest.mark.parametrize(("workflow", "phase"), sorted(PHASE_MODULES))
def test_a_registered_phase_can_be_requested(workflow, phase, tmp_path):
    """The registry and the vocabulary are two lists of the same thing."""
    assert workflow in WORKFLOWS
    assert phase in PHASES
    request = RunRequest(workflow=workflow, phase=phase, workspace=tmp_path)
    assert request.phase == phase


def test_the_cli_can_dispatch_the_brief_render_phase(monkeypatch):
    """A phase nobody can type is a phase that does not exist.

    Driven through `cli.main` rather than through the renderer, because the
    break was in the seam between them: argparse choices, then the request
    vocabulary, then the registry.
    """
    from clawock import cli
    from clawock.harness import runner

    seen = {}

    def record(workflow, phase, argv, *, workspace=None, profile=None):
        seen.update(workflow=workflow, phase=phase, argv=list(argv))
        return 0

    monkeypatch.setattr(runner, "run_phase", record)

    assert cli.main(["brief", "render", "--date", "2026-08-31", "--dry-run"]) == 0
    assert seen["workflow"] == "brief" and seen["phase"] == "render"
    assert "--date" in seen["argv"] and "2026-08-31" in seen["argv"], (
        "the date has to reach the renderer, or only today can ever be rendered")
    assert "--dry-run" in seen["argv"]


def test_the_render_phase_is_the_briefs_alone(monkeypatch):
    """`intraday render` must stay a typo, not a half-wired command."""
    from clawock import cli

    with pytest.raises(SystemExit):
        cli.main(["intraday", "render"])
