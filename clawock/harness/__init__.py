"""Runtime-neutral harness contracts and the CLI-facing instance adapter.

The package owns lifecycle vocabulary and artifact invariants.  OpenClaw owns
the conversation/tool loop; the kcn checkout supplies today's heavy pre/post
flight implementation as an adapter.  No agent loop is reimplemented here.
"""
from .model import Artifact, ArtifactSet, RunRequest
from .runner import run_phase

__all__ = ["Artifact", "ArtifactSet", "RunRequest", "run_phase"]
