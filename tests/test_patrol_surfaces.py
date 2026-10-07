"""The patrol filing gate's surface set covers what the site actually publishes (#2149).

`ops/host/clawock-patrol/surfaces.json` is a hand-kept closed set: a draft that
claims a surface must cite a path matching one of its patterns. When a public
page family was missing from every surface — `docs/**`, `memory/weekly/**`, seven
of the thirteen sidecars the browser fetches — a real finding there could only be
filed as `SURFACE: 无（基础设施）` or under a surface whose name did not fit
(#2135 filed a weekly-review defect as 「简报」). This stages the site the way
Pages does and asks every public file to land on some surface, so a new page
family or sidecar turns this red instead of silently falling outside the gate.
"""
import fnmatch
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "pages"))

import stage_site  # noqa: E402

SURFACES = json.loads((ROOT / "ops/host/clawock-patrol/surfaces.json").read_text(encoding="utf-8"))
PAGES = json.loads((ROOT / "config/pages-public.json").read_text(encoding="utf-8"))


def _gate_hit(path, pattern):
    # The same test gate_issue.py applies to a cited path.
    return (fnmatch.fnmatch(path, pattern)
            or fnmatch.fnmatch(path, pattern.rstrip("/*") + "/*") or path == pattern)


def _public_repo_paths(tmp_path):
    staged = stage_site.stage(tmp_path / "site", source_root=ROOT)
    public = set(PAGES["browser_data"])
    for file in staged.rglob("*"):
        if not file.is_file():
            continue
        rel = file.relative_to(staged).as_posix()
        # Only Markdown with front matter is a Jekyll page. Generated Markdown
        # alternates are static files and must be checked under their actual URL.
        is_page = rel.endswith(".md") and file.read_text(encoding="utf-8").startswith("---")
        served = rel[:-3] + ".html" if is_page else rel
        if not any(fnmatch.fnmatch(served, pat) for pat in PAGES["artifact_include"]):
            continue
        if any(fnmatch.fnmatch(served, pat) for pat in PAGES.get("repository_only", [])):
            continue
        # site/ is copied to the root first; everything else comes from the repo root.
        public.add(f"site/{rel}" if (ROOT / "site" / rel).is_file() else rel)
    return public


def test_every_file_the_site_publishes_lands_on_a_surface(tmp_path):
    public = _public_repo_paths(tmp_path)
    assert any(p.startswith("docs/") for p in public), "staging no longer carries docs/"
    patterns = [pat for surface in SURFACES["surfaces"].values() for pat in surface["patterns"]]
    orphaned = sorted(p for p in public if not any(_gate_hit(p, pat) for pat in patterns))
    assert orphaned == [], (
        f"{len(orphaned)} public file(s) match no surface in surfaces.json — a finding "
        f"there has no honest SURFACE to name: {orphaned[:12]}")


def test_the_ledger_surface_carries_the_trace_its_description_promises():
    ledger = SURFACES["surfaces"]["决策台账"]
    assert "trace" in ledger["who"]
    assert any(_gate_hit("assets/data/decision_trail.json", pat) for pat in ledger["patterns"])
