"""Every `from X import Y` a workflow runs inline must resolve (#1912).

weekly-health imported `analyze_hk_stocks`, a top-level module #425 moved into
the package; the step's `continue-on-error` (meant for the network) turned the
ModuleNotFoundError green every week. Workflow YAML is not imported by any test,
so nothing else notices a stale import until the schedule fires.
"""
import importlib
import importlib.util
import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
FROM_IMPORT = re.compile(r"^\s*from\s+([A-Za-z_][\w.]*)\s+import\s+([\w, ]+?)\s*\"?$",
                         re.MULTILINE)
IMPORTS = sorted({
    (path.name, module, name.split(" as ")[0].strip())
    for path in WORKFLOWS.glob("*.yml")
    for module, names in FROM_IMPORT.findall(path.read_text(encoding="utf-8"))
    for name in names.split(",") if name.strip()
})


def test_the_scan_sees_the_imports_it_guards():
    assert ("weekly-health.yml", "clawock.market_data.hk_analysis",
            "fetch_hk_quotes") in IMPORTS


@pytest.mark.parametrize("workflow, module, name", IMPORTS)
def test_an_inline_workflow_import_resolves(workflow, module, name):
    parent = importlib.import_module(module)
    resolved = hasattr(parent, name) or (
        hasattr(parent, "__path__")
        and importlib.util.find_spec(f"{module}.{name}") is not None)
    assert resolved, f"{workflow}: `from {module} import {name}` does not resolve"
