"""Compatibility shim: the implementation now lives in the `clawock` package.

51 modules under `scripts/` do `sys.path.insert(scripts/data)` then
`from workspace import workspace_root`. Keeping this name resolvable means the
package move did not require touching any of them — and it keeps the live
checkout working whether or not `clawock` is pip-installed.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from clawock.workspace import (  # noqa: E402,F401
    ENV_VAR, REQUIRED, describe, missing_pieces, workspace_root,
)
