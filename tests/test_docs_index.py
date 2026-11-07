"""docs/README.md says "Keep this index current when adding or removing docs"; this is
what keeps it (#2137: docs/design/data-health.md had no link from anywhere)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def test_every_doc_is_reachable_from_the_index():
    index = (DOCS / "README.md").read_text()
    linked = {(DOCS / target).resolve() for target in re.findall(r"\]\(([^)#\s]+)", index)}
    docs = [p for p in DOCS.rglob("*.md") if p != DOCS / "README.md"]
    assert len(docs) > 10, "docs/ no longer found: the walk checks nothing"
    # A moved-page stub keeps old links alive and points on; it is not a document.
    stubs = {p for p in docs if "\n# Moved" in p.read_text()}
    missing = sorted(str(p.relative_to(ROOT)) for p in docs
                     if p.resolve() not in linked and p not in stubs)
    assert not missing, f"not linked from docs/README.md: {missing}"


def test_every_moved_page_points_at_a_document_that_exists():
    """A redirect stub is only useful while its destination is there."""
    stubs = [p for p in DOCS.rglob("*.md") if "\n# Moved" in p.read_text()]
    assert len(stubs) >= 2, "moved-page stubs disappeared; this check is vacuous"
    for stub in stubs:
        targets = [t for t in re.findall(r"\]\(([^)#\s]+)", stub.read_text())
                   if not t.startswith(("http://", "https://", "mailto:"))]
        assert targets, f"{stub.relative_to(ROOT)} names no destination"
        for target in targets:
            assert (stub.parent / target).resolve().exists(), (
                f"{stub.relative_to(ROOT)} points at missing {target}")


def test_moved_pages_are_reachable_but_not_indexable():
    """A moved-page stub is a redirect for people, not a search result.

    #3274 kept the old paths reachable, but the stubs are nine lines of
    "this moved" copy. Left in the sitemap they are thin duplicates of pages
    the reader wanted; left indexable they compete with the document that
    actually owns the subject. The old URL must keep working, so the fix is
    `noindex` plus `sitemap: false`, never a deletion or a redirect chain.
    """
    import re

    stubs = [p for p in DOCS.rglob("*.md") if "\n# Moved" in p.read_text()]
    assert stubs, "the moved-page stubs disappeared; this check would be vacuous"
    titles = []
    for stub in stubs:
        text = stub.read_text()
        front = text.split("---", 2)[1]
        assert "sitemap: false" in front, f"{stub} is still advertised in sitemap.xml"
        assert "robots: noindex" in front, f"{stub} is still indexable"
        match = re.search(r"^title:\s*(.+)$", front, re.M)
        assert match, f"{stub} has no title"
        titles.append(match.group(1).strip())
    assert len(titles) == len(set(titles)), f"moved-page titles collide: {titles}"
