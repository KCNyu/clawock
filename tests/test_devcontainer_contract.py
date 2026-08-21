"""The zero-install trial path.

The README's claim is "install the same decision workflow into your own agent,
in any harness". Between reading that and seeing it run there was nothing but
`pip install clawock` on the reader's own machine — and the funnel says that
step is where people are lost: PyPI 896 downloads a month and npm 1,126 against
110 unique repository visitors in 14 days and 10 stars. Plenty install; almost
nobody leaves a trace.

CI already proves a stranger can finish a run from a clean environment — it
runs examples/cli/minimal-run/run.sh against every published wheel. Until #788
that proof was executable only by GitHub. The devcontainer hands the same script
to the reader.

These assertions exist because a devcontainer rots quietly: it is exercised only
by people who are not yet contributors, so nobody notices when it stops working.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER = ROOT / ".devcontainer" / "devcontainer.json"
WELCOME = ROOT / ".devcontainer" / "welcome.sh"


@pytest.fixture(scope="module")
def config() -> dict:
    # devcontainer.json is JSONC. Strip whole-line comments only; nothing here
    # needs a general parser and a general parser would eat "https://".
    raw = DEVCONTAINER.read_text(encoding="utf-8")
    return json.loads(re.sub(r"^\s*//.*$", "", raw, flags=re.M))


def test_the_install_uses_named_extras_that_actually_exist(config):
    """A hand-written package list here would be the tenth place dependencies
    are declared — the exact drift pyproject was made to end."""
    command = config["postCreateCommand"]
    extras = set(re.findall(r"\[([a-z,]+)\]", command)[0].split(","))
    declared = set(tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["optional-dependencies"])

    assert extras, "the devcontainer must install the package"
    unknown = extras - declared
    assert not unknown, f"devcontainer.json installs extras pyproject does not declare: {unknown}"
    assert "test" in extras, "a contributor's first `pytest` must not fail on collection"


def test_the_image_satisfies_the_declared_python_floor(config):
    floor = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    required = floor["project"]["requires-python"]
    minimum = tuple(int(p) for p in re.search(r"(\d+)\.(\d+)", required).groups())
    image = re.search(r"(\d+)\.(\d+)", config["image"])
    assert image, f"cannot read a Python version out of {config['image']}"
    assert tuple(int(p) for p in image.groups()) >= minimum, (
        f"the devcontainer image is older than requires-python {required}"
    )


def test_the_first_thing_offered_is_a_run_that_needs_no_credentials():
    """The trial has to work with nothing configured. A quickstart that opens
    with "obtain five API keys" is not a trial, and the package half of clawock
    genuinely does not need any."""
    welcome = WELCOME.read_text(encoding="utf-8")
    assert "examples/cli/minimal-run/run.sh" in welcome
    script = (ROOT / "examples" / "cli" / "minimal-run" / "run.sh")
    assert script.exists() and script.stat().st_mode & 0o111, (
        "the script the welcome message offers must exist and be executable"
    )


def test_the_offered_script_is_the_one_ci_runs_against_the_wheel():
    """What CI proves and what a reader runs must stay one file. Two copies
    would drift, and the drift would only show up on someone else's machine."""
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    welcome = WELCOME.read_text(encoding="utf-8")
    for script in ("examples/cli/minimal-run/run.sh", "examples/cli/run.sh"):
        assert script in release, f"{script} is no longer exercised by release.yml"
        assert script in welcome, f"{script} is no longer offered to the reader"


def test_the_readme_advertises_the_trial():
    """A one-click trial nobody can find is not a trial."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "codespaces.new/KCNyu/clawock" in readme, "the README must offer the Codespace"
