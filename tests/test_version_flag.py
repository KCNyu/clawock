"""`clawock --version` has to answer, and answer with the installed artifact.

Until 2026-08-11 it was the only documented-looking invocation that failed.
`--version` was never declared, so argparse treated it as an unknown argument
and replied with exit 2 and the entire 50-subcommand usage block. That is the
first thing a reader does after `pip install clawock` — the README's own
quickstart opens with the install line — so the package's first impression was
a failure and a wall of text.

Two properties, because fixing only the first is how the old
An old adapter-local `__version__ = "0.1.0"` literal shipped the previous
release (`tests/test_versions_agree.py`):

1. the flag exists and exits 0;
2. what it prints is read from distribution metadata, not restated in source.

The public package deliberately exposes no `clawock.__version__` — that choice
and its reasoning live in `test_versions_agree.py`, and this file does not
reverse it. The CLI reads the distribution directly instead.
"""
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "clawock.cli", *args],
        capture_output=True, text=True, cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src")},
    )


def test_the_version_flag_exits_zero_and_names_the_program():
    done = _run("--version")
    # The regression was exit 2 with usage on stderr; assert the exit code and
    # the shape, since argparse's failure also contains the word "clawock".
    assert done.returncode == 0, (
        f"`clawock --version` exited {done.returncode}: {done.stderr[:400]}")
    assert re.fullmatch(r"clawock \S+.*", done.stdout.strip()), done.stdout
    assert "usage:" not in done.stdout


def test_the_reported_version_is_the_installed_one():
    """The half that catches a literal: it must agree with what pip recorded.

    Skipped rather than faked when the package is not installed — in that state
    there is no truth to compare against, and asserting the checkout's declared
    number instead would pass for exactly the code this test rejects.
    """
    try:
        from importlib.metadata import version
        installed = version("clawock")
    except Exception:
        pytest.skip("clawock is not installed in this environment")

    printed = " ".join(_run("--version").stdout.split())
    assert printed.startswith(f"clawock {installed}")
    # An editable install may append the drift note below; nothing else may.
    assert printed == f"clawock {installed}" or "editable install of" in printed


def test_an_editable_install_whose_checkout_moved_on_says_which_code_runs(tmp_path):
    """#745 was written from a `--version` that was true and useless.

    The desk host installs clawock editable and then runs whatever `git pull`
    leaves in the checkout — deliberately, so a merged fix is live without a
    release. pip's metadata keeps the number from install time, so `--version`
    read 0.1.5 while the code was three releases ahead, and a genuinely broken
    command was reported as a missing feature of an old package.
    """
    import json

    from clawock import cli

    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n')

    class _Editable:
        version = "0.1.5"

        def read_text(self, name):
            assert name == "direct_url.json"
            return json.dumps({"dir_info": {"editable": True},
                               "url": tmp_path.as_uri()})

    note = cli._editable_drift(_Editable())
    assert str(tmp_path) in note and "9.9.9" in note
    assert "install_clawock_launcher.sh" in note, "the note must say how to fix it"

    class _Wheel(_Editable):
        def read_text(self, name):
            return json.dumps({"dir_info": {}, "url": tmp_path.as_uri()})

    assert cli._editable_drift(_Wheel()) == "", "a wheel install has no second version"

    class _Agreeing(_Editable):
        version = "9.9.9"

    assert cli._editable_drift(_Agreeing()) == "", "no note while the two agree"


def test_the_version_is_not_restated_anywhere_in_the_package():
    """Mutation guard. `--version` reading a hard-coded string would satisfy
    both tests above on the day it was written and be wrong at the next bump —
    which is precisely how the instance package shipped 0.1.1 announcing 0.1.0.
    """
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "src" / "clawock").rglob("*.py"))
        if f'"{declared}"' in path.read_text() or f"'{declared}'" in path.read_text()
    ]
    assert not offenders, (
        f"version {declared} is restated in {offenders}; read it from the "
        "installed distribution so a bump cannot leave a copy behind"
    )
    # Anti-vacuity: the scan above passes just as well if it walks nothing.
    assert len(list((ROOT / "src" / "clawock").rglob("*.py"))) > 50
