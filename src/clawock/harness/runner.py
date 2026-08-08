"""In-process harness dispatch.

This is a strangler adapter: cron and other runtimes call a stable package CLI,
while the live desk implementation remains importable from ``scripts/harness``
until its product/instance seams are extracted.  Crucially this never shells out
to a script; the selected module's ``main(argv)`` is called in the same process.
A wheel without the kcn instance can still import all harness contracts and gets
a named adapter error if it asks to run that instance.
"""
from __future__ import annotations

import importlib
import os
from contextlib import contextmanager
from pathlib import Path

from .model import RunRequest


ENTRYPOINTS = {
    ("brief", "preflight"): "scripts.harness.brief_preflight:main",
    ("brief", "postflight"): "scripts.harness.brief_postflight:main",
    ("report", "preflight"): "scripts.harness.report_preflight:main",
    ("report", "postflight"): "scripts.harness.report_postflight:main",
    ("intraday", "preflight"): "scripts.harness.intraday_preflight:main",
    ("intraday", "postflight"): "scripts.harness.intraday_postflight:main",
}


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
    target = ENTRYPOINTS[(request.workflow, request.phase)]
    module_name, function_name = target.split(":", 1)
    try:
        with _workspace_env(request.workspace):
            module = importlib.import_module(module_name)
            function = getattr(module, function_name)
            return int(function(list(request.argv)) or 0)
    except ModuleNotFoundError as exc:
        raise AdapterUnavailable(
            f"{workflow} {phase} needs an installed instance adapter; "
            f"{module_name} is unavailable"
        ) from exc
