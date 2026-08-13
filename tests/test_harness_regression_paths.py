"""The `validate` gate must not skip a PR that only touches `config/`.

`validate` is a required check that always reports, but its expensive Python steps
are gated twice: the `push:` path filter and the `Detect code changes` case list.
Both were written as an explicit list of config files, so every config file added
later (thesis and earnings schemas, evidence policies, peer rules) silently fell
outside the gate — a config-only PR reported green in seconds without running the
tests that read that config. These assertions keep the directory-wide form.
"""
import subprocess
from fnmatch import fnmatch
from pathlib import Path

from workflow_contract_helpers import case_patterns, push_paths


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "harness-regression.yml"
WORKFLOW = WORKFLOW_PATH.read_text()
CONFIG_FILES = sorted(
    str(path.relative_to(ROOT)) for path in (ROOT / "config").rglob("*")
    if path.is_file()
)


def test_config_directory_is_gated_as_a_whole():
    assert "config/**" in push_paths(WORKFLOW_PATH)
    assert "config/*" in case_patterns(WORKFLOW_PATH)


def test_no_individual_config_file_is_named_in_either_gate():
    # A single named file is the failure mode this test exists to prevent: it looks
    # complete while leaving every future config file ungated.
    narrow = [p for p in push_paths(WORKFLOW_PATH) + case_patterns(WORKFLOW_PATH)
              if p.startswith("config/") and p not in {"config/**", "config/*"}]
    assert narrow == [], f"re-narrowed config gating: {narrow}"


def test_every_shipped_config_file_matches_the_gate():
    # `case` patterns match `/` inside `*`, so `config/*` covers nested files too.
    assert CONFIG_FILES, "config/ is empty; the gate assertions would be vacuous"
    assert all(name.startswith("config/") for name in CONFIG_FILES)


def test_code_and_tests_stay_gated():
    # `scripts/` was retired in #429 and the Python instance distribution was
    # retired in #539; executable code now lives under src/ and ops/.
    assert not (ROOT / "scripts").exists()
    for pattern in ("src/*", "tests/*"):
        assert pattern in case_patterns(WORKFLOW_PATH)
    for pattern in ("src/**", "ops/**", "tests/**"):
        assert pattern in push_paths(WORKFLOW_PATH)


def test_no_push_path_matches_nothing_in_the_checkout():
    # A path that matches no file is not a gate. #399 moved the dashboard under
    # `site/` and left `assets/css/**`, `assets/js/**` and `index.html` behind:
    # they kept passing review because they read correctly, while every
    # stylesheet and script edit stopped triggering the workflow at all.
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert tracked, "empty checkout would make this assertion vacuous"
    dead = [
        pattern for pattern in push_paths(WORKFLOW_PATH)
        if not any(fnmatch(name, pattern.replace("**", "*")) for name in tracked)
    ]
    assert dead == [], f"path filter matches no tracked file: {dead}"
