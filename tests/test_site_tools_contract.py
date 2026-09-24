"""Screenshot tooling stays inside the code regression gate."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "ci"))
import push_scope  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_the_tooling_is_inside_the_regression_gate():
    """The gate this file exists to close — assert the wiring, not just the tests."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "'site/tools/**'" in workflow, "site/tools is outside the push trigger"
    assert "site/tools/*" in push_scope.CODE_GLOBS, (
        "site/tools is outside the classifier's code lane")
    assert "find src ops site/tools" in workflow, (
        "the Python syntax check does not reach site/tools")
    assert "node --check" in workflow, "the JS tools are not syntax-checked"
