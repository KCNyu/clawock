"""In-process dispatch to an installed instance adapter.

The portable wheel knows the phase protocol but not the KCNyu implementation.
Instance distributions register phase callables through the
``clawock.instance_phases`` entry-point group. External runtimes therefore keep
one stable ``clawock`` command while the product wheel remains free of live desk
code, portfolio data and repository-layout imports.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from importlib.metadata import entry_points
from pathlib import Path

from .model import RunRequest


ENTRYPOINT_GROUP = "clawock.instance_phases"


class AdapterUnavailable(RuntimeError):
    pass


@contextmanager
def _workspace_env(path: Path):
    """Expose the request to legacy adapters that resolve workspace on import."""
    key = "CLAWOCK_WORKSPACE"
    previous = os.environ.get(key)
    os.environ[key] = str(path.expanduser().resolve())
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def run_phase(workflow: str, phase: str, argv=(), *, workspace=None) -> int:
    request = RunRequest(
        workflow=workflow,
        phase=phase,
        workspace=Path(workspace or os.environ.get("CLAWOCK_WORKSPACE") or Path.cwd()),
        argv=tuple(argv),
    )
    instance = os.environ.get("CLAWOCK_INSTANCE", "").strip()
    if not instance:
        raise AdapterUnavailable(
            f"{workflow} {phase} needs an installed instance adapter; "
            "set CLAWOCK_INSTANCE to its registered name"
        )
    name = f"{instance}.{request.workflow}.{request.phase}"
    matches = tuple(entry_points().select(group=ENTRYPOINT_GROUP, name=name))
    if len(matches) != 1:
        raise AdapterUnavailable(
            f"{workflow} {phase} needs exactly one installed '{instance}' "
            f"adapter entry point; found {len(matches)} for {name}"
        )
    with _workspace_env(request.workspace):
        function = matches[0].load()
        return int(function(list(request.argv)) or 0)
