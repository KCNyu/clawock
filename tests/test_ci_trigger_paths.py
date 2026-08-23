"""The `validate` gate must not skip a PR that only touches `config/`.

`validate` is a required check that always reports, but its expensive Python steps
are gated twice: the `push:` path filter and the lane classifier. Both halves used
to be explicit file lists that looked complete while leaving every later addition
ungated (config files before the directory-wide form; `ops/**` and the Tavily
skill before #750). The classification itself now lives in `ops/ci/push_scope.py`,
and these assertions drive it behaviourally instead of parsing YAML text.
"""
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

from workflow_contract_helpers import push_paths

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
WORKFLOW = WORKFLOW_PATH.read_text()
CONFIG_FILES = sorted(
    str(path.relative_to(ROOT)) for path in (ROOT / "config").rglob("*")
    if path.is_file()
)

sys.path.insert(0, str(ROOT / "ops" / "ci"))
import push_scope  # noqa: E402


def _tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return out.stdout.split()


def test_config_directory_is_gated_as_a_whole():
    assert "config/**" in push_paths(WORKFLOW_PATH)
    assert "config/*" in push_scope.CODE_GLOBS


def test_no_individual_config_file_is_named_in_either_gate():
    # A single named file is the failure mode this test exists to prevent: it looks
    # complete while leaving every future config file ungated.
    narrow = [p for p in push_paths(WORKFLOW_PATH) + push_scope.CODE_GLOBS
              if p.startswith("config/") and p not in {"config/**", "config/*"}]
    assert narrow == [], f"re-narrowed config gating: {narrow}"


def test_every_shipped_config_file_matches_the_gate():
    # Glob lanes match `/` inside `*`, so `config/*` covers nested files too.
    assert CONFIG_FILES, "config/ is empty; the gate assertions would be vacuous"
    assert all(name.startswith("config/") for name in CONFIG_FILES)


def test_code_and_tests_stay_gated():
    # `scripts/` was retired in #429 and the Python instance distribution was
    # retired in #539; executable code now lives under src/ and ops/.
    assert not (ROOT / "scripts").exists()
    for pattern in ("src/*", "tests/*"):
        assert pattern in push_scope.CODE_GLOBS
    for pattern in ("src/**", "ops/**", "tests/**"):
        assert pattern in push_paths(WORKFLOW_PATH)


def test_no_push_path_matches_nothing_in_the_checkout():
    # A path that matches no file is not a gate. #399 moved the dashboard under
    # `site/` and left `assets/css/**`, `assets/js/**` and `index.html` behind:
    # they kept passing review because they read correctly, while every
    # stylesheet and script edit stopped triggering the workflow at all.
    tracked = _tracked()
    assert tracked, "empty checkout would make this assertion vacuous"
    dead = [
        pattern for pattern in push_paths(WORKFLOW_PATH)
        if not any(fnmatch(name, pattern.replace("**", "*")) for name in tracked)
    ]
    assert dead == [], f"path filter matches no tracked file: {dead}"


def test_every_push_trigger_path_reaches_a_lane():
    """A trigger path with no matching classifier pattern is a gate that skips itself.

    Both halves ran before #750 and both looked right in review: the trigger
    listed `ops/**` and `skills/tavily-search/**`, and the inline case list —
    whose own comment claimed to be kept in sync — named neither. So a PR
    touching only those skipped the entire suite while `validate` reported
    green in seconds. This is now behavioural: every tracked file under every
    push-trigger glob must light up at least one lane in the real classifier.
    """
    import fnmatch as fm

    tracked = _tracked()
    assert tracked, "empty checkout would make this assertion vacuous"

    uncovered = {}
    for path in push_paths(WORKFLOW_PATH):
        matches = [name for name in tracked if fnmatch(name, path.replace("**", "*"))]
        if matches and all(
            not any(push_scope.classify([name]).values()) for name in matches
        ):
            uncovered[path] = matches[:3]
    assert uncovered == {}, (
        "these push-trigger paths reach no classifier lane, so a change confined "
        f"to them runs no test: {uncovered}")


def test_all_three_gates_read_the_one_classifier():
    """Three inline copies of diff-classification bash are how #750 happened.

    The detector, the lint scope and the CodeQL scope must all call
    ops/ci/push_scope.py rather than carrying private copies of the patterns.
    """
    calls = WORKFLOW.count("ops/ci/push_scope.py")
    assert calls >= 3, f"expected detector + lint + CodeQL to route through the classifier, found {calls}"
    assert "grep -Eq '" not in WORKFLOW, (
        "inline lane greps are back; the classifier owns the patterns")


def test_the_heavy_lanes_are_not_gated_on_the_event_that_started_the_run():
    """#750: the browser contract and the DSH plugin gates could not run on master.

    Their conditions read `github.event_name == 'pull_request' && changes...`
    while the detector that feeds them was itself PR-only, so on a master push
    the detector was skipped, the two conditions were false, and the two most
    expensive gates in the repository never ran outside a PR.

    The detector runs on every event, so the lanes read only its answer.
    """
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
