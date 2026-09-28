"""docs/README.md says "Keep this index current when adding or removing docs"; this is
what keeps it (#2137: docs/design/data-health.md had no link from anywhere)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def test_every_doc_is_reachable_from_the_index():
    index = (DOCS / "README.md").read_text()
    linked = {(DOCS / target).resolve() for target in re.findall(r"\]\(([^)#\s]+)", index)}
    docs = [p for p in DOCS.rglob("*.md") if p.name != "README.md"]
    assert len(docs) > 10, "docs/ no longer found: the walk checks nothing"
    # A moved-page stub keeps old links alive and points on; it is not a document.
    stubs = {p for p in docs if "\n# Moved" in p.read_text()}
    missing = sorted(str(p.relative_to(ROOT)) for p in docs
                     if p.resolve() not in linked and p not in stubs)
    assert not missing, f"not linked from docs/README.md: {missing}"
