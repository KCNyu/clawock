"""clawock — portable decision intelligence for external agents.

This package is the part that is meant to be installable and pointed at any
workspace. Everything under `scripts/` remains the operator-side implementation
of kcn's own desk; the boundary is deliberately thin for now and will move as
more of the loop becomes importable rather than shelled.
"""

from clawock.workspace import ENV_VAR, describe, missing_pieces, workspace_root

__all__ = ["ENV_VAR", "describe", "missing_pieces", "workspace_root"]
