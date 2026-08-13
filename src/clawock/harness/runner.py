"""In-process dispatch while lifecycle implementations migrate into core.

Profiles are declarative and selected explicitly. The entry-point lookup below
is a temporary compatibility bridge for phases not yet moved into the root
wheel; it keys that bridge from the profile id rather than treating a Python
distribution as the source of instance identity.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from importlib.metadata import entry_points
from pathlib import Path

from clawock.config.profiles import ENV_VAR as PROFILE_ENV_VAR
from clawock.config.profiles import load_profile

from .model import RunRequest


ENTRYPOINT_GROUP = "clawock.instance_phases"


class AdapterUnavailable(RuntimeError):
    pass


@contextmanager
def _phase_env(path: Path, profile_path: Path | None):
    """Expose the request to legacy adapters that resolve workspace on import."""
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
    selected_profile = None
    if profile is not None or os.environ.get(PROFILE_ENV_VAR):
        selected_profile = load_profile(root, profile)
    request = RunRequest(
        workflow=workflow,
        phase=phase,
        workspace=root,
        profile=selected_profile.profile_id if selected_profile else None,
        argv=tuple(argv),
    )
    # CLAWOCK_INSTANCE remains only until #539 deletes compatibility entry points.
    instance = os.environ.get("CLAWOCK_INSTANCE", "").strip()
    instance = request.profile or instance
    if not instance:
        raise AdapterUnavailable(
            f"{workflow} {phase} needs a profile; pass --profile or set "
            f"{PROFILE_ENV_VAR}"
        )
    name = f"{instance}.{request.workflow}.{request.phase}"
    matches = tuple(entry_points().select(group=ENTRYPOINT_GROUP, name=name))
    if len(matches) != 1:
        raise AdapterUnavailable(
            f"{workflow} {phase} needs exactly one installed '{instance}' "
            f"adapter entry point; found {len(matches)} for {name}"
        )
    with _phase_env(
        request.workspace,
        selected_profile.path if selected_profile is not None else None,
    ):
        function = matches[0].load()
        return int(function(list(request.argv)) or 0)
