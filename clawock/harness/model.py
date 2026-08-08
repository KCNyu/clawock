"""Small contracts shared by runners, validators and publishers."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


WORKFLOWS = ("brief", "report", "intraday")
PHASES = ("preflight", "postflight")


@dataclass(frozen=True)
class RunRequest:
    workflow: str
    phase: str
    workspace: Path
    argv: tuple[str, ...] = ()

    def __post_init__(self):
        if self.workflow not in WORKFLOWS:
            raise ValueError(f"unknown workflow: {self.workflow}")
        if self.phase not in PHASES:
            raise ValueError(f"unknown phase: {self.phase}")


@dataclass(frozen=True)
class Artifact:
    name: str
    path: Path
    media_type: str
    generation_id: str


@dataclass(frozen=True)
class ArtifactSet:
    """Correlated outputs from one agent run, pinned to one generation."""
    generation_id: str
    artifacts: tuple[Artifact, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not self.generation_id:
            raise ValueError("artifact set has no generation_id")
        mismatched = [a.name for a in self.artifacts
                      if a.generation_id != self.generation_id]
        if mismatched:
            raise ValueError(
                "mixed artifact generations: " + ", ".join(mismatched))
