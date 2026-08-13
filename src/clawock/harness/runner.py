"""In-process dispatch to lifecycle implementations owned by clawock."""
from __future__ import annotations

import os
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path

from clawock.config.profiles import ENV_VAR as PROFILE_ENV_VAR
from clawock.config.profiles import load_profile

from .model import RunRequest


PHASE_MODULES = {
    ("brief", "preflight"): "clawock.harness.brief_preflight",
    ("brief", "postflight"): "clawock.harness.brief_postflight",
    ("report", "preflight"): "clawock.harness.report_preflight",
    ("report", "postflight"): "clawock.harness.report_postflight",
    ("intraday", "preflight"): "clawock.harness.intraday_preflight",
    ("intraday", "postflight"): "clawock.harness.intraday_postflight",
}


class AdapterUnavailable(RuntimeError):
    pass


@contextmanager
def _phase_env(path: Path, profile_path: Path | None):
    """Scope workspace and profile for modules that resolve resources on import."""
    updates = {"CLAWOCK_WORKSPACE": str(path.expanduser().resolve())}
    if profile_path is not None:
        updates[PROFILE_ENV_VAR] = str(profile_path)
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run_phase(workflow: str, phase: str, argv=(), *, workspace=None, profile=None) -> int:
    root = Path(workspace or os.environ.get("CLAWOCK_WORKSPACE") or Path.cwd())
    selected_profile = load_profile(root, profile)
    request = RunRequest(
        workflow=workflow,
        phase=phase,
        workspace=root,
        profile=selected_profile.profile_id if selected_profile else None,
        argv=tuple(argv),
    )
    configured = selected_profile.workflows.get(workflow)
    if configured is None or not configured.enabled:
        raise AdapterUnavailable(
            f"profile {selected_profile.profile_id!r} does not enable {workflow}"
        )
    module_name = PHASE_MODULES.get((request.workflow, request.phase))
    if module_name is None:
        raise AdapterUnavailable(f"unsupported lifecycle phase: {workflow} {phase}")
    with _phase_env(
        request.workspace,
        selected_profile.path,
    ):
        function = import_module(module_name).main
        return int(function(list(request.argv)) or 0)
