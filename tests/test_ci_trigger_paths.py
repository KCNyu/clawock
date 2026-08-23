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
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
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


def _ui_and_plugin_regexes():
    """The two lanes the `case` list does not cover — they use grep, not case."""
    import re
    found = re.findall(r"grep -Eq '([^']+)'", WORKFLOW)
    assert len(found) >= 2, f"detector no longer greps for the ui/plugin lanes: {found}"
    return found


def test_detector_covers_every_push_trigger_path():
    """A push path with no matching detector pattern is a gate that skips itself.

    Both halves ran before #750 and both looked right in review: the trigger
    listed `ops/**` and `skills/tavily-search/**`, and the `Detect code changes`
    case list — whose own comment claims to be kept in sync with that trigger —
    named neither. So a PR touching only `ops/` or the Tavily skill triggered
    `validate`, matched nothing, skipped every Python step, and reported green in
    seconds. That is the same shape as the dead `assets/css/**` filter below:
    a gate that reads correctly and guards nothing.
    """
    import re

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    assert tracked, "empty checkout would make this assertion vacuous"

    covering = [p.replace("*", "*") for p in case_patterns(WORKFLOW_PATH)]
    regexes = [re.compile(pattern) for pattern in _ui_and_plugin_regexes()]

    def covered(name):
        return (any(fnmatch(name, pattern) for pattern in covering)
                or any(regex.search(name) for regex in regexes))

    uncovered = {}
    for path in push_paths(WORKFLOW_PATH):
        matches = [name for name in tracked
                   if fnmatch(name, path.replace("**", "*"))]
        if matches and not any(covered(name) for name in matches):
            uncovered[path] = matches[:3]
    assert uncovered == {}, (
        "these push-trigger paths reach no detector pattern, so a change confined "
        f"to them runs no test: {uncovered}")


def test_the_heavy_lanes_are_not_gated_on_the_event_that_started_the_run():
    """#750: the browser contract and the DSH plugin gates could not run on master.

    Their conditions read `github.event_name == 'pull_request' && changes...`
    while the `Detect code changes` step that feeds them was itself PR-only, so
    on a master push the detector was skipped, the two conditions were false, and
    the two most expensive gates in the repository never ran outside a PR. The
    unit suite did run there — measured on run 31059122903 — which is why this
    stayed invisible: `validate` was green and mostly busy.

    The detector now runs on every event, so the lanes read only its answer.
    """
    import re

    for lane in ("ui", "dsplugin", "code"):
        gates = re.findall(rf"if: .*steps\.changes\.outputs\.{lane} == 'true'", WORKFLOW)
        assert gates, f"no step gates on the {lane} lane any more"
        offenders = [gate for gate in gates if "github.event_name" in gate]
        assert not offenders, (
            f"{lane} lane is gated on the event again: {offenders}")

    detector = WORKFLOW.split("- name: Detect code changes", 1)[1].split("id: changes", 1)[1]
    head = detector.split("run: |", 1)[0]
    assert "if:" not in head, (
        "the detector must run on every event; gating it is what made the "
        "push-side lanes unreachable")
