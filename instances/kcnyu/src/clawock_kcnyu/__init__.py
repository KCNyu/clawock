"""KCNyu instance adapter for the runtime-neutral clawock package."""
from importlib.metadata import PackageNotFoundError, version as _installed_version

__all__ = ["__version__"]

# Read from the installed distribution rather than restated here. This was a
# literal until 2026-08-10, which made it a second source of truth that nothing
# compared against pyproject — so the first version bump after it was written
# would have shipped a package reporting the previous version, silently and
# correctly-looking. Found by bumping to 0.1.1.
try:
    __version__ = _installed_version("clawock-kcnyu")
except PackageNotFoundError:  # running from a source tree, never installed
    __version__ = "0.0.0+unknown"
