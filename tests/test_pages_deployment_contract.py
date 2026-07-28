import fnmatch
import json
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "config/pages-public.json").read_text())
WORKFLOW = (ROOT / ".github/workflows/pages.yml").read_text()
UI = (ROOT / "assets/js/dashboard.ui.js").read_text()


def _sidecar_keys() -> set[str]:
    block = UI.split("const SIDECAR_TAB = {", 1)[1].split("};", 1)[0]
    return set(re.findall(r"([a-z][a-z0-9_]+)\s*:", block))


def test_every_browser_fetch_is_declared_public():
    expected = {"assets/data/dashboard.json"}
    expected.update(f"assets/data/{key}.json" for key in _sidecar_keys())

    assert set(CONTRACT["browser_data"]) == expected


def test_repository_only_patterns_cannot_match_browser_data():
    for path in CONTRACT["browser_data"]:
        assert not any(
            fnmatch.fnmatch(path, pattern)
            for pattern in CONTRACT["artifact_excludes"]
        )


def test_all_action_data_and_rendered_briefs_trigger_pages_build():
    # assets/data/** is deliberately broad: producer ownership can grow without
    # requiring a synchronized workflow edit before the new output deploys.
    for path in (
        "'assets/data/**'",
        "'memory/*-pre-open.md'",
        "'memory/weekly/**'",
        "'config/pages-public.json'",
        "'scripts/build/prepare_pages_artifact.py'",
    ):
        assert WORKFLOW.count(path) == 2


def test_workflow_uses_official_non_committing_pages_flow():
    for action in (
        "actions/configure-pages@v5",
        "actions/jekyll-build-pages@v1",
        "actions/upload-pages-artifact@v4",
        "actions/deploy-pages@v4",
    ):
        assert action in WORKFLOW
    assert "pages: write" in WORKFLOW
    assert "id-token: write" in WORKFLOW
    assert 'sudo chown -R "$(id -u):$(id -g)" _site' in WORKFLOW
    assert "git push" not in WORKFLOW
    assert "CLAWOCK_PUBLISH_SSH_KEY" not in WORKFLOW
    assert "github.event_name == 'push'" in WORKFLOW


def test_pruner_only_mutates_built_site(tmp_path):
    site = tmp_path / "_site"
    shutil.copytree(ROOT / "assets", site / "assets")
    (site / "index.html").write_text("ok")
    source_gif_size = (ROOT / "assets/dashboard.gif").stat().st_size
    source_jsonl = sorted((ROOT / "assets/data").glob("*.jsonl"))

    result = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts/build/prepare_pages_artifact.py"),
            "--site-dir",
            str(site),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert not (site / "assets/dashboard.gif").exists()
    assert not list((site / "assets/data").glob("*.jsonl"))
    assert (site / "assets/data/dashboard.json").is_file()
    assert (ROOT / "assets/dashboard.gif").stat().st_size == source_gif_size
    assert all(path.is_file() for path in source_jsonl)
    assert "Pages artifact:" in result.stdout


def test_readme_gif_stays_available_from_repository():
    readme = (ROOT / "README.md").read_text()
    assert (
        "https://raw.githubusercontent.com/KCNyu/clawock/refs/heads/master/"
        "assets/dashboard.gif"
    ) in readme
