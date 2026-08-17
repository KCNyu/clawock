"""`refresh_live.sh` decides what a merge costs the desk, so the decision is tested.

The rule it encodes — the host runs the checkout, a release is for other people
(docs/operations/release.md § Running the latest code on this host) — is only
worth writing down if the follow-up work it names is right. Two of the three
cases cost something: a `pyproject.toml` move needs the venv reinstalled (pip
recorded the dependency set and the entry points at install time), and a
`clawock-dsh` move needs the plugin reinstalled (pnpm installed a copy, not a
link — #709). The third, ordinary Python, costs nothing because the install is
editable, and claiming otherwise would reintroduce the reinstall-per-merge habit
this script exists to remove.

Driven through `--check` against a throwaway remote, so the test needs no venv,
no dsh and no network.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "host" / "refresh_live.sh"


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(repo),
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


@pytest.fixture
def desk(tmp_path):
    """An upstream repo and a checkout of it, in the shape the desk has."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "master")
    (upstream / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    plugin = upstream / "examples" / "dsh" / "packages" / "clawock-dsh"
    plugin.mkdir(parents=True)
    (plugin / "package.json").write_text("{}\n")
    (upstream / "src").mkdir()
    (upstream / "src" / "thing.py").write_text("x = 1\n")
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-qm", "base")

    checkout = tmp_path / "checkout"
    _git(tmp_path, "clone", "-q", str(upstream), str(checkout))
    return upstream, checkout


def _check(checkout):
    return subprocess.run(
        ["bash", str(SCRIPT), "--check"], capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(checkout),
             "LIVE_CHECKOUT": str(checkout)},
    )


def _advance(upstream, relative, body):
    path = upstream / relative
    path.write_text(body)
    _git(upstream, "add", "-A")
    _git(upstream, "commit", "-qm", f"touch {relative}")


def test_it_is_quiet_and_exits_zero_when_the_desk_is_current(desk):
    _upstream, checkout = desk
    done = _check(checkout)
    assert done.returncode == 0, done.stderr
    assert "is at origin/master" in done.stdout
    assert "needs" not in done.stdout


def test_ordinary_python_needs_no_reinstall_because_the_install_is_editable(desk):
    upstream, checkout = desk
    _advance(upstream, "src/thing.py", "x = 2\n")
    done = _check(checkout)
    assert done.returncode == 1, "being behind must be reportable as a failure"
    assert "editable install picks it up" in done.stdout
    assert "install_clawock_launcher.sh" not in done.stdout
    assert "install_dsh_plugin.sh" not in done.stdout


def test_a_pyproject_move_names_the_venv_reinstall(desk):
    upstream, checkout = desk
    _advance(upstream, "pyproject.toml", '[project]\nversion = "0.2.0"\n')
    done = _check(checkout)
    assert done.returncode == 1
    assert "install_clawock_launcher.sh" in done.stdout
    assert "install_dsh_plugin.sh" not in done.stdout


def test_a_plugin_move_names_the_plugin_reinstall(desk):
    upstream, checkout = desk
    _advance(upstream, "examples/dsh/packages/clawock-dsh/package.json", '{"a":1}\n')
    done = _check(checkout)
    assert done.returncode == 1
    assert "install_dsh_plugin.sh --restart" in done.stdout
    assert "install_clawock_launcher.sh" not in done.stdout


def test_check_writes_nothing(desk):
    """The half that makes `--check` usable from a cron or a review."""
    upstream, checkout = desk
    _advance(upstream, "src/thing.py", "x = 3\n")
    before = _git(checkout, "rev-parse", "HEAD").stdout
    _check(checkout)
    assert _git(checkout, "rev-parse", "HEAD").stdout == before
    assert (checkout / "src" / "thing.py").read_text() == "x = 1\n"
