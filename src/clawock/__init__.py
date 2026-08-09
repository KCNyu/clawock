"""clawock — portable decision intelligence for external agents.

This package is the runtime-neutral product that can be installed and pointed at
any workspace. Cohesive product areas live in domain subpackages such as
``clawock.evidence`` and ``clawock.portfolio``; remaining code under ``scripts``
is instance or repository operations, never an alternate product namespace.
"""

from clawock.workspace import ENV_VAR, describe, missing_pieces, workspace_root

__all__ = ["ENV_VAR", "describe", "missing_pieces", "workspace_root"]
