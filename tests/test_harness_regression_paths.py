"""The `validate` gate must not skip a PR that only touches `config/`.

`validate` is a required check that always reports, but its expensive Python steps
are gated twice: the `push:` path filter and the `Detect code changes` case list.
Both were written as an explicit list of config files, so every config file added
later (thesis and earnings schemas, evidence policies, peer rules) silently fell
outside the gate — a config-only PR reported green in seconds without running the
tests that read that config. These assertions keep the directory-wide form.
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" / "harness-regression.yml").read_text()
CONFIG_FILES = sorted(
    str(path.relative_to(ROOT)) for path in (ROOT / "config").rglob("*")
    if path.is_file()
)


def _push_paths():
    block = WORKFLOW.split("    paths:", 1)[1].split("  pull_request:", 1)[0]
    return re.findall(r"^\s*-\s*'([^']+)'", block, re.MULTILINE)


def _case_patterns():
    detect = WORKFLOW.split("Detect code changes", 1)[1]
    line = next(ln for ln in detect.splitlines() if ln.strip().endswith(")") and "|" in ln)
    return line.strip().rstrip(")").split("|")


def test_config_directory_is_gated_as_a_whole():
    assert "config/**" in _push_paths()
    assert "config/*" in _case_patterns()


def test_no_individual_config_file_is_named_in_either_gate():
    # A single named file is the failure mode this test exists to prevent: it looks
    # complete while leaving every future config file ungated.
    narrow = [p for p in _push_paths() + _case_patterns()
              if p.startswith("config/") and p not in {"config/**", "config/*"}]
    assert narrow == [], f"re-narrowed config gating: {narrow}"


def test_every_shipped_config_file_matches_the_gate():
    # `case` patterns match `/` inside `*`, so `config/*` covers nested files too.
    assert CONFIG_FILES, "config/ is empty; the gate assertions would be vacuous"
    assert all(name.startswith("config/") for name in CONFIG_FILES)


def test_scripts_and_tests_stay_gated():
    for pattern in ("scripts/*", "tests/*"):
        assert pattern in _case_patterns()
    for pattern in ("scripts/**", "tests/**"):
        assert pattern in _push_paths()
