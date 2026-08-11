"""Every internal link on the site must resolve to something the build emits.

The site-wide nav carried a `README` entry pointing at `/README.html`. That URL
worked while the repository root *was* the Jekyll source root: `README.md` sat
in the tree and Jekyll rendered it. #399 moved the site under `site/` and had
`ops/pages/stage_site.py` assemble the source tree instead, and the root README
is not part of it — so since 2026-08-08 every page on the site advertised a
404, in its header, to every visitor and every crawler. Nothing noticed,
because no check ever asked whether a link had a destination.

Crawl budget is this site's binding constraint, which makes a dead link in the
site-wide nav worse than a missing one: it is spent on a URL that cannot exist.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

# Some published URLs are not files in this checkout: the dashboard's own JSON
# lives on the data branch (#314) and is joined in during staging. What makes
# them real is the declaration, so that is what this reads — a link to an
# undeclared artifact is exactly the thing worth failing on.
PUBLIC = json.loads((ROOT / "config" / "pages-public.json").read_text())
PUBLISHED = set(PUBLIC["browser_data"]) | set(PUBLIC["required_pages"])

HREF = re.compile(r'href="([^"]+)"')
MARKDOWN_LINK = re.compile(r'(?<!!)\[[^\]]*\]\(([^)\s]+)')
# {{ '/briefs.html' | relative_url }} — a quoted literal. `{{ f.url | ... }}`
# is a loop variable with no static destination, so it is not one of these.
RELATIVE_URL = re.compile(r"^\{\{\s*'([^']+)'\s*\|\s*relative_url\s*\}\}$")

EXTERNAL = ("http://", "https://", "//", "mailto:", "data:")


def pages() -> list[Path]:
    return sorted(
        path for path in SITE.rglob("*")
        if path.suffix in {".html", ".md"} and path.is_file()
    )


def targets(text: str) -> list[str]:
    return HREF.findall(text) + MARKDOWN_LINK.findall(text)


def internal_links() -> list[tuple[Path, str]]:
    found = []
    for page in pages():
        for raw in targets(page.read_text(encoding="utf-8")):
            link = raw.strip()
            match = RELATIVE_URL.match(link)
            if match:
                link = match.group(1)
            if link.startswith(EXTERNAL) or link.startswith("#") or not link:
                continue
            if "{{" in link or "{%" in link:
                continue  # a Liquid variable; its destination is not static
            found.append((page, link.split("?")[0].split("#")[0]))
    return found


def resolves(link: str) -> bool:
    relative = link.lstrip("/")
    if relative in {"", "./"}:
        return (SITE / "index.html").exists()
    if relative in PUBLISHED:
        return True
    candidate = SITE / relative
    if candidate.is_file():
        return True
    if relative.endswith("/"):
        return any((candidate / f"index{s}").exists() for s in (".html", ".md"))
    if relative.endswith(".html"):
        # Jekyll emits page.html from page.md — but only for a *page*, and what
        # makes a markdown file a page is front matter. `optional_front_matter`
        # is deliberately off in _config.yml, so a file without it is copied as
        # a static file and no .html is ever produced. `site/README.md` is one:
        # it exists, which is why linking to /README.html looked safe, and
        # /README.html has never resolved.
        source = candidate.with_suffix(".md")
        return source.exists() and source.read_text(encoding="utf-8").startswith("---")
    return False


def test_no_page_links_to_a_destination_the_build_will_not_emit():
    links = internal_links()
    # Without this the check would pass loudest exactly when the extraction
    # broke and it stopped seeing any link at all.
    assert len(links) >= 8, f"only found {len(links)} internal links to check"
    assert any(link.endswith("briefs.html") for _, link in links)
    assert any(link.endswith("evidence.html") for _, link in links)

    dead = sorted({
        f"{page.relative_to(ROOT)} -> {link}"
        for page, link in links if not resolves(link)
    })
    assert dead == [], "internal links with no destination: " + "; ".join(dead)


def test_the_shared_nav_does_not_advertise_a_page_the_site_does_not_have():
    # The nav is on every page, so one dead entry there is one dead link per
    # page — the shape that made this cost three days of crawls unnoticed.
    layout = (SITE / "_layouts" / "default.html").read_text(encoding="utf-8")
    nav = layout[layout.index('<nav class="topbar-actions">'):]
    nav = nav[:nav.index("</nav>")]
    for raw in HREF.findall(nav):
        match = RELATIVE_URL.match(raw.strip())
        if not match:
            continue
        assert resolves(match.group(1)), f"shared nav links to missing {match.group(1)}"
