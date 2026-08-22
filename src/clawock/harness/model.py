"""Compatibility re-export: the runtime model moved to `clawock.runtime_model`.

It moved because it imports nothing from clawock and two packages need it, so
living under `harness` forced `workflows` to depend on the harness for a
dataclass (#814). Kept as a module rather than rewriting every caller: the name
`clawock.harness.model` appears in the run-receipt contract and in tests.
"""
from clawock.runtime_model import *  # noqa: F401,F403
from clawock.runtime_model import (  # noqa: F401  (explicit, for `from ... import X`)
    AgentRunRequest,
    ArtifactSet,
    RunReceipt,
    ValidationIssue,
)
