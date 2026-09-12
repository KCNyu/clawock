"""The repo's hand-kept lists of files, held against the registry that owns them.

Two shapes of the same bug (#1448, #1449): a set of paths is declared in one
place and re-declared, by hand, in another. Both halves stay right only as long
as whoever adds a file remembers every copy — and the copies fail in opposite
directions, so the one that matters is the one that fails silently.

    BASELINE_TRACKED (ops/system_check.py)  vs  config/root-allowlist.json
        forget the allowlist -> `root ownership` CRITICAL, push blocked (loud)
        forget BASELINE_TRACKED -> the file quietly stops being required (silent)

    config/dashboard-outputs.json  vs  ci.yml  vs  dashboard.ui.js
        a sixth output is built and published, while the determinism check and
        the live-origin routing table keep talking about five

Both copies are gone now (the registry and the contract are read directly); what
is left to pin is the JavaScript, which cannot import Python, and the claim that
the registry-derived lists are actually complete.

Deliberately NOT asserted: `pages-public.json::browser_data` ⊆
`dashboard-outputs.json`, which #1449 proposed. `dashboard-outputs.json` is the
DASHBOARD BUILDER's write set — the five files `write_generation` swaps in
atomically and `test_dashboard_output_ownership` polices. `macro.json`,
`sentiment.json`, `em_news.json`, `influencer_feed.json`, `us_news_digest.json`
come from GitHub Actions scans and `brief_projection.json` from the brief
preflight; declaring them as builder outputs to satisfy a freshness gate would
make the write-set contract say something false. The invariant that IS true of
browser_data — every file the browser fetches is declared public, and nothing
else is — is checked below.
"""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops"))

import system_check  # noqa: E402

ALLOWLIST = json.loads((ROOT / "config/root-allowlist.json").read_text())
OUTPUTS = json.loads((ROOT / "config/dashboard-outputs.json").read_text())["outputs"]
PAGES = json.loads((ROOT / "config/pages-public.json").read_text())
UI_JS = (ROOT / "site/assets/js/dashboard.ui.js").read_text()
CI_YML = (ROOT / ".github/workflows/ci.yml").read_text()


# ── #1448: the bootstrap baseline ────────────────────────────────────────────

def test_baseline_tracked_is_derived_not_retyped():
    tree = ast.parse((ROOT / "ops/system_check.py").read_text())
    assigned = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "BASELINE_TRACKED" for t in node.targets)
    ]
    assert assigned, "BASELINE_TRACKED is gone — point this gate at its replacement"
    for value in assigned:
        assert not isinstance(value, (ast.List, ast.Tuple, ast.Set)), (
            "BASELINE_TRACKED is a literal list again. It is a second, "
            "hand-kept copy of config/root-allowlist.json's top-level files; "
            "flag the entry `\"baseline\": true` there instead."
        )


def test_every_baseline_file_is_owned_tracked_and_present():
    baseline = system_check.BASELINE_TRACKED
    assert len(baseline) >= 9, (
        f"only {len(baseline)} baseline files — the registry flag stopped "
        f"matching, and check_baseline_files now watches almost nothing"
    )
    tracked = set(subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split())
    for name in baseline:
        meta = ALLOWLIST["entries"].get(name)
        assert meta, f"{name} is flagged baseline but has no allowlist entry"
        assert meta.get("owner") and meta.get("consumer"), (
            f"{name}: `root ownership` requires owner and consumer"
        )
        assert name in tracked, (
            f"{name} is required in every checkout but is not tracked by git — "
            f"no checkout can satisfy that"
        )
        assert (ROOT / name).exists(), f"{name} is missing from this checkout"


def test_a_newly_flagged_root_file_joins_the_baseline_by_itself(tmp_path, monkeypatch):
    """The point of deriving it: adding a file is one edit, not two."""
    (tmp_path / "config").mkdir()
    entries = dict(ALLOWLIST["entries"])
    entries["NEWFILE.md"] = {"owner": "t", "consumer": "t", "baseline": True}
    (tmp_path / "config/root-allowlist.json").write_text(
        json.dumps({"schema_version": 1, "entries": entries})
    )
    monkeypatch.setattr(system_check, "WS", tmp_path)
    assert "NEWFILE.md" in system_check._baseline_tracked()


def test_an_unreadable_registry_is_a_readable_critical(tmp_path, monkeypatch):
    monkeypatch.setattr(system_check, "WS", tmp_path)
    monkeypatch.setattr(system_check, "BASELINE_TRACKED", [])
    result = system_check.Result()
    system_check.check_baseline_files(result)
    assert result.critical_count() == 1, (
        f"an unreadable baseline registry passes silently: {result.checks}"
    )


# ── #1449: the data-plane write set ──────────────────────────────────────────

def _js_data_plane_names():
    m = re.search(r"const DATA_PLANE_FILES = new Set\(\[(.*?)\]\)", UI_JS, re.S)
    assert m, "DATA_PLANE_FILES is gone from dashboard.ui.js"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _publisher_names():
    sys.path.insert(0, str(ROOT / "ops/publish"))
    import publish_data_branch  # noqa: E402
    # Optional members count as published: the branch carries one whenever it
    # exists, and the browser may route it before the first weekly run has written
    # it. Narrowing this to the required set would let the routing table and the
    # publisher disagree about a file that is genuinely on the branch.
    return {p.rsplit("/", 1)[-1].removesuffix(".json")
            for p in publish_data_branch.DATA_PLANE_FILES
            + publish_data_branch.DATA_PLANE_OPTIONAL}


def test_the_browser_routes_exactly_the_files_the_publisher_puts_on_the_branch():
    """`DATA_PLANE_FILES` in JS is a routing table for the live origin.

    A file the publisher ships but the browser does not route reads from Pages
    instead — up to a deploy behind, with every gate green. A name the browser
    routes but the publisher never ships is a 404 on the live origin.
    """
    js, publisher = _js_data_plane_names(), _publisher_names()
    assert js, "the JS routing table is empty"
    assert js == publisher, (
        f"data-plane routing drift — only in JS: {sorted(js - publisher)}; "
        f"only in the publisher: {sorted(publisher - js)}"
    )


def test_browser_data_is_exactly_what_the_page_fetches():
    """`pages-public.json::browser_data` vs the fetches dashboard.ui.js makes."""
    m = re.search(r"const SIDECAR_TAB = \{(.*?)\n  \};", UI_JS, re.S)
    assert m, "SIDECAR_TAB is gone from dashboard.ui.js"
    fetched = set(re.findall(r"(\w+):\s*(?:\"|\[)", m.group(1)))
    # The two the shell fetches directly, outside the sidecar machinery.
    fetched |= {name for name in re.findall(r'_dataUrl\("(\w+)"', UI_JS)}
    assert len(fetched) > 5, f"only found {sorted(fetched)} — the regex went stale"

    declared = {p.rsplit("/", 1)[-1].removesuffix(".json")
                for p in PAGES["browser_data"]}
    assert declared == fetched, (
        f"browser_data drift — fetched but not declared public (404 in the "
        f"browser): {sorted(fetched - declared)}; declared but never fetched: "
        f"{sorted(declared - fetched)}"
    )


def test_ci_reads_the_output_contract_instead_of_restating_it():
    """The determinism check must cover whatever the contract says today."""
    body = re.sub(r"^\s*#.*$", "", CI_YML, flags=re.M)
    assert "config/dashboard-outputs.json" in body, (
        "ci.yml never reads the output contract"
    )
    loops = re.findall(r"for name in ([^;]+); do", body)
    assert loops, "the determinism loops are gone — point this gate at what replaced them"
    for loop in loops:
        assert loop.strip() == "$names", (
            f"ci.yml restates the output names instead of reading the contract: "
            f"`for name in {loop.strip()}` — a sixth output would be built, "
            f"published, and never checked for determinism"
        )
