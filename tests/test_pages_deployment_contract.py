import fnmatch
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "config/pages-public.json").read_text())
WORKFLOW = (ROOT / ".github/workflows/pages.yml").read_text()
UI = (ROOT / "site/assets/js/dashboard.ui.js").read_text()
INDEX = (ROOT / "site/index.html").read_text()
INDEXNOW_KEY = "4fb2df1611ed42e5b67fd6171a237acb.txt"
GOOGLE_VERIFICATION = "google7be5b41525cebe9d.html"


def _sidecar_keys() -> set[str]:
    block = UI.split("const SIDECAR_TAB = {", 1)[1].split("};", 1)[0]
    return set(re.findall(r"([a-z][a-z0-9_]+)\s*:", block))


def test_every_browser_fetch_is_declared_public():
    expected = {"assets/data/overview.json", "assets/data/dashboard.json"}
    expected.update(f"assets/data/{key}.json" for key in _sidecar_keys())

    assert set(CONTRACT["browser_data"]) == expected
    for asset in (
        "assets/css/dashboard.css",
        "assets/data/overview.json",
        "assets/js/dashboard.core.js",
        "assets/js/dashboard.charts.js",
        "assets/js/dashboard.hero.js",
        "assets/js/dashboard.render.js",
        "assets/js/dashboard.ui.js",
        "assets/js/echarts.min.js",
    ):
        assert asset in CONTRACT["required_pages"]


def test_linked_web_manifest_is_required_and_triggers_deploy():
    manifest = re.search(
        r'<link\s+rel="manifest"\s+href="([^"]+)"', INDEX
    ).group(1)

    assert manifest in CONTRACT["required_pages"]
    assert manifest in CONTRACT["artifact_include"]
    assert WORKFLOW.count("'site/**'") == 2


def test_llms_txt_is_required_public_and_linked():
    # #667: llms.txt shipped in site/ but the allowlist never published it, so
    # the deploy was green while the URL 404'd. Pin source, allowlist, and the
    # FAQ link it promises (llms.txt links faq.html; the link must not dangle).
    assert (ROOT / "site" / "llms.txt").is_file()
    assert "llms.txt" in CONTRACT["required_pages"]
    assert "llms.txt" in CONTRACT["artifact_include"]
    assert "faq.html" in (ROOT / "site" / "llms.txt").read_text()
    assert WORKFLOW.count("'site/**'") == 2


def test_faq_page_is_required_public_and_has_an_entry_point():
    # #667: faq.md builds to faq.html in _site (same as briefs.md/evidence.md);
    # the deployed page needs an in-site link so it is reachable and crawlable.
    assert (ROOT / "site" / "faq.md").is_file()
    assert "faq.html" in CONTRACT["required_pages"]
    assert "faq.html" in CONTRACT["artifact_include"]
    assert 'href="faq.html"' in INDEX
    assert WORKFLOW.count("'site/**'") == 2


def test_indexnow_key_is_required_public_and_triggers_deploy():
    """The key proves ownership to IndexNow; without it every submit 403s.

    Retired with the submitter in #592/#679 and restored in #767 — the key file,
    the deploy contract and the submitter have to come back together or the
    feature is green-but-dead again.
    """
    assert (ROOT / "site" / INDEXNOW_KEY).read_text().strip() == INDEXNOW_KEY.removesuffix(".txt")
    assert INDEXNOW_KEY in CONTRACT["required_pages"]
    assert INDEXNOW_KEY in CONTRACT["artifact_include"]
    assert WORKFLOW.count("'site/**'") == 2


def test_repository_only_patterns_cannot_match_browser_data():
    for path in CONTRACT["browser_data"]:
        assert any(
            fnmatch.fnmatch(path, pattern)
            for pattern in CONTRACT["artifact_include"]
        )
        assert not any(
            fnmatch.fnmatch(path, pattern)
            for pattern in CONTRACT["repository_only"]
        )


def test_all_action_data_and_rendered_briefs_trigger_pages_build():
    # assets/data/** is deliberately broad: producer ownership can grow without
    # requiring a synchronized workflow edit before the new output deploys.
    for path in (
        "'assets/data/**'",
        "'memory/*-pre-open.md'",
        "'memory/weekly/**'",
        "'config/pages-public.json'",
        "'ops/pages/**'",
    ):
        assert WORKFLOW.count(path) == 2


def test_workflow_uses_official_non_committing_pages_flow():
    # Assert the official action and a pinned major, not which major. The
    # invariant here is the non-committing flow below; pinning the digits made
    # every dependabot major bump a guaranteed red that said nothing about it.
    for action in (
        "actions/configure-pages",
        "actions/jekyll-build-pages",
        "actions/upload-pages-artifact",
        "actions/deploy-pages",
    ):
        assert re.search(rf"uses: {re.escape(action)}@v\d+\b", WORKFLOW), action
    assert "pages: write" in WORKFLOW
    assert "id-token: write" in WORKFLOW
    assert "git push" not in WORKFLOW
    assert "CLAWOCK_PUBLISH_SSH_KEY" not in WORKFLOW
    assert "github.event_name == 'push'" in WORKFLOW


def test_the_data_plane_is_fetched_before_jekyll_reads_the_checkout():
    """Jekyll builds `_site` from the checkout, so a generation that arrives
    after it is a generation the site does not serve. Ordering, not presence, is
    the invariant — the step can be moved without breaking anything visible until
    a publish lands between the two."""
    steps = [line for line in WORKFLOW.splitlines()
             if "fetch_data_plane.py" in line or "actions/jekyll-build-pages@" in line]

    assert len(steps) == 2, f"expected one fetch and one Jekyll build, got {steps}"
    assert "fetch_data_plane.py" in steps[0], (
        "the data plane must be in the checkout before Jekyll reads it")


def test_the_reader_and_the_writer_cannot_disagree_about_the_branch():
    """A rename that updated only one side would publish to one ref and serve
    from another, with every gate green and the site frozen at whatever it last
    built. The reader imports the name; nothing restates it."""
    reader = (ROOT / "ops/pages/fetch_data_plane.py").read_text()

    assert "from publish_data_branch import DATA_BRANCH" in reader
    assert '"data-plane"' not in reader and "'data-plane'" not in reader


def test_the_browser_reads_the_same_branch_and_files_the_publisher_writes():
    """The browser reaches the data branch by URL, which no import can follow.
    Both halves fail soft, which is what makes them worth pinning: a renamed
    branch leaves the poll 404-ing and falling back to this origin, and a file
    the publisher moved onto the branch but the browser still asks Pages for
    goes back to being a deployment behind. Either way the site quietly stops
    refreshing and every gate stays green."""
    import sys

    sys.path.insert(0, str(ROOT / "ops/publish"))
    from publish_data_branch import DATA_BRANCH, DATA_PLANE_FILES

    origin = re.search(r'DATA_PLANE_ORIGIN\s*=\s*"([^"]+)"', UI).group(1)
    assert origin.endswith(f"/{DATA_BRANCH}/"), (
        f"the browser polls {origin}, the publisher writes {DATA_BRANCH}")

    block = UI.split("const DATA_PLANE_FILES = new Set([", 1)[1].split("]);", 1)[0]
    browser = set(re.findall(r'"([^"]+)"', block))
    published = {Path(name).stem for name in DATA_PLANE_FILES}
    assert browser == published, (
        f"browser reads {sorted(browser)}, publisher writes {sorted(published)}")


def test_builder_stages_only_public_consumers(tmp_path):
    site = tmp_path / "_site"
    output = tmp_path / "_pages"
    shutil.copytree(ROOT / "site/assets", site / "assets")
    shutil.copytree(ROOT / "assets/data", site / "assets/data")
    (site / "index.html").write_text("ok")
    for path in (
        "briefs.html", "evidence.html", "faq.html", "llms.txt",
        "robots.txt", "manifest.webmanifest",
        INDEXNOW_KEY, GOOGLE_VERIFICATION,
    ):
        (site / path).write_text("ok")
    (site / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://kcnyu.github.io/clawock/</loc></url>'
        '<url><loc>https://kcnyu.github.io/clawock/tests/private.html</loc></url>'
        '</urlset>'
    )
    (site / "tests").mkdir()
    (site / "tests/private.txt").write_text("not public")
    (site / "memory").mkdir()
    (site / "memory/decisions.jsonl").write_text("{}\n")
    # QA fixtures ride inside docs/, which IS publicly included as a whole —
    # they are kept out only by the repository_only contract, so this pair
    # pins both halves: the sibling doc ships, the regression captures do not.
    (site / "docs/visual-regression/issue-206").mkdir(parents=True)
    (site / "docs/visual-regression/issue-206/before-1440.jpg").write_bytes(b"\xff\xd8")
    (site / "docs/architecture.md").write_text("ok")
    source_gif_size = (ROOT / "site/assets/dashboard.gif").stat().st_size
    source_jsonl = sorted((ROOT / "assets/data").glob("*.jsonl"))

    result = subprocess.run(
        [
            "python3",
            str(ROOT / "ops/pages/prepare_pages_artifact.py"),
            "--site-dir",
            str(site),
            "--output-dir",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert (site / "assets/dashboard.gif").is_file()
    assert list((site / "assets/data").glob("*.jsonl"))
    assert not (output / "assets/dashboard.gif").exists()
    assert not list((output / "assets/data").glob("*.jsonl"))
    assert not (output / "memory/decisions.jsonl").exists()
    assert not (output / "tests").exists()
    assert not (output / "docs/visual-regression/issue-206").exists()
    assert (output / "docs/architecture.md").is_file()
    sitemap_locs = [
        node.text for node in ET.parse(output / "sitemap.xml").getroot().iter()
        if node.tag.rsplit("}", 1)[-1] == "loc"
    ]
    assert sitemap_locs == ["https://kcnyu.github.io/clawock/"]
    assert (output / INDEXNOW_KEY).is_file()
    assert (output / GOOGLE_VERIFICATION).is_file()
    assert (output / "faq.html").is_file()
    assert (output / "llms.txt").is_file()
    assert (output / "assets/data/dashboard.json").is_file()
    assert (output / "assets/data/overview.json").is_file()
    assert (ROOT / "site/assets/dashboard.gif").stat().st_size == source_gif_size
    assert all(path.is_file() for path in source_jsonl)
    assert "Pages artifact:" in result.stdout


def test_readme_gif_stays_available_from_repository():
    readme = (ROOT / "README.md").read_text()
    assert (
        "https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/"
        "site/assets/dashboard.gif"
    ) in readme


def test_seo_logo_resolves_once_to_a_real_asset():
    """jekyll-seo-tag prepends url+baseurl to `logo` itself, so a baseurl-
    prefixed value shipped clawock/clawock/… (404) in every rendered page's
    JSON-LD publisher block (#974). The value must be site-root relative and
    must land on an asset the Pages artifact actually ships."""
    config = (ROOT / "site/_config.yml").read_text()
    baseurl = re.search(r"^baseurl:\s*(\S+)", config, re.M).group(1)
    logo = re.search(r"^logo:\s*(\S+)", config, re.M).group(1)
    assert logo.startswith("/")
    assert not logo.startswith(f"/{baseurl.strip('/')}")
    assert (ROOT / "site" / logo.lstrip("/")).is_file()


def test_site_staging_joins_owned_source_and_runtime_inputs(tmp_path):
    output = tmp_path / "site-source"
    subprocess.run(
        [
            "python3",
            str(ROOT / "ops/pages/stage_site.py"),
            "--output-dir",
            str(output),
        ],
        cwd=ROOT,
        check=True,
    )

    assert (output / "index.html").is_file()
    assert (output / "_config.yml").is_file()
    assert (output / "assets/js/dashboard.core.js").is_file()
    assert (output / "assets/data/overview.json").is_file()
    assert (output / "docs/architecture/harness.md").is_file()
    assert not (output / "portfolio.json").exists()
